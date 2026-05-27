#!/usr/bin/env python3
"""Simulated crash + auto_resume demo for Faultline Cloud."""

from __future__ import annotations

import argparse
import os
import sys

import faultline


def main() -> int:
    parser = argparse.ArgumentParser(description="Faultline crash/resume demo")
    parser.add_argument("--run-id", help="Attach to existing run after crash")
    parser.add_argument("--crash-at", type=int, default=15, help="Step to simulate crash")
    parser.add_argument("--max-steps", type=int, default=30)
    args = parser.parse_args()

    api_key = os.environ.get("FAULTLINE_API_KEY", "fl_dev_local")
    base_url = os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080")

    if args.run_id:
        run, start_step = faultline.auto_resume(
            run_id=args.run_id,
            api_key=api_key,
            base_url=base_url,
        )
        print(f"Resumed run {run.run_id} from step {start_step}")
    else:
        run = faultline.quickstart(project="crash-demo", api_key=api_key, base_url=base_url)
        start_step = 0
        print(f"Started run {run.run_id}")

    try:
        for step in range(start_step, args.max_steps):
            loss = 1.0 / (step + 1)
            faultline.log_progress(run, step, loss=loss)
            if step % 5 == 0 and step > 0:
                run.save(step=step, state={"step": step, "loss": loss})
            if step == args.crash_at and not args.run_id:
                print(f"Simulating crash at step {step}")
                run.fail(message="simulated crash")
                print(f"Re-run with: python {sys.argv[0]} --run-id {run.run_id}")
                return 0
        run.complete()
        print("Training completed")
    except KeyboardInterrupt:
        print(f"Interrupted — resume with: python {sys.argv[0]} --run-id {run.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
