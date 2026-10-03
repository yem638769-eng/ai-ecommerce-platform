"""优惠券接口：可领列表、领取、我的券、下单可用券匹配。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.response import ok
from app.crud import coupon as crud_coupon
from app.models import User
from app.schemas.coupon import CouponOut, UsableCouponOut, UserCouponOut

router = APIRouter(prefix="/coupons", tags=["优惠券"])


@router.get("")
async def list_coupons(
    merchant_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    coupons = await crud_coupon.list_available(db, merchant_id)
    return ok([CouponOut.model_validate(c) for c in coupons])


@router.get("/mine")
async def my_coupons(
    status: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_coupons = await crud_coupon.list_mine(db, user.id, status)
    return ok([UserCouponOut.model_validate(uc) for uc in user_coupons])


@router.get("/usable")
async def usable_coupons(
    order_amount: float = Query(..., gt=0, description="订单商品金额"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_coupons = await crud_coupon.list_usable(db, user.id, order_amount)
    return ok(
        [
            UsableCouponOut(
                user_coupon_id=uc.id,
                discount_amount=crud_coupon.calc_discount(uc.coupon, order_amount),
                coupon=CouponOut.model_validate(uc.coupon),
            )
            for uc in user_coupons
        ]
    )


@router.post("/{coupon_id}/receive")
async def receive_coupon(
    coupon_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_coupon = await crud_coupon.receive_coupon(db, user.id, coupon_id)
    return ok(UserCouponOut.model_validate(user_coupon), message="领取成功")
