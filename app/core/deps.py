"""通用依赖：DB 会话、当前用户、商家身份等。"""
from typing import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BizError
from app.core.security import decode_token
from app.db.base import AsyncSessionLocal
from app.models import Merchant, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise BizError(1001, "未登录", 401)
    payload = decode_token(token, expected_type="access")
    user = await db.get(User, int(payload["sub"]))
    if user is None or user.status != 1:
        raise BizError(1002, "账号不可用", 403)
    return user


async def get_current_user_optional(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not token:
        return None
    try:
        payload = decode_token(token, expected_type="access")
    except BizError:
        return None
    user = await db.get(User, int(payload["sub"]))
    if user is None or user.status != 1:
        return None
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise BizError(1003, "需要管理员权限", 403)
    return user


async def get_current_merchant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Merchant]:
    """返回 (用户, 商家) 二元组；未开店返回 5001。"""
    stmt = select(Merchant).where(Merchant.user_id == user.id)
    merchant = (await db.execute(stmt)).scalar_one_or_none()
    if merchant is None:
        raise BizError(5001, "请先开通店铺", 403)
    if merchant.status == 0:
        raise BizError(5001, "店铺已被冻结", 403)
    return user, merchant
