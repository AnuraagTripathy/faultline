"""Simulate a spot GPU interruption event."""

from __future__ import annotations

import os
import random

from faultline.cloud_client import CloudIngestClient


def main() -> int:
    client = CloudIngestClient(
        base_url=os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080"),
        api_key=os.environ.get("FAULTLINE_API_KEY", "fl_dev_local"),
    )
    run = client.start_run("failure-scenarios", "spot-gpu-interruption", tags=["spot", "demo"])
    run_id = str(run["run_id"])
    for step in (100, 200, 300):
        client.log_metrics(run_id, step=step, metrics={"loss": random.uniform(0.3, 1.3)})
        client.upload_checkpoint(run_id, step=step, data=f"spot-step-{step}".encode())
    client.log_event(
        run_id,
        event_type="faultline.run.failed",
        level="error",
        message="AWS spot interruption notice received (simulated)",
    )
    print(f"Created simulated spot interruption for run {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
