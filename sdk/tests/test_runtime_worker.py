import pickle
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.runtime import (
    AsyncPersistentRuntime,
    PersistentRuntime,
    global_step_for_worker,
)


class TestRuntimeWorker(unittest.TestCase):
    def setUp(self) -> None:
        self.persistent = PersistentRuntime(runtime_dir="runtime")
        self.async_runtime = AsyncPersistentRuntime(runtime_dir="runtime")

    def test_global_step_for_worker(self) -> None:
        self.assertEqual(global_step_for_worker(0, 5), 5)
        self.assertEqual(global_step_for_worker(1, 10), 1_000_010)
        self.assertEqual(global_step_for_worker(2, 15), 2_000_015)

    def test_save_worker_checkpoint_file_command_shape(self) -> None:
        with patch.object(self.persistent, "_send_command", return_value={"ok": True}) as send:
            self.persistent.save_worker_checkpoint_file(1, 10, 1_000_010, "payload.bin")

        command = send.call_args.args[0]
        self.assertEqual(command["cmd"], "save_worker_from_file")
        self.assertEqual(command["worker_id"], 1)
        self.assertEqual(command["local_step"], 10)
        self.assertEqual(command["step"], 1_000_010)

    def test_enqueue_worker_checkpoint_file_command_shape(self) -> None:
        with patch.object(self.async_runtime, "_send_command", return_value={"ok": True}) as send:
            self.async_runtime.enqueue_worker_checkpoint_file(
                2, 5, 2_000_005, "payload.bin"
            )

        command = send.call_args.args[0]
        self.assertEqual(command["cmd"], "enqueue_worker_from_file")
        self.assertEqual(command["worker_id"], 2)
        self.assertEqual(command["local_step"], 5)
        self.assertEqual(command["step"], 2_000_005)

    def test_latest_checkpoint_for_worker_parses_entry(self) -> None:
        entry = {
            "step": 1_000_010,
            "path": "checkpoints/step_1000010.ckpt",
            "status": "committed",
            "worker_id": 1,
            "local_step": 10,
        }
        with patch.object(
            self.async_runtime,
            "_send_command",
            return_value={"ok": True, "checkpoint": entry},
        ):
            latest = self.async_runtime.latest_checkpoint_for_worker(1)

        self.assertEqual(latest, entry)

    def test_prune_per_worker_command_shape(self) -> None:
        with patch.object(
            self.async_runtime,
            "_send_command",
            return_value={"ok": True, "deleted": 4},
        ) as send:
            message = self.async_runtime.prune_per_worker(1)

        self.assertIn("4", message)
        command = send.call_args.args[0]
        self.assertEqual(command["cmd"], "prune_per_worker")
        self.assertEqual(command["keep_last_per_worker"], 1)

    def test_load_latest_pickle_for_worker_roundtrip(self) -> None:
        payload = {"worker_id": 1, "local_step": 10}
        encoded = __import__("base64").b64encode(pickle.dumps(payload)).decode("ascii")
        with patch.object(
            self.persistent,
            "_send_command",
            return_value={"ok": True, "data": encoded},
        ):
            loaded = self.persistent.load_latest_pickle_for_worker(1)

        self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
