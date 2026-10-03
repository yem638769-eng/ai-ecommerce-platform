"""全局 Redis 客户端（异步）。"""
from redis.asyncio import Redis, from_url

from app.core.config import settings

redis: Redis = from_url(settings.redis_url, decode_responses=True)


async def get_redis() -> Redis:
    return redis
