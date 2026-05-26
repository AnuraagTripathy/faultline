"""Tests for CloudRun and cloud init mode."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from faultline.cloud_run import CloudRun
from faultline.run import init


class TestCloudRun(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.start_run.return_value = {
            "run_id": "uuid-run-1",
            "project_name": "protein-model",
            "run_name": "exp-1",
            "status": "running",
            "tags": ["demo"],
            "latest_step": 0,
            "latest_loss": None,
            "created_at_ms": 1000,
            "updated_at_ms": 1000,
        }
        self.client.log_metrics.return_value = {
            "run_id": "uuid-run-1",
            "status": "running",
            "latest_step": 2,
            "latest_loss": 0.5,
        }
        self.client.log_event.return_value = {
            "run_id": "uuid-run-1",
            "status": "completed",
            "latest_step": 2,
        }

    def test_init_cloud_mode(self) -> None:
        with patch("faultline.run.CloudRun") as mock_cloud_run:
            mock_cloud_run.start.return_value = MagicMock(run_id="uuid-run-1")
            run = init(
                "protein-model",
                "exp-1",
                mode="cloud",
                api_key="fl_dev_local",
                base_url="http://127.0.0.1:8080",
            )
            mock_cloud_run.start.assert_called_once_with(
                project="protein-model",
                run_name="exp-1",
                api_key="fl_dev_local",
                base_url="http://127.0.0.1:8080",
                tags=None,
            )
            self.assertEqual(run.run_id, "uuid-run-1")

    def test_init_cloud_requires_api_key(self) -> None:
        with self.assertRaises(ValueError):
            init("p", "r", mode="cloud")

    def test_log_metrics(self) -> None:
        run = CloudRun(
            self.client,
            project="protein-model",
            run_name="exp-1",
            metadata=self.client.start_run.return_value,
        )
        run.log_metrics({"loss": 0.5}, step=2)
        self.client.log_metrics.assert_called_once_with(
            "uuid-run-1",
            step=2,
            metrics={"loss": 0.5},
        )

    def test_complete_fail_stop(self) -> None:
        run = CloudRun(
            self.client,
            project="p",
            run_name="r",
            metadata=self.client.start_run.return_value,
        )
        run.complete()
        self.client.log_event.assert_called_with(
            "uuid-run-1",
            event_type="faultline.run.completed",
            level="info",
            message="run completed",
        )

        run.fail("boom")
        self.client.log_event.assert_called_with(
            "uuid-run-1",
            event_type="faultline.run.failed",
            level="error",
            message="boom",
        )

        run.stop()
        self.client.log_event.assert_called_with(
            "uuid-run-1",
            event_type="faultline.run.stopped",
            level="warn",
            message="run stopped",
        )


if __name__ == "__main__":
    unittest.main()
