"""API key authentication."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cloud.api.db import api_key_prefix, connect, resolve_api_key
from cloud.api.usage import touch_last_used

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    api_key: str
    api_key_id: str
    key_prefix: str
    key_created_at_ms: int


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <api_key>",
        )
    api_key = credentials.credentials.strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty API key",
        )

    conn = connect()
    try:
        row = resolve_api_key(conn, api_key)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        user_id = str(row["user_id"])
        touch_last_used(conn, user_id)
        conn.commit()
        return AuthContext(
            user_id=user_id,
            api_key=api_key,
            api_key_id=str(row["id"]),
            key_prefix=api_key_prefix(api_key),
            key_created_at_ms=int(row["created_at_ms"]),
        )
    finally:
        conn.close()


def get_current_user_id(auth: AuthContext = Depends(get_auth_context)) -> str:
    return auth.user_id
