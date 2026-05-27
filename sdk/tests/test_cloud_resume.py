"""SDK tests for launch config and resume (v17.2)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from faultline.cloud_run import CloudRun


class TestCloudResumeSdk(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.run = CloudRun(
            self.client,
            project="demo",
            run_name="r1",
            metadata={"run_id": "uuid-1", "latest_step": 0},
        )

    def test_register_launch_command(self) -> None:
        self.client.register_launch_config.return_value = {"launch_type": "local_command"}
        self.run.register_launch_command(["python", "train.py"])
        self.client.register_launch_config.assert_called_once_with(
            "uuid-1",
            {
                "launch_type": "local_command",
                "command": ["python", "train.py"],
            },
        )

    def test_register_slurm_script(self) -> None:
        self.run.register_slurm_script("train.slurm", working_dir="/tmp")
        args = self.client.register_launch_config.call_args[0][1]
        self.assertEqual(args["launch_type"], "slurm_script")
        self.assertEqual(args["script_path"], "train.slurm")
        self.assertEqual(args["working_dir"], "/tmp")

    def test_resume_wrapper(self) -> None:
        self.client.resume_run.return_value = {"status": "resume_started", "pid": 9}
        result = self.run.resume()
        self.client.resume_run.assert_called_once_with("uuid-1")
        self.assertEqual(result["pid"], 9)


if __name__ == "__main__":
    unittest.main()
