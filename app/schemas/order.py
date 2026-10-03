"""订单与支付相关模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OrderSkuItemIn(BaseModel):
    sku_id: int
    quantity: int = Field(..., ge=1, le=999)


class OrderCreateIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    address_id: int
    # buy_now 直接购买 / cart 购物车结算（取勾选商品，忽略 sku_items）
    from_: str = Field("buy_now", alias="from", pattern="^(cart|buy_now)$")
    sku_items: list[OrderSkuItemIn] = Field(default_factory=list)
    coupon_id: Optional[int] = None
    remark: Optional[str] = Field(None, max_length=200)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    sku_id: int
    product_name: str
    sku_specs: Optional[dict] = None
    image: Optional[str] = None
    price: float
    quantity: int
    subtotal: float


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    status: str
    total_amount: float
    discount_amount: float
    pay_amount: float
    address_snapshot: Optional[dict] = None
    items_snapshot: Optional[list] = None
    coupon_id: Optional[int] = None
    remark: Optional[str] = None
    tracking_no: Optional[str] = None
    paid_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_at: datetime
    items: list[OrderItemOut] = []


# ===== 支付 =====


class PaymentCreateIn(BaseModel):
    order_no: str
    pay_method: str = "mock"


class MockConfirmIn(BaseModel):
    transaction_id: str


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    pay_method: str
    amount: float
    status: str
    transaction_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
