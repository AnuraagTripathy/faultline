"""Local training simulation for ``faultline demo`` (streams to Cloud API)."""

from __future__ import annotations

import pickle
import time
from typing import Any

from faultline.cloud_client import CloudIngestClient


def run_live_demo(
    *,
    api_key: str,
    base_url: str,
    project: str = "faultline-demo",
    run_name: str = "cli-live-demo",
    steps: int = 60,
    crash_at: int | None = 45,
    sleep_s: float = 0.15,
) -> dict[str, Any]:
    """Create a run, stream metrics/checkpoints, optionally simulate a crash."""
    client = CloudIngestClient(base_url=base_url, api_key=api_key)
    meta = client.start_run(
        project,
        run_name,
        tags=["cli-demo", "integration:pytorch"],
    )
    run_id = str(meta["run_id"])
    print(f"Run {run_id} — open http://localhost:3000/runs/{run_id}")

    for step in range(steps):
        loss = 2.0 * (0.97**step)
        client.log_metrics(run_id, step=step, metrics={"loss": loss, "progress_pct": 100.0 * step / steps})
        if step > 0 and step % 10 == 0:
            blob = pickle.dumps({"step": step, "loss": loss})
            client.upload_checkpoint(
                run_id,
                step=step,
                data=blob,
                metadata_json='{"source":"faultline-demo"}',
            )
            print(f"  checkpoint step {step}")
        if crash_at is not None and step == crash_at:
            client.log_event(
                run_id,
                event_type="faultline.run.failed",
                level="error",
                message="simulated crash (faultline demo)",
            )
            print(f"Crashed at step {step}. Resume with: python -m faultline.cli resume {run_id}")
            return {"run_id": run_id, "crashed": True, "step": step}
        if sleep_s > 0:
            time.sleep(sleep_s)

    client.log_event(
        run_id,
        event_type="faultline.run.completed",
        level="info",
        message="demo completed",
    )
    print("Demo completed successfully.")
    return {"run_id": run_id, "crashed": False}
