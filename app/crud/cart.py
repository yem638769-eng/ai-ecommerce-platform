"""购物车 CRUD：列表/加购/修改/删除，均按当前用户隔离。"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CartItem, Product, ProductSKU


async def get_item(db: AsyncSession, user_id: int, item_id: int) -> CartItem | None:
    stmt = select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_sku(db: AsyncSession, user_id: int, sku_id: int) -> CartItem | None:
    stmt = select(CartItem).where(CartItem.user_id == user_id, CartItem.sku_id == sku_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _list_join(db: AsyncSession, user_id: int, checked_only: bool) -> list[tuple[CartItem, ProductSKU, Product]]:
    """联查购物车项 + SKU + 商品（显式 join，避免异步下懒加载）。"""
    stmt = (
        select(CartItem, ProductSKU, Product)
        .join(ProductSKU, CartItem.sku_id == ProductSKU.id)
        .join(Product, ProductSKU.product_id == Product.id)
        .where(CartItem.user_id == user_id)
        .order_by(CartItem.id.desc())
    )
    if checked_only:
        stmt = stmt.where(CartItem.checked.is_(True))
    return list((await db.execute(stmt)).all())


async def list_with_product(
    db: AsyncSession, user_id: int
) -> list[tuple[CartItem, ProductSKU, Product]]:
    return await _list_join(db, user_id, checked_only=False)


async def list_checked_with_product(
    db: AsyncSession, user_id: int
) -> list[tuple[CartItem, ProductSKU, Product]]:
    return await _list_join(db, user_id, checked_only=True)


async def add_item(db: AsyncSession, user_id: int, sku_id: int, quantity: int) -> CartItem:
    """加购：同一 SKU 已在购物车则累加数量。"""
    item = await get_by_sku(db, user_id, sku_id)
    if item is None:
        item = CartItem(user_id=user_id, sku_id=sku_id, quantity=quantity, checked=True)
        db.add(item)
    else:
        item.quantity += quantity
    await db.commit()
    await db.refresh(item)
    return item


async def update_item(
    db: AsyncSession,
    item: CartItem,
    quantity: int | None = None,
    checked: bool | None = None,
) -> CartItem:
    if quantity is not None:
        item.quantity = quantity
    if checked is not None:
        item.checked = checked
    await db.commit()
    await db.refresh(item)
    return item


async def delete_item(db: AsyncSession, item: CartItem) -> None:
    await db.delete(item)
    await db.commit()


async def delete_by_skus(db: AsyncSession, user_id: int, sku_ids: list[int]) -> None:
    """删除指定 SKU 的购物车项（购物车结算后调用）。"""
    if not sku_ids:
        return
    await db.execute(
        delete(CartItem).where(CartItem.user_id == user_id, CartItem.sku_id.in_(sku_ids))
    )
    await db.commit()


async def delete_invalid(db: AsyncSession, user_id: int) -> int:
    """清空失效商品（已下架 / 停用 / 无库存），返回删除条数。"""
    invalid_ids = (
        select(CartItem.id)
        .join(ProductSKU, CartItem.sku_id == ProductSKU.id)
        .join(Product, ProductSKU.product_id == Product.id)
        .where(
            CartItem.user_id == user_id,
            (Product.status != 1) | (ProductSKU.status != 1) | (ProductSKU.stock < 1),
        )
        .scalar_subquery()
    )
    result = await db.execute(delete(CartItem).where(CartItem.id.in_(invalid_ids)))
    await db.commit()
    return result.rowcount or 0
