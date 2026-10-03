"""商品 / 分类 CRUD。"""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product, ProductImage, ProductSKU
from app.schemas.product import ProductCreateIn, ProductUpdateIn

# 列表排序映射
_SORT_ORDERS = {
    "default": (Product.id.desc(),),
    "sales": (Product.sales_count.desc(), Product.id.desc()),
    "price_asc": (Product.price_min.asc(), Product.id.desc()),
    "price_desc": (Product.price_max.desc(), Product.id.desc()),
    "rating": (Product.rating_avg.desc(), Product.id.desc()),
}


def _gen_sku_code() -> str:
    """自动生成 SKU 编码（商家未传 sku_code 时兜底）。"""
    return uuid4().hex[:16]


# ===== 分类 =====


async def list_categories(db: AsyncSession) -> list[Category]:
    """全量分类。children 链式 selectin 预加载两层，避免递归序列化时懒加载。"""
    stmt = (
        select(Category)
        .options(selectinload(Category.children).selectinload(Category.children))
        .order_by(Category.sort, Category.id)
    )
    return list((await db.execute(stmt)).scalars())


async def _category_descendant_ids(db: AsyncSession, category_id: int) -> list[int]:
    """收集分类及其全部后代 ID（分类表数据量小，全量加载后内存展开）。"""
    categories = await list_categories(db)
    children_map: dict[int, list[int]] = {}
    for cat in categories:
        if cat.parent_id is not None:
            children_map.setdefault(cat.parent_id, []).append(cat.id)
    ids = [category_id]
    stack = [category_id]
    while stack:
        for child_id in children_map.get(stack.pop(), []):
            ids.append(child_id)
            stack.append(child_id)
    return ids


# ===== 商品查询 =====


async def get_product(db: AsyncSession, product_id: int) -> Product | None:
    """按 ID 查询上架商品（SKU / 图集 / 商家 / 分类随关系自动加载）。"""
    stmt = select(Product).where(Product.id == product_id, Product.status == 1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_products(
    db: AsyncSession,
    *,
    category_id: int | None,
    keyword: str | None,
    min_price: float | None,
    max_price: float | None,
    sort: str,
    page: int,
    page_size: int,
) -> tuple[list[Product], int]:
    """商品列表：分类（含子分类）/ 关键词 / 价格区间过滤 + 排序分页，仅上架商品。"""
    stmt = select(Product).where(Product.status == 1)

    if category_id is not None:
        stmt = stmt.where(
            Product.category_id.in_(await _category_descendant_ids(db, category_id))
        )

    if keyword:
        stmt = stmt.where(
            Product.name.icontains(keyword, autoescape=True)
            | Product.subtitle.icontains(keyword, autoescape=True)
        )

    if min_price is not None:
        stmt = stmt.where(Product.price_max >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.price_min <= max_price)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = (
        stmt.order_by(*_SORT_ORDERS.get(sort, _SORT_ORDERS["default"]))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    products = list((await db.execute(stmt)).scalars())
    return products, int(total or 0)


async def list_hot_products(db: AsyncSession, limit: int = 10) -> list[Product]:
    """热销榜 SQL 版：按销量倒序（Redis ZSet 未命中时回退）。"""
    stmt = (
        select(Product)
        .where(Product.status == 1)
        .order_by(Product.sales_count.desc(), Product.id)
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def get_products_by_ids(db: AsyncSession, product_ids: list[int]) -> list[Product]:
    """按 ID 列表取上架商品，保持传入顺序（用于 Redis 热销榜）。"""
    if not product_ids:
        return []
    stmt = select(Product).where(Product.id.in_(product_ids), Product.status == 1)
    products = list((await db.execute(stmt)).scalars())
    by_id = {p.id: p for p in products}
    return [by_id[i] for i in product_ids if i in by_id]


async def suggest_keywords(db: AsyncSession, prefix: str, limit: int = 10) -> list[str]:
    """搜索联想：商品名前缀匹配（同名取销量最高者排前，仅上架商品）。"""
    stmt = (
        select(Product.name)
        .where(Product.status == 1, Product.name.istartswith(prefix, autoescape=True))
        .group_by(Product.name)
        .order_by(func.max(Product.sales_count).desc())
        .limit(limit)
    )
    return [row[0] for row in (await db.execute(stmt))]


# ===== 商品写入（商家端契约，M4 复用）=====


async def create_product(db: AsyncSession, merchant_id: int, data: ProductCreateIn) -> Product:
    """创建商品：默认草稿（status=0），按 SKU 最低 / 最高价计算价格区间。"""
    prices = [Decimal(str(sku.price)) for sku in data.skus]
    product = Product(
        merchant_id=merchant_id,
        category_id=data.category_id,
        name=data.name,
        subtitle=data.subtitle,
        description=data.description,
        main_image=data.main_image,
        price_min=min(prices),
        price_max=max(prices),
        status=0,
    )
    db.add(product)
    await db.flush()

    for sku_in in data.skus:
        db.add(
            ProductSKU(
                product_id=product.id,
                sku_code=sku_in.sku_code or _gen_sku_code(),
                specs=sku_in.specs,
                price=Decimal(str(sku_in.price)),
                stock=sku_in.stock,
                image=sku_in.image,
                status=sku_in.status,
            )
        )
    for image_in in data.images:
        db.add(ProductImage(product_id=product.id, url=image_in.url, sort=image_in.sort))

    await db.commit()
    await db.refresh(product)
    return product


async def update_product(db: AsyncSession, product: Product, data: ProductUpdateIn) -> Product:
    """编辑商品：未设置的字段不更新；skus / images 传入则整体替换并重算价格区间。"""
    payload = data.model_dump(exclude_unset=True)

    skus_in = payload.pop("skus", None)
    images_in = payload.pop("images", None)
    for key, value in payload.items():
        setattr(product, key, value)

    if skus_in is not None:
        await db.execute(delete(ProductSKU).where(ProductSKU.product_id == product.id))
        prices = []
        for sku_in in data.skus or []:
            price = Decimal(str(sku_in.price))
            prices.append(price)
            db.add(
                ProductSKU(
                    product_id=product.id,
                    sku_code=sku_in.sku_code or _gen_sku_code(),
                    specs=sku_in.specs,
                    price=price,
                    stock=sku_in.stock,
                    image=sku_in.image,
                    status=sku_in.status,
                )
            )
        product.price_min = min(prices)
        product.price_max = max(prices)

    if images_in is not None:
        await db.execute(delete(ProductImage).where(ProductImage.product_id == product.id))
        for image_in in data.images or []:
            db.add(ProductImage(product_id=product.id, url=image_in.url, sort=image_in.sort))

    await db.commit()
    await db.refresh(product)
    return product


async def set_product_status(db: AsyncSession, product: Product, status: int) -> Product:
    """更新商品状态（0 草稿 / 1 上架 / 2 下架）。"""
    product.status = status
    await db.commit()
    await db.refresh(product)
    return product
