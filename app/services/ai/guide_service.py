"""AI 导购服务（§6.3）：需求提取 → 组合召回 → 相似度重排 → 推荐话术生成。

LLM 异常时降级：需求提取失败 → 直接按原文语义召回；话术生成失败 → 返回纯商品结果无话术。
"""
import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.crud import chat as crud_chat
from app.crud import product as crud_product
from app.models import Category, User
from app.services.ai.llm import LLMError, get_llm
from app.services.ai.search import semantic_search_products

logger = logging.getLogger(__name__)

# 语义召回候选数（重排前）
RECALL_K = 20
# 最终推荐商品数
TOP_N = 5
# 需求提取参考的最近消息条数（多轮导购上下文）
HISTORY_LIMIT = 6

_EXTRACT_PROMPT = """你是电商导购助手。请从用户的购物需求中提取结构化信息，只输出一个 JSON 对象，不要输出任何其他内容。
字段说明：category（品类名，无法判断为 null）、budget_min 与 budget_max（预算上下限，数字或 null。
用户说“预算X左右/大约X”等近似表述时，取上下浮动 20% 的区间，如预算1000左右则 budget_min=800、budget_max=1200；
“X以内/不超过X/最多X”只填 budget_max 且直接等于 X 本身，不得打折；
“X以上/起码X”只填 budget_min 且直接等于 X 本身），
attributes（偏好关键词数组，如 ["拍照", "轻薄"]）、use_case（用途，如 "送妈妈"，无法判断为 null）。
{history_hint}用户需求：{message}"""

_REPLY_PROMPT = """你是「智选商城」的导购助手。候选商品列表是本商城真实在售的全部可选商品，你的回答只能从中选择推荐，
用 2~3 句自然的中文说明匹配理由（价格、功能、用途），语气亲切。
规则：
1. 只能推荐候选列表中存在的商品，必须原样使用其中的商品名称，一个字都不能改；
2. 若候选商品与用户想要的品类不一致（如用户要耳机但候选是手表），必须如实告知本店暂无该品类，并说明最接近的替代品是什么；
3. 不要输出 JSON。

用户需求：{message}
提取到的需求：{requirements}
候选商品（共 {n_products} 件，只能从这里选）：
{products}

示例格式（仅供参考语气，商品名必须用上面的真实名称）：
“为您推荐「某真实商品名」，它……（匹配理由）。”"""


