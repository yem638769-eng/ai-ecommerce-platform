"""商家知识库接口：文档创建（后台向量化）、列表、删除。"""
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_merchant, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import kb as crud_kb
from app.models import Merchant, User
from app.schemas.ai import KBDocumentCreateIn, KBDocumentOut
from app.schemas.common import PageOut
from app.services.ai.indexing import delete_document_chunks, index_kb_document

router = APIRouter(prefix="/merchant/kb", tags=["商家知识库"])


@router.post("/documents")
async def create_document(
    data: KBDocumentCreateIn,
    background_tasks: BackgroundTasks,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """创建知识库文档：落库后后台任务向量化（status 0 处理中 → 1 成功 / 2 失败）。"""
    _user, merchant = auth
    document = await crud_kb.create_document(db, merchant.id, data)
    background_tasks.add_task(index_kb_document, document.id)
    return ok(KBDocumentOut.model_validate(document), message="文档已创建，正在向量化")


@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """商家文档列表（含向量化状态）。"""
    _user, merchant = auth
    documents, total = await crud_kb.list_documents(db, merchant.id, page, page_size)
    return ok(
        PageOut[KBDocumentOut](
            items=[KBDocumentOut.model_validate(d) for d in documents],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    auth: tuple[User, Merchant] = Depends(get_current_merchant),
    db: AsyncSession = Depends(get_db),
):
    """删除文档：先清理全部分块，再删文档本身。"""
    _user, merchant = auth
    document = await crud_kb.get_document(db, document_id, merchant.id)
    if document is None:
        raise BizError(6002, "文档不存在", 404)
    await delete_document_chunks(document.id)
    await crud_kb.delete_document(db, document)
    return ok(message="文档已删除")
