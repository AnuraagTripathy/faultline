"""Tests for V17 friendly cloud SDK (start, log, save, restore_latest)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import faultline
from faultline.cloud_run import CloudRun
from faultline.start import start


class _MockModule:
    def __init__(self, state: dict | None = None) -> None:
        self._state = state or {"w": 1.0}
        self.loaded: dict | None = None

    def state_dict(self) -> dict:
        return dict(self._state)

    def load_state_dict(self, state: dict) -> None:
        self.loaded = dict(state)


class TestStart(unittest.TestCase):
    def test_start_calls_init_cloud_mode(self) -> None:
        with patch("faultline.start.init") as mock_init:
            mock_run = MagicMock(spec=CloudRun)
            mock_init.return_value = mock_run
            run = start(
                "my-run",
                project="my-project",
                api_key="fl_dev_local",
                base_url="http://127.0.0.1:8080",
            )
            mock_init.assert_called_once_with(
                project="my-project",
                run_name="my-run",
                mode="cloud",
                api_key="fl_dev_local",
                base_url="http://127.0.0.1:8080",
                tags=None,
            )
            self.assertIs(run, mock_run)

    def test_start_exported_from_package(self) -> None:
        self.assertIs(faultline.start, start)


class TestCloudRunLog(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.metadata = {
            "run_id": "uuid-run-1",
            "latest_step": 5,
        }
        self.client.log_metrics.return_value = {**self.metadata, "latest_step": 6}
        self.run = CloudRun(
            self.client,
            project="p",
            run_name="r",
            metadata=self.metadata,
        )

    def test_log_auto_step_increments(self) -> None:
        self.run.log(loss=0.5)
        self.run.log(accuracy=0.9)
        calls = self.client.log_metrics.call_args_list
        self.assertEqual(calls[0].kwargs["step"], 6)
        self.assertEqual(calls[1].kwargs["step"], 7)
        self.assertEqual(calls[0].kwargs["metrics"], {"loss": 0.5})
        self.assertEqual(calls[1].kwargs["metrics"], {"accuracy": 0.9})

    def test_log_explicit_step(self) -> None:
        self.run.log(loss=0.1, step=10)
        self.client.log_metrics.assert_called_once_with(
            "uuid-run-1",
            step=10,
            metrics={"loss": 0.1},
        )


class TestCloudRunSave(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.metadata = {"run_id": "uuid-run-1", "latest_step": 0}
        self.client.upload_checkpoint.return_value = {"step": 10, "size_bytes": 100}
        self.client.get_run.return_value = self.metadata
        self.run = CloudRun(
            self.client,
            project="p",
            run_name="r",
            metadata=self.metadata,
        )

    def test_save_builds_payload_from_mocked_modules(self) -> None:
        model = _MockModule({"layer": 1})
        optimizer = _MockModule({"lr": 0.01})
        self.run.save(model=model, optimizer=optimizer, step=10)
        self.client.upload_checkpoint.assert_called_once()
        args, kwargs = self.client.upload_checkpoint.call_args
        self.assertEqual(kwargs["step"], 10)
        import pickle

        payload = pickle.loads(kwargs["data"])
        self.assertEqual(payload["step"], 10)
        self.assertEqual(payload["model_state"], {"layer": 1})
        self.assertEqual(payload["optimizer_state"], {"lr": 0.01})

    def test_save_with_state_dict_fallback(self) -> None:
        self.run.save(state={"custom": True}, step=3)
        import pickle

        payload = pickle.loads(self.client.upload_checkpoint.call_args.kwargs["data"])
        self.assertEqual(payload["step"], 3)
        self.assertTrue(payload["custom"])


class TestCloudRunRestoreLatest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.metadata = {"run_id": "uuid-run-1", "latest_step": 0}
        self.run = CloudRun(
            self.client,
            project="p",
            run_name="r",
            metadata=self.metadata,
        )

    def test_restore_latest_no_checkpoint_returns_zero(self) -> None:
        with patch.object(self.run, "load_latest_checkpoint_or_none", return_value=None):
            step = self.run.restore_latest(model=_MockModule(), optimizer=_MockModule())
        self.assertEqual(step, 0)

    def test_restore_latest_restores_state_dicts(self) -> None:
        state = {
            "step": 42,
            "model_state": {"layer": 2},
            "optimizer_state": {"lr": 0.001},
        }
        model = _MockModule()
        optimizer = _MockModule()
        with patch.object(self.run, "load_latest_checkpoint_or_none", return_value=state):
            step = self.run.restore_latest(model=model, optimizer=optimizer)
        self.assertEqual(step, 42)
        self.assertEqual(model.loaded, {"layer": 2})
        self.assertEqual(optimizer.loaded, {"lr": 0.001})
        self.assertEqual(self.run._step_counter, 42)


if __name__ == "__main__":
    unittest.main()
