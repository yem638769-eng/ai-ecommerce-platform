"""优惠券 CRUD：可领列表、Redis 原子领券、我的券、可用券匹配、过期任务。"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.redis import redis
from app.db.base import AsyncSessionLocal
from app.models import Coupon, UserCoupon

logger = logging.getLogger(__name__)

_STOCK_KEY = "coupon:stock:{coupon_id}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def calc_discount(coupon: Coupon, order_amount: float) -> float:
    """计算优惠券可抵扣金额：1 满减（固定金额）/ 2 折扣（value=折扣率，0.9=九折）。"""
    if coupon.type == 1:
        discount = float(coupon.value)
    else:
        discount = order_amount * (1 - float(coupon.value))
    return round(max(min(discount, order_amount), 0.0), 2)


async def get_coupon(db: AsyncSession, coupon_id: int) -> Coupon | None:
    return await db.get(Coupon, coupon_id)


async def list_available(
    db: AsyncSession, merchant_id: int | None = None
) -> list[Coupon]:
    """可领券列表：启用中、在有效期内、尚有余量。"""
    now = _now()
    stmt = select(Coupon).where(
        Coupon.status == 1,
        Coupon.start_time <= now,
        Coupon.end_time >= now,
        Coupon.received_count < Coupon.total_count,
    )
    if merchant_id is not None:
        stmt = stmt.where(Coupon.merchant_id == merchant_id)
    stmt = stmt.order_by(Coupon.id.desc())
    return list((await db.execute(stmt)).scalars())


async def receive_coupon(db: AsyncSession, user_id: int, coupon_id: int) -> UserCoupon:
    """领券：Redis 原子扣减库存 + DB 条件更新 received_count + 写持券记录。"""
    coupon = await get_coupon(db, coupon_id)
    now = _now()
    if (
        coupon is None
        or coupon.status != 1
        or not (coupon.start_time <= now <= coupon.end_time)
    ):
        raise BizError(4003, "优惠券不存在或已停用", 404)

    key = _STOCK_KEY.format(coupon_id=coupon.id)
    # 键不存在时初始化为 剩余可领数量（NX 防止并发覆盖），TTL 取券有效期
    init_value = coupon.total_count - coupon.received_count
    if init_value <= 0:
        raise BizError(4003, "已抢完", 409)
    ttl = max(int((coupon.end_time - now).total_seconds()), 60)
    await redis.set(key, init_value, nx=True, ex=ttl)

    remaining = await redis.decr(key)
    if remaining < 0:
        # 扣减后小于 0：回补并视为抢完
        await redis.incr(key)
        raise BizError(4003, "已抢完", 409)

    # DB 条件更新，防止与 Redis 出现偏差时超发
    result = await db.execute(
        update(Coupon)
        .where(Coupon.id == coupon.id, Coupon.received_count < Coupon.total_count)
        .values(received_count=Coupon.received_count + 1)
    )
    if result.rowcount == 0:
        await redis.incr(key)
        raise BizError(4003, "已抢完", 409)

    user_coupon = UserCoupon(
        coupon_id=coupon.id, user_id=user_id, status=1, received_at=now
    )
    db.add(user_coupon)
    await db.commit()
    await db.refresh(user_coupon)
    return user_coupon


async def list_mine(
    db: AsyncSession, user_id: int, status: int | None = None
) -> list[UserCoupon]:
    stmt = select(UserCoupon).where(UserCoupon.user_id == user_id)
    if status is not None:
        stmt = stmt.where(UserCoupon.status == status)
    stmt = stmt.order_by(UserCoupon.id.desc())
    return list((await db.execute(stmt)).scalars())


async def list_usable(
    db: AsyncSession, user_id: int, order_amount: float
) -> list[UserCoupon]:
    """下单可用券：未使用、启用中、在有效期内、满足门槛。"""
    now = _now()
    stmt = (
        select(UserCoupon)
        .join(Coupon, UserCoupon.coupon_id == Coupon.id)
        .where(
            UserCoupon.user_id == user_id,
            UserCoupon.status == 1,
            Coupon.status == 1,
            Coupon.start_time <= now,
            Coupon.end_time >= now,
            Coupon.min_amount <= order_amount,
        )
        .order_by(UserCoupon.id.desc())
    )
    return list((await db.execute(stmt)).scalars())


async def validate_for_use(
    db: AsyncSession, user_id: int, coupon_id: int, order_amount: float
) -> tuple[UserCoupon, float]:
    """下单时校验用户券可用性，返回 (持券记录, 可抵扣金额)；不可用抛 4003。"""
    stmt = select(UserCoupon).where(UserCoupon.id == coupon_id, UserCoupon.user_id == user_id)
    user_coupon = (await db.execute(stmt)).scalar_one_or_none()
    now = _now()
    coupon = user_coupon.coupon if user_coupon is not None else None
    if (
        user_coupon is None
        or user_coupon.status != 1
        or coupon is None
        or coupon.status != 1
        or not (coupon.start_time <= now <= coupon.end_time)
        or order_amount < float(coupon.min_amount)
    ):
        raise BizError(4003, "优惠券不可用", 400)
    return user_coupon, calc_discount(coupon, order_amount)


async def refund(db: AsyncSession, user_coupon_id: int) -> None:
    """退还优惠券（取消订单时调用）：status 回 1、清空 used_at。"""
    user_coupon = await db.get(UserCoupon, user_coupon_id)
    if user_coupon is not None and user_coupon.status == 2:
        user_coupon.status = 1
        user_coupon.used_at = None
        await db.commit()


async def expire_user_coupons() -> int:
    """定时任务：将过期未使用的用户券置为已过期（status=3），返回更新条数。"""
    async with AsyncSessionLocal() as db:
        now = _now()
        expired_coupon_ids = select(Coupon.id).where(Coupon.end_time < now)
        result = await db.execute(
            update(UserCoupon)
            .where(UserCoupon.status == 1, UserCoupon.coupon_id.in_(expired_coupon_ids))
            .values(status=3)
        )
        await db.commit()
        if result.rowcount:
            logger.info("已过期用户券: %s 张", result.rowcount)
        return result.rowcount or 0
