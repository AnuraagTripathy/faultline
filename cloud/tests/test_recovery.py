"""Recovery endpoint tests (v17.1 crash-to-resume)."""

from __future__ import annotations

import os
import pickle
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
from cloud.api.storage import get_checkpoint_storage  # noqa: E402

AUTH = {"Authorization": f"Bearer {DEV_API_KEY}"}


class TestCloudRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._db.name
        os.environ["FAULTLINE_CLOUD_CHECKPOINTS_DIR"] = str(
            Path(self._tmpdir) / "checkpoints"
        )
        conn = connect()
        init_db(conn)
        conn.close()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ.pop("FAULTLINE_CLOUD_CHECKPOINTS_DIR", None)
        Path(self._db.name).unlink(missing_ok=True)

    def _start_run(self) -> str:
        response = self.client.post(
            "/v1/runs/start",
            json={"project": "demo", "run_name": "recovery-test"},
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["run_id"]

    def test_recovery_no_checkpoint(self) -> None:
        run_id = self._start_run()
        self.client.post(
            f"/v1/runs/{run_id}/metrics",
            json={"step": 5, "metrics": {"loss": 0.5}},
            headers=AUTH,
        )
        recovery = self.client.get(f"/v1/runs/{run_id}/recovery", headers=AUTH)
        self.assertEqual(recovery.status_code, 200)
        body = recovery.json()
        self.assertFalse(body["has_checkpoint"])
        self.assertEqual(body["recommendation"], "no_checkpoint")
        self.assertEqual(body["recovery_badge"], "no_checkpoint")
        self.assertEqual(body["estimated_lost_steps"], 5)

    def test_recovery_with_lost_steps(self) -> None:
        run_id = self._start_run()
        blob = pickle.dumps({"step": 10, "model_state": {"w": 1.0}})
        upload = self.client.post(
            f"/v1/runs/{run_id}/checkpoints",
            data={"step": "10"},
            files={"file": ("c.pkl", blob, "application/octet-stream")},
            headers=AUTH,
        )
        self.assertEqual(upload.status_code, 200)
        for step in range(11, 16):
            self.client.post(
                f"/v1/runs/{run_id}/metrics",
                json={"step": step, "metrics": {"loss": 0.1}},
                headers=AUTH,
            )
        recovery = self.client.get(f"/v1/runs/{run_id}/recovery", headers=AUTH)
        body = recovery.json()
        self.assertTrue(body["has_checkpoint"])
        self.assertEqual(body["latest_checkpoint_step"], 10)
        self.assertEqual(body["latest_step"], 15)
        self.assertEqual(body["estimated_lost_steps"], 5)
        self.assertEqual(body["checkpoint_health"], "ok")
        self.assertEqual(body["recommendation"], "resume_from_checkpoint")
        self.assertIn("restore_latest", body["resume_snippet"])

    def test_recovery_after_failed_run(self) -> None:
        run_id = self._start_run()
        blob = pickle.dumps({"step": 10})
        self.client.post(
            f"/v1/runs/{run_id}/checkpoints",
            data={"step": "10"},
            files={"file": ("c.pkl", blob, "application/octet-stream")},
            headers=AUTH,
        )
        self.client.post(
            f"/v1/runs/{run_id}/events",
            json={
                "event_type": "faultline.run.failed",
                "level": "error",
                "message": "simulated crash",
            },
            headers=AUTH,
        )
        recovery = self.client.get(f"/v1/runs/{run_id}/recovery", headers=AUTH)
        body = recovery.json()
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["recommendation"], "resume_from_checkpoint")
        self.assertEqual(body["recovery_badge"], "recoverable")

    def test_recovery_missing_checkpoint_file(self) -> None:
        run_id = self._start_run()
        blob = pickle.dumps({"step": 3})
        self.client.post(
            f"/v1/runs/{run_id}/checkpoints",
            data={"step": "3"},
            files={"file": ("c.pkl", blob, "application/octet-stream")},
            headers=AUTH,
        )
        conn = connect()
        row = conn.execute(
            "SELECT storage_path FROM checkpoints WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.close()
        storage = get_checkpoint_storage()
        stored_path = str(row["storage_path"])
        storage.delete_checkpoint(stored_path)

        recovery = self.client.get(f"/v1/runs/{run_id}/recovery", headers=AUTH)
        body = recovery.json()
        self.assertEqual(body["checkpoint_health"], "missing_file")
        self.assertEqual(body["recovery_badge"], "checkpoint_missing")
        self.assertEqual(body["restore_status"], "unhealthy")


class TestDashboardRecoveryPanel(unittest.TestCase):
    def test_dashboard_html_has_recovery_panel(self) -> None:
        html = (REPO_ROOT / "cloud" / "api" / "static" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("recovery-panel", html)
        self.assertIn("recovery-resume-snippet", html)


if __name__ == "__main__":
    unittest.main()
