"""订单 CRUD：查询 / 分页 / 发货（M4 商家端契约）。"""
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.models import Order, OrderItem, OrderStatus, Product


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_by_no(db: AsyncSession, order_no: str) -> Order | None:
    stmt = select(Order).where(Order.order_no == order_no)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_for_user(db: AsyncSession, user_id: int, order_no: str) -> Order | None:
    stmt = select(Order).where(Order.order_no == order_no, Order.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _paginate(
    db: AsyncSession, stmt, page: int, page_size: int
) -> tuple[list[Order], int]:
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).scalars()
    return list(rows), total


async def list_for_user(
    db: AsyncSession,
    user_id: int,
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Order], int]:
    stmt = select(Order).where(Order.user_id == user_id)
    if status:
        stmt = stmt.where(Order.status == status)
    stmt = stmt.order_by(Order.created_at.desc())
    return await _paginate(db, stmt, page, page_size)


async def list_for_merchant(
    db: AsyncSession,
    merchant_id: int,
    status: str | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Order], int]:
    """店铺订单列表：经订单项关联到本店商品，keyword 匹配订单号/收货人。"""
    stmt = (
        select(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Product.merchant_id == merchant_id)
    )
    if status:
        stmt = stmt.where(Order.status == status)
    if keyword:
        receiver = Order.address_snapshot["receiver"].astext
        stmt = stmt.where(
            or_(
                Order.order_no.ilike(f"%{keyword}%"),
                receiver.ilike(f"%{keyword}%"),
            )
        )
    stmt = stmt.distinct().order_by(Order.created_at.desc())
    return await _paginate(db, stmt, page, page_size)


async def ship(db: AsyncSession, order: Order, tracking_no: str) -> Order:
    """发货：PAID → SHIPPED 并记录 shipped_at；状态不符抛 4002。"""
    if order.status != OrderStatus.PAID:
        raise BizError(4002, "当前状态不允许发货", 400)
    order.tracking_no = tracking_no
    order.status = OrderStatus.SHIPPED
    order.shipped_at = _now()
    await db.commit()
    await db.refresh(order)
    return order
