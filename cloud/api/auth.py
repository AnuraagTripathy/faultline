"""Authentication: Bearer API keys (SDK) and JWT session cookies (browser)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cloud.api.db import api_key_prefix, connect, resolve_api_key, touch_api_key_last_used
from cloud.api.sessions import SESSION_COOKIE_NAME, decode_access_token
from cloud.api.usage import touch_last_used

_bearer = HTTPBearer(auto_error=False)

AuthMethod = Literal["api_key", "session"]


@dataclass(frozen=True)
class UserAuth:
    user_id: str
    method: AuthMethod
    api_key_id: str | None = None
    api_key: str | None = None
    key_prefix: str | None = None
    key_created_at_ms: int | None = None


# Backwards-compatible alias used in older code/tests.
AuthContext = UserAuth


def _auth_from_api_key(api_key: str) -> UserAuth:
    conn = connect()
    try:
        row = resolve_api_key(conn, api_key)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        user_id = str(row["user_id"])
        api_key_id = str(row["id"])
        touch_last_used(conn, user_id)
        touch_api_key_last_used(conn, api_key_id)
        conn.commit()
        return UserAuth(
            user_id=user_id,
            method="api_key",
            api_key_id=api_key_id,
            api_key=api_key,
            key_prefix=api_key_prefix(api_key),
            key_created_at_ms=int(row["created_at_ms"]),
        )
    finally:
        conn.close()


def _auth_from_session_token(token: str) -> UserAuth:
    try:
        payload = decode_access_token(token)
    except Exception as error:  # noqa: BLE001 — invalid/expired JWT
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        ) from error
    user_id = str(payload.get("sub", "")).strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token",
        )
    conn = connect()
    try:
        touch_last_used(conn, user_id)
        conn.commit()
    finally:
        conn.close()
    return UserAuth(user_id=user_id, method="session")


def get_user_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    faultline_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> UserAuth:
    """Resolve user from Bearer API key, Bearer session JWT, or session cookie."""
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials.strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empty API key",
            )
        if token.startswith("fl_"):
            return _auth_from_api_key(token)
        return _auth_from_session_token(token)

    if faultline_session:
        return _auth_from_session_token(faultline_session)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (Bearer API key or session)",
    )


def get_auth_context(auth: UserAuth = Depends(get_user_auth)) -> UserAuth:
    """Require API key auth specifically (SDK endpoints that need key metadata)."""
    if auth.method != "api_key":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer API key required",
        )
    return auth


def get_current_user_id(auth: UserAuth = Depends(get_user_auth)) -> str:
    return auth.user_id
