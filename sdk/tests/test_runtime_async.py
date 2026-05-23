import pickle
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.runtime import AsyncPersistentRuntime


class TestRuntimeAsync(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = AsyncPersistentRuntime(runtime_dir="runtime")

    def test_enqueue_pickle_cleans_temp_file(self) -> None:
        payload = {"step": 1, "weights": [1.0, 2.0]}
        temp_paths: list[str] = []

        def capture_enqueue(_step: int, path: str) -> str:
            temp_paths.append(path)
            self.assertTrue(Path(path).exists())
            return "queued checkpoint step 1"

        with patch.object(
            self.runtime, "enqueue_checkpoint_file", side_effect=capture_enqueue
        ):
            message = self.runtime.enqueue_pickle_checkpoint_via_file(1, payload)

        self.assertEqual(message, "queued checkpoint step 1")
        self.assertEqual(len(temp_paths), 1)
        self.assertFalse(Path(temp_paths[0]).exists())

    def test_enqueue_checkpoint_file_sends_command(self) -> None:
        with patch.object(
            self.runtime,
            "_send_command",
            return_value={"ok": True, "message": "queued checkpoint step 2"},
        ) as send:
            message = self.runtime.enqueue_checkpoint_file(2, "payload.bin")

        self.assertEqual(message, "queued checkpoint step 2")
        command = send.call_args.args[0]
        self.assertEqual(command["cmd"], "enqueue_from_file")
        self.assertEqual(command["step"], 2)

    def test_try_enqueue_returns_queued_flag(self) -> None:
        with patch.object(
            self.runtime,
            "_send_command",
            return_value={"ok": True, "queued": False},
        ):
            queued = self.runtime.try_enqueue_pickle_checkpoint_via_file(3, {"x": 1})

        self.assertFalse(queued)

    def test_checkpoint_status_and_metrics(self) -> None:
        with patch.object(
            self.runtime,
            "_send_command",
            side_effect=[
                {"ok": True, "status": "Committed"},
                {
                    "ok": True,
                    "metrics": {
                        "total_enqueued": 1,
                        "total_committed": 1,
                        "total_failed": 0,
                        "total_dropped": 0,
                        "total_bytes_written": 10,
                        "total_write_time_ms": 5,
                        "average_write_time_ms": 5.0,
                    },
                },
            ],
        ):
            status = self.runtime.checkpoint_status(1)
            metrics = self.runtime.metrics()

        self.assertEqual(status, "Committed")
        self.assertEqual(metrics["total_committed"], 1)


if __name__ == "__main__":
    unittest.main()
