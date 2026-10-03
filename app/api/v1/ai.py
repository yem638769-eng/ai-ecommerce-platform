"""AI 中台接口：统一对话（SSE 流式）、会话管理、AI 导购、个性化推荐。"""
import logging
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_current_user_optional, get_db
from app.core.exceptions import BizError
from app.core.response import ok
from app.crud import chat as crud_chat
from app.models import User
from app.schemas.ai import (
    ChatIn,
    ChatMessageOut,
    ChatSessionDetailOut,
    ChatSessionOut,
    GuideIn,
    GuideOut,
    RecommendItemOut,
)
from app.schemas.common import PageOut
from app.services.ai import chat_service, guide_service, recommend_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI 中台"])


@router.post("/chat")
async def chat(
    data: ChatIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """统一 AI 对话入口（SSE 流式）。

    事件流：meta（session_id 等）/ tool（Agent 工具调用中间结果）/ delta（增量文本）/
    done（完整回复与 message_id）；每 15 秒发送 ": ping" 心跳。
    """
    if data.session_id is not None:
        session = await crud_chat.get_session(db, data.session_id, user.id)
        if session is None:
            raise BizError(6001, "会话不存在", 404)
        if session.type != data.type:
            raise BizError(6001, "会话类型不匹配", 400)
    return StreamingResponse(
        chat_service.sse_chat(user.id, data.session_id, data.type, data.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions")
async def list_sessions(
    type: str | None = Query(None, description="按类型过滤：service / guide"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我的会话列表。"""
    sessions, total = await crud_chat.list_sessions(db, user.id, type, page, page_size)
    return ok(
        PageOut[ChatSessionOut](
            items=[ChatSessionOut.model_validate(s) for s in sessions],
            total=total,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """会话详情（含历史消息，分页）。"""
    session = await crud_chat.get_session(db, session_id, user.id)
    if session is None:
        raise BizError(6001, "会话不存在", 404)
    messages, _total = await crud_chat.list_messages(db, session_id, page, page_size)
    detail = ChatSessionDetailOut(
        **ChatSessionOut.model_validate(session).model_dump(),
        messages=[ChatMessageOut.model_validate(m) for m in messages],
    )
    return ok(detail)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除会话（消息级联删除）。"""
    session = await crud_chat.get_session(db, session_id, user.id)
    if session is None:
        raise BizError(6001, "会话不存在", 404)
    await crud_chat.delete_session(db, session)
    return ok(message="会话已删除")


@router.post("/guide")
async def guide(
    data: GuideIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI 导购：需求提取 → 语义召回重排 → 推荐话术；LLM 异常降级为纯搜索结果。"""
    result = await guide_service.run_guide(db, user, data.session_id, data.message)
    return ok(GuideOut.model_validate(result))


@router.get("/recommendations")
async def recommendations(
    limit: int = Query(10, ge=1, le=50),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """首页猜你喜欢：未登录 → 热销榜；已登录 → 行为偏好向量召回（缓存 30 分钟）。"""
    cards = await recommend_service.get_recommendations(
        db, user.id if user else None, limit
    )
    return ok([RecommendItemOut.model_validate(c) for c in cards])


@router.get("/recommendations/similar/{product_id}")
async def similar_recommendations(
    product_id: int,
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """相似商品推荐：商品向量近邻 top-k。"""
    cards = await recommend_service.get_similar(db, product_id, limit)
    return ok([RecommendItemOut.model_validate(c) for c in cards])
