"""收藏 CRUD：幂等的收藏 / 取消收藏与收藏列表。"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Favorite


async def add_favorite(db: AsyncSession, user_id: int, product_id: int) -> Favorite:
    """收藏商品（幂等：已收藏直接返回原记录）。"""
    stmt = select(Favorite).where(
        Favorite.user_id == user_id, Favorite.product_id == product_id
    )
    favorite = (await db.execute(stmt)).scalar_one_or_none()
    if favorite is not None:
        return favorite
    favorite = Favorite(user_id=user_id, product_id=product_id)
    db.add(favorite)
    await db.commit()
    await db.refresh(favorite)
    return favorite


async def remove_favorite(db: AsyncSession, user_id: int, product_id: int) -> None:
    """取消收藏（幂等：未收藏时静默成功）。"""
    stmt = select(Favorite).where(
        Favorite.user_id == user_id, Favorite.product_id == product_id
    )
    favorite = (await db.execute(stmt)).scalar_one_or_none()
    if favorite is not None:
        await db.delete(favorite)
        await db.commit()


async def list_favorites(
    db: AsyncSession, user_id: int, page: int, page_size: int
) -> tuple[list[Favorite], int]:
    """我的收藏分页（最新在前，商品信息由 joined 关系加载）。"""
    base = select(Favorite).where(Favorite.user_id == user_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    stmt = (
        base.order_by(Favorite.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    favorites = list((await db.execute(stmt)).scalars())
    return favorites, int(total or 0)
