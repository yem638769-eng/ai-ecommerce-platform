import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base, TimestampMixin


class ChatSession(TimestampMixin, Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    # service 客服 / guide 导购
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="service", server_default="service")
    title: Mapped[str | None] = mapped_column(String(100))

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        lazy="selectin", order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_created", "session_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    # user / assistant / system / tool
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[list | None] = mapped_column(JSONB)
    tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session = relationship("ChatSession", back_populates="messages")


class KBDocument(TimestampMixin, Base):
    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # faq / product_doc / policy / shipping
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="faq", server_default="faq")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 0 处理中 / 1 已向量化 / 2 失败
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")

    chunks = relationship(
        "KBChunk", back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )


class KBChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index(
            "ix_kb_chunks_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_kb_chunks_document", "document_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"), nullable=False)
    merchant_id: Mapped[int | None] = mapped_column(index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(settings.embed_dim), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document = relationship("KBDocument", back_populates="chunks")
