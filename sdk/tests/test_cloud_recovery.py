"""SDK tests for cloud recovery (v17.1)."""

from __future__ import annotations

import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from faultline.cloud_run import CloudRun


class TestCloudRecoverySdk(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.metadata = {
            "run_id": "uuid-1",
            "project_name": "demo",
            "run_name": "r1",
            "status": "failed",
            "latest_step": 15,
            "latest_checkpoint_step": 10,
        }
        self.client.get_recovery.return_value = {
            "run_id": "uuid-1",
            "project_name": "demo",
            "run_name": "r1",
            "status": "failed",
            "latest_step": 15,
            "latest_checkpoint_step": 10,
            "estimated_lost_steps": 5,
            "checkpoint_health": "ok",
            "restore_status": "ready",
            "recovery_badge": "recoverable",
            "recommendation": "resume_from_checkpoint",
            "checkpoint_age_ms": 5000,
            "inline_restore_snippet": "state = run.load_latest_checkpoint_or_none()",
            "resume_snippet": "import faultline",
        }
        self.run = CloudRun(
            self.client,
            project="demo",
            run_name="r1",
            metadata=self.metadata,
        )

    def test_recovery_calls_api(self) -> None:
        info = self.run.recovery()
        self.client.get_recovery.assert_called_once_with("uuid-1")
        self.assertEqual(info["estimated_lost_steps"], 5)

    def test_print_resume_instructions(self) -> None:
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            self.run.print_resume_instructions()
        output = buffer.getvalue()
        self.assertIn("Faultline recovery", output)
        self.assertIn("Lost steps: 5", output)
        self.assertIn("load_latest_checkpoint_or_none", output)

    def test_fail_preserves_checkpoint_hint(self) -> None:
        self.run._metadata["latest_checkpoint_step"] = 10
        self.run.fail("simulated crash")
        self.client.log_event.assert_called_once()
        message = self.client.log_event.call_args.kwargs["message"]
        self.assertIn("checkpoint step 10", message)
        self.assertIn("/recovery", message)


if __name__ == "__main__":
    unittest.main()
