"""统一业务异常与全局异常处理器。

错误码段：1xxx 通用 / 2xxx 用户 / 3xxx 商品 / 4xxx 订单 / 5xxx 商家 / 6xxx AI
"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class BizError(Exception):
    def __init__(self, code: int, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def biz_error_handler(request: Request, exc: BizError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    msg = first.get("msg", "参数校验失败")
    message = f"{loc}: {msg}" if loc else msg
    return JSONResponse(
        status_code=422,
        content={"code": 1000, "message": message, "data": None},
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": str(exc.detail), "data": None},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": 1500, "message": "服务器内部错误", "data": None},
    )
