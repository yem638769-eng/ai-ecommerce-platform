from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Coupon(TimestampMixin, Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 1 满减（value=固定金额） / 2 折扣（value=折扣率，0.9=九折）
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    min_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    received_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 1 启用 / 0 停用
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")


class UserCoupon(TimestampMixin, Base):
    __tablename__ = "user_coupons"
    __table_args__ = ({"comment": "用户持券表"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # 1 未使用 / 2 已使用 / 3 已过期
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    coupon = relationship("Coupon", lazy="joined")
