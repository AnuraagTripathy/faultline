import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.runtime import (
    AsyncPersistentRuntime,
    PersistentRuntime,
    build_serve_command,
)


class TestRuntimeWriteDelay(unittest.TestCase):
    def test_build_serve_command_omits_flag_when_zero(self) -> None:
        self.assertEqual(
            build_serve_command("serve"),
            ["cargo", "run", "--", "serve"],
        )

    def test_build_serve_command_includes_delay(self) -> None:
        self.assertEqual(
            build_serve_command("serve-async", 500),
            ["cargo", "run", "--", "serve-async", "--write-delay-ms", "500"],
        )

    def test_persistent_runtime_passes_write_delay(self) -> None:
        runtime = PersistentRuntime(runtime_dir="runtime", write_delay_ms=250)
        with patch("faultline.runtime.subprocess.Popen") as popen:
            runtime.start()
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(
            command,
            ["cargo", "run", "--", "serve", "--write-delay-ms", "250"],
        )

    def test_async_persistent_runtime_passes_write_delay(self) -> None:
        runtime = AsyncPersistentRuntime(runtime_dir="runtime", write_delay_ms=500)
        with patch("faultline.runtime.subprocess.Popen") as popen:
            runtime.start()
        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(
            command,
            ["cargo", "run", "--", "serve-async", "--write-delay-ms", "500"],
        )


if __name__ == "__main__":
    unittest.main()
