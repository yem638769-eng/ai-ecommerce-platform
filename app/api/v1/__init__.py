"""API 路由聚合。"""
from fastapi import APIRouter

from app.api.v1 import (
    ai,
    ai_kb,
    auth,
    cart,
    coupons,
    merchant,
    orders,
    payments,
    products,
    search,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(products.router)
api_router.include_router(search.router)
api_router.include_router(cart.router)
api_router.include_router(orders.router)
api_router.include_router(payments.router)
api_router.include_router(coupons.router)
api_router.include_router(merchant.router)
api_router.include_router(ai.router)
api_router.include_router(ai_kb.router)
