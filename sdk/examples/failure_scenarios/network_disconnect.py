"""Simulate interrupted upload and stale run detection."""

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
    run = client.start_run("failure-scenarios", "network-disconnect", tags=["network", "upload"])
    run_id = str(run["run_id"])
    for step in (40, 80, 120):
        client.log_metrics(run_id, step=step, metrics={"loss": random.uniform(0.1, 1.0)})
    client.log_event(
        run_id,
        event_type="faultline.checkpoint.upload_interrupted",
        level="warning",
        message="Checkpoint upload interrupted by network disconnect (simulated)",
    )
    time.sleep(1.2)
    client.log_event(
        run_id,
        event_type="faultline.run.stale",
        level="warning",
        message="Run marked stale after telemetry gap (simulated)",
    )
    print(f"Created simulated network disconnect for run {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
