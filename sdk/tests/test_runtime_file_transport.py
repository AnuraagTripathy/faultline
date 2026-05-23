import pickle
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.runtime import PersistentRuntime


class TestRuntimeFileTransport(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = PersistentRuntime(runtime_dir="runtime")

    def test_save_pickle_checkpoint_via_file_cleans_temp_file(self) -> None:
        payload = {"step": 1, "weights": [1.0, 2.0, 3.0]}
        temp_paths: list[str] = []

        def capture_save(_step: int, path: str) -> str:
            temp_paths.append(path)
            self.assertTrue(Path(path).exists())
            return "saved"

        with patch.object(
            self.runtime, "save_checkpoint_file", side_effect=capture_save
        ) as save_file:
            result = self.runtime.save_pickle_checkpoint_via_file(1, payload)

        self.assertEqual(result, "saved")
        save_file.assert_called_once()
        self.assertEqual(len(temp_paths), 1)
        self.assertFalse(Path(temp_paths[0]).exists())

    def test_save_checkpoint_file_sends_save_from_file(self) -> None:
        with patch.object(
            self.runtime,
            "_send_command",
            return_value={"ok": True, "message": "saved checkpoint step 2 from file"},
        ) as send:
            message = self.runtime.save_checkpoint_file(2, "payload.bin")

        self.assertEqual(message, "saved checkpoint step 2 from file")
        send.assert_called_once()
        command = send.call_args.args[0]
        self.assertEqual(command["cmd"], "save_from_file")
        self.assertEqual(command["step"], 2)
        self.assertTrue(Path(command["path"]).is_absolute())


if __name__ == "__main__":
    unittest.main()
