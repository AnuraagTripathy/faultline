"""Cloud ingestion API tests."""

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


class TestCloudApi(unittest.TestCase):
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

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_auth_required(self) -> None:
        response = self.client.get("/v1/runs")
        self.assertEqual(response.status_code, 401)

    def test_invalid_api_key(self) -> None:
        response = self.client.get(
            "/v1/runs",
            headers={"Authorization": "Bearer invalid"},
        )
        self.assertEqual(response.status_code, 401)

    def test_start_run_and_log_metrics(self) -> None:
        start = self.client.post(
            "/v1/runs/start",
            json={
                "project": "protein-model",
                "run_name": "cloud-exp-1",
                "tags": ["demo"],
            },
            headers=AUTH,
        )
        self.assertEqual(start.status_code, 200)
        body = start.json()
        run_id = body["run_id"]
        self.assertEqual(body["status"], "running")
        self.assertEqual(body["project_name"], "protein-model")

        metrics = self.client.post(
            f"/v1/runs/{run_id}/metrics",
            json={"step": 1, "metrics": {"loss": 0.42, "learning_rate": 0.01}},
            headers=AUTH,
        )
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json()["latest_step"], 1)
        self.assertAlmostEqual(metrics.json()["latest_loss"], 0.42)

        history = self.client.get(
            f"/v1/runs/{run_id}/metrics",
            headers=AUTH,
        )
        self.assertEqual(history.status_code, 200)
        points = history.json()
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["metrics"]["loss"], 0.42)

    def test_complete_via_event(self) -> None:
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        done = self.client.post(
            f"/v1/runs/{run_id}/events",
            json={
                "event_type": "faultline.run.completed",
                "level": "info",
                "message": "finished",
            },
            headers=AUTH,
        )
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["status"], "completed")

        listed = self.client.get("/v1/runs", headers=AUTH)
        self.assertEqual(listed.json()[0]["run_id"], run_id)

    def test_list_run_events(self) -> None:
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        self.client.post(
            f"/v1/runs/{run_id}/events",
            json={
                "event_type": "faultline.run.completed",
                "level": "info",
                "message": "done",
            },
            headers=AUTH,
        )
        events = self.client.get(
            f"/v1/runs/{run_id}/events",
            headers=AUTH,
        )
        self.assertEqual(events.status_code, 200)
        body = events.json()
        self.assertGreaterEqual(len(body), 1)
        self.assertEqual(body[0]["event_type"], "faultline.run.completed")
        self.assertEqual(body[0]["message"], "done")

    def test_dashboard_returns_html(self) -> None:
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn(b"Faultline Cloud", response.content)

    def test_list_runs_includes_summary_fields(self) -> None:
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "proj", "run_name": "run-a"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        self.client.post(
            f"/v1/runs/{run_id}/metrics",
            json={"step": 3, "metrics": {"loss": 1.5}},
            headers=AUTH,
        )
        listed = self.client.get("/v1/runs", headers=AUTH)
        row = next(item for item in listed.json() if item["run_id"] == run_id)
        self.assertEqual(row["project_name"], "proj")
        self.assertEqual(row["run_name"], "run-a")
        self.assertEqual(row["latest_step"], 3)
        self.assertAlmostEqual(row["latest_loss"], 1.5)
        self.assertIn(row["status"], ("running", "completed", "failed", "stopped"))


if __name__ == "__main__":
    unittest.main()
