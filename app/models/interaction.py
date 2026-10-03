from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

# 推荐系统行为权重
EVENT_WEIGHTS = {"view": 1, "click": 2, "cart": 3, "favorite": 4, "purchase": 5}


class Review(TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (Index("ix_reviews_product_created", "product_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    images: Mapped[list | None] = mapped_column(JSONB)

    user = relationship("User", lazy="joined")


class Favorite(TimestampMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_favorites_user_product"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)

    product = relationship("Product", lazy="joined")


class SearchHistory(Base):
    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UserBehavior(Base):
    __tablename__ = "user_behaviors"
    __table_args__ = (
        Index("ix_behaviors_user_created", "user_id", "created_at"),
        Index("ix_behaviors_product_event", "product_id", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    # view / click / cart / favorite / purchase
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
