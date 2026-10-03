"""商家端路由聚合（§5.7）：店铺 / 商品 / 订单 / 统计 / 优惠券。"""
from fastapi import APIRouter

from app.api.v1.merchant import coupons, orders, products, shop, stats

router = APIRouter()
router.include_router(shop.router)
router.include_router(products.router)
router.include_router(orders.router)
router.include_router(stats.router)
router.include_router(coupons.router)
