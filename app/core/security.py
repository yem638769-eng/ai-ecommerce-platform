"""密码哈希（bcrypt）与 JWT 签发/校验。"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import BizError


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise BizError(1004, "密码过长")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _create_token(user_id: int, role: str, token_type: str, expires_delta: timedelta) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "exp": datetime.now(timezone.utc) + expires_delta,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(
        user_id, role, "access",
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: int, role: str) -> str:
    return _create_token(
        user_id, role, "refresh",
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise BizError(1001, "无效或过期的凭证", 401)
    if payload.get("type") != expected_type:
        raise BizError(1001, "凭证类型错误", 401)
    return payload
