"""支付服务（模拟）：创建支付单、按 transaction_id 幂等确认。"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.redis import redis
from app.crud import order as crud_order
from app.crud.interaction import log_behavior
from app.models import (
    InventoryLog,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Product,
    User,
)
from app.schemas.order import PaymentCreateIn

logger = logging.getLogger(__name__)

_HOT_RANK_KEY = "rank:hot:products"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_payment(
    db: AsyncSession, user: User, data: PaymentCreateIn
) -> tuple[Payment, str]:
    """创建模拟支付单（PENDING），返回 (支付记录, 模拟支付链接)。"""
    if data.pay_method != "mock":
        raise BizError(1000, "暂仅支持 mock 模拟支付", 400)
    order = await crud_order.get_by_no(db, data.order_no)
    if order is None or order.user_id != user.id:
        raise BizError(4001, "订单不存在", 404)
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise BizError(4002, "当前状态不允许支付", 400)

    transaction_id = uuid.uuid4().hex
    payment = Payment(
        order_id=order.id,
        pay_method="mock",
        amount=order.pay_amount,
        status=PaymentStatus.PENDING,
        transaction_id=transaction_id,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    pay_url = f"/api/v1/payments/mock/confirm?transaction_id={transaction_id}"
    return payment, pay_url


async def mock_confirm(db: AsyncSession, user: User, transaction_id: str) -> Payment:
    """模拟支付回调：按 transaction_id 幂等确认。

    同一 transaction_id 重复调用直接返回原结果；
    首次成功：Payment→SUCCESS、订单→PAID、写 sale 库存流水（仅记录）、
    累加商品销量、热销榜 ZINCRBY、记录 purchase 行为。
    """
    stmt = select(Payment).where(Payment.transaction_id == transaction_id)
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        raise BizError(4004, "支付记录不存在", 404)
    order = await db.get(Order, payment.order_id)
    if order is None or order.user_id != user.id:
        raise BizError(4004, "支付记录不存在", 404)

    # 幂等：已成功的支付单重复确认，返回原结果
    if payment.status == PaymentStatus.SUCCESS:
        return payment
    if payment.status != PaymentStatus.PENDING:
        raise BizError(4004, "支付记录已关闭", 400)

    # 订单已被其他支付单支付或已取消：本单置为失败
    if order.status != OrderStatus.PENDING_PAYMENT:
        payment.status = PaymentStatus.FAILED
        await db.commit()
        raise BizError(4002, "当前状态不允许支付", 400)

    now = _now()
    payment.status = PaymentStatus.SUCCESS
    payment.paid_at = now
    order.status = OrderStatus.PAID
    order.paid_at = now

    for item in order.items:
        # sale 支付核销流水：仅记录，不再扣库存（下单时已扣减）
        db.add(
            InventoryLog(
                sku_id=item.sku_id,
                change_type="sale",
                quantity=item.quantity,
                order_id=order.id,
            )
        )
        await db.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(sales_count=Product.sales_count + item.quantity)
        )
    await db.commit()

    # 热销榜（每个商品 ZINCRBY 一次）与 purchase 行为；失败不影响支付结果
    for item in order.items:
        try:
            await redis.zincrby(_HOT_RANK_KEY, 1, str(item.product_id))
        except Exception:
            logger.exception("更新热销榜失败: product=%s", item.product_id)
        await log_behavior(order.user_id, item.product_id, "purchase")

    await db.refresh(payment)
    return payment
