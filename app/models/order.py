from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class OrderStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"

    ALL = (PENDING_PAYMENT, PAID, SHIPPED, COMPLETED, CANCELLED, REFUNDED)


class PaymentStatus:
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    pay_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    address_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    items_snapshot: Mapped[list | None] = mapped_column(JSONB)
    coupon_id: Mapped[int | None] = mapped_column(ForeignKey("user_coupons.id"))
    remark: Mapped[str | None] = mapped_column(String(200))
    tracking_no: Mapped[str | None] = mapped_column(String(50))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("product_skus.id"), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku_specs: Mapped[dict | None] = mapped_column(JSONB)
    image: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    order = relationship("Order", back_populates="items")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    pay_method: Mapped[str] = mapped_column(String(20), nullable=False, default="mock", server_default="mock")
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", server_default="PENDING")
    transaction_id: Mapped[str | None] = mapped_column(String(64), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
