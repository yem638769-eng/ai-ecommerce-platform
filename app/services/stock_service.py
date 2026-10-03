"""库存服务：条件更新库存并记录库存流水（M4 商家端会直接调用 adjust_stock）。"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryLog, ProductSKU


async def adjust_stock(
    db: AsyncSession,
    sku_id: int,
    delta: int,
    change_type: str,
    order_id: int | None = None,
) -> ProductSKU:
    """条件更新 SKU 库存并写一条库存流水。

    - delta > 0：回补（cancel 取消回滚 / restock 补货），无附加条件；
    - delta < 0：条件扣减（purchase 下单扣减），要求 stock >= |delta|，
      库存不足时不动库存、不写流水，返回 None；
    - change_type：purchase 下单扣减 / cancel 取消回滚 / restock 补货；
    - InventoryLog.quantity 记录带符号的库存变化量。
    """
    if delta < 0:
        stmt = (
            update(ProductSKU)
            .where(ProductSKU.id == sku_id, ProductSKU.stock >= -delta)
            .values(stock=ProductSKU.stock + delta)
        )
    else:
        stmt = (
            update(ProductSKU)
            .where(ProductSKU.id == sku_id)
            .values(stock=ProductSKU.stock + delta)
        )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        return None

    db.add(
        InventoryLog(
            sku_id=sku_id, change_type=change_type, quantity=delta, order_id=order_id
        )
    )
    await db.commit()

    # 重新读取，保证返回的是数据库中的最新库存
    sku = (
        await db.execute(
            select(ProductSKU)
            .where(ProductSKU.id == sku_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return sku
