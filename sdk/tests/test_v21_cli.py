"""CLI v21 — login, whoami, demo helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from faultline.cli import cmd_init, cmd_whoami, main
from faultline.config import CONFIG_FILE, load_config, save_config


class TestCliV21(unittest.TestCase):
    def test_init_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cmd_init(Path(tmp)), 0)
            self.assertTrue((Path(tmp) / "train.py").is_file())

    @patch("faultline.cli._http_json")
    def test_whoami_api_key(self, mock_http: MagicMock) -> None:
        mock_http.return_value = {
            "user": {"email": "u@test.com", "user_id": "id-1"},
            "usage": {"runs_created": 3, "checkpoints_created": 1},
        }
        with patch("faultline.cli.get_session_token", return_value=None):
            with patch("faultline.cli.get_api_key", return_value="fl_test"):
                with patch("faultline.cli.get_base_url", return_value="http://127.0.0.1:8080"):
                    self.assertEqual(cmd_whoami("http://127.0.0.1:8080"), 0)

    def test_config_roundtrip(self) -> None:
        prev = CONFIG_FILE
        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "config.json"
            with patch("faultline.config.CONFIG_FILE", test_file):
                save_config({"email": "a@b.com", "api_key": "fl_x"})
                cfg = load_config()
                self.assertEqual(cfg["email"], "a@b.com")

    @patch("faultline.cli.run_live_demo")
    def test_main_demo_command(self, mock_run: MagicMock) -> None:
        mock_run.return_value = {"run_id": "abc", "crashed": True}
        with patch("faultline.cli.get_api_key", return_value="fl_dev_local"):
            with patch("faultline.cli.get_base_url", return_value="http://127.0.0.1:8080"):
                with patch("faultline.cli.webbrowser.open"):
                    self.assertEqual(main(["demo", "--no-crash"]), 0)


if __name__ == "__main__":
    unittest.main()
