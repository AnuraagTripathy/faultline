"""
Cloud checkpoint upload and restore demo.

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
        project="checkpoint-demo",
        run_name="ckpt-run-1",
        mode="cloud",
        api_key="fl_dev_local",
        base_url="http://127.0.0.1:8080",
    )
    print(f"Started run {run.run_id}")

    for step in range(1, 11):
        run.log_metrics({"loss": 1.0 / step}, step=step)
        if step in (5, 10):
            payload = {"step": step, "weights": [0.1 * step, 0.2 * step]}
            result = run.checkpoint(payload, step=step)
            print(f"checkpoint step {step}: {result['size_bytes']} bytes")

    checkpoints = run.list_checkpoints()
    print(f"Listed {len(checkpoints)} checkpoint(s)")
    for cp in checkpoints:
        print(f"  step {cp['step']}: {cp['size_bytes']} B ({cp['status']})")

    state = run.load_latest_checkpoint_or_none()
    if state is not None:
        print(f"Latest checkpoint step: {state.get('step')}")
    else:
        print("No checkpoint found")

    run.complete()
    run.shutdown()
    print("Done. Open http://127.0.0.1:8080/dashboard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
