"""购物车相关模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CartAddIn(BaseModel):
    sku_id: int
    quantity: int = Field(1, ge=1, le=999)


class CartUpdateIn(BaseModel):
    quantity: Optional[int] = Field(None, ge=1, le=999)
    checked: Optional[bool] = None


class CartItemOut(BaseModel):
    id: int
    sku_id: int
    product_id: int
    product_name: str
    image: Optional[str] = None
    sku_specs: Optional[dict] = None
    price: float
    stock: int
    quantity: int
    checked: bool
    subtotal: float
    # 商品下架 / SKU 停用 / 库存不足 时标记失效
    invalid: bool
    created_at: datetime


class CartOut(BaseModel):
    items: list[CartItemOut]
    # 有效商品金额合计
    total_amount: float
    # 勾选商品金额合计
    checked_amount: float
    # 有效商品件数合计
    total_count: int
