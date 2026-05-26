"""Dashboard API tests with mocked gRPC client."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "sdk"))

from fastapi.testclient import TestClient  # noqa: E402

from dashboard.app import create_app  # noqa: E402


class TestDashboardApp(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_client = MagicMock()
        self.mock_client.get_runtime_overview.return_value = {
            "total_datasets": 1,
            "total_shards": 3,
            "pending_shards": 1,
            "claimed_shards": 1,
            "completed_shards": 1,
            "failed_shards": 0,
            "total_checkpoints": 2,
            "workers_seen": 2,
            "async_metrics": {"total_committed": 2},
        }
        self.mock_client.list_workers.return_value = [
            {
                "worker_id": 0,
                "latest_checkpoint_step": 0,
                "latest_local_step": 0,
                "committed_checkpoints": 1,
                "claimed_shards": 0,
                "completed_shards": 1,
            }
        ]
        self.mock_client.list_datasets.return_value = [
            {
                "name": "obs-demo",
                "total_samples": 30,
                "shard_size": 10,
                "total_shards": 3,
            }
        ]
        self.mock_client.list_runs.return_value = [
            {
                "run_id": "protein-model__exp__1",
                "project_name": "protein-model",
                "run_name": "exp",
                "status": "running",
                "latest_step": 10,
                "latest_loss": 0.42,
                "latest_checkpoint_step": 8,
                "latest_metric_at_ms": 1_700_000_000_000,
                "total_workers_seen": 1,
            }
        ]
        self.mock_client.list_events.return_value = [
            {
                "event_id": 1,
                "timestamp_ms": 1000,
                "level": "INFO",
                "event_type": "shard_claimed",
                "worker_id": 2,
                "dataset_name": "obs-demo",
                "shard_id": 1,
                "step": None,
                "message": "worker 2 claimed shard 1",
            }
        ]
        self.mock_client.evaluate_alerts.return_value = {
            "active_count": 1,
            "alerts": [
                {
                    "alert_id": "default-high-loss-run-2",
                    "rule_id": "default-high-loss",
                    "alert_type": "metric_threshold",
                    "severity": "warning",
                    "run_id": "protein-model__exp__1",
                    "message": "loss=12.5 gt 10.0",
                    "timestamp_ms": 500,
                    "event_id": None,
                }
            ],
        }
        self.mock_client.list_shards.return_value = [
            {
                "shard_id": 1,
                "start": 10,
                "end": 20,
                "status": "claimed",
                "worker_id": 2,
                "updated_at_ms": 1000,
            }
        ]

        self.app = create_app(
            grpc_client_factory=lambda: self.mock_client,
            use_lifespan=False,
        )
        self.client = TestClient(self.app)

    def test_health_ok(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_overview(self) -> None:
        response = self.client.get("/api/overview")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_shards"], 3)
        self.mock_client.get_runtime_overview.assert_called_once()

    def test_runs(self) -> None:
        response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["run_name"], "exp")
        self.assertEqual(body[0]["latest_loss"], 0.42)
        self.mock_client.list_runs.assert_called_once()

    def test_run_metrics(self) -> None:
        self.mock_client.list_run_metrics.return_value = [
            {
                "run_id": "protein-model__exp__1",
                "step": 1,
                "timestamp_ms": 100,
                "metrics": {"loss": 1.0},
            },
            {
                "run_id": "protein-model__exp__1",
                "step": 2,
                "timestamp_ms": 200,
                "metrics": {
                    "loss": 0.5,
                    "step_time_ms": 12.0,
                    "cpu_percent": 33.0,
                },
            },
        ]
        response = self.client.get("/api/runs/protein-model__exp__1/metrics?limit=100")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[1]["metrics"]["loss"], 0.5)
        self.assertEqual(body[1]["metrics"]["step_time_ms"], 12.0)
        self.assertEqual(body[1]["metrics"]["cpu_percent"], 33.0)
        self.mock_client.list_run_metrics.assert_called_once_with(
            "protein-model__exp__1",
            limit=100,
        )

    def test_runs_include_latest_metric_timestamp(self) -> None:
        response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]["latest_metric_at_ms"],
            1_700_000_000_000,
        )

    def test_workers(self) -> None:
        response = self.client.get("/api/workers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_datasets(self) -> None:
        response = self.client.get("/api/datasets")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["name"], "obs-demo")

    def test_events(self) -> None:
        response = self.client.get("/api/events?limit=25")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body[0]["event_type"], "shard_claimed")
        self.mock_client.list_events.assert_called_once_with(limit=25)

    def test_shards_with_status_filter(self) -> None:
        response = self.client.get("/api/shards/obs-demo?status=Pending")
        self.assertEqual(response.status_code, 200)
        self.mock_client.list_shards.assert_called_once_with("obs-demo", status="pending")

    def test_alerts(self) -> None:
        response = self.client.get("/api/alerts")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["active_count"], 1)
        self.assertEqual(body["alerts"][0]["alert_type"], "metric_threshold")
        self.assertEqual(body["alerts"][0]["severity"], "warning")
        self.mock_client.evaluate_alerts.assert_called_once()

    def test_index_html(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
