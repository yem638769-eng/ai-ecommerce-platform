"""行为日志：独立会话写入，不参与调用方事务。"""
import logging

from app.db.base import AsyncSessionLocal
from app.models import UserBehavior

logger = logging.getLogger(__name__)


async def log_behavior(user_id: int | None, product_id: int, event_type: str) -> None:
    """记录用户行为（view/click/cart/favorite/purchase），失败仅记日志不影响主流程。"""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                UserBehavior(
                    user_id=user_id, product_id=product_id, event_type=event_type
                )
            )
            await db.commit()
    except Exception:
        logger.exception("记录行为日志失败: user=%s product=%s event=%s", user_id, product_id, event_type)
