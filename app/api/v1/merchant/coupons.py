"""商家端 - 优惠券接口：创建、列表。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_merchant, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import merchant as crud_merchant
from app.models import Merchant, User
from app.schemas.common import PageOut
from app.schemas.coupon import CouponOut
from app.schemas.merchant import CouponCreateIn

router = APIRouter(prefix="/merchant", tags=["商家端"])


@router.post("/coupons")
async def create_coupon(
    data: CouponCreateIn,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """创建本店优惠券：type 1 满减 / 2 折扣。"""
    _, merchant = auth
    if data.end_time <= data.start_time:
        raise BizError(5003, "结束时间必须晚于开始时间", 400)
    coupon = await crud_merchant.create_coupon(db, merchant.id, data)
    return ok(CouponOut.model_validate(coupon), message="创建成功")


@router.get("/coupons")
async def list_coupons(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """本店优惠券列表（含领取数量统计）。"""
    _, merchant = auth
    coupons, total = await crud_merchant.list_coupons(db, merchant.id, page, page_size)
    return ok(
        PageOut[CouponOut](
            items=[CouponOut.model_validate(c) for c in coupons],
            total=total,
            page=page,
            page_size=page_size,
        )
    )
