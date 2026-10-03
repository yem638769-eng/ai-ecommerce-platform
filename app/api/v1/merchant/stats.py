"""商家端 - 数据统计接口：经营看板、商品销量排行、逐日趋势。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_merchant, get_db
from app.core.response import ok
from app.crud import merchant as crud_merchant
from app.models import Merchant, User
from app.schemas.merchant import DashboardOut, ProductSalesOut, TrendItemOut

router = APIRouter(prefix="/merchant", tags=["商家端"])


@router.get("/stats/dashboard")
async def dashboard(
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """经营看板：总销售额 / 总订单数 / 在售商品数 / 待发货订单数。"""
    _, merchant = auth
    data = await crud_merchant.get_dashboard(db, merchant.id)
    return ok(DashboardOut(**data))


@router.get("/stats/products")
async def product_sales_rank(
    limit: int = Query(10, ge=1, le=50),
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """本店商品销量排行 top N（按有效订单的销量聚合）。"""
    _, merchant = auth
    rows = await crud_merchant.get_product_sales_rank(db, merchant.id, limit)
    return ok([ProductSalesOut(**row) for row in rows])


@router.get("/stats/trend")
async def sales_trend(
    days: int = Query(7, ge=1, le=90),
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """近 N 天逐日销售额 / 订单量趋势（按支付时间聚合，补齐无数据日期）。"""
    _, merchant = auth
    trend = await crud_merchant.get_sales_trend(db, merchant.id, days)
    return ok([TrendItemOut(**item) for item in trend])