def _to_float(value) -> float | None:
    try:
        number = float(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def _strip_code_fence(text: str) -> str:
    """剥离 ```json ... ``` 代码块包裹（模型未严格遵守 json_mode 时兜底）。"""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
    return "\n".join(lines).strip()


async def _match_category(db: AsyncSession, name: str) -> int | None:
    """品类名 → 分类 ID：先精确匹配，再模糊匹配。"""
    name = name.strip()
    if not name:
        return None
    stmt = select(Category).where(Category.name == name)
    category = (await db.execute(stmt)).scalars().first()
    if category is None:
        stmt = select(Category).where(Category.name.ilike(f"%{name}%"))
        category = (await db.execute(stmt)).scalars().first()
    return category.id if category else None


async def _extract_requirements(message: str, history_texts: list[str]) -> dict | None:
    """LLM json_mode 提取需求：预算 / 品类 / 用途 / 偏好关键词。"""
    history_hint = ""
    if history_texts:
        history_hint = (
            "最近对话（用于理解指代与补充，如“不要红色的”）：\n"
            + "\n".join(history_texts[-HISTORY_LIMIT:])
            + "\n"
        )
    prompt = _EXTRACT_PROMPT.format(history_hint=history_hint, message=message)
    result = await get_llm().chat(
        [{"role": "user", "content": prompt}], json_mode=True, temperature=0.1
    )
    content = _strip_code_fence(result.get("content") or "")
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("导购需求提取结果解析失败: %s", content[:200])
        return None
    if not isinstance(data, dict):
        return None
    return {
        "category": data.get("category") or None,
        "budget_min": _to_float(data.get("budget_min")),
        "budget_max": _to_float(data.get("budget_max")),
        "attributes": [str(a) for a in (data.get("attributes") or []) if a][:5],
        "use_case": data.get("use_case") or None,
    }


async def _generate_reply(message: str, requirements: dict | None, results: list[dict]) -> str:
    """LLM 生成自然语言推荐话术。"""
    lines = []
    for row in results:
        p = row["product"]
        lines.append(
            f"- {p.name}（¥{float(p.price_min)} 起，销量 {p.sales_count}）：{p.subtitle or '无描述'}"
        )
    prompt = _REPLY_PROMPT.format(
        message=message,
        requirements=json.dumps(requirements, ensure_ascii=False) if requirements else "未提取到",
        n_products=len(lines),
        products="\n".join(lines),
    )
    result = await get_llm().chat([{"role": "user", "content": prompt}], temperature=0.3)
    return (result.get("content") or "").strip()


def _product_card(row: dict, attributes: list[str], max_price: float | None) -> dict:
    """组装商品卡片：附匹配理由（偏好关键词命中 / 预算之内）。"""
    p = row["product"]
    text = " ".join(filter(None, [p.name, p.subtitle or "", p.description or ""]))
    reasons = [a for a in attributes if a and a in text]
    if max_price is not None and float(p.price_min) <= max_price:
        reasons.append("预算之内")
    if not reasons:
        reasons.append((p.subtitle or p.name)[:20])
    similarity = row.get("similarity")
    return {
        "id": p.id,
        "name": p.name,
        "subtitle": p.subtitle,
        "price_min": float(p.price_min),
        "price_max": float(p.price_max),
        "main_image": p.main_image,
        "sales_count": p.sales_count,
        "similarity": round(similarity, 4) if similarity is not None else None,
        "match_reasons": reasons[:3],
    }


async def run_guide(
    db: AsyncSession, user: User, session_id: uuid.UUID | None, message: str
) -> dict:
    """AI 导购主流程，返回 {session_id, requirements, reply, products}。"""
    # 1. 会话定位 / 新建（guide 类型，支持多轮补充需求）
    session = None
    if session_id is not None:
        session = await crud_chat.get_session(db, session_id, user.id)
        if session is None:
            raise BizError(6001, "会话不存在", 404)
        if session.type != "guide":
            raise BizError(6001, "会话类型不匹配", 400)
    if session is None:
        session = await crud_chat.create_session(db, user.id, "guide", message[:50])

    history_rows = await crud_chat.list_recent_messages(db, session.id, HISTORY_LIMIT)
    history_texts = [m.content for m in reversed(history_rows)]

    # 2. 需求提取（失败降级为纯语义召回）
    requirements = None
    try:
        requirements = await _extract_requirements(message, history_texts)
    except LLMError:
        logger.warning("导购需求提取失败，降级为纯语义搜索")

    # 3. 组合召回：品类 / 预算结构化过滤 + 语义相似度
    category_id = None
    min_price = max_price = None
    if requirements:
        if requirements.get("category"):
            category_id = await _match_category(db, requirements["category"])
        min_price = requirements.get("budget_min")
        max_price = requirements.get("budget_max")

    results: list[dict] = []
    try:
        results = await semantic_search_products(
            db,
            message,
            top_k=RECALL_K,
            category_id=category_id,
            min_price=min_price,
            max_price=max_price,
        )
    except LLMError:
        logger.warning("导购语义召回失败，降级结构化查询")
    if not results:
        # 语义服务不可用或无命中：按结构化条件（品类/预算）兜底
        products, _ = await crud_product.list_products(
            db,
            category_id=category_id,
            keyword=None,
            min_price=min_price,
            max_price=max_price,
            sort="sales",
            page=1,
            page_size=TOP_N,
        )
        results = [{"product": p, "similarity": None} for p in products]

    # 4. 相似度重排取前 N
    results = results[:TOP_N]

    # 5. 推荐话术（失败降级为无话术）
    reply = None
    if results:
        try:
            reply = await _generate_reply(message, requirements, results)
        except LLMError:
            logger.warning("导购话术生成失败，降级为纯商品结果")

    # 6. 商品卡片
    attributes = (requirements or {}).get("attributes") or []
    cards = [_product_card(row, attributes, max_price) for row in results]

    # 7. 会话消息持久化（用户消息 + 助手推荐结果）
    await crud_chat.add_message(db, session.id, "user", message)
    assistant_content = reply or (
        "抱歉，暂时没有找到符合您需求的商品，您可以换个说法或调整预算再试试。"
        if not cards
        else "根据您的需求，为您推荐以下商品："
    )
    await crud_chat.add_message(
        db, session.id, "assistant", assistant_content, tokens=max(len(assistant_content) // 2, 1)
    )

    return {
        "session_id": str(session.id),
        "requirements": requirements,
        "reply": reply,
        "products": cards,
    }
