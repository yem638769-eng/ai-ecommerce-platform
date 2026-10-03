"""优惠券相关模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: Optional[int] = None
    name: str
    # 1 满减 / 2 折扣
    type: int
    value: float
    min_amount: float
    total_count: int
    received_count: int
    start_time: datetime
    end_time: datetime


class UserCouponOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    coupon_id: int
    # 1 未使用 / 2 已使用 / 3 已过期
    status: int
    received_at: datetime
    used_at: Optional[datetime] = None
    coupon: CouponOut


class UsableCouponOut(BaseModel):
    """下单可用券：持券信息 + 该金额下可抵扣金额。"""

    user_coupon_id: int
    discount_amount: float
    coupon: CouponOut
