"""Simulate Slurm preemption and delayed resume."""

from __future__ import annotations

import os
import random
import time

from faultline.cloud_client import CloudIngestClient


def main() -> int:
    client = CloudIngestClient(
        base_url=os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080"),
        api_key=os.environ.get("FAULTLINE_API_KEY", "fl_dev_local"),
    )
    run = client.start_run("failure-scenarios", "slurm-preemption", tags=["slurm", "preempt"])
    run_id = str(run["run_id"])
    for step in (250, 300, 350, 400):
        client.log_metrics(run_id, step=step, metrics={"loss": random.uniform(0.2, 0.8)})
        if step % 100 == 0:
            client.upload_checkpoint(run_id, step=step, data=f"slurm-{step}".encode())
    client.log_event(
        run_id,
        event_type="faultline.run.failed",
        level="error",
        message="Slurm job preempted (simulated)",
    )
    time.sleep(1.0)
    client.log_event(
        run_id,
        event_type="faultline.run.resumed",
        level="info",
        message="Slurm requeue complete (simulated delayed resume)",
    )
    print(f"Created simulated Slurm preemption for run {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
