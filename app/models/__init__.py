"""导入所有模型，保证 create_all 时全部注册。"""
from app.models.user import User, UserAddress
from app.models.merchant import Merchant
from app.models.product import Category, Product, ProductSKU, ProductImage, InventoryLog, ProductEmbedding
from app.models.cart import CartItem
from app.models.order import Order, OrderItem, Payment, OrderStatus, PaymentStatus
from app.models.coupon import Coupon, UserCoupon
from app.models.interaction import Review, Favorite, SearchHistory, UserBehavior, EVENT_WEIGHTS
from app.models.ai import ChatSession, ChatMessage, KBDocument, KBChunk

__all__ = [
    "User", "UserAddress", "Merchant", "Category", "Product", "ProductSKU",
    "ProductImage", "InventoryLog", "ProductEmbedding", "CartItem", "Order",
    "OrderItem", "Payment", "OrderStatus", "PaymentStatus", "Coupon",
    "UserCoupon", "Review", "Favorite", "SearchHistory", "UserBehavior",
    "EVENT_WEIGHTS", "ChatSession", "ChatMessage", "KBDocument", "KBChunk",
]
