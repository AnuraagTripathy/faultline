"""Tests for the high-level Faultline Runs API."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from faultline.run import FaultlineRun, init


class TestFaultlineRun(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.create_run.return_value = {
            "run_id": "protein-model__experiment-1__100",
            "project_name": "protein-model",
            "run_name": "experiment-1",
            "status": "running",
            "latest_step": 0,
            "latest_checkpoint_step": 0,
            "total_workers_seen": 0,
            "latest_loss": None,
            "tags": ["demo"],
        }
        self.client.attach_worker_to_run.return_value = {
            "run_id": "protein-model__experiment-1__100",
            "total_workers_seen": 1,
            "latest_step": 0,
            "latest_checkpoint_step": 0,
            "status": "running",
        }
        self.client.log_run_metrics.return_value = {
            "run_id": "protein-model__experiment-1__100",
            "latest_step": 5,
            "latest_loss": 0.25,
            "status": "running",
            "total_workers_seen": 1,
            "latest_checkpoint_step": 0,
        }
        self.client.list_run_metrics.return_value = [
            {
                "run_id": "protein-model__experiment-1__100",
                "step": 5,
                "timestamp_ms": 1000,
                "metrics": {"loss": 0.25},
            }
        ]
        self.client.enqueue_worker_pickle_checkpoint_bytes.return_value = "queued"
        self.client.complete_run.return_value = {
            "run_id": "protein-model__experiment-1__100",
            "status": "completed",
            "latest_step": 5,
        }

    def test_init_creates_run_and_attaches_worker(self) -> None:
        with patch("faultline.run.GrpcAsyncRuntime") as mock_runtime_cls:
            mock_runtime_cls.return_value = self.client
            run = init(
                project="protein-model",
                run_name="experiment-1",
                tags=["demo"],
                start_server=False,
            )
            self.client.start.assert_called_once()
            self.client.create_run.assert_called_once_with(
                "protein-model",
                "experiment-1",
                tags=["demo"],
            )
            self.client.attach_worker_to_run.assert_called_once_with(
                "protein-model__experiment-1__100",
                0,
            )
            self.assertEqual(run.run_id, "protein-model__experiment-1__100")

    def test_log_metrics_appends_history(self) -> None:
        run = FaultlineRun(
            self.client,
            project="protein-model",
            run_name="experiment-1",
        )
        metadata = run.log_metrics({"loss": 0.25, "learning_rate": 0.01}, step=5)
        self.assertEqual(metadata["latest_step"], 5)
        self.client.log_run_metrics.assert_called_once_with(
            "protein-model__experiment-1__100",
            step=5,
            metrics={"loss": 0.25, "learning_rate": 0.01},
            worker_id=0,
        )

    def test_metrics_lists_history(self) -> None:
        run = FaultlineRun(
            self.client,
            project="protein-model",
            run_name="experiment-1",
        )
        history = run.metrics(limit=100)
        self.assertEqual(len(history), 1)
        self.client.list_run_metrics.assert_called_once_with(
            "protein-model__experiment-1__100",
            limit=100,
        )

    def test_checkpoint_enqueues_and_updates_step(self) -> None:
        run = FaultlineRun(
            self.client,
            project="protein-model",
            run_name="experiment-1",
        )
        message = run.checkpoint({"weights": [1, 2, 3]}, step=4)
        self.assertIn("queued", message)
        self.client.enqueue_worker_pickle_checkpoint_bytes.assert_called_once()
        self.assertTrue(
            any(
                call.kwargs.get("latest_checkpoint_step") == 4
                for call in self.client.update_run_metrics.call_args_list
            )
        )

    def test_complete_marks_run_completed(self) -> None:
        run = FaultlineRun(
            self.client,
            project="protein-model",
            run_name="experiment-1",
        )
        metadata = run.complete()
        self.client.complete_run.assert_called_once_with(
            "protein-model__experiment-1__100",
            status="completed",
        )
        self.assertEqual(metadata["status"], "completed")


if __name__ == "__main__":
    unittest.main()
