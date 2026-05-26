"""
Upload training metrics to the Faultline cloud ingestion API.

Prerequisites:
  uvicorn cloud.api.app:app --reload --port 8080
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faultline


def main() -> int:
    run = faultline.init(
        project="protein-model",
        run_name="cloud-demo-1",
        mode="cloud",
        api_key="fl_dev_local",
        base_url="http://127.0.0.1:8080",
        tags=["demo", "cloud"],
    )

    print(f"Started cloud run {run.run_id}")

    for step in range(1, 6):
        loss = 1.0 / step
        run.log_metrics(
            {"loss": loss, "learning_rate": 0.01},
            step=step,
        )
        print(f"step {step}: loss={loss:.4f}")

    metadata = run.complete()
    print(f"Completed: status={metadata['status']} latest_step={metadata['latest_step']}")
    run.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
