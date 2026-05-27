"""Migration runner tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from cloud.api.database import connect, reset_engine  # noqa: E402
from cloud.api.env_validation import validate_startup_config  # noqa: E402
from cloud.api.migrations import (  # noqa: E402
    database_revision,
    head_revision,
    run_pending_migrations,
    verify_migrations_at_head,
)


class TestMigrations(unittest.TestCase):
    def _cleanup_db_file(self, db_path: str) -> None:
        reset_engine()
        try:
            Path(db_path).unlink(missing_ok=True)
        except PermissionError:
            pass

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_DATABASE_URL", None)
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ.pop("FAULTLINE_ENV", None)

    def test_upgrade_head_on_empty_sqlite(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        os.environ["FAULTLINE_DATABASE_URL"] = f"sqlite:///{Path(db_path).as_posix()}"
        os.environ["FAULTLINE_ENV"] = "development"
        try:
            revision = run_pending_migrations()
            self.assertEqual(revision, head_revision())
            verify_migrations_at_head()
            conn = connect()
            try:
                self.assertTrue(conn.table_exists("users"))
            finally:
                conn.close()
        finally:
            self._cleanup_db_file(db_path)

    def test_second_upgrade_is_idempotent(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        os.environ["FAULTLINE_DATABASE_URL"] = f"sqlite:///{Path(db_path).as_posix()}"
        os.environ["FAULTLINE_ENV"] = "development"
        try:
            run_pending_migrations()
            first = database_revision()
            run_pending_migrations()
            second = database_revision()
            self.assertEqual(first, second)
            verify_migrations_at_head()
        finally:
            self._cleanup_db_file(db_path)

    def test_production_requires_postgres_url(self) -> None:
        os.environ["FAULTLINE_ENV"] = "production"
        os.environ["FAULTLINE_JWT_SECRET"] = "x" * 32
        os.environ["FAULTLINE_COOKIE_SECURE"] = "true"
        os.environ.pop("FAULTLINE_DATABASE_URL", None)
        with self.assertRaises(RuntimeError):
            validate_startup_config()


if __name__ == "__main__":
    unittest.main()
