"""商家端 - 订单接口：店铺订单列表、发货。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_merchant, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import merchant as crud_merchant
from app.crud import order as crud_order
from app.models import Merchant, User
from app.schemas.common import PageOut
from app.schemas.merchant import ShipIn
from app.schemas.order import OrderOut

router = APIRouter(prefix="/merchant", tags=["商家端"])


@router.get("/orders")
async def list_orders(
    status: str | None = None,
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """店铺订单列表：经订单项关联本店商品，keyword 匹配订单号 / 收货人。"""
    _, merchant = auth
    orders, total = await crud_order.list_for_merchant(
        db, merchant.id, status, keyword, page, page_size
    )
    return ok(
        PageOut[OrderOut](
            items=[OrderOut.model_validate(o) for o in orders],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/orders/{order_no}/ship")
async def ship_order(
    order_no: str,
    data: ShipIn,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """发货：仅限包含本店商品的 PAID 订单。"""
    _, merchant = auth
    order = await crud_order.get_by_no(db, order_no)
    if order is None:
        raise BizError(4001, "订单不存在", 404)
    if not await crud_merchant.order_has_shop_items(db, merchant.id, order.id):
        raise BizError(4003, "无权操作该订单", 403)
    order = await crud_order.ship(db, order, data.tracking_no)
    return ok(OrderOut.model_validate(order), message="发货成功")
