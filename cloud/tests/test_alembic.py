"""Alembic migration tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from cloud.api.database import connect, reset_engine  # noqa: E402


class TestAlembic(unittest.TestCase):
    def test_upgrade_head_sqlite(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name
        url = f"sqlite:///{Path(db_path).as_posix()}"
        os.environ["FAULTLINE_DATABASE_URL"] = url
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ["FAULTLINE_ENV"] = "development"
        os.environ["FAULTLINE_DB_AUTO_CREATE"] = "false"
        reset_engine()
        try:
            subprocess.run(
                [sys.executable, "-m", "alembic", "-c", "cloud/alembic.ini", "upgrade", "head"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            conn = connect()
            try:
                self.assertTrue(conn.table_exists("users"))
                self.assertTrue(conn.table_exists("checkpoints"))
                self.assertTrue(conn.table_exists("user_oauth_accounts"))
            finally:
                conn.close()
        finally:
            reset_engine()
            os.environ.pop("FAULTLINE_DATABASE_URL", None)
            os.environ.pop("FAULTLINE_DB_AUTO_CREATE", None)
            Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
