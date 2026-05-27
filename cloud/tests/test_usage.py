"""Usage tracking and account API tests."""

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

AUTH = {"Authorization": f"Bearer {DEV_API_KEY}"}


class TestCloudUsage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._tmp.name
        conn = connect()
        init_db(conn)
        conn.close()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_me_returns_user_key_usage(self) -> None:
        response = self.client.get("/v1/me", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"]["email"], "dev@faultline.local")
        self.assertIn("fl_dev", body["api_key"]["prefix"])
        self.assertIn("usage", body)

    def test_usage_endpoint(self) -> None:
        response = self.client.get("/v1/usage", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIn("runs_created", response.json())

    def test_runs_metrics_events_update_usage(self) -> None:
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        self.client.post(
            f"/v1/runs/{run_id}/metrics",
            json={"step": 1, "metrics": {"loss": 0.1}},
            headers=AUTH,
        )
        self.client.post(
            f"/v1/runs/{run_id}/events",
            json={"event_type": "note", "message": "hi"},
            headers=AUTH,
        )
        usage = self.client.get("/v1/usage", headers=AUTH).json()
        self.assertGreaterEqual(usage["runs_created"], 1)
        self.assertGreaterEqual(usage["metric_points_ingested"], 1)
        self.assertGreaterEqual(usage["events_ingested"], 1)
        self.assertIsNotNone(usage["last_used_at_ms"])

    def test_landing_and_getting_started(self) -> None:
        landing = self.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertIn(b"resume failed training", landing.content)

        gs = self.client.get("/getting-started")
        self.assertEqual(gs.status_code, 200)
        self.assertIn(b"Faultline Cloud", gs.content)

    def test_dashboard_still_loads(self) -> None:
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Account", response.content)


if __name__ == "__main__":
    unittest.main()
