from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    icon: Mapped[str | None] = mapped_column(String(500))

    children = relationship("Category", cascade="all, delete-orphan", lazy="selectin")


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_category_status", "category_id", "status"),
        Index("ix_products_sales", "sales_count"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    subtitle: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    main_image: Mapped[str] = mapped_column(String(500), nullable=False)
    price_min: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    price_max: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    # 0 草稿 / 1 上架 / 2 下架
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    sales_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 1), nullable=False, default=5.0, server_default="5.0")

    merchant = relationship("Merchant", back_populates="products", lazy="joined")
    category = relationship("Category", lazy="joined")
    skus = relationship(
        "ProductSKU", back_populates="product", cascade="all, delete-orphan",
        lazy="selectin", order_by="ProductSKU.id",
    )
    images = relationship(
        "ProductImage", back_populates="product", cascade="all, delete-orphan",
        lazy="selectin", order_by="ProductImage.sort",
    )
    embedding = relationship(
        "ProductEmbedding", back_populates="product",
        cascade="all, delete-orphan", lazy="selectin", uselist=False,
    )


class ProductSKU(TimestampMixin, Base):
    __tablename__ = "product_skus"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    sku_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    specs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    image: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")

    product = relationship("Product", back_populates="skus")


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    product = relationship("Product", back_populates="images")


class InventoryLog(Base):
    __tablename__ = "inventory_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("product_skus.id"), nullable=False, index=True)
    # purchase 下单扣减 / cancel 取消回滚 / restock 补货 / sale 支付核销
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductEmbedding(Base):
    __tablename__ = "product_embeddings"
    __table_args__ = (
        Index(
            "ix_product_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(settings.embed_dim), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    product = relationship("Product", back_populates="embedding")
