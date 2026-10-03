"""AI 中台出入参模型：对话 / 会话 / 导购 / 推荐 / 商家知识库。"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ===== 统一对话（SSE） =====


class ChatIn(BaseModel):
    """统一 AI 对话入参：session_id 为空则新建会话。"""

    session_id: Optional[uuid.UUID] = None
    message: str = Field(..., min_length=1, max_length=2000)
    type: Literal["service", "guide"] = "service"


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    tool_calls: Optional[list] = None
    tokens: Optional[int] = None
    created_at: datetime


class ChatSessionDetailOut(ChatSessionOut):
    """会话详情：含历史消息。"""

    messages: list[ChatMessageOut] = []


# ===== AI 导购 =====


class GuideIn(BaseModel):
    """AI 导购入参：自然语言需求，session_id 支持多轮补充。"""

    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[uuid.UUID] = None


class GuideRequirementsOut(BaseModel):
    """LLM 提取的结构化需求。"""

    category: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    attributes: list[str] = []
    use_case: Optional[str] = None


class GuideProductOut(BaseModel):
    """导购推荐商品卡片。"""

    id: int
    name: str
    subtitle: Optional[str] = None
    price_min: float
    price_max: float
    main_image: str
    sales_count: int
    similarity: Optional[float] = None
    match_reasons: list[str] = []


class GuideOut(BaseModel):
    session_id: str
    requirements: Optional[GuideRequirementsOut] = None
    reply: Optional[str] = None
    products: list[GuideProductOut] = []


# ===== 个性化推荐 =====


class RecommendItemOut(BaseModel):
    """推荐商品卡片（热销 / 个性化 / 相似通用）。"""

    id: int
    name: str
    subtitle: Optional[str] = None
    price_min: float
    price_max: float
    main_image: str
    sales_count: int
    rating_avg: float
    similarity: Optional[float] = None


# ===== 商家知识库 =====


class KBDocumentCreateIn(BaseModel):
    """创建知识库文档。"""

    title: str = Field(..., min_length=1, max_length=200)
    source_type: Literal["faq", "product_doc", "policy", "shipping"] = "faq"
    content: str = Field(..., min_length=1)


class KBDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source_type: str
    status: int
    created_at: datetime
    updated_at: datetime
