"""
Long Faultline Cloud training demo — runs on YOUR machine, streams to the dashboard.

Training executes locally in this process. Faultline Cloud stores metrics and
checkpoints over HTTP; the web UI at http://localhost:3000 shows live progress.

Prerequisites:
  - Faultline Cloud API running (Docker or uvicorn on :8080)
  - API key from Account page

Run (from repo root):

  set PYTHONPATH=sdk
  set FAULTLINE_API_KEY=your-key-here
  python sdk/examples/cloud_long_training.py

  # Or pass explicitly:
  python sdk/examples/cloud_long_training.py ^
    --api-key fl_... ^
    --steps 400 ^
    --step-delay 0.08

While it runs, open:
  - Next.js UI:  http://localhost:3000/runs
  - Legacy UI:   http://127.0.0.1:8080/dashboard

Stop with Ctrl+C — checkpoint is saved and run marked stopped (resume on re-run).
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faultline

FEATURE_DIM = 32
BATCH_SIZE = 64
WARMUP_STEPS = 40


class TinyClassifier:
    """Minimal trainable model (stdlib only — no PyTorch install required)."""

    def __init__(self, seed: int = 0) -> None:
        rng = random.Random(seed)
        self.w = [rng.gauss(0, 0.12) for _ in range(FEATURE_DIM)]
        self.b = 0.0

    def state_dict(self) -> dict:
        return {"w": list(self.w), "b": self.b}

    def load_state_dict(self, state: dict) -> None:
        self.w = list(state["w"])
        self.b = float(state["b"])

    def predict_proba(self, features: list[float]) -> float:
        z = sum(w * x for w, x in zip(self.w, features)) + self.b
        z = max(-20.0, min(20.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    def train_batch(
        self, batch: list[tuple[list[float], float]], lr: float
    ) -> tuple[float, float, float]:
        total_loss = 0.0
        correct = 0
        grad_w = [0.0] * FEATURE_DIM
        grad_b = 0.0

        for features, label in batch:
            pred = self.predict_proba(features)
            error = pred - label
            total_loss += -(
                label * math.log(max(pred, 1e-9))
                + (1.0 - label) * math.log(max(1.0 - pred, 1e-9))
            )
            correct += int((pred >= 0.5) == (label >= 0.5))
            for i in range(FEATURE_DIM):
                grad_w[i] += error * features[i]
            grad_b += error

        n = len(batch)
        scale = lr / n
        grad_norm = math.sqrt(sum(g * g for g in grad_w) + grad_b * grad_b)
        for i in range(FEATURE_DIM):
            self.w[i] -= scale * grad_w[i]
        self.b -= scale * grad_b
        return total_loss / n, correct / n, grad_norm


class TrainingState:
    def __init__(self) -> None:
        self.global_step = 0
        self.base_lr = 0.08
        self.epoch = 0

    def state_dict(self) -> dict:
        return {
            "global_step": self.global_step,
            "base_lr": self.base_lr,
            "epoch": self.epoch,
        }

    def load_state_dict(self, state: dict) -> None:
        self.global_step = int(state["global_step"])
        self.base_lr = float(state["base_lr"])
        self.epoch = int(state.get("epoch", 0))


def make_dataset(n: int, seed: int) -> list[tuple[list[float], float]]:
    rng = random.Random(seed)
    rows: list[tuple[list[float], float]] = []
    for _ in range(n):
        features = [rng.gauss(0, 1) for _ in range(FEATURE_DIM)]
        label = 1.0 if sum(features[:6]) + rng.gauss(0, 0.3) > 0 else 0.0
        rows.append((features, label))
    return rows


def sample_batch(
    dataset: list[tuple[list[float], float]], rng: random.Random
) -> list[tuple[list[float], float]]:
    return [rng.choice(dataset) for _ in range(BATCH_SIZE)]


def learning_rate(step: int, base_lr: float) -> float:
    if step < WARMUP_STEPS:
        return base_lr * (step + 1) / WARMUP_STEPS
    decay = 0.998 ** (step - WARMUP_STEPS)
    return base_lr * decay


def parse_args() -> argparse.Namespace:
    # NOTE: This script defaults to a specific key for convenience in this workspace.
    # Prefer setting FAULTLINE_API_KEY in your shell instead of committing keys.
    default_key = os.environ.get("FAULTLINE_API_KEY", "fl_oWSUte0WfPzjsY-l7ceZw3jCE6G2vm2k")
    default_url = os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080")
    parser = argparse.ArgumentParser(
        description="Long Faultline Cloud training demo (local CPU, cloud observability)."
    )
    parser.add_argument("--project", default="demo", help="Faultline project")
    parser.add_argument("--run-name", default="long-training-run", help="Run name in UI")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Resume an existing run id (from Ctrl+C output or dashboard URL)",
    )
    parser.add_argument("--steps", type=int, default=350, help="Training steps")
    parser.add_argument(
        "--step-delay",
        type=float,
        default=0.1,
        help="Seconds per step (simulates compute time)",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=25,
        help="Upload checkpoint every N steps",
    )
    parser.add_argument("--api-key", default=default_key, help="Faultline API key")
    parser.add_argument("--base-url", default=default_url, help="Cloud API URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.api_key:
        print("Error: set FAULTLINE_API_KEY or pass --api-key", file=sys.stderr)
        return 2

    dataset = make_dataset(8192, seed=42)
    rng = random.Random(99)
    model = TinyClassifier(seed=1)
    trainer = TrainingState()

    print("=" * 60)
    print("Faultline Cloud — long training demo")
    print("=" * 60)
    print(f"  API:       {args.base_url}")
    print(f"  Project:   {args.project}")
    print(f"  Run name:  {args.run_name}")
    print(f"  Steps:     {args.steps}  (~{args.steps * args.step_delay:.0f}s)")
    print(f"  Dashboard: http://localhost:3000/runs")
    print()

    if args.run_id:
        run = faultline.attach(
            args.run_id,
            api_key=args.api_key,
            base_url=args.base_url,
        )
        print(f"Attached to cloud run: {run.run_id}")
    else:
        run = faultline.start(
            args.run_name,
            project=args.project,
            api_key=args.api_key,
            base_url=args.base_url,
            tags=["long-demo", "local-training", "v18"],
        )
        print(f"Started cloud run: {run.run_id}")

    resume_step = run.restore_latest(model=model, optimizer=trainer)
    if resume_step > 0:
        print(f"Resumed from checkpoint at step {resume_step}")
    start_step = max(resume_step, trainer.global_step)
    end_step = start_step + args.steps

    steps_per_epoch = max(1, len(dataset) // BATCH_SIZE)
    best_loss = float("inf")

    try:
        for step in range(start_step, end_step):
            t0 = time.perf_counter()
            trainer.global_step = step
            trainer.epoch = step // steps_per_epoch
            lr = learning_rate(step, trainer.base_lr)

            batch = sample_batch(dataset, rng)
            loss, accuracy, grad_norm = model.train_batch(batch, lr=lr)
            best_loss = min(best_loss, loss)
            step_ms = (time.perf_counter() - t0) * 1000.0 + args.step_delay * 1000.0

            run.log(
                loss=loss,
                accuracy=accuracy,
                learning_rate=lr,
                grad_norm=grad_norm,
                best_loss=best_loss,
                step_time_ms=step_ms,
                step=step,
            )

            if step > 0 and step % args.checkpoint_every == 0:
                run.save(model=model, optimizer=trainer, step=step)
                print(
                    f"  [ckpt] step {step:4d}  loss={loss:.4f}  "
                    f"acc={accuracy:.3f}  lr={lr:.5f}"
                )

            if step % 20 == 0 or step == end_step - 1:
                print(
                    f"  step {step:4d}  epoch={trainer.epoch}  "
                    f"loss={loss:.4f}  acc={accuracy:.3f}  lr={lr:.5f}"
                )

            time.sleep(args.step_delay)

        run.save(model=model, optimizer=trainer, step=end_step - 1)
        meta = run.complete()
        print()
        print("Training complete.")
        print(f"  status:      {meta.get('status')}")
        print(f"  latest_step: {meta.get('latest_step')}")
        print(f"  View run:    http://localhost:3000/runs/{run.run_id}")
    except KeyboardInterrupt:
        print("\nInterrupted — saving checkpoint and marking run stopped.")
        run.save(model=model, optimizer=trainer, step=trainer.global_step)
        run.stop()
        print(f"  Resume with:")
        print(
            f"    python sdk/examples/cloud_long_training.py "
            f'--run-id {run.run_id} --steps {max(0, args.steps)}'
        )
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
