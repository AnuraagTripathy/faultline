import io
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.runtime import PersistentRuntime


class TestPersistentRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = PersistentRuntime(runtime_dir="runtime")

    def test_send_command_success(self) -> None:
        stdout = io.StringIO('{"ok": true, "message": "saved checkpoint step 1"}\n')
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = io.StringIO()
        mock_process.stdout = stdout
        self.runtime._process = mock_process

        response = self.runtime._send_command(
            {"cmd": "save", "step": 1, "data": "hello"}
        )

        self.assertTrue(response["ok"])
        self.assertEqual(mock_process.stdin.getvalue(), '{"cmd": "save", "step": 1, "data": "hello"}\n')

    def test_send_command_error_raises(self) -> None:
        stdout = io.StringIO('{"ok": false, "error": "boom"}\n')
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = io.StringIO()
        mock_process.stdout = stdout
        self.runtime._process = mock_process

        with self.assertRaises(RuntimeError) as ctx:
            self.runtime._send_command({"cmd": "list"})

        self.assertEqual(str(ctx.exception), "boom")

    def test_pickle_roundtrip_with_mocked_commands(self) -> None:
        payloads: list[dict] = []

        def fake_send(command: dict) -> dict:
            payloads.append(command)
            if command["cmd"] == "save":
                return {"ok": True, "message": f"saved checkpoint step {command['step']}"}
            if command["cmd"] == "load_latest":
                return {"ok": True, "data": payloads[0]["data"]}
            raise AssertionError(f"unexpected command: {command}")

        with patch.object(self.runtime, "_send_command", side_effect=fake_send):
            self.runtime.save_pickle_checkpoint(1, {"step": 1, "loss": 0.5})
            latest = self.runtime.load_latest_pickle()

        self.assertEqual(latest["step"], 1)
        self.assertEqual(latest["loss"], 0.5)

    def test_shutdown_twice_is_safe(self) -> None:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = io.StringIO()
        mock_process.stdout = io.StringIO('{"ok": true, "message": "shutting down"}\n')
        self.runtime._process = mock_process

        with patch.object(self.runtime, "_send_command", return_value={"ok": True}) as send:
            self.runtime.shutdown()
            self.runtime.shutdown()

        send.assert_called_once_with({"cmd": "shutdown"})
        mock_process.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
