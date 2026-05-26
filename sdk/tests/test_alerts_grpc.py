"""Tests for alert gRPC wrappers."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from faultline.grpc_client import GrpcAsyncRuntime, _alert_to_dict


class TestAlertWrappers(unittest.TestCase):
    def test_alert_to_dict(self) -> None:
        alert = MagicMock()
        alert.alert_id = "a1"
        alert.rule_id = "default-run-stale"
        alert.alert_type = "run_stale"
        alert.severity = "warning"
        alert.message = "stale"
        alert.timestamp_ms = 100
        alert.HasField.side_effect = lambda name: name == "run_id"
        alert.run_id = "proj__run__1"
        alert.event_id = None

        payload = _alert_to_dict(alert)
        self.assertEqual(payload["run_id"], "proj__run__1")
        self.assertIsNone(payload["event_id"])

    def test_evaluate_alerts(self) -> None:
        client = GrpcAsyncRuntime(addr="127.0.0.1:50051", start_server=False)
        stub = MagicMock()
        client._stub = stub

        alert = MagicMock()
        alert.alert_id = "high-loss-proj__run__1-step-2"
        alert.rule_id = "high-loss"
        alert.alert_type = "metric_threshold"
        alert.severity = "warning"
        alert.message = "loss high"
        alert.timestamp_ms = 200
        alert.HasField.return_value = False

        response = MagicMock()
        response.ok = True
        response.alerts = [alert]
        response.active_count = 1
        stub.EvaluateAlerts.return_value = response

        result = client.evaluate_alerts()
        self.assertEqual(result["active_count"], 1)
        self.assertEqual(result["alerts"][0]["alert_type"], "metric_threshold")
        stub.EvaluateAlerts.assert_called_once()

    def test_list_alerts(self) -> None:
        client = GrpcAsyncRuntime(addr="127.0.0.1:50051", start_server=False)
        stub = MagicMock()
        client._stub = stub

        response = MagicMock()
        response.ok = True
        response.alerts = []
        response.active_count = 0
        stub.ListAlerts.return_value = response

        result = client.list_alerts()
        self.assertEqual(result["active_count"], 0)
        self.assertEqual(result["alerts"], [])
        stub.ListAlerts.assert_called_once()


if __name__ == "__main__":
    unittest.main()
