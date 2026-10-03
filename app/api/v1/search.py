"""搜索接口：语义搜索（LLM 异常降级关键词）与搜索联想。"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user_optional, get_db
from app.core.redis import redis
from app.core.response import ok
from app.crud import product as crud_product
from app.models import SearchHistory, User
from app.schemas.common import PageOut
from app.schemas.product import SearchItemOut
from app.services.ai.llm import LLMError
from app.services.ai.search import semantic_search_products

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["搜索"])

# 热搜词 ZSet（文档未定义具体 key，按 rank:* 惯例自定义）
_HOT_KEYWORDS_KEY = "search:hot:keywords"


async def _record_search(db: AsyncSession, user_id: int | None, keyword: str) -> None:
    """登录用户写搜索历史，关键词计入热搜 ZSet；失败仅记日志不影响主流程。"""
    if user_id is not None:
        try:
            db.add(SearchHistory(user_id=user_id, keyword=keyword))
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("写入搜索历史失败: user=%s keyword=%s", user_id, keyword)
    try:
        await redis.zincrby(_HOT_KEYWORDS_KEY, 1, keyword)
    except Exception:
        logger.exception("更新热搜词失败: keyword=%s", keyword)


def _highlight(text: str | None, keyword: str) -> str | None:
    """从文本中截取包含关键词的片段，关键词用 <em> 强调；未命中返回 None。"""
    if not text or not keyword:
        return None
    pos = text.find(keyword)
    if pos < 0:
        return None
    start = max(0, pos - 20)
    end = min(len(text), pos + len(keyword) + 40)
    snippet = ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
    return snippet.replace(keyword, f"<em>{keyword}</em>", 1)


def _product_highlight(product, keyword: str) -> str | None:
    return _highlight(product.subtitle or product.description, keyword)


@router.get("")
async def search(
    q: str = Query(..., min_length=1, max_length=100, description="自然语言搜索词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """语义搜索：向量召回 top-50 与关键词命中融合排序；LLM 服务异常时降级关键词过滤。"""
    items: list[dict] = []
    try:
        results = await semantic_search_products(db, q, top_k=50)
        items = [
            {
                "product": row["product"],
                "similarity": row["similarity"],
                "highlight": _product_highlight(row["product"], q),
            }
            for row in results
        ]
    except LLMError:
        logger.warning("语义搜索不可用，降级为关键词搜索: %s", q)

    # 关键词 LIKE 融合：向量结果中命中的加成排序，未进榜的关键词命中商品追加
    like_products, _ = await crud_product.list_products(
        db,
        category_id=None,
        keyword=q,
        min_price=None,
        max_price=None,
        sort="sales",
        page=1,
        page_size=50,
    )
    like_ids = {p.id for p in like_products}
    for item in items:
        if item["product"].id in like_ids:
            item["similarity"] = item["similarity"] + 0.1
    vector_ids = {item["product"].id for item in items}
    for product in like_products:
        if product.id not in vector_ids:
            items.append(
                {
                    "product": product,
                    "similarity": None,
                    "highlight": _product_highlight(product, q),
                }
            )
    items.sort(
        key=lambda it: it["similarity"] if it["similarity"] is not None else -1.0,
        reverse=True,
    )

    await _record_search(db, user.id if user else None, q)

    total = len(items)
    start = (page - 1) * page_size
    out = [
        SearchItemOut(
            id=item["product"].id,
            name=item["product"].name,
            subtitle=item["product"].subtitle,
            price_min=float(item["product"].price_min),
            main_image=item["product"].main_image,
            sales_count=item["product"].sales_count,
            similarity=item["similarity"],
            highlight=item["highlight"],
        )
        for item in items[start : start + page_size]
    ]
    return ok(
        PageOut[SearchItemOut](items=out, total=total, page=page, page_size=page_size)
    )


@router.get("/suggest")
async def suggest(
    q: str = Query("", max_length=100, description="联想前缀"),
    limit: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """搜索联想：商品名前缀匹配 + 热搜词 ZSet。"""
    hot_words: list[str] = []
    try:
        hot_words = await redis.zrevrange(_HOT_KEYWORDS_KEY, 0, limit - 1)
    except Exception:
        logger.exception("读取热搜词失败")

    keywords: list[str] = []
    if q:
        keywords = await crud_product.suggest_keywords(db, q, limit)

    return ok({"keywords": keywords, "hot": hot_words})
