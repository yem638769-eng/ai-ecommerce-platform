"""评价 CRUD：列表 / 购买资格校验 / 发表评价并重算商品评分。"""
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderItem, OrderStatus, Product, Review
from app.schemas.product import ReviewIn


async def list_reviews(
    db: AsyncSession, product_id: int, page: int, page_size: int
) -> tuple[list[Review], int]:
    """商品评价分页（最新在前，评价人信息由 joined 关系加载）。"""
    base = select(Review).where(Review.product_id == product_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    stmt = (
        base.order_by(Review.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    reviews = list((await db.execute(stmt)).scalars())
    return reviews, int(total or 0)


async def has_purchased(db: AsyncSession, user_id: int, product_id: int) -> bool:
    """校验用户存在包含该商品且状态为 COMPLETED 的订单。"""
    stmt = (
        select(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.user_id == user_id,
            Order.status == OrderStatus.COMPLETED,
            OrderItem.product_id == product_id,
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def create_review(
    db: AsyncSession, user_id: int, product_id: int, data: ReviewIn
) -> Review:
    """写评价并重算商品 rating_avg（调用方需先校验购买资格）。"""
    review = Review(
        user_id=user_id,
        product_id=product_id,
        rating=data.rating,
        content=data.content,
        images=data.images,
    )
    db.add(review)
    await db.flush()
    await recalc_product_rating(db, product_id)
    await db.commit()
    await db.refresh(review)
    return review


async def recalc_product_rating(db: AsyncSession, product_id: int) -> None:
    """按全部评价的平均分更新商品 rating_avg（保留 1 位小数，无评价时回 5.0）。"""
    avg = await db.scalar(
        select(func.avg(Review.rating)).where(Review.product_id == product_id)
    )
    rating = round(float(avg), 1) if avg is not None else 5.0
    await db.execute(
        update(Product).where(Product.id == product_id).values(rating_avg=rating)
    )
