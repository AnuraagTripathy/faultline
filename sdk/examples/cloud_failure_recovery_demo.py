"""
Crash-to-resume demo — training runs locally; Faultline stores recovery metadata.

Prerequisites:
  uvicorn cloud.api.app:app --reload --port 8080

Run:
  set PYTHONPATH=sdk
  python sdk/examples/cloud_failure_recovery_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faultline


class FakeModel:
    def __init__(self) -> None:
        self.w = 0.0

    def state_dict(self) -> dict:
        return {"w": self.w}

    def load_state_dict(self, state: dict) -> None:
        self.w = float(state["w"])


class FakeOptimizer:
    def __init__(self) -> None:
        self.step_count = 0

    def state_dict(self) -> dict:
        return {"step_count": self.step_count}

    def load_state_dict(self, state: dict) -> None:
        self.step_count = int(state["step_count"])


def main() -> int:
    model = FakeModel()
    optimizer = FakeOptimizer()

    run = faultline.start(
        "recovery-demo",
        project="demo",
        api_key="fl_dev_local",
        base_url="http://127.0.0.1:8080",
        tags=["recovery-demo"],
    )
    print(f"Started run {run.run_id}")

    for step in range(20):
        model.w += 0.01
        optimizer.step_count = step
        run.log(loss=1.0 / (step + 1), step=step)
        if step == 10:
            run.save(model=model, optimizer=optimizer, step=step)
            print(f"  saved checkpoint @ step {step}")
        if step == 15:
            print(f"  simulated crash @ step {step}")
            run.fail("simulated crash")
            break

    recovery = run.recovery()
    run.print_resume_instructions(recovery)

    recovered_step = run.restore_latest(model=model, optimizer=optimizer)
    print(f"Recovered checkpoint step: {recovered_step}")
    print(f"Model w={model.w:.4f} optimizer steps={optimizer.step_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
