"""商品 / 分类 / 评价 / 收藏接口（用户端，§5.3 / §5.6）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_user_optional, get_db
from app.core.exceptions import BizError
from app.core.redis import redis
from app.core.response import ok
from app.crud import favorite as crud_favorite
from app.crud import interaction as crud_interaction
from app.crud import product as crud_product
from app.crud import review as crud_review
from app.models import User
from app.schemas.common import PageOut
from app.schemas.product import (
    CategoryOut,
    FavoriteIn,
    FavoriteOut,
    ProductDetailOut,
    ProductOut,
    ReviewIn,
    ReviewOut,
)

# /categories 与 /favorites 不在 /products 前缀下，路由路径写全
router = APIRouter(tags=["商品"])

_HOT_RANK_KEY = "rank:hot:products"
_SORT_VALUES = ("default", "sales", "price_asc", "price_desc", "rating")


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """分类树（顶级节点 + 递归 children）。"""
    categories = await crud_product.list_categories(db)
    tree = [cat for cat in categories if cat.parent_id is None]
    return ok([CategoryOut.model_validate(cat) for cat in tree])


@router.get("/products")
async def list_products(
    category_id: int | None = None,
    keyword: str | None = Query(None, max_length=100),
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    sort: str = "default",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """商品列表：分类 / 关键词 / 价格区间过滤 + 排序 + 分页（仅上架商品）。"""
    if sort not in _SORT_VALUES:
        raise BizError(3002, f"非法排序方式，可选：{'/'.join(_SORT_VALUES)}", 400)
    products, total = await crud_product.list_products(
        db,
        category_id=category_id,
        keyword=keyword,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return ok(
        PageOut[ProductOut](
            items=[ProductOut.model_validate(p) for p in products],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/products/hot")
async def hot_products(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """热销榜：优先读 Redis ZSet rank:hot:products，为空回退 SQL 按销量倒序。"""
    product_ids: list[int] = []
    try:
        members = await redis.zrevrange(_HOT_RANK_KEY, 0, limit - 1)
        product_ids = [int(m) for m in members]
    except Exception:
        product_ids = []

    if product_ids:
        products = await crud_product.get_products_by_ids(db, product_ids)
        if products:
            return ok([ProductOut.model_validate(p) for p in products])

    products = await crud_product.list_hot_products(db, limit)
    return ok([ProductOut.model_validate(p) for p in products])


@router.get("/products/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """商品详情（含 SKU / 图集 / 商家 / 分类），并记录浏览行为。"""
    product = await crud_product.get_product(db, product_id)
    if product is None:
        raise BizError(3001, "商品不存在或已下架", 404)
    await crud_interaction.log_behavior(user.id if user else None, product_id, "view")
    return ok(ProductDetailOut.model_validate(product))


@router.get("/products/{product_id}/reviews")
async def list_reviews(
    product_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """商品评价分页。"""
    product = await crud_product.get_product(db, product_id)
    if product is None:
        raise BizError(3001, "商品不存在或已下架", 404)
    reviews, total = await crud_review.list_reviews(db, product_id, page, page_size)
    return ok(
        PageOut[ReviewOut](
            items=[ReviewOut.model_validate(r) for r in reviews],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/products/{product_id}/reviews")
async def create_review(
    product_id: int,
    data: ReviewIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """发表评价：需存在包含该商品且状态 COMPLETED 的订单。"""
    product = await crud_product.get_product(db, product_id)
    if product is None:
        raise BizError(3001, "商品不存在或已下架", 404)
    if not await crud_review.has_purchased(db, user.id, product_id):
        raise BizError(4002, "购买后才能评价", 403)
    review = await crud_review.create_review(db, user.id, product_id, data)
    return ok(ReviewOut.model_validate(review))


# ===== 收藏（§5.6）=====


@router.get("/favorites")
async def list_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """我的收藏分页（含商品信息）。"""
    favorites, total = await crud_favorite.list_favorites(db, user.id, page, page_size)
    return ok(
        PageOut[FavoriteOut](
            items=[FavoriteOut.model_validate(f) for f in favorites],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.post("/favorites")
async def add_favorite(
    data: FavoriteIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """收藏商品（幂等：重复收藏不报错）。"""
    product = await crud_product.get_product(db, data.product_id)
    if product is None:
        raise BizError(3001, "商品不存在或已下架", 404)
    await crud_favorite.add_favorite(db, user.id, data.product_id)
    await crud_interaction.log_behavior(user.id, data.product_id, "favorite")
    return ok(message="已收藏")


@router.delete("/favorites/{product_id}")
async def remove_favorite(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """取消收藏（幂等：未收藏时静默成功）。"""
    await crud_favorite.remove_favorite(db, user.id, product_id)
    return ok(message="已取消收藏")
