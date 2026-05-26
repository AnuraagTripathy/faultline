"""Tests for run progress and system telemetry helpers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from faultline.run import FaultlineRun
from faultline.telemetry import (
    build_progress_metrics,
    collect_system_metrics,
    try_collect_system_metrics,
)


class TestBuildProgressMetrics(unittest.TestCase):
    def test_all_fields(self) -> None:
        metrics = build_progress_metrics(
            loss=0.5,
            learning_rate=1e-3,
            samples_per_sec=128.0,
            step_time_ms=12.5,
        )
        self.assertEqual(
            metrics,
            {
                "loss": 0.5,
                "learning_rate": 0.001,
                "samples_per_sec": 128.0,
                "step_time_ms": 12.5,
            },
        )

    def test_empty_when_no_values(self) -> None:
        self.assertEqual(build_progress_metrics(), {})


class TestSystemMetrics(unittest.TestCase):
    def test_collect_system_metrics_mock(self) -> None:
        mock_psutil = MagicMock()
        mock_psutil.cpu_percent.return_value = 42.0
        mock_psutil.virtual_memory.return_value = MagicMock(percent=55.0)
        process = MagicMock()
        process.memory_info.return_value = MagicMock(rss=10 * 1024 * 1024)
        mock_psutil.Process.return_value = process

        import sys

        with patch.dict(sys.modules, {"psutil": mock_psutil}):
            metrics = collect_system_metrics()

        self.assertEqual(metrics["cpu_percent"], 42.0)
        self.assertEqual(metrics["memory_percent"], 55.0)
        self.assertAlmostEqual(metrics["process_rss_mb"], 10.0)
        self.assertIn("client_timestamp_ms", metrics)

    def test_try_collect_skips_without_psutil(self) -> None:
        with patch(
            "faultline.telemetry.collect_system_metrics",
            side_effect=ImportError("missing"),
        ):
            self.assertIsNone(try_collect_system_metrics())


class TestFaultlineRunTelemetry(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.create_run.return_value = {
            "run_id": "proj__run__1",
            "project_name": "proj",
            "run_name": "run",
            "status": "running",
            "latest_step": 3,
            "latest_checkpoint_step": 0,
            "total_workers_seen": 0,
            "latest_loss": None,
            "tags": [],
        }
        self.client.attach_worker_to_run.return_value = self.client.create_run.return_value
        self.client.log_run_metrics.return_value = {
            "run_id": "proj__run__1",
            "latest_step": 4,
            "status": "running",
        }

    def test_log_progress_payload(self) -> None:
        run = FaultlineRun(self.client, project="proj", run_name="run")
        run.log_progress(4, loss=0.1, learning_rate=0.01)
        self.client.log_run_metrics.assert_called_once_with(
            "proj__run__1",
            step=4,
            metrics={"loss": 0.1, "learning_rate": 0.01},
            worker_id=0,
        )

    @patch("faultline.run.try_collect_system_metrics")
    def test_log_system_metrics_skips_when_unavailable(
        self,
        mock_try: MagicMock,
    ) -> None:
        mock_try.return_value = None
        run = FaultlineRun(self.client, project="proj", run_name="run")
        self.assertIsNone(run.log_system_metrics(step=2))
        self.client.log_run_metrics.assert_not_called()

    @patch("faultline.run.try_collect_system_metrics")
    def test_log_system_metrics_logs_when_available(
        self,
        mock_try: MagicMock,
    ) -> None:
        mock_try.return_value = {"cpu_percent": 1.0, "memory_percent": 2.0}
        run = FaultlineRun(self.client, project="proj", run_name="run")
        run.log_system_metrics(step=5)
        self.client.log_run_metrics.assert_called_once_with(
            "proj__run__1",
            step=5,
            metrics={"cpu_percent": 1.0, "memory_percent": 2.0},
            worker_id=0,
        )

    def test_track_step_logs_timing(self) -> None:
        run = FaultlineRun(self.client, project="proj", run_name="run")
        with run.track_step(7, num_samples=32):
            pass
        self.client.log_run_metrics.assert_called_once()
        _args, kwargs = self.client.log_run_metrics.call_args
        metrics = kwargs["metrics"]
        self.assertIn("step_time_ms", metrics)
        self.assertGreater(metrics["step_time_ms"], 0.0)
        self.assertIn("samples_per_sec", metrics)
        self.assertGreater(metrics["samples_per_sec"], 0.0)


if __name__ == "__main__":
    unittest.main()
