"""订单服务：下单（Redis 锁 + SQL 条件扣减防超卖）、取消、确认收货、超时取消任务。"""
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BizError
from app.core.redis import redis
from app.crud import cart as crud_cart
from app.crud import coupon as crud_coupon
from app.crud import order as crud_order
from app.crud.interaction import log_behavior
from app.db.base import AsyncSessionLocal
from app.models import (
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductSKU,
    User,
    UserAddress,
)
from app.schemas.order import OrderCreateIn
from app.services import stock_service

logger = logging.getLogger(__name__)

_LOCK_KEY = "lock:sku:{sku_id}"
_LOCK_TTL_SECONDS = 10
_UNLOCK_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_order_no() -> str:
    """订单号：日期时间（14 位）+ 6 位随机串，全局唯一。"""
    return _now().strftime("%Y%m%d%H%M%S") + f"{random.randint(0, 999999):06d}"


async def _lock_skus(sku_ids: list[int]) -> list[tuple[int, str]]:
    """逐个获取 Redis SKU 锁（SETNX + TTL 10s）。

    任一锁获取失败：释放已获取的锁并抛出 429。
    返回 [(sku_id, token), ...]，token 用于安全释放。
    """
    acquired: list[tuple[int, str]] = []
    for sku_id in sorted(sku_ids):
        token = uuid.uuid4().hex
        success = await redis.set(
            _LOCK_KEY.format(sku_id=sku_id), token, nx=True, ex=_LOCK_TTL_SECONDS
        )
        if not success:
            for sid, tok in acquired:
                await _unlock_sku(sid, tok)
            raise BizError(3002, "操作过于频繁，请稍后再试", 429)
        acquired.append((sku_id, token))
    return acquired


async def _unlock_sku(sku_id: int, token: str) -> None:
    """释放锁：token 匹配才删除；失败仅记日志，等 TTL 自动过期。"""
    try:
        await redis.eval(_UNLOCK_LUA, 1, _LOCK_KEY.format(sku_id=sku_id), token)
    except Exception:
        logger.warning("释放 SKU 锁失败: sku_id=%s", sku_id)


async def create_order(db: AsyncSession, user: User, data: OrderCreateIn) -> Order:
    """下单核心流程：校验 → 锁库存 → 条件扣减 → 生成订单与快照 → 核销优惠券。"""
    # 1. 校验收货地址
    stmt = select(UserAddress).where(
        UserAddress.id == data.address_id, UserAddress.user_id == user.id
    )
    address = (await db.execute(stmt)).scalar_one_or_none()
    if address is None:
        raise BizError(1005, "收货地址不存在", 404)

    # 2. 组装订单项（cart 购物车结算取勾选项 / buy_now 直接购买）
    if data.from_ == "cart":
        rows = await crud_cart.list_checked_with_product(db, user.id)
        if not rows:
            raise BizError(1000, "购物车中没有勾选的商品", 400)
        item_sources = [(sku, product, cart_item.quantity) for cart_item, sku, product in rows]
        cart_sku_ids = [sku.id for _, sku, _ in rows]
    else:
        if not data.sku_items:
            raise BizError(1000, "请选择要购买的商品", 400)
        merged: dict[int, int] = {}
        for item in data.sku_items:
            merged[item.sku_id] = merged.get(item.sku_id, 0) + item.quantity
        item_sources = []
        for sku_id, qty in merged.items():
            stmt = (
                select(ProductSKU, Product)
                .join(Product, ProductSKU.product_id == Product.id)
                .where(ProductSKU.id == sku_id)
            )
            row = (await db.execute(stmt)).first()
            if row is None:
                raise BizError(3001, "商品不存在或已下架", 404)
            sku, product = row
            item_sources.append((sku, product, qty))

    for sku, product, _qty in item_sources:
        if sku.status != 1 or product.status != 1:
            raise BizError(3001, "商品不存在或已下架", 404)

    # 3. 计算金额 & 校验优惠券（未核销，仅校验与试算）
    total_amount = 0.0
    for sku, _product, qty in item_sources:
        total_amount += float(sku.price) * qty
    total_amount = round(total_amount, 2)

    user_coupon = None
    discount_amount = 0.0
    if data.coupon_id:
        user_coupon, discount_amount = await crud_coupon.validate_for_use(
            db, user.id, data.coupon_id, total_amount
        )
    pay_amount = round(max(total_amount - discount_amount, 0.0), 2)

    # 4. Redis 锁 + SQL 条件扣减（防超卖核心）
    address_snapshot = {
        "receiver": address.receiver,
        "phone": address.phone,
        "province": address.province,
        "city": address.city,
        "district": address.district,
        "detail": address.detail,
    }
    items_snapshot = [
        {
            "product_id": product.id,
            "sku_id": sku.id,
            "product_name": product.name,
            "sku_specs": sku.specs,
            "image": sku.image or product.main_image,
            "price": float(sku.price),
            "quantity": qty,
            "subtotal": round(float(sku.price) * qty, 2),
        }
        for sku, product, qty in item_sources
    ]

    sku_ids = [sku.id for sku, _product, _qty in item_sources]
    locks = await _lock_skus(sku_ids)
    deducted: list[tuple[int, int]] = []
    try:
        for sku, _product, qty in item_sources:
            updated = await stock_service.adjust_stock(db, sku.id, -qty, "purchase")
            if updated is None:
                # 库存不足：回补本次已扣减的项后抛出冲突
                for sid, q in deducted:
                    await stock_service.adjust_stock(db, sid, q, "cancel")
                raise BizError(3002, "库存不足", 409)
            deducted.append((sku.id, qty))

        # 5. 生成订单（订单号唯一）+ 订单项明细 + 核销优惠券
        order_no = _generate_order_no()
        for _ in range(3):
            if await crud_order.get_by_no(db, order_no) is None:
                break
            order_no = _generate_order_no()

        try:
            if user_coupon is not None:
                user_coupon.status = 2
                user_coupon.used_at = _now()
            order = Order(
                order_no=order_no,
                user_id=user.id,
                status=OrderStatus.PENDING_PAYMENT,
                total_amount=total_amount,
                discount_amount=discount_amount,
                pay_amount=pay_amount,
                address_snapshot=address_snapshot,
                items_snapshot=items_snapshot,
                coupon_id=user_coupon.id if user_coupon is not None else None,
                remark=data.remark,
            )
            db.add(order)
            await db.flush()
            for sku, product, qty in item_sources:
                db.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        sku_id=sku.id,
                        product_name=product.name,
                        sku_specs=sku.specs,
                        image=sku.image or product.main_image,
                        price=float(sku.price),
                        quantity=qty,
                        subtotal=round(float(sku.price) * qty, 2),
                    )
                )
            await db.commit()
        except Exception:
            # 订单落库失败：整体回滚并回补已扣减的库存（优惠券改动随事务回滚）
            await db.rollback()
            for sid, q in deducted:
                try:
                    await stock_service.adjust_stock(db, sid, q, "cancel")
                except Exception:
                    logger.exception("订单回滚时回补库存失败，请人工对账: sku=%s qty=%s", sid, q)
            raise
    finally:
        # 下单结束（成功或失败）释放全部锁
        for sid, token in locks:
            await _unlock_sku(sid, token)

    await db.refresh(order)

    # 6. 购物车场景：移除已结算的购物车项，并记录加购行为
    if data.from_ == "cart":
        await crud_cart.delete_by_skus(db, user.id, cart_sku_ids)
        for _sku, product, _qty in item_sources:
            await log_behavior(user.id, product.id, "cart")
    return order


