from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_session_token(*, user_id: uuid.UUID) -> str:
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(minutes=int(settings.auth_token_ttl_minutes))
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "session",
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=ALGORITHM)


def decode_session_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.auth_jwt_secret, algorithms=[ALGORITHM])
        if payload.get("type") != "session":
            raise ValueError("Invalid token type")
        return uuid.UUID(str(payload.get("sub")))
    except (JWTError, ValueError) as e:
        raise ValueError("Invalid session") from e
