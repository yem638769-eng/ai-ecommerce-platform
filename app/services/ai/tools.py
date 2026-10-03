"""Agent 工具集（§6.6）：订单 / 商品 / 优惠券查询 + 危险操作二次确认。

- 只读工具：query_order / search_products / query_coupon / get_product_detail
- 危险工具：cancel_order / start_refund（未传 confirm=true 时只返回确认提示，不执行）
- 越权防护：所有查询与操作强制 user_id 过滤，只能访问本人数据
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.crud import order as crud_order
from app.crud import product as crud_product
from app.models import Coupon, Order, OrderStatus, Product, User, UserCoupon
from app.services import order_service
from app.services.ai.llm import LLMError
from app.services.ai.search import semantic_search_products

logger = logging.getLogger(__name__)

# 需要二次确认的危险工具
DANGEROUS_TOOLS = {"cancel_order", "start_refund"}

# 工具定义（OpenAI function calling 格式，llm.py 负责 Ollama 转换）
TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "查询当前用户的订单：可按订单号精确查询；或按状态筛选最近的订单；两者都不传时返回最近 5 笔订单。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {"type": "string", "description": "订单号（可选）"},
                    "status": {
                        "type": "string",
                        "enum": list(OrderStatus.ALL),
                        "description": "订单状态筛选（可选）",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "语义搜索在售商品：按自然语言关键词召回最相关的商品，可附加分类与价格过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词或需求描述"},
                    "category_id": {"type": "integer", "description": "分类 ID（可选）"},
                    "min_price": {"type": "number", "description": "最低价（可选）"},
                    "max_price": {"type": "number", "description": "最高价（可选）"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_coupon",
            "description": "查询当前用户持有的可用优惠券（未使用且在有效期内）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_detail",
            "description": "按商品 ID 查询在售商品详情（价格区间、库存、销量、描述）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer", "description": "商品 ID"},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "取消当前用户的订单（仅待支付订单可取消）。危险操作：必须先向用户确认，用户明确同意后才传 confirm=true。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {"type": "string", "description": "订单号"},
                    "confirm": {
                        "type": "boolean",
                        "description": "用户明确同意后才传 true，其余情况必须传 false 或不传",
                    },
                },
                "required": ["order_no"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_refund",
            "description": "为当前用户的订单发起退款申请（仅已支付/已发货/已完成订单可申请）。危险操作：必须先向用户确认，用户明确同意后才传 confirm=true。",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_no": {"type": "string", "description": "订单号"},
                    "reason": {"type": "string", "description": "退款原因"},
                    "confirm": {
                        "type": "boolean",
                        "description": "用户明确同意后才传 true，其余情况必须传 false 或不传",
                    },
                },
                "required": ["order_no"],
            },
        },
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_time(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None


def _order_brief(order: Order) -> dict:
    """订单摘要（给 LLM 的精简结构）。"""
    return {
        "order_no": order.order_no,
        "status": order.status,
        "total_amount": float(order.total_amount),
        "pay_amount": float(order.pay_amount),
        "tracking_no": order.tracking_no,
        "created_at": _fmt_time(order.created_at),
        "items": [
            {"product_name": it.product_name, "quantity": it.quantity, "price": float(it.price)}
            for it in (order.items or [])
        ],
    }


async def _tool_query_order(db: AsyncSession, user: User, args: dict) -> dict:
    order_no = str(args.get("order_no") or "").strip()
    status = str(args.get("status") or "").strip()
    if order_no:
        stmt = select(Order).where(Order.order_no == order_no, Order.user_id == user.id)
        order = (await db.execute(stmt)).scalar_one_or_none()
        if order is None:
            return {"success": False, "message": f"未找到您的订单 {order_no}"}
        return {"success": True, "order": _order_brief(order)}

    stmt = select(Order).where(Order.user_id == user.id)
    if status:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.created_at.desc()).limit(5)
    orders = list((await db.execute(stmt)).scalars())
    if not orders:
        return {"success": True, "orders": [], "message": "您暂无相关订单"}
    return {"success": True, "orders": [_order_brief(o) for o in orders]}


async def _tool_search_products(db: AsyncSession, user: User, args: dict) -> dict:
    keyword = str(args.get("keyword") or "").strip()
    if not keyword:
        return {"success": False, "message": "缺少搜索关键词"}

    def _cards(products_with_sim) -> list[dict]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "subtitle": p.subtitle,
                "price_min": float(p.price_min),
                "price_max": float(p.price_max),
                "main_image": p.main_image,
                "sales_count": p.sales_count,
                "similarity": round(sim, 4) if sim is not None else None,
            }
            for p, sim in products_with_sim
        ]

    try:
        results = await semantic_search_products(
            db,
            keyword,
            top_k=5,
            category_id=args.get("category_id"),
            min_price=args.get("min_price"),
            max_price=args.get("max_price"),
        )
        cards = _cards([(r["product"], r["similarity"]) for r in results])
    except LLMError:
        logger.warning("Agent 语义搜索不可用，降级关键词查询: %s", keyword)
        cards = []

    if not cards:
        # 语义服务不可用或无向量结果：关键词 LIKE 兜底
        products, _ = await crud_product.list_products(
            db,
            category_id=args.get("category_id"),
            keyword=keyword,
            min_price=args.get("min_price"),
            max_price=args.get("max_price"),
            sort="sales",
            page=1,
            page_size=5,
        )
        cards = _cards([(p, None) for p in products])

    if not cards:
        return {"success": True, "products": [], "message": "未找到相关商品"}
    return {"success": True, "products": cards}


async def _tool_query_coupon(db: AsyncSession, user: User, args: dict) -> dict:
    now = _now()
    stmt = (
        select(UserCoupon)
        .join(Coupon, Coupon.id == UserCoupon.coupon_id)
        .where(UserCoupon.user_id == user.id, UserCoupon.status == 1, Coupon.end_time >= now)
        .order_by(UserCoupon.id.desc())
        .limit(10)
    )
    rows = list((await db.execute(stmt)).scalars())
    if not rows:
        return {"success": True, "coupons": [], "message": "您暂无可用优惠券"}
    coupons = [
        {
            "id": uc.id,
            "name": uc.coupon.name,
            "type": "满减" if uc.coupon.type == 1 else "折扣",
            "value": float(uc.coupon.value),
            "min_amount": float(uc.coupon.min_amount),
            "end_time": _fmt_time(uc.coupon.end_time),
        }
        for uc in rows
    ]
    return {"success": True, "coupons": coupons}


async def _tool_get_product_detail(db: AsyncSession, user: User, args: dict) -> dict:
    product_id = args.get("product_id")
    if not isinstance(product_id, int):
        return {"success": False, "message": "缺少商品 ID"}
    stmt = select(Product).where(Product.id == product_id, Product.status == 1)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product is None:
        return {"success": False, "message": f"商品 {product_id} 不存在或已下架"}
    return {
        "success": True,
        "product": {
            "id": product.id,
            "name": product.name,
            "subtitle": product.subtitle,
            "description": (product.description or "")[:300],
            "price_min": float(product.price_min),
            "price_max": float(product.price_max),
            "sales_count": product.sales_count,
            "rating_avg": float(product.rating_avg),
            "total_stock": sum(sku.stock for sku in product.skus),
        },
    }


async def _tool_cancel_order(db: AsyncSession, user: User, args: dict) -> dict:
    order_no = str(args.get("order_no") or "").strip()
    if not order_no:
        return {"success": False, "message": "缺少订单号"}
    order = await crud_order.get_for_user(db, user.id, order_no)
    if order is None:
        return {"success": False, "message": f"未找到您的订单 {order_no}"}
    if not args.get("confirm"):
        # 第一轮：不执行，仅返回确认提示，由 LLM 向用户求确认
        return {
            "need_confirm": True,
            "message": (
                f"即将取消订单 {order_no}（应付 ¥{float(order.pay_amount)}，"
                f"共 {len(order.items or [])} 件商品），取消后不可恢复。请向用户确认是否取消。"
            ),
            "order_no": order_no,
        }
    try:
        order = await order_service.cancel_order(db, user, order_no)
    except BizError as e:
        return {"success": False, "message": e.message}
    return {
        "success": True,
        "message": f"订单 {order_no} 已取消",
        "order": _order_brief(order),
    }


async def _tool_start_refund(db: AsyncSession, user: User, args: dict) -> dict:
    order_no = str(args.get("order_no") or "").strip()
    reason = str(args.get("reason") or "").strip() or "未填写"
    if not order_no:
        return {"success": False, "message": "缺少订单号"}
    order = await crud_order.get_for_user(db, user.id, order_no)
    if order is None:
        return {"success": False, "message": f"未找到您的订单 {order_no}"}
    if order.status not in (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.COMPLETED):
        return {
            "success": False,
            "message": f"订单 {order_no} 当前状态（{order.status}）不支持申请退款",
        }
    if not args.get("confirm"):
        # 第一轮：不执行，仅返回确认提示，由 LLM 向用户求确认
        return {
            "need_confirm": True,
            "message": (
                f"即将为订单 {order_no}（实付 ¥{float(order.pay_amount)}）发起退款申请，"
                f"退款原因：{reason}。请向用户确认是否申请。"
            ),
            "order_no": order_no,
            "reason": reason,
        }
    # 支付为 mock，无独立售后表：直接将订单置为已退款，并在备注中登记原因
    order.status = OrderStatus.REFUNDED
    refund_note = f"[AI售后] {reason}"
    order.remark = (
        f"{order.remark} | {refund_note}" if order.remark else refund_note
    )[:200]
    await db.commit()
    await db.refresh(order)
    return {
        "success": True,
        "message": f"订单 {order_no} 退款申请已受理",
        "order": _order_brief(order),
    }


_HANDLERS = {
    "query_order": _tool_query_order,
    "search_products": _tool_search_products,
    "query_coupon": _tool_query_coupon,
    "get_product_detail": _tool_get_product_detail,
    "cancel_order": _tool_cancel_order,
    "start_refund": _tool_start_refund,
}


async def execute_tool(db: AsyncSession, user: User, name: str, args: dict) -> dict:
    """执行工具并返回结果 dict（作为 role=tool 消息内容回传 LLM）。

    危险工具未带 confirm=true 时只返回确认提示，不执行任何写操作。
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"success": False, "message": f"未知工具 {name}"}
    try:
        return await handler(db, user, args or {})
    except BizError as e:
        return {"success": False, "message": e.message}
    except Exception:
        logger.exception("Agent 工具执行异常: %s", name)
        await db.rollback()
        return {"success": False, "message": "工具执行出错，请稍后再试"}
