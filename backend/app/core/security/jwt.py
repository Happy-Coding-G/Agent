from __future__ import annotations

from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError

from app.core.config import settings


class TokenDecodeError(Exception):
    pass


# 生成JWT令牌
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def safe_decode(token: str) -> dict:
    try:
        return decode_access_token(token)
    except JWTError as e:
        raise TokenDecodeError(str(e))

