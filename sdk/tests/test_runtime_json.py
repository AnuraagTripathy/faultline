import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.runtime import Runtime


class TestRuntimeJson(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Runtime(runtime_dir="runtime")

    def test_save_json_checkpoint_uses_json_dumps(self) -> None:
        payload = {"step": 1, "loss": 0.95}
        with patch.object(self.runtime, "save_checkpoint", return_value="ok") as save:
            result = self.runtime.save_json_checkpoint(1, payload)

        save.assert_called_once_with(1, data='{"step": 1, "loss": 0.95}')
        self.assertEqual(result, "ok")

    def test_load_latest_json_parses_dict(self) -> None:
        raw = '{"step": 2, "loss": 0.72, "model": "toy-model"}'
        with patch.object(self.runtime, "load_latest", return_value=raw):
            latest = self.runtime.load_latest_json()

        self.assertEqual(latest["step"], 2)
        self.assertEqual(latest["loss"], 0.72)

    def test_load_latest_json_raises_when_not_json(self) -> None:
        with patch.object(self.runtime, "load_latest", return_value="not json"):
            with self.assertRaises(ValueError) as ctx:
                self.runtime.load_latest_json()

        self.assertIn("not valid JSON", str(ctx.exception))

    def test_load_latest_json_raises_when_no_checkpoint(self) -> None:
        with patch.object(
            self.runtime, "load_latest", return_value="No latest checkpoint found."
        ):
            with self.assertRaises(ValueError) as ctx:
                self.runtime.load_latest_json()

        self.assertIn("No latest checkpoint found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
