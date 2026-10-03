"""商家端 - 商品接口：本店商品管理（含草稿 / 下架）、上下架、库存调整。"""
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_merchant, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import merchant as crud_merchant
from app.crud import product as crud_product
from app.models import Merchant, Product, User
from app.schemas.common import PageOut
from app.schemas.merchant import StockAdjustIn
from app.schemas.product import ProductCreateIn, ProductOut, ProductUpdateIn, SKUOut
from app.services import stock_service

router = APIRouter(prefix="/merchant", tags=["商家端"])


async def _rebuild_product_embedding(product_id: int) -> None:
    """后台任务：上架后重建商品向量索引（延迟导入，避免模块级依赖 AI 中台）。"""
    from app.services.ai import indexing

    await indexing.rebuild_product_embedding(product_id)


async def _remove_product_embedding(product_id: int) -> None:
    """后台任务：下架后删除商品向量索引（延迟导入，避免模块级依赖 AI 中台）。"""
    from app.services.ai import indexing

    await indexing.remove_product_embedding(product_id)


async def _get_owned_product(
    db: AsyncSession, merchant_id: int, product_id: int
) -> Product:
    """取本店商品（不限状态）；不存在或非本店商品一律按 3001 处理。"""
    product = await crud_merchant.get_shop_product(db, merchant_id, product_id)
    if product is None:
        raise BizError(3001, "商品不存在", 404)
    return product


@router.post("/products")
async def create_product(
    data: ProductCreateIn,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """创建商品（默认草稿，需手动上架）。"""
    _, merchant = auth
    product = await crud_product.create_product(db, merchant.id, data)
    return ok(ProductOut.model_validate(product), message="创建成功")


@router.get("/products")
async def list_products(
    status: int | None = Query(None, ge=0, le=2),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """本店商品列表（含草稿 / 下架）：状态 + 关键词过滤 + 分页。"""
    _, merchant = auth
    products, total = await crud_merchant.list_shop_products(
        db, merchant.id, status, keyword, page, page_size
    )
    return ok(
        PageOut[ProductOut](
            items=[ProductOut.model_validate(p) for p in products],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/products/{product_id}")
async def get_product(
    product_id: int,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """本店商品详情（含草稿 / 下架）。"""
    _, merchant = auth
    product = await _get_owned_product(db, merchant.id, product_id)
    return ok(ProductOut.model_validate(product))


@router.put("/products/{product_id}")
async def update_product(
    product_id: int,
    data: ProductUpdateIn,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """编辑本店商品；skus / images 传入则整体替换。"""
    _, merchant = auth
    product = await _get_owned_product(db, merchant.id, product_id)
    product = await crud_product.update_product(db, product, data)
    return ok(ProductOut.model_validate(product), message="更新成功")


@router.post("/products/{product_id}/on")
async def on_shelf_product(
    product_id: int,
    background_tasks: BackgroundTasks,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """上架：更新状态后异步重建向量索引。"""
    _, merchant = auth
    product = await _get_owned_product(db, merchant.id, product_id)
    product = await crud_product.set_product_status(db, product, 1)
    background_tasks.add_task(_rebuild_product_embedding, product_id)
    return ok(ProductOut.model_validate(product), message="上架成功")


@router.post("/products/{product_id}/off")
async def off_shelf_product(
    product_id: int,
    background_tasks: BackgroundTasks,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """下架：更新状态后异步删除向量索引。"""
    _, merchant = auth
    product = await _get_owned_product(db, merchant.id, product_id)
    product = await crud_product.set_product_status(db, product, 2)
    background_tasks.add_task(_remove_product_embedding, product_id)
    return ok(ProductOut.model_validate(product), message="下架成功")


@router.put("/skus/{sku_id}/stock")
async def adjust_stock(
    sku_id: int,
    data: StockAdjustIn,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """调整 SKU 库存：delta 正数补货 / 负数扣减，写库存流水。"""
    _, merchant = auth
    if await crud_merchant.get_shop_sku(db, merchant.id, sku_id) is None:
        raise BizError(3001, "SKU 不存在", 404)
    sku = await stock_service.adjust_stock(db, sku_id, data.delta, "restock")
    if sku is None:
        raise BizError(3002, "库存不足", 409)
    return ok(SKUOut.model_validate(sku), message="库存已更新")
