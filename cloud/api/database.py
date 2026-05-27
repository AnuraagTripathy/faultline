"""SQLAlchemy database layer — SQLite (dev) and PostgreSQL (production)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterator, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, Result

_engine: Engine | None = None


def default_sqlite_path() -> Path:
    raw = os.environ.get("FAULTLINE_CLOUD_DB")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "data" / "faultline.db"


def database_url() -> str:
    explicit = os.environ.get("FAULTLINE_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    path = default_sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def is_postgres() -> bool:
    return database_url().startswith("postgresql")


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = database_url()
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
    return _engine


def reset_engine() -> None:
    """Test helper — clear cached engine after env change."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


class DbRow(Mapping[str, Any]):
    """sqlite3.Row-compatible mapping from SQLAlchemy rows."""

    def __init__(self, mapping: Mapping[str, Any]) -> None:
        self._data = dict(mapping)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def keys(self) -> list[str]:
        return list(self._data.keys())


class DbCursor:
    def __init__(self, result: Result[Any] | None) -> None:
        self._result = result

    def fetchone(self) -> DbRow | None:
        if self._result is None:
            return None
        row = self._result.fetchone()
        if row is None:
            return None
        return DbRow(row._mapping)

    def fetchall(self) -> list[DbRow]:
        if self._result is None:
            return []
        return [DbRow(r._mapping) for r in self._result.fetchall()]


_QMARK_PATTERN = re.compile(r"\?")


def _bind_qmark_sql(sql: str, params: tuple[Any, ...]) -> tuple[str, dict[str, Any]]:
    if not params:
        return sql, {}
    if "?" not in sql:
        return sql, dict(zip([f"p{i}" for i in range(len(params))], params))
    parts = _QMARK_PATTERN.split(sql, len(params))
    if len(parts) != len(params) + 1:
        raise ValueError("SQL placeholder count does not match params")
    bind: dict[str, Any] = {}
    out: list[str] = [parts[0]]
    for index, part in enumerate(parts[1:]):
        key = f"p{index}"
        bind[key] = params[index]
        out.append(f":{key}")
        out.append(part)
    return "".join(out), bind


class DbConnection:
    """Unified DB connection for SQLite and PostgreSQL."""

    def __init__(self, conn: Connection | None = None) -> None:
        self._owned = conn is None
        self._conn = conn if conn is not None else get_engine().connect()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> DbCursor:
        bound_sql, bind = _bind_qmark_sql(sql, params)
        result = self._conn.execute(text(bound_sql), bind)
        return DbCursor(result)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            stmt = statement.strip()
            if stmt:
                self._conn.execute(text(stmt))

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        if self._owned:
            self._conn.close()

    def table_exists(self, name: str) -> bool:
        if is_postgres():
            row = self.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = ?
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        else:
            row = self.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                (name,),
            ).fetchone()
        return row is not None

    def column_exists(self, table: str, column: str) -> bool:
        if is_postgres():
            row = self.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ? AND column_name = ?
                LIMIT 1
                """,
                (table, column),
            ).fetchone()
        else:
            rows = self.execute(f"PRAGMA table_info({table})").fetchall()
            return any(str(r["name"]) == column for r in rows)
        return row is not None


def connect() -> DbConnection:
    return DbConnection()
