"""Simulate checkpoint corruption and failed restore signal."""

from __future__ import annotations

import os
import random

from faultline.cloud_client import CloudIngestClient


def main() -> int:
    client = CloudIngestClient(
        base_url=os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080"),
        api_key=os.environ.get("FAULTLINE_API_KEY", "fl_dev_local"),
    )
    run = client.start_run("failure-scenarios", "corrupted-checkpoint", tags=["corruption", "demo"])
    run_id = str(run["run_id"])
    for step in (100, 200):
        client.log_metrics(run_id, step=step, metrics={"loss": random.uniform(0.2, 0.9)})
        client.upload_checkpoint(run_id, step=step, data=f"valid-{step}".encode())
    client.upload_checkpoint(run_id, step=260, data=b"\x00\x01\x02corrupt")
    client.log_event(
        run_id,
        event_type="faultline.checkpoint.corrupt",
        level="error",
        message="Checksum mismatch on latest checkpoint (simulated)",
    )
    client.log_event(
        run_id,
        event_type="faultline.run.failed",
        level="error",
        message="Restore failed due to checkpoint corruption (simulated)",
    )
    print(f"Created simulated corrupted checkpoint for run {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
