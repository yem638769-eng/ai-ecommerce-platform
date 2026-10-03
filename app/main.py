"""FastAPI 应用入口。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.models  # noqa: F401  导入以注册全部模型
from app.api.v1 import api_router
from app.core.config import settings
from app.core.exceptions import (
    BizError,
    biz_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.redis import redis
from app.core.response import ok
from app.db.base import Base, engine
from app.services.ai.llm import get_llm
from app.tasks.scheduler import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def _init_tables() -> None:
    """开发模式：自动创建 vector 扩展与全部数据表。"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据表已就绪（AUTO_CREATE_TABLES）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        try:
            await _init_tables()
        except Exception:
            logger.exception("自动建表失败，请检查数据库连接")
    start_scheduler()
    yield
    await engine.dispose()
    await redis.aclose()


app = FastAPI(title="AI 电商平台 API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(BizError, biz_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["系统"])
async def health():
    db_ok = redis_ok = llm_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        pass
    try:
        llm_ok = await get_llm().health()
    except Exception:
        llm_ok = False
    return ok({"database": db_ok, "redis": redis_ok, "llm": llm_ok})
