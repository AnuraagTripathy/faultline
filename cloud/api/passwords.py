"""Password hashing for user accounts (bcrypt)."""

from __future__ import annotations

try:
    import bcrypt
except ImportError as error:  # pragma: no cover
    raise ImportError(
        "bcrypt is required for user authentication. Install with: pip install bcrypt"
    ) from error


def hash_password(password: str) -> str:
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return digest.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False
