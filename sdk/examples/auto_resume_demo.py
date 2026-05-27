"""
Auto-resume demo — register launch command, fail, relaunch via API.

Prerequisites:
  uvicorn cloud.api.app:app --reload --port 8080

Run:
  set PYTHONPATH=sdk
  python sdk/examples/auto_resume_demo.py
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
        self.n = 0

    def state_dict(self) -> dict:
        return {"n": self.n}

    def load_state_dict(self, state: dict) -> None:
        self.n = int(state["n"])


def main() -> int:
    model = FakeModel()
    optimizer = FakeOptimizer()

    run = faultline.start(
        "auto-resume-demo",
        project="demo",
        api_key="fl_dev_local",
        base_url="http://127.0.0.1:8080",
    )

    run.register_launch_command(
        [sys.executable, "-c", "print('faultline relaunched training')"],
    )
    print("Registered local launch command")

    for step in range(20):
        model.w = step * 0.1
        optimizer.n = step
        run.log(loss=1.0 / (step + 1), step=step)
        if step == 10:
            run.save(model=model, optimizer=optimizer, step=step)
            print(f"  checkpoint @ {step}")
        if step == 15:
            run.fail("simulated crash")
            print(f"  failed @ {step}")
            break

    recovery = run.recovery()
    print(f"Recovery: can_resume={recovery.get('can_resume')} lost={recovery.get('estimated_lost_steps')}")

    result = run.resume()
    print(f"Resume API: {result}")

    start_step = run.restore_latest(model=model, optimizer=optimizer)
    print(f"Restored checkpoint step {start_step} (model.w={model.w})")

    for step in range(start_step, start_step + 3):
        run.log(loss=0.05, step=step)

    run.complete()
    print("Done — see dashboard Recovery panel for launch + resume timeline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
