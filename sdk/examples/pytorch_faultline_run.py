"""
PyTorch-style fake training loop using the Faultline Runs API.

Prerequisites (two terminals):
  1. cd runtime && cargo run -- serve-grpc --addr 127.0.0.1:50051
  2. uvicorn dashboard.app:app --reload   # optional live Runs panel
"""

from __future__ import annotations

import os

# Windows/conda: PyTorch and MKL may each ship libiomp5md.dll (OMP Error #15).
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import faultline

TOTAL_STEPS = 12
CHECKPOINT_EVERY = 4
SYSTEM_METRICS_EVERY = 3
LEARNING_RATE = 0.01
BATCH_SIZE = 1


def build_model() -> nn.Linear:
    torch.manual_seed(0)
    return nn.Linear(1, 1)


def synthetic_batch(step: int) -> tuple[torch.Tensor, torch.Tensor]:
    x = torch.tensor([[float(step) / 10.0]])
    y = 2.0 * x + 1.0
    return x, y


def train_one_step(
    model: nn.Linear,
    optimizer: optim.SGD,
    step: int,
) -> float:
    model.train()
    optimizer.zero_grad()
    x, y = synthetic_batch(step)
    pred = model(x)
    loss = ((pred - y) ** 2).mean()
    loss.backward()
    optimizer.step()
    return float(loss.item())


def main() -> int:
    model = build_model()
    optimizer = optim.SGD(model.parameters(), lr=LEARNING_RATE)

    run = faultline.init(
        project="protein-model",
        run_name="experiment-1",
        tags=["demo", "pytorch"],
        addr="127.0.0.1:50051",
        start_server=False,
    )

    print(f"Started run {run.run_id} ({run.project}/{run.run_name})")

    try:
        for step in range(1, TOTAL_STEPS + 1):
            with run.track_step(step, num_samples=BATCH_SIZE):
                loss = train_one_step(model, optimizer, step)

            run.log_progress(
                step,
                loss=loss,
                learning_rate=LEARNING_RATE,
            )

            if step % SYSTEM_METRICS_EVERY == 0:
                run.log_system_metrics(step=step)

            if step % CHECKPOINT_EVERY == 0:
                payload = {
                    "model": model.state_dict(),
                    "optimizer": optimizer.state_dict(),
                    "step": step,
                    "loss": loss,
                }
                message = run.checkpoint(payload, step=step)
                print(f"step {step}: loss={loss:.4f} checkpoint queued ({message})")
            else:
                print(f"step {step}: loss={loss:.4f}")

            time.sleep(0.05)

        metadata = run.complete()
        print(f"Run completed: status={metadata['status']} latest_step={metadata['latest_step']}")
    finally:
        run.shutdown()

    print("Open http://127.0.0.1:8000 and check the Runs section (metric selector + system charts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
