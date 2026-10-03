"""后台定时任务调度器（60s 循环）。

M3 交易模块完成后，在文件底部追加任务注册，例如：
    from app.services.order_service import cancel_expired_orders
    register_task(cancel_expired_orders)
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_TASKS: list = []


def register_task(fn) -> None:
    if fn not in _TASKS:
        _TASKS.append(fn)


async def _run_forever() -> None:
    while True:
        for fn in _TASKS:
            try:
                await fn()
            except Exception:
                logger.exception("定时任务执行失败: %s", getattr(fn, "__name__", fn))
        await asyncio.sleep(60)


def start_scheduler() -> None:
    asyncio.create_task(_run_forever())


# ===== M3 交易模块定时任务注册 =====
from app.crud.coupon import expire_user_coupons  # noqa: E402
from app.services.order_service import cancel_expired_orders  # noqa: E402

register_task(cancel_expired_orders)
register_task(expire_user_coupons)
