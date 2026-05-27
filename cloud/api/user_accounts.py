"""User account helpers (signup / lookup)."""

from __future__ import annotations

import uuid

from cloud.api.database import DbConnection, DbRow
from cloud.api.db import now_ms
from cloud.api.passwords import hash_password

def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> None:
    """Pragmatic check — must accept GitHub noreply addresses and multi-label domains."""
    normalized = normalize_email(email)
    if "@" not in normalized or normalized.count("@") != 1:
        raise ValueError("invalid email address")
    local, _, domain = normalized.partition("@")
    if not local or not domain or "." not in domain:
        raise ValueError("invalid email address")
    if any(ch.isspace() for ch in normalized):
        raise ValueError("invalid email address")


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")


def get_user_by_email(conn: DbConnection, email: str) -> DbRow | None:
    return conn.execute(
        "SELECT id, email, password_hash, created_at_ms FROM users WHERE email = ? ORDER BY created_at_ms ASC",
        (normalize_email(email),),
    ).fetchone()


def create_user_with_password(
    conn: DbConnection,
    email: str,
    password: str,
) -> DbRow:
    normalized = normalize_email(email)
    validate_email(normalized)
    validate_password(password)
    if get_user_by_email(conn, normalized) is not None:
        raise ValueError("email already registered")

    user_id = str(uuid.uuid4())
    created = now_ms()
    conn.execute(
        """
        INSERT INTO users (id, email, password_hash, created_at_ms)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, normalized, hash_password(password), created),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, email, password_hash, created_at_ms FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    assert row is not None
    return row


def get_or_create_user_for_oauth(
    conn: DbConnection,
    *,
    email: str,
    provider: str,
) -> DbRow:
    normalized = normalize_email(email)
    validate_email(normalized)
    existing = get_user_by_email(conn, normalized)
    if existing is not None:
        return existing
    user_id = str(uuid.uuid4())
    created = now_ms()
    conn.execute(
        """
        INSERT INTO users (id, email, auth_provider, created_at_ms)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, normalized, provider, created),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, email, password_hash, auth_provider, created_at_ms FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    assert row is not None
    return row
