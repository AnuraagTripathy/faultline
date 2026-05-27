"""JWT session tokens for browser authentication."""

from __future__ import annotations

import os
import time
from typing import Any

try:
    import jwt
except ImportError as error:  # pragma: no cover
    raise ImportError(
        "PyJWT is required for session authentication. "
        "Install with: pip install PyJWT"
    ) from error

SESSION_COOKIE_NAME = "faultline_session"
SESSION_TTL_SECONDS = int(os.environ.get("FAULTLINE_SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
JWT_ALGORITHM = "HS256"


def jwt_secret() -> str:
    secret = os.environ.get("FAULTLINE_JWT_SECRET", "").strip()
    if secret:
        return secret
    return "faultline-dev-jwt-secret-change-in-production"


def create_access_token(user_id: str, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
