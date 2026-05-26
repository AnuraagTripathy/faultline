"""Tests for CloudRun checkpoint helpers."""

from __future__ import annotations

import pickle
import unittest
from unittest.mock import MagicMock

from faultline.cloud_run import CloudRun


class TestCloudRunCheckpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.create_run.return_value = {
            "run_id": "run-1",
            "project_name": "p",
            "run_name": "r",
            "status": "running",
            "latest_step": 0,
            "latest_checkpoint_step": 0,
        }
        self.client.get_run.return_value = self.client.create_run.return_value
        self.client.upload_checkpoint.return_value = {
            "checkpoint_id": "cp-1",
            "run_id": "run-1",
            "step": 5,
            "size_bytes": 100,
            "status": "committed",
        }
        self.client.list_checkpoints.return_value = [
            {"checkpoint_id": "cp-1", "step": 5, "size_bytes": 100, "status": "committed"}
        ]
        self.client.latest_checkpoint.return_value = {
            "checkpoint_id": "cp-1",
            "step": 5,
        }

    def test_checkpoint_uploads_pickle(self) -> None:
        run = CloudRun(
            self.client,
            project="p",
            run_name="r",
            metadata=self.client.create_run.return_value,
        )
        payload = {"step": 5, "x": 1}
        run.checkpoint(payload, step=5)
        self.client.upload_checkpoint.assert_called_once()
        args, kwargs = self.client.upload_checkpoint.call_args
        self.assertEqual(args[0], "run-1")
        self.assertEqual(kwargs["step"], 5)
        self.assertEqual(pickle.loads(kwargs["data"]), payload)

    def test_load_latest_checkpoint(self) -> None:
        payload = {"step": 10}
        self.client.download_latest_checkpoint.return_value = pickle.dumps(payload)
        run = CloudRun(
            self.client,
            project="p",
            run_name="r",
            metadata=self.client.create_run.return_value,
        )
        with self.assertWarns(UserWarning):
            loaded = run.load_latest_checkpoint()
        self.assertEqual(loaded, payload)

    def test_load_latest_checkpoint_or_none_on_404(self) -> None:
        self.client.download_latest_checkpoint.side_effect = RuntimeError(
            "cloud API GET failed (404): no checkpoints"
        )
        run = CloudRun(
            self.client,
            project="p",
            run_name="r",
            metadata=self.client.create_run.return_value,
        )
        self.assertIsNone(run.load_latest_checkpoint_or_none())


if __name__ == "__main__":
    unittest.main()
