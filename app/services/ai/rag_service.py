"""RAG 检索服务（§6.2 / §6.5）：知识库分块向量召回与上下文组装。"""
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KBChunk, KBDocument
from app.services.ai.embedding import get_embedding

# 组装知识上下文的长度上限（字符数，近似 token 控制）
_MAX_CONTEXT_CHARS = 2000


async def retrieve(
    db: AsyncSession,
    query: str,
    merchant_id: int | None = None,
    top_k: int = 4,
    score_threshold: float = 0.35,
) -> list[dict]:
    """知识库向量检索：KBChunk cosine 近邻，score = 1 - distance。

    merchant_id 过滤：匹配该商家文档 + 平台级文档（merchant_id 为 NULL）；
    merchant_id 为 None 时不过滤，检索全部知识库。
    低于 score_threshold 的结果丢弃；返回按相似度降序的
    [{"content", "score", "title", "document_id"}]。
    """
    query_vec = await get_embedding(query)
    distance = KBChunk.embedding.cosine_distance(query_vec)
    stmt = select(KBChunk, KBDocument.title, distance.label("distance")).join(
        KBDocument, KBDocument.id == KBChunk.document_id
    )
    if merchant_id is not None:
        stmt = stmt.where(
            or_(KBChunk.merchant_id == merchant_id, KBChunk.merchant_id.is_(None))
        )
    stmt = stmt.order_by(distance).limit(top_k)

    results: list[dict] = []
    for chunk, title, dist in await db.execute(stmt):
        score = 1 - float(dist)
        if score < score_threshold:
            continue
        results.append(
            {
                "content": chunk.content,
                "score": round(score, 4),
                "title": title,
                "document_id": chunk.document_id,
            }
        )
    return results


def build_context(chunks: list[dict]) -> str:
    """将检索结果组装为带包裹标记的知识上下文（防提示注入），总长限制 2000 字。"""
    if not chunks:
        return "（暂无相关知识）"
    parts: list[str] = []
    total = 0
    for i, chunk in enumerate(chunks, start=1):
        remaining = _MAX_CONTEXT_CHARS - total
        if remaining <= 0:
            break
        snippet = chunk["content"][:remaining]
        parts.append(
            f"<知识片段{i} 来源：{chunk['title']}>\n{snippet}\n</知识片段{i}>"
        )
        total += len(snippet)
    return "\n".join(parts)