async def cancel_order(db: AsyncSession, user: User, order_no: str) -> Order:
    """买家取消订单：仅待支付可取消。"""
    order = await crud_order.get_by_no(db, order_no)
    if order is None or order.user_id != user.id:
        raise BizError(4001, "订单不存在", 404)
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise BizError(4002, "当前状态不允许取消", 400)
    await _cancel_order(db, order)
    return order


async def _cancel_order(db: AsyncSession, order: Order) -> bool:
    """取消核心逻辑：条件状态流转 + 回补库存 + 退还优惠券。

    条件更新保证并发下只有一方能把 PENDING_PAYMENT 置为 CANCELLED；
    返回 False 表示订单已被支付或取消，本次跳过。
    """
    result = await db.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == OrderStatus.PENDING_PAYMENT)
        .values(status=OrderStatus.CANCELLED, cancelled_at=_now())
    )
    if result.rowcount == 0:
        return False

    # 回补库存 + 写取消流水
    for item in order.items:
        await stock_service.adjust_stock(
            db, item.sku_id, item.quantity, "cancel", order.id
        )
    # 退还优惠券：status 回 1
    if order.coupon_id:
        await crud_coupon.refund(db, order.coupon_id)
    await db.commit()
    await db.refresh(order)
    return True


async def confirm_order(db: AsyncSession, user: User, order_no: str) -> Order:
    """确认收货：SHIPPED → COMPLETED。"""
    order = await crud_order.get_by_no(db, order_no)
    if order is None or order.user_id != user.id:
        raise BizError(4001, "订单不存在", 404)
    if order.status != OrderStatus.SHIPPED:
        raise BizError(4002, "当前状态不允许确认收货", 400)
    order.status = OrderStatus.COMPLETED
    order.completed_at = _now()
    await db.commit()
    await db.refresh(order)
    return order


async def cancel_expired_orders() -> int:
    """定时任务：取消超时未支付订单并回滚库存/退券（独立会话），返回处理条数。"""
    async with AsyncSessionLocal() as db:
        deadline = _now() - timedelta(minutes=settings.order_timeout_minutes)
        stmt = select(Order).where(
            Order.status == OrderStatus.PENDING_PAYMENT,
            Order.created_at < deadline,
        )
        orders = list((await db.execute(stmt)).scalars())
        count = 0
        for order in orders:
            try:
                if await _cancel_order(db, order):
                    count += 1
                    logger.info("超时订单已自动取消: %s", order.order_no)
            except Exception:
                logger.exception("取消超时订单失败: %s", order.order_no)
                await db.rollback()
        return count
