"""知识库文档 CRUD（商家端）。"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KBDocument
from app.schemas.ai import KBDocumentCreateIn


async def create_document(
    db: AsyncSession, merchant_id: int, data: KBDocumentCreateIn
) -> KBDocument:
    """创建文档：默认 status=0（处理中），向量化由后台任务完成。"""
    document = KBDocument(
        merchant_id=merchant_id,
        title=data.title,
        source_type=data.source_type,
        content=data.content,
        status=0,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def get_document(
    db: AsyncSession, document_id: int, merchant_id: int
) -> KBDocument | None:
    """按 ID 查询本商家的文档（越权防护）。"""
    stmt = select(KBDocument).where(
        KBDocument.id == document_id, KBDocument.merchant_id == merchant_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_documents(
    db: AsyncSession, merchant_id: int, page: int = 1, page_size: int = 10
) -> tuple[list[KBDocument], int]:
    """商家文档列表（含向量化状态，按 id 倒序）。"""
    stmt = select(KBDocument).where(KBDocument.merchant_id == merchant_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    stmt = (
        stmt.order_by(KBDocument.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    documents = list((await db.execute(stmt)).scalars())
    return documents, int(total)


async def delete_document(db: AsyncSession, document: KBDocument) -> None:
    """删除文档（分块建议先由 indexing.delete_document_chunks 清理）。"""
    await db.delete(document)
    await db.commit()
