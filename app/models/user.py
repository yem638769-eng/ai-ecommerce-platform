from sqlalchemy import BigInteger, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(120), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user", server_default="user")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")

    addresses: Mapped[list["UserAddress"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class UserAddress(TimestampMixin, Base):
    __tablename__ = "user_addresses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    receiver: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    province: Mapped[str] = mapped_column(String(50), nullable=False)
    city: Mapped[str] = mapped_column(String(50), nullable=False)
    district: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[str] = mapped_column(String(200), nullable=False)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    user: Mapped[User] = relationship(back_populates="addresses")
