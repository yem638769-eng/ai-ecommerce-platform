"""商家端 CRUD：开店、本店商品 / SKU / 优惠券查询、数据统计（SQL 聚合）。

订单表无 merchant_id，本店订单口径与 crud_order.list_for_merchant 一致：
经 OrderItem → Product.merchant_id 过滤，并用 DISTINCT 去重防止一个订单多个订单项重复计数。
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Coupon,
    Merchant,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductSKU,
    User,
)
from app.schemas.merchant import CouponCreateIn, ShopRegisterIn

# 计入销售额 / 销量的有效订单状态（已支付及之后，不含取消 / 退款）
_VALID_ORDER_STATUS = (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.COMPLETED)


# ===== 店铺 =====


async def get_by_user_id(db: AsyncSession, user_id: int) -> Merchant | None:
    stmt = select(Merchant).where(Merchant.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_shop_name(db: AsyncSession, shop_name: str) -> Merchant | None:
    stmt = select(Merchant).where(Merchant.shop_name == shop_name)
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_shop(db: AsyncSession, user: User, data: ShopRegisterIn) -> Merchant:
    """开店：创建 Merchant（直接营业 status=1），并把用户角色升级为 merchant。"""
    merchant = Merchant(
        user_id=user.id,
        shop_name=data.shop_name,
        logo=data.logo,
        description=data.description,
        status=1,
    )
    db.add(merchant)
    user.role = "merchant"
    await db.commit()
    await db.refresh(merchant)
    return merchant


# ===== 本店商品 / SKU =====


async def list_shop_products(
    db: AsyncSession,
    merchant_id: int,
    status: int | None,
    keyword: str | None,
    page: int,
    page_size: int,
) -> tuple[list[Product], int]:
    """本店商品列表（含草稿 / 下架）：状态 + 关键词过滤 + 分页。"""
    stmt = select(Product).where(Product.merchant_id == merchant_id)
    if status is not None:
        stmt = stmt.where(Product.status == status)
    if keyword:
        stmt = stmt.where(
            Product.name.icontains(keyword, autoescape=True)
            | Product.subtitle.icontains(keyword, autoescape=True)
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(Product.id.desc()).offset((page - 1) * page_size).limit(page_size)
    products = list((await db.execute(stmt)).scalars())
    return products, int(total or 0)


async def get_shop_product(
    db: AsyncSession, merchant_id: int, product_id: int
) -> Product | None:
    """按 ID 取本店商品（不限状态，供商家管理草稿 / 下架商品）。"""
    stmt = select(Product).where(Product.id == product_id, Product.merchant_id == merchant_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_shop_sku(
    db: AsyncSession, merchant_id: int, sku_id: int
) -> ProductSKU | None:
    """按 ID 取属于本店商品的 SKU（join 商品表校验归属）。"""
    stmt = (
        select(ProductSKU)
        .join(Product, Product.id == ProductSKU.product_id)
        .where(ProductSKU.id == sku_id, Product.merchant_id == merchant_id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def order_has_shop_items(
    db: AsyncSession, merchant_id: int, order_id: int
) -> bool:
    """判断订单是否包含本店商品（防止商家操作他店订单）。"""
    stmt = (
        select(OrderItem.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order_id, Product.merchant_id == merchant_id)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar() is not None


# ===== 优惠券 =====


async def create_coupon(
    db: AsyncSession, merchant_id: int, data: CouponCreateIn
) -> Coupon:
    """创建本店优惠券。"""
    coupon = Coupon(merchant_id=merchant_id, **data.model_dump())
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return coupon


async def list_coupons(
    db: AsyncSession, merchant_id: int, page: int, page_size: int
) -> tuple[list[Coupon], int]:
    """本店优惠券列表（含领取数量统计）。"""
    stmt = select(Coupon).where(Coupon.merchant_id == merchant_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(Coupon.id.desc()).offset((page - 1) * page_size).limit(page_size)
    coupons = list((await db.execute(stmt)).scalars())
    return coupons, int(total or 0)


# ===== 数据统计（SQL 聚合）=====


def _shop_order_ids(merchant_id: int):
    """本店订单 ID 子查询：经 OrderItem → Product.merchant_id 过滤并去重。"""
    return (
        select(OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Product.merchant_id == merchant_id)
        .distinct()
        .subquery()
    )


async def get_dashboard(db: AsyncSession, merchant_id: int) -> dict:
    """经营看板：总销售额 / 总订单数 / 在售商品数 / 待发货订单数。"""
    order_ids = _shop_order_ids(merchant_id)

    # 总销售额：有效状态订单的 pay_amount 合计（子查询已去重，多订单项不会重复求和）
    total_sales = (
        await db.execute(
            select(func.coalesce(func.sum(Order.pay_amount), 0))
            .join(order_ids, order_ids.c.order_id == Order.id)
            .where(Order.status.in_(_VALID_ORDER_STATUS))
        )
    ).scalar() or 0

    # 总订单数：包含本店商品的去重订单数（不限状态）
    total_orders = (
        await db.execute(
            select(func.count(Order.id)).join(
                order_ids, order_ids.c.order_id == Order.id
            )
        )
    ).scalar() or 0

    # 在售商品数
    on_sale_products = (
        await db.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.merchant_id == merchant_id, Product.status == 1)
        )
    ).scalar() or 0

    # 待发货订单数：已支付未发货
    pending_ship_orders = (
        await db.execute(
            select(func.count(Order.id))
            .join(order_ids, order_ids.c.order_id == Order.id)
            .where(Order.status == OrderStatus.PAID)
        )
    ).scalar() or 0

    return {
        "total_sales": float(total_sales),
        "total_orders": int(total_orders),
        "on_sale_products": int(on_sale_products),
        "pending_ship_orders": int(pending_ship_orders),
    }


async def get_product_sales_rank(
    db: AsyncSession, merchant_id: int, limit: int = 10
) -> list[dict]:
    """本店商品销量排行：按有效订单的订单项 quantity 聚合，销量并列时按商品 ID 排序。"""
    stmt = (
        select(
            OrderItem.product_id,
            Product.name.label("product_name"),
            func.sum(OrderItem.quantity).label("sales"),
            func.sum(OrderItem.subtotal).label("sales_amount"),
        )
        .join(Product, Product.id == OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Product.merchant_id == merchant_id, Order.status.in_(_VALID_ORDER_STATUS))
        .group_by(OrderItem.product_id, Product.name)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.product_id)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).mappings().all()
    return [
        {
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "sales": int(row["sales"]),
            "sales_amount": float(row["sales_amount"]),
        }
        for row in rows
    ]


async def get_sales_trend(db: AsyncSession, merchant_id: int, days: int) -> list[dict]:
    """近 N 天逐日销售额 / 订单量趋势。

    按 Order.paid_at（支付时间）聚合而非 created_at：销售额应以实际支付为准，
    未支付 / 已取消订单不计入；日期桶取 paid_at 的自然日（数据库时区）。
    """
    start = date.today() - timedelta(days=days - 1)
    # 窗口起点用 UTC 零点的带时区时间，避免 date → timestamptz 隐式转换依赖会话时区
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    order_ids = _shop_order_ids(merchant_id)

    day = func.date(Order.paid_at)
    stmt = (
        select(
            day.label("day"),
            func.sum(Order.pay_amount).label("sales"),
            func.count(Order.id).label("order_count"),
        )
        .join(order_ids, order_ids.c.order_id == Order.id)
        .where(Order.status.in_(_VALID_ORDER_STATUS), Order.paid_at >= start_dt)
        .group_by(day)
        .order_by(day)
    )
    rows = (await db.execute(stmt)).mappings().all()
    by_day = {row["day"]: (row["sales"], row["order_count"]) for row in rows}

    # 补齐无数据日期，便于前端绘制连续折线
    trend = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        sales, order_count = by_day.get(d, (0, 0))
        trend.append(
            {
                "date": d.isoformat(),
                "sales": float(sales or 0),
                "order_count": int(order_count or 0),
            }
        )
    return trend
