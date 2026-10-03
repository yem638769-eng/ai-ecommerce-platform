"""购物车接口：列表（实时校验价格/库存，标记失效商品）、加购、修改、删除。"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import cart as crud_cart
from app.models import Product, ProductSKU, User
from app.schemas.cart import CartAddIn, CartItemOut, CartOut, CartUpdateIn

router = APIRouter(prefix="/cart", tags=["购物车"])


async def _get_sku_with_product(db: AsyncSession, sku_id: int):
    """联查 SKU 与所属商品（显式 join，避免异步下懒加载）。"""
    stmt = (
        select(ProductSKU, Product)
        .join(Product, ProductSKU.product_id == Product.id)
        .where(ProductSKU.id == sku_id)
    )
    return (await db.execute(stmt)).first()


def _build_item_out(cart_item, sku, product) -> CartItemOut:
    price = float(sku.price)
    invalid = product.status != 1 or sku.status != 1 or sku.stock < cart_item.quantity
    return CartItemOut(
        id=cart_item.id,
        sku_id=sku.id,
        product_id=product.id,
        product_name=product.name,
        image=sku.image or product.main_image,
        sku_specs=sku.specs,
        price=price,
        stock=sku.stock,
        quantity=cart_item.quantity,
        checked=cart_item.checked,
        subtotal=round(price * cart_item.quantity, 2),
        invalid=invalid,
        created_at=cart_item.created_at,
    )


@router.get("")
async def get_cart(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await crud_cart.list_with_product(db, user.id)
    items = [_build_item_out(cart_item, sku, product) for cart_item, sku, product in rows]
    valid_items = [i for i in items if not i.invalid]
    return ok(
        CartOut(
            items=items,
            total_amount=round(sum(i.subtotal for i in valid_items), 2),
            checked_amount=round(sum(i.subtotal for i in valid_items if i.checked), 2),
            total_count=sum(i.quantity for i in valid_items),
        )
    )


@router.post("/items")
async def add_item(
    data: CartAddIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_sku_with_product(db, data.sku_id)
    if row is None:
        raise BizError(3001, "商品不存在或已下架", 404)
    sku, product = row
    if sku.status != 1 or product.status != 1:
        raise BizError(3001, "商品不存在或已下架", 404)

    existing = await crud_cart.get_by_sku(db, user.id, data.sku_id)
    new_quantity = data.quantity + (existing.quantity if existing else 0)
    if new_quantity > sku.stock:
        raise BizError(3002, "库存不足", 409)

    item = await crud_cart.add_item(db, user.id, data.sku_id, data.quantity)
    return ok({"id": item.id, "quantity": item.quantity}, message="已加入购物车")


@router.put("/items/{item_id}")
async def update_item(
    item_id: int,
    data: CartUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await crud_cart.get_item(db, user.id, item_id)
    if item is None:
        raise BizError(1006, "购物车项不存在", 404)

    if data.quantity is not None:
        row = await _get_sku_with_product(db, item.sku_id)
        if row is None:
            raise BizError(3001, "商品不存在或已下架", 404)
        sku, product = row
        if sku.status != 1 or product.status != 1:
            raise BizError(3001, "商品不存在或已下架", 404)
        if data.quantity > sku.stock:
            raise BizError(3002, "库存不足", 409)

    item = await crud_cart.update_item(db, item, data.quantity, data.checked)
    return ok(
        {"id": item.id, "quantity": item.quantity, "checked": item.checked},
        message="已更新",
    )


@router.delete("/items/{item_id}")
async def delete_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await crud_cart.get_item(db, user.id, item_id)
    if item is None:
        raise BizError(1006, "购物车项不存在", 404)
    await crud_cart.delete_item(db, item)
    return ok(message="已移除")


@router.delete("")
async def clear_invalid(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await crud_cart.delete_invalid(db, user.id)
    return ok({"removed": removed}, message="已清空失效商品")
