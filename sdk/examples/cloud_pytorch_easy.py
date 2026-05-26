"""
Faultline Cloud training demo — runs on YOUR machine.

Where does training happen?
  • The model trains here (your laptop, VM, or cluster node) in this Python process.
  • Faultline Cloud (uvicorn on :8080) only receives metrics and checkpoints over HTTP.
  • The dashboard reads that stored data — it does not run your model.

Prerequisites:
  uvicorn cloud.api.app:app --reload --port 8080

Run (from repo root):
  set PYTHONPATH=sdk
  python sdk/examples/cloud_pytorch_easy.py

Options:
  python sdk/examples/cloud_pytorch_easy.py --steps 200 --step-delay 0.12
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faultline

# Feature dimension for a tiny logistic-regression-style model (stdlib only, no PyTorch).
FEATURE_DIM = 16
BATCH_SIZE = 32


class TinyClassifier:
    """Minimal trainable model with PyTorch-like state_dict hooks."""

    def __init__(self, seed: int = 0) -> None:
        rng = random.Random(seed)
        self.w = [rng.gauss(0, 0.15) for _ in range(FEATURE_DIM)]
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

    def train_batch(self, batch: list[tuple[list[float], float]], lr: float) -> tuple[float, float]:
        """One SGD step; returns (loss, accuracy) for the batch."""
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
        for i in range(FEATURE_DIM):
            self.w[i] -= scale * grad_w[i]
        self.b -= scale * grad_b
        return total_loss / n, correct / n


class TrainingState:
    """Optimizer-ish bookkeeping for checkpoints."""

    def __init__(self) -> None:
        self.global_step = 0
        self.lr = 0.05

    def state_dict(self) -> dict:
        return {"global_step": self.global_step, "lr": self.lr}

    def load_state_dict(self, state: dict) -> None:
        self.global_step = int(state["global_step"])
        self.lr = float(state["lr"])


def make_synthetic_dataset(n: int, seed: int) -> list[tuple[list[float], float]]:
    rng = random.Random(seed)
    rows: list[tuple[list[float], float]] = []
    for _ in range(n):
        features = [rng.gauss(0, 1) for _ in range(FEATURE_DIM)]
        label = 1.0 if sum(features[:4]) > 0 else 0.0
        rows.append((features, label))
    return rows


def sample_batch(dataset: list[tuple[list[float], float]], rng: random.Random) -> list[tuple[list[float], float]]:
    return [rng.choice(dataset) for _ in range(BATCH_SIZE)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Longer Faultline Cloud training demo (local CPU).")
    parser.add_argument("--project", default="demo", help="Faultline project name")
    parser.add_argument("--run-name", default="training-demo", help="Run name in the dashboard")
    parser.add_argument("--steps", type=int, default=180, help="Training steps (more = longer demo)")
    parser.add_argument(
        "--step-delay",
        type=float,
        default=0.12,
        help="Seconds to sleep per step (simulates real train time)",
    )
    parser.add_argument("--checkpoint-every", type=int, default=30, help="Upload checkpoint every N steps")
    parser.add_argument("--api-key", default="fl_dev_local")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = make_synthetic_dataset(4096, seed=42)
    rng = random.Random(7)

    model = TinyClassifier(seed=1)
    trainer = TrainingState()

    print("Training runs on this machine (your laptop).")
    print("Faultline Cloud only stores metrics/checkpoints — open the dashboard while this runs.")
    print(f"  Dashboard: {args.base_url}/dashboard")
    print()

    run = faultline.start(
        args.run_name,
        project=args.project,
        api_key=args.api_key,
        base_url=args.base_url,
        tags=["demo", "local-training"],
    )
    print(f"Cloud run id: {run.run_id}")

    resume_step = run.restore_latest(model=model, optimizer=trainer)
    if resume_step > 0:
        print(f"Resumed from checkpoint at step {resume_step}")
    start_step = max(resume_step, trainer.global_step)
    end_step = start_step + args.steps

    estimated_sec = args.steps * args.step_delay
    print(f"Training steps {start_step} → {end_step} (~{estimated_sec:.0f}s at {args.step_delay}s/step)")
    print()

    try:
        for step in range(start_step, end_step):
            trainer.global_step = step
            # Learning rate decay for a nicer chart
            trainer.lr = 0.05 * (0.995**step)

            batch = sample_batch(dataset, rng)
            loss, accuracy = model.train_batch(batch, lr=trainer.lr)

            run.log(
                loss=loss,
                accuracy=accuracy,
                learning_rate=trainer.lr,
                step=step,
            )

            if step > 0 and step % args.checkpoint_every == 0:
                run.save(model=model, optimizer=trainer, step=step)
                print(f"  checkpoint @ step {step}  loss={loss:.4f}  acc={accuracy:.3f}")

            if step % 10 == 0 or step == end_step - 1:
                print(f"  step {step:4d}  loss={loss:.4f}  acc={accuracy:.3f}  lr={trainer.lr:.5f}")

            time.sleep(args.step_delay)

        run.save(model=model, optimizer=trainer, step=end_step - 1)
        metadata = run.complete()
        print()
        print(f"Done. status={metadata.get('status')} latest_step={metadata.get('latest_step')}")
        print(f"View run: {args.base_url}/dashboard")
    except KeyboardInterrupt:
        print("\nInterrupted — saving checkpoint and marking run stopped.")
        run.save(model=model, optimizer=trainer, step=trainer.global_step)
        run.stop()
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
