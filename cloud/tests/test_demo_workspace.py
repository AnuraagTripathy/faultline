"""Public demo workspace API tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from cloud.api.app import create_app  # noqa: E402
from cloud.api.database import reset_engine  # noqa: E402
from cloud.api.db import DEV_API_KEY, connect, init_db  # noqa: E402
from cloud.api.demo_seed import seed_demo_data  # noqa: E402


class TestDemoWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        self._db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._db.name
        conn = connect()
        init_db(conn)
        conn.close()
        seed_demo_data()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        Path(self._db.name).unlink(missing_ok=True)

    def test_workspace_returns_runs(self) -> None:
        response = self.client.get("/v1/demo/workspace")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("runs", body)
        self.assertIsInstance(body["runs"], list)
        self.assertIn("events", body)
        self.assertIn("checkpoints", body)


if __name__ == "__main__":
    unittest.main()
