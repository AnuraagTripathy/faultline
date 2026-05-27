"""Version 20.0 — integrations, quickstart, auto_resume, CLI."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from faultline.cloud_run import CloudRun
from faultline.integrations.huggingface import FaultlineTrainerCallback, _scalar_metrics
from faultline.integrations.lightning import FaultlineLightningCallback, _callback_metrics
from faultline.quickstart import quickstart
from faultline.resume import auto_resume
from faultline.start import start


class TestScalarMetrics(unittest.TestCase):
    def test_scalar_metrics_filters(self) -> None:
        out = _scalar_metrics({"loss": 0.5, "epoch": 1, "flag": True, "name": "x"})
        self.assertEqual(out, {"loss": 0.5, "epoch": 1.0})


class TestQuickstart(unittest.TestCase):
    @patch("faultline.quickstart.start")
    def test_quickstart_generates_run_name(self, mock_start: MagicMock) -> None:
        mock_start.return_value = MagicMock(spec=CloudRun)
        quickstart("demo", api_key="fl_test")
        args, kwargs = mock_start.call_args
        self.assertTrue(args[0].startswith("quickstart-"))
        self.assertEqual(kwargs["project"], "demo")
        self.assertEqual(kwargs["api_key"], "fl_test")
        self.assertIn("quickstart", kwargs["tags"])


class TestAutoResume(unittest.TestCase):
    @patch("faultline.resume.attach")
    def test_auto_resume_attach_restore(self, mock_attach: MagicMock) -> None:
        run = MagicMock(spec=CloudRun)
        run.recovery.return_value = {
            "has_checkpoint": True,
            "checkpoint_health": "ok",
        }
        run.restore_latest.return_value = 42
        mock_attach.return_value = run
        got_run, step = auto_resume(run_id="uuid-1", api_key="fl_x")
        self.assertIs(got_run, run)
        self.assertEqual(step, 42)
        run.restore_latest.assert_called_once()

    @patch("faultline.resume.start")
    def test_auto_resume_start_when_no_id(self, mock_start: MagicMock) -> None:
        run = MagicMock(spec=CloudRun)
        run.recovery.return_value = {"has_checkpoint": False}
        run.restore_latest.return_value = 0
        mock_start.return_value = run
        _, step = auto_resume(run_name="exp-1", project="p")
        self.assertEqual(step, 0)


class TestStartResumeIfAvailable(unittest.TestCase):
    @patch("faultline.start.init")
    def test_resume_if_available(self, mock_init: MagicMock) -> None:
        run = MagicMock(spec=CloudRun)
        run.restore_latest.return_value = 10
        mock_init.return_value = run
        result = start("r1", resume_if_available=True, model="m", optimizer="o")
        run.restore_latest.assert_called_once_with(model="m", optimizer="o")
        self.assertEqual(getattr(result, "_initial_resume_step", 0), 10)


class TestHuggingFaceCallback(unittest.TestCase):
    def test_callback_tags(self) -> None:
        try:
            cb = FaultlineTrainerCallback(run_name="hf-run", api_key="fl_x")
        except ImportError:
            self.skipTest("transformers not installed")
        self.assertIn("integration:huggingface", cb.tags)

    @patch("faultline.integrations.huggingface.start")
    def test_on_log_calls_run_log(self, mock_start: MagicMock) -> None:
        try:
            from transformers import TrainerCallback
        except ImportError:
            self.skipTest("transformers not installed")
        run = MagicMock(spec=CloudRun)
        mock_start.return_value = run
        cb = FaultlineTrainerCallback(run_name="hf-run", api_key="fl_x", auto_resume=False)
        state = MagicMock(global_step=5, max_steps=100)
        cb._run = run
        cb.on_log(None, state, MagicMock(), logs={"loss": 0.1})
        run.log.assert_called_once()
        run.log_progress.assert_called_once()


class TestLightningCallback(unittest.TestCase):
    def test_callback_metrics_from_trainer(self) -> None:
        trainer = MagicMock()
        loss = MagicMock()
        loss.item.return_value = 0.25
        trainer.callback_metrics = {"train_loss": loss}
        metrics = _callback_metrics(trainer)
        self.assertIn("train_loss", metrics)

    def test_lightning_tags(self) -> None:
        try:
            cb = FaultlineLightningCallback(run_name="pl-run", api_key="fl_x")
        except ImportError:
            self.skipTest("lightning not installed")
        self.assertIn("integration:lightning", cb.tags)


class TestCliInit(unittest.TestCase):
    def test_init_writes_files(self) -> None:
        from faultline.cli import cmd_init

        with tempfile.TemporaryDirectory() as tmp:
            rc = cmd_init(Path(tmp))
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp) / "train.py").is_file())
            self.assertTrue((Path(tmp) / ".env.example").is_file())


class TestCliResume(unittest.TestCase):
    def test_resume_prints_run_id(self) -> None:
        from faultline.cli import cmd_resume

        with patch("builtins.print") as mock_print:
            rc = cmd_resume("abc-123")
        self.assertEqual(rc, 0)
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("abc-123", printed)


if __name__ == "__main__":
    unittest.main()
