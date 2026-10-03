from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class CartItem(TimestampMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "sku_id", name="uq_cart_user_sku"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("product_skus.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    sku = relationship("ProductSKU", lazy="joined")
