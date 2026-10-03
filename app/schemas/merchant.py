"""商家端出入参模型（§5.7）。商品 / 订单 / 券的输出复用既有 ProductOut / OrderOut / CouponOut。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ===== 店铺 =====


class ShopRegisterIn(BaseModel):
    """开店申请入参。"""

    shop_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    logo: Optional[str] = Field(None, max_length=500)


class MerchantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    shop_name: str
    logo: Optional[str] = None
    description: Optional[str] = None
    status: int
    rating: float
    created_at: datetime


# ===== 库存 / 发货 =====


class StockAdjustIn(BaseModel):
    """库存调整入参：delta 正数补货、负数扣减。"""

    delta: int


class ShipIn(BaseModel):
    """发货入参。"""

    tracking_no: str = Field(..., min_length=1, max_length=50)


# ===== 优惠券 =====


class CouponCreateIn(BaseModel):
    """创建优惠券：type 1 满减（value=固定金额）/ 2 折扣（value=折扣率，0.9=九折）。"""

    name: str = Field(..., min_length=1, max_length=100)
    type: int = Field(..., ge=1, le=2)
    value: float = Field(..., gt=0)
    min_amount: float = Field(0, ge=0)
    total_count: int = Field(..., ge=0)
    start_time: datetime
    end_time: datetime


# ===== 数据统计 =====


class DashboardOut(BaseModel):
    """经营看板。"""

    total_sales: float  # 总销售额（PAID/SHIPPED/COMPLETED 订单的 pay_amount 合计）
    total_orders: int  # 总订单数（包含本店商品的去重订单数）
    on_sale_products: int  # 在售商品数
    pending_ship_orders: int  # 待发货订单数（已支付未发货）


class ProductSalesOut(BaseModel):
    """商品销量排行项。"""

    product_id: int
    product_name: str
    sales: int
    sales_amount: float


class TrendItemOut(BaseModel):
    """逐日销售额趋势项。"""

    date: str
    sales: float
    order_count: int
