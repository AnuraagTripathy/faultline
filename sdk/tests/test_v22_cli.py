"""CLI v22 failure simulation command tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from faultline.cli import cmd_demo_crash, main


class TestCliV22(unittest.TestCase):
    @patch("faultline.cli.runpy.run_path")
    def test_demo_crash_runs_scenario(self, mock_run_path: MagicMock) -> None:
        self.assertEqual(cmd_demo_crash("process_kill_resume"), 0)
        self.assertTrue(mock_run_path.called)

    @patch("faultline.cli.runpy.run_path")
    def test_main_demo_crash(self, mock_run_path: MagicMock) -> None:
        self.assertEqual(main(["demo", "crash", "--scenario", "network_disconnect"]), 0)
        self.assertTrue(mock_run_path.called)

    def test_benchmark_report_renderer(self) -> None:
        module_path = (
            Path(__file__).resolve().parents[2]
            / "benchmark"
            / "recovery"
            / "run_benchmark.py"
        )
        spec = importlib.util.spec_from_file_location("recovery_benchmark", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.render_report(  # type: ignore[attr-defined]
            [
                {
                    "upload_latency_ms": 10,
                    "recovery_detection_ms": 20,
                    "resume_startup_ms": 30,
                    "estimated_lost_steps": 4,
                }
            ]
        )
        self.assertIn("Avg checkpoint upload latency", report)
        self.assertIn("Avg estimated lost progress", report)


if __name__ == "__main__":
    unittest.main()
