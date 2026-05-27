"""PostgreSQL / SQLAlchemy database layer tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from cloud.api.database import connect, database_url, is_postgres, reset_engine
from cloud.api.db import init_db, now_ms, seed_dev_user


class TestDatabaseLayer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_file = Path(self._tmpdir.name) / "test.db"
        os.environ["FAULTLINE_DATABASE_URL"] = f"sqlite:///{self._db_file.as_posix()}"
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        reset_engine()

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_DATABASE_URL", None)
        self._tmpdir.cleanup()

    def test_sqlite_url_default(self) -> None:
        os.environ.pop("FAULTLINE_DATABASE_URL", None)
        reset_engine()
        url = database_url()
        self.assertTrue(url.startswith("sqlite:///"))
        self.assertFalse(is_postgres())

    def test_connect_and_init(self) -> None:
        conn = connect()
        try:
            init_db(conn)
            row = conn.execute("SELECT 1 AS n").fetchone()
            self.assertEqual(int(row["n"]), 1)
            seed_dev_user(conn)
            users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
            self.assertGreaterEqual(int(users["c"]), 1)
        finally:
            conn.close()

    def test_alert_settings_table_exists(self) -> None:
        conn = connect()
        try:
            init_db(conn)
            self.assertTrue(conn.table_exists("user_alert_settings"))
            self.assertTrue(conn.table_exists("background_tasks"))
        finally:
            conn.close()

    def test_epoch_ms_fits_in_users_created_at(self) -> None:
        conn = connect()
        try:
            init_db(conn)
            ts = now_ms()
            conn.execute(
                "INSERT INTO users (id, email, created_at_ms) VALUES (?, ?, ?)",
                ("bigint-test", "bigint@test.com", ts),
            )
            row = conn.execute(
                "SELECT created_at_ms FROM users WHERE id = ?",
                ("bigint-test",),
            ).fetchone()
            self.assertEqual(int(row["created_at_ms"]), ts)
            self.assertGreater(ts, 2_147_483_647)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
