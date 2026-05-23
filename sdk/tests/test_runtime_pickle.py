import base64
import pickle
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.runtime import Runtime


class TestRuntimePickle(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = Runtime(runtime_dir="runtime")

    def test_save_pickle_checkpoint_uses_base64(self) -> None:
        payload = {"step": 5, "loss": 0.42}
        expected = base64.b64encode(pickle.dumps(payload)).decode("ascii")

        with patch.object(self.runtime, "save_checkpoint", return_value="ok") as save:
            result = self.runtime.save_pickle_checkpoint(5, payload)

        save.assert_called_once_with(5, data=expected)
        self.assertEqual(result, "ok")

    def test_load_latest_pickle_round_trips_object(self) -> None:
        payload = {
            "step": 5,
            "optimizer": {"lr": 0.001, "momentum": 0.9},
        }
        encoded = base64.b64encode(pickle.dumps(payload)).decode("ascii")

        with patch.object(self.runtime, "load_latest", return_value=encoded):
            latest = self.runtime.load_latest_pickle()

        self.assertEqual(latest["step"], 5)
        self.assertEqual(latest["optimizer"]["lr"], 0.001)

    def test_load_latest_pickle_raises_on_invalid_base64(self) -> None:
        with patch.object(self.runtime, "load_latest", return_value="not!!!base64"):
            with self.assertRaises(ValueError) as ctx:
                self.runtime.load_latest_pickle()

        self.assertIn("could not be unpickled", str(ctx.exception))

    def test_load_latest_pickle_raises_on_invalid_pickle_bytes(self) -> None:
        encoded = base64.b64encode(b"not a pickle").decode("ascii")
        with patch.object(self.runtime, "load_latest", return_value=encoded):
            with self.assertRaises(ValueError) as ctx:
                self.runtime.load_latest_pickle()

        self.assertIn("could not be unpickled", str(ctx.exception))

    def test_load_latest_pickle_raises_when_no_checkpoint(self) -> None:
        with patch.object(
            self.runtime, "load_latest", return_value="No latest checkpoint found."
        ):
            with self.assertRaises(ValueError) as ctx:
                self.runtime.load_latest_pickle()

        self.assertIn("No latest checkpoint found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
