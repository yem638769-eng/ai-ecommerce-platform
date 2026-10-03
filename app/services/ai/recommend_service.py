"""个性化推荐（§6.4）：行为加权偏好向量召回 + 热销兜底 + Redis 缓存 30 分钟。

- 未登录 / 无行为数据（L0 冷启动）→ 热销榜（sales_count DESC）
- 有行为数据（L1 行为推荐）→ 近期行为按 EVENT_WEIGHTS 加权聚合商品向量得偏好向量，
  cosine 检索相似商品（排除已交互商品）
- 相似推荐（L2）→ 单商品向量近邻
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.redis import redis
from app.crud import product as crud_product
from app.models import EVENT_WEIGHTS, Product, ProductEmbedding, UserBehavior
from app.services.ai.search import similar_products

logger = logging.getLogger(__name__)

# 推荐结果缓存
_CACHE_KEY = "cache:recommend:{user_id}"
_CACHE_TTL_SECONDS = 30 * 60
# 缓存 / 个性化召回的计算条数（按需截断返回）
_CACHE_SIZE = 50
# 参与偏好聚合的近期行为条数
_RECENT_BEHAVIORS = 100


def _card(product: Product, similarity: float | None = None) -> dict:
    return {
        "id": product.id,
        "name": product.name,
        "subtitle": product.subtitle,
        "price_min": float(product.price_min),
        "price_max": float(product.price_max),
        "main_image": product.main_image,
        "sales_count": product.sales_count,
        "rating_avg": float(product.rating_avg),
        "similarity": round(similarity, 4) if similarity is not None else None,
    }


async def _hot_cards(db: AsyncSession, limit: int) -> list[dict]:
    """热销榜兜底（L0 冷启动）。"""
    products = await crud_product.list_hot_products(db, limit)
    return [_card(p) for p in products]


async def get_recommendations(
    db: AsyncSession, user_id: int | None, limit: int = 10
) -> list[dict]:
    """首页猜你喜欢：未登录 → 热销榜；已登录 → 个性化偏好向量召回（Redis 缓存 30 分钟）。"""
    if user_id is None:
        return await _hot_cards(db, limit)

    cached = await _load_cache(user_id)
    if cached:
        return cached[:limit]

    stmt = (
        select(UserBehavior)
        .where(UserBehavior.user_id == user_id)
        .order_by(UserBehavior.created_at.desc())
        .limit(_RECENT_BEHAVIORS)
    )
    behaviors = list((await db.execute(stmt)).scalars())
    if not behaviors:
        # 冷启动：热销兜底，不写缓存（产生行为后可立即个性化）
        return await _hot_cards(db, limit)

    cards = await _personalized(db, behaviors, _CACHE_SIZE)
    if not cards:
        return await _hot_cards(db, limit)
    await _save_cache(user_id, cards)
    return cards[:limit]


async def _personalized(db: AsyncSession, behaviors: list[UserBehavior], limit: int) -> list[dict]:
    """L1 行为推荐：行为权重加权聚合商品向量 → 偏好向量 → cosine 近邻（排除已交互商品）。"""
    # 按商品聚合行为权重
    weights: dict[int, float] = {}
    for b in behaviors:
        weights[b.product_id] = weights.get(b.product_id, 0.0) + EVENT_WEIGHTS.get(
            b.event_type, 1
        )

    interacted_ids = list(weights.keys())
    stmt = select(ProductEmbedding).where(ProductEmbedding.product_id.in_(interacted_ids))
    embeddings = list((await db.execute(stmt)).scalars())
    if not embeddings:
        return []

    # 加权平均得到用户偏好向量
    dim = len(embeddings[0].embedding)
    pref = [0.0] * dim
    total_weight = 0.0
    for emb in embeddings:
        w = weights[emb.product_id]
        vec = emb.embedding
        for i in range(dim):
            pref[i] += float(vec[i]) * w
        total_weight += w
    if total_weight <= 0:
        return []
    pref = [v / total_weight for v in pref]

    # cosine 近邻检索，排除已交互过的商品
    distance = ProductEmbedding.embedding.cosine_distance(pref)
    stmt = (
        select(Product, distance.label("distance"))
        .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .where(Product.status == 1, ProductEmbedding.product_id.notin_(interacted_ids))
        .order_by(distance)
        .limit(limit)
    )
    rows = await db.execute(stmt)
    return [_card(p, 1 - float(d)) for p, d in rows]


async def get_similar(db: AsyncSession, product_id: int, top_k: int = 8) -> list[dict]:
    """L2 相似推荐：单商品向量近邻；商品不存在或已下架抛 3001。"""
    product = await db.get(Product, product_id)
    if product is None or product.status != 1:
        raise BizError(3001, "商品不存在或已下架", 404)
    results = await similar_products(db, product_id, top_k)
    return [_card(p, sim) for p, sim in results]


async def _load_cache(user_id: int) -> list[dict] | None:
    try:
        raw = await redis.get(_CACHE_KEY.format(user_id=user_id))
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("读取推荐缓存失败: user=%s", user_id)
        return None


async def _save_cache(user_id: int, cards: list[dict]) -> None:
    try:
        await redis.set(
            _CACHE_KEY.format(user_id=user_id),
            json.dumps(cards, ensure_ascii=False),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception:
        logger.warning("写入推荐缓存失败: user=%s", user_id)
