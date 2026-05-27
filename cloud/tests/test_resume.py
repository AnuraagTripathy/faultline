"""Launch config and resume relaunch tests (v17.2)."""

from __future__ import annotations

import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from cloud.api.app import create_app  # noqa: E402
from cloud.api.database import reset_engine  # noqa: E402
from cloud.api.db import DEV_API_KEY, connect, init_db  # noqa: E402

AUTH = {"Authorization": f"Bearer {DEV_API_KEY}"}


class TestLaunchConfig(unittest.TestCase):
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
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "resume-test"},
            headers=AUTH,
        )
        self.run_id = start.json()["run_id"]

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ.pop("FAULTLINE_CLOUD_CHECKPOINTS_DIR", None)
        Path(self._db.name).unlink(missing_ok=True)

    def test_register_local_launch_config(self) -> None:
        response = self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={
                "launch_type": "local_command",
                "command": ["python", "train.py"],
            },
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["launch_type"], "local_command")
        self.assertEqual(body["command"], ["python", "train.py"])

        get_resp = self.client.get(
            f"/v1/runs/{self.run_id}/launch-config",
            headers=AUTH,
        )
        self.assertEqual(get_resp.status_code, 200)

    def test_invalid_launch_config(self) -> None:
        response = self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={"launch_type": "local_command"},
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={"launch_type": "slurm_script"},
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 422)

    def _upload_checkpoint(self, step: int = 10) -> None:
        blob = pickle.dumps({"step": step})
        upload = self.client.post(
            f"/v1/runs/{self.run_id}/checkpoints",
            data={"step": str(step)},
            files={"file": ("c.pkl", blob, "application/octet-stream")},
            headers=AUTH,
        )
        self.assertEqual(upload.status_code, 200)

    def test_resume_without_checkpoint(self) -> None:
        self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={
                "launch_type": "local_command",
                "command": ["python", "train.py"],
            },
            headers=AUTH,
        )
        response = self.client.post(
            f"/v1/runs/{self.run_id}/resume",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 400)

    def test_resume_without_launch_config(self) -> None:
        self._upload_checkpoint()
        response = self.client.post(
            f"/v1/runs/{self.run_id}/resume",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 400)

    @patch("cloud.api.resume_launcher.subprocess.Popen")
    def test_local_resume_success(self, mock_popen: MagicMock) -> None:
        self._upload_checkpoint(10)
        self.client.post(
            f"/v1/runs/{self.run_id}/metrics",
            json={"step": 15, "metrics": {"loss": 0.1}},
            headers=AUTH,
        )
        self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={
                "launch_type": "local_command",
                "command": [sys.executable, "-c", "pass"],
            },
            headers=AUTH,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 4242
        mock_popen.return_value = mock_proc

        response = self.client.post(
            f"/v1/runs/{self.run_id}/resume",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "resume_started")
        self.assertEqual(body["pid"], 4242)
        self.assertEqual(body["checkpoint_step"], 10)
        self.assertEqual(body["estimated_lost_steps"], 5)

        events = self.client.get(
            f"/v1/runs/{self.run_id}/events",
            headers=AUTH,
        ).json()
        types = {e["event_type"] for e in events}
        self.assertIn("faultline.run.resume_requested", types)
        self.assertIn("faultline.run.resume_started", types)

    @patch("cloud.api.resume_launcher.subprocess.Popen")
    def test_local_resume_failure(self, mock_popen: MagicMock) -> None:
        self._upload_checkpoint()
        self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={
                "launch_type": "local_command",
                "command": ["python", "train.py"],
            },
            headers=AUTH,
        )
        mock_popen.side_effect = OSError("permission denied")

        response = self.client.post(
            f"/v1/runs/{self.run_id}/resume",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 500)
        events = self.client.get(
            f"/v1/runs/{self.run_id}/events",
            headers=AUTH,
        ).json()
        self.assertTrue(
            any(e["event_type"] == "faultline.run.resume_failed" for e in events)
        )

    @patch("cloud.api.resume_launcher.subprocess.run")
    def test_slurm_resume_mocked(self, mock_run: MagicMock) -> None:
        self._upload_checkpoint(20)
        self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={
                "launch_type": "slurm_script",
                "script_path": "train.slurm",
            },
            headers=AUTH,
        )
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Submitted batch job 991122\n",
            stderr="",
        )

        response = self.client.post(
            f"/v1/runs/{self.run_id}/resume",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["slurm_job_id"], "991122")

    @patch("cloud.api.resume_launcher.subprocess.Popen")
    def test_recovery_after_relaunch(self, mock_popen: MagicMock) -> None:
        self._upload_checkpoint(10)
        self.client.post(
            f"/v1/runs/{self.run_id}/launch-config",
            json={
                "launch_type": "local_command",
                "command": ["python", "train.py"],
            },
            headers=AUTH,
        )
        mock_popen.return_value = MagicMock(pid=1)
        self.client.post(f"/v1/runs/{self.run_id}/resume", headers=AUTH)

        recovery = self.client.get(
            f"/v1/runs/{self.run_id}/recovery",
            headers=AUTH,
        ).json()
        self.assertIsNotNone(recovery["launch_config"])
        self.assertIsNotNone(recovery["last_resume"])
        self.assertEqual(recovery["last_resume"]["pid"], 1)


class TestDashboardResumeUi(unittest.TestCase):
    def test_dashboard_has_resume_controls(self) -> None:
        html = (REPO_ROOT / "cloud" / "api" / "static" / "dashboard.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("resume-run-btn", html)
        self.assertIn("recovery-launch-config", html)
        self.assertIn("recovery-timeline", html)


if __name__ == "__main__":
    unittest.main()
