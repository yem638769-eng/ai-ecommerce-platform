"""向量检索：语义搜索与相似商品召回（pgvector cosine）。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductEmbedding
from app.services.ai.embedding import get_embedding


async def semantic_search_products(
    db: AsyncSession,
    query: str,
    top_k: int = 50,
    category_id: int | None = None,
    merchant_id: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """语义搜索：返回 [{"product": Product, "similarity": float}]，按相似度降序。"""
    query_vec = await get_embedding(query)
    distance = ProductEmbedding.embedding.cosine_distance(query_vec)
    stmt = (
        select(Product, distance.label("distance"))
        .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .where(Product.status == 1)
    )
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if merchant_id:
        stmt = stmt.where(Product.merchant_id == merchant_id)
    if min_price is not None:
        stmt = stmt.where(Product.price_max >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.price_min <= max_price)
    stmt = stmt.order_by(distance).limit(top_k)
    rows = await db.execute(stmt)
    return [{"product": row[0], "similarity": 1 - float(row[1])} for row in rows]


async def similar_products(
    db: AsyncSession, product_id: int, top_k: int = 8
) -> list[tuple[Product, float]]:
    """相似商品召回：返回 [(Product, similarity)]，排除自身与下架商品。"""
    stmt = select(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
    emb = (await db.execute(stmt)).scalar_one_or_none()
    if emb is None:
        return []
    distance = ProductEmbedding.embedding.cosine_distance(emb.embedding)
    stmt = (
        select(Product, distance.label("distance"))
        .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .where(Product.status == 1, Product.id != product_id)
        .order_by(distance)
        .limit(top_k)
    )
    rows = await db.execute(stmt)
    return [(row[0], 1 - float(row[1])) for row in rows]
