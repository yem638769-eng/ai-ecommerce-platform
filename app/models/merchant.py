from sqlalchemy import BigInteger, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Merchant(TimestampMixin, Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    shop_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    logo: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    # 1 营业 / 0 冻结 / 2 审核中
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    rating: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False, default=5.0, server_default="5.0")

    user = relationship("User")
    products = relationship("Product", back_populates="merchant", lazy="selectin")
