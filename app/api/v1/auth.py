"""认证接口：注册 / 登录 / 刷新 / 登出。Refresh Token 白名单存 Redis。"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.exceptions import BizError
from app.core.redis import redis
from app.core.response import ok
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.crud import user as crud_user
from app.models import User
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["认证"])

_TOKEN_KEY = "user:token:{user_id}"


def _issue_tokens(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id, user.role),
        user=UserOut.model_validate(user),
    )


async def _store_refresh_token(user_id: int, token: str) -> None:
    await redis.set(
        _TOKEN_KEY.format(user_id=user_id),
        token,
        ex=timedelta(days=settings.refresh_token_expire_days),
    )


@router.post("/register")
async def register(data: RegisterIn, db: AsyncSession = Depends(get_db)):
    if data.username and await crud_user.get_by_username(db, data.username):
        raise BizError(2001, "用户名已存在", 409)
    if data.email and await crud_user.get_by_email(db, data.email):
        raise BizError(2001, "邮箱已被注册", 409)
    if data.phone and await crud_user.get_by_phone(db, data.phone):
        raise BizError(2001, "手机号已被注册", 409)

    user = await crud_user.create_user(db, data)
    tokens = _issue_tokens(user)
    await _store_refresh_token(user.id, tokens.refresh_token)
    return ok(tokens)


@router.post("/login")
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)):
    user = await crud_user.get_by_account(db, data.account)
    if user is None or not verify_password(data.password, user.password_hash):
        raise BizError(2002, "账号或密码错误", 401)
    if user.status != 1:
        raise BizError(2002, "账号已被禁用", 403)

    tokens = _issue_tokens(user)
    await _store_refresh_token(user.id, tokens.refresh_token)
    return ok(tokens)


@router.post("/refresh")
async def refresh(data: RefreshIn, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token, expected_type="refresh")
    user_id = int(payload["sub"])
    stored = await redis.get(_TOKEN_KEY.format(user_id=user_id))
    if stored != data.refresh_token:
        raise BizError(1001, "登录已失效，请重新登录", 401)

    user = await crud_user.get_by_id(db, user_id)
    if user is None or user.status != 1:
        raise BizError(1002, "账号不可用", 403)

    tokens = _issue_tokens(user)
    await _store_refresh_token(user.id, tokens.refresh_token)
    return ok(tokens)


@router.post("/logout")
async def logout(data: RefreshIn):
    try:
        payload = decode_token(data.refresh_token, expected_type="refresh")
        user_id = int(payload["sub"])
    except BizError:
        return ok(message="已退出登录")
    stored = await redis.get(_TOKEN_KEY.format(user_id=user_id))
    if stored == data.refresh_token:
        await redis.delete(_TOKEN_KEY.format(user_id=user_id))
    return ok(message="已退出登录")
