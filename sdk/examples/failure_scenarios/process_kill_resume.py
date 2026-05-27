"""Simulate process kill and resume workflow against Faultline Cloud."""

from __future__ import annotations

import os
import random
import time

from faultline.cloud_client import CloudIngestClient


def main() -> int:
    api_key = os.environ.get("FAULTLINE_API_KEY", "fl_dev_local")
    base_url = os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080")
    client = CloudIngestClient(base_url=base_url, api_key=api_key)
    run = client.start_run("failure-scenarios", "process-kill-resume", tags=["demo", "failure"])
    run_id = str(run["run_id"])
    for step in range(1, 8):
        client.log_metrics(run_id, step=step * 50, metrics={"loss": random.uniform(0.1, 1.2)})
        if step % 2 == 0:
            client.upload_checkpoint(run_id, step=step * 50, data=f"checkpoint-{step}".encode())
        time.sleep(0.15)
    client.log_event(
        run_id,
        event_type="faultline.run.failed",
        level="error",
        message="Process killed with SIGKILL (simulated)",
    )
    resume = client.resume_run(run_id)
    print(f"run_id={run_id}")
    print(f"resume_status={resume.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
