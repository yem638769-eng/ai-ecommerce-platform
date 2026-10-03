"""对话会话与消息 CRUD。"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatSession


async def create_session(
    db: AsyncSession, user_id: int, chat_type: str, title: str | None = None
) -> ChatSession:
    """新建会话，title 取首条消息摘要。"""
    session = ChatSession(user_id=user_id, type=chat_type, title=title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: int
) -> ChatSession | None:
    """按 ID 查询本人的会话（越权防护）。"""
    stmt = select(ChatSession).where(
        ChatSession.id == session_id, ChatSession.user_id == user_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_sessions(
    db: AsyncSession,
    user_id: int,
    chat_type: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[ChatSession], int]:
    """我的会话列表（按更新时间倒序，可按类型过滤）。"""
    stmt = select(ChatSession).where(ChatSession.user_id == user_id)
    if chat_type:
        stmt = stmt.where(ChatSession.type == chat_type)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    stmt = (
        stmt.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    sessions = list((await db.execute(stmt)).scalars())
    return sessions, int(total)


async def list_messages(
    db: AsyncSession, session_id: uuid.UUID, page: int = 1, page_size: int = 50
) -> tuple[list[ChatMessage], int]:
    """会话历史消息（按 id 升序分页）。"""
    stmt = select(ChatMessage).where(ChatMessage.session_id == session_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    stmt = (
        stmt.order_by(ChatMessage.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    messages = list((await db.execute(stmt)).scalars())
    return messages, int(total)


async def list_recent_messages(
    db: AsyncSession, session_id: uuid.UUID, limit: int = 20
) -> list[ChatMessage]:
    """最近 limit 条 user / assistant 消息（id 倒序返回，调用方自行反转）。"""
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.role.in_(["user", "assistant"]))
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars())


async def add_message(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: str,
    content: str,
    tool_calls: list | None = None,
    tokens: int | None = None,
) -> ChatMessage:
    """追加一条消息。"""
    message = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tokens=tokens,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def delete_session(db: AsyncSession, session: ChatSession) -> None:
    """删除会话（消息随外键级联删除）。"""
    await db.delete(session)
    await db.commit()
