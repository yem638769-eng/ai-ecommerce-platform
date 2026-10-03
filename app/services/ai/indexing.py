"""向量索引（§6.5 离线 Pipeline）：商品向量重建 / 移除、知识库文档向量化 / 分块删除。

全部使用 AsyncSessionLocal 自开会话，不接收调用方 db（M4 商品上下架契约）。
"""
import logging
import re

from sqlalchemy import delete, update

from app.db.base import AsyncSessionLocal
from app.models import KBChunk, KBDocument, Product, ProductEmbedding
from app.services.ai.embedding import get_embeddings

logger = logging.getLogger(__name__)

# 中文分块：每块约 500 字，相邻块重叠 50 字
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
# 向量化批量大小
_EMBED_BATCH = 32
# 商品描述参与向量化的长度上限（字）
_PRODUCT_DESC_MAX = 500

_HTML_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(text: str | None) -> str:
    """文本清洗：去 HTML 标签、统一空白为单个空格。"""
    if not text:
        return ""
    return _WS_RE.sub(" ", _HTML_RE.sub(" ", text)).strip()


def split_chunks(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """中文分块：固定窗口滑动切分，步长 = size - overlap，保证相邻块重叠。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(size - overlap, 1)
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


async def rebuild_product_embedding(product_id: int) -> bool:
    """重建商品向量（M4 契约）：仅 status==1 时重建，先删 ProductEmbedding 再插。

    content = 商品名称 + 副标题 + 分类名 + 描述（截断 500 字）。
    """
    async with AsyncSessionLocal() as db:
        product = await db.get(Product, product_id)
        if product is None or product.status != 1:
            # 商品不存在或未上架：清理可能残留的旧向量后返回 False
            await db.execute(
                delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
            )
            await db.commit()
            return False

        parts = [product.name]
        if product.subtitle:
            parts.append(product.subtitle)
        if product.category is not None and product.category.name:
            parts.append(product.category.name)
        if product.description:
            parts.append(clean_text(product.description)[:_PRODUCT_DESC_MAX])
        content = " ".join(p for p in parts if p).strip()
        if not content:
            return False

        try:
            embedding = (await get_embeddings([content]))[0]
        except Exception:
            logger.exception("商品向量化失败: product_id=%s", product_id)
            return False

        await db.execute(
            delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
        )
        db.add(ProductEmbedding(product_id=product_id, content=content, embedding=embedding))
        await db.commit()
        return True


async def remove_product_embedding(product_id: int) -> None:
    """移除商品向量（M4 契约）：商品下架 / 删除时调用。"""
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ProductEmbedding).where(ProductEmbedding.product_id == product_id)
        )
        await db.commit()


async def index_kb_document(document_id: int) -> bool:
    """知识库文档向量化（M4 契约）：清洗 → 分块 → 批量向量化 → 写 KBChunk。

    成功置 KBDocument.status=1；异常捕获后置 2 并返回 False。
    """
    async with AsyncSessionLocal() as db:
        document = await db.get(KBDocument, document_id)
        if document is None:
            logger.warning("向量化目标文档不存在: document_id=%s", document_id)
            return False
        try:
            raw_chunks = split_chunks(clean_text(document.content))
            if not raw_chunks:
                raise ValueError("文档清洗后无有效内容")
            # 标题前缀拼入每块，便于检索结果溯源
            chunks = [f"{document.title}\n{c}" for c in raw_chunks]

            embeddings: list[list[float]] = []
            for i in range(0, len(chunks), _EMBED_BATCH):
                embeddings.extend(await get_embeddings(chunks[i : i + _EMBED_BATCH]))

            await db.execute(delete(KBChunk).where(KBChunk.document_id == document_id))
            for idx, (chunk, vector) in enumerate(zip(chunks, embeddings)):
                db.add(
                    KBChunk(
                        document_id=document_id,
                        merchant_id=document.merchant_id,
                        chunk_index=idx,
                        content=chunk,
                        embedding=vector,
                    )
                )
            document.status = 1
            await db.commit()
            return True
        except Exception:
            logger.exception("知识库文档向量化失败: document_id=%s", document_id)
            # rollback 会使 ORM 对象过期，改用显式 UPDATE 置失败状态
            await db.rollback()
            await db.execute(
                update(KBDocument).where(KBDocument.id == document_id).values(status=2)
            )
            await db.commit()
            return False


async def delete_document_chunks(document_id: int) -> None:
    """删除文档全部分块（M4 契约）：删除知识库文档前调用。"""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(KBChunk).where(KBChunk.document_id == document_id))
        await db.commit()
