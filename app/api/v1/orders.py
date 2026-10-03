"""订单接口：下单、我的订单、详情、取消、确认收货。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import order as crud_order
from app.models import User
from app.schemas.common import PageOut
from app.schemas.order import OrderCreateIn, OrderOut
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["订单"])


@router.post("")
async def create_order(
    data: OrderCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await order_service.create_order(db, user, data)
    return ok(OrderOut.model_validate(order), message="下单成功")


@router.get("")
async def list_orders(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    orders, total = await crud_order.list_for_user(db, user.id, status, page, page_size)
    return ok(
        PageOut(
            items=[OrderOut.model_validate(o) for o in orders],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/{order_no}")
async def get_order(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await crud_order.get_for_user(db, user.id, order_no)
    if order is None:
        raise BizError(4001, "订单不存在", 404)
    return ok(OrderOut.model_validate(order))


@router.post("/{order_no}/cancel")
async def cancel_order(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await order_service.cancel_order(db, user, order_no)
    return ok(OrderOut.model_validate(order), message="订单已取消")


@router.post("/{order_no}/confirm")
async def confirm_order(
    order_no: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    order = await order_service.confirm_order(db, user, order_no)
    return ok(OrderOut.model_validate(order), message="已确认收货")
