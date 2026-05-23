"""
Tiny PyTorch training demo with Faultline pickle checkpoints and simulated crash/resume.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import Runtime

TOTAL_STEPS = 20
SAVE_EVERY = 5
CRASH_AT_STEP = 12

runtime_dir = Path(__file__).resolve().parents[2] / "runtime"
runtime = Runtime(runtime_dir=str(runtime_dir))


def build_model() -> nn.Linear:
    torch.manual_seed(0)
    return nn.Linear(1, 1)


def build_optimizer(model: nn.Linear) -> optim.SGD:
    return optim.SGD(model.parameters(), lr=0.01)


def synthetic_batch(step: int) -> tuple[torch.Tensor, torch.Tensor]:
    x = torch.tensor([[float(step) / 10.0]])
    y = 2.0 * x + 1.0
    return x, y


def make_payload(
    model: nn.Linear,
    optimizer: optim.SGD,
    step: int,
    loss: float,
) -> dict:
    return {
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "step": step,
        "loss": loss,
    }


def restore_payload(
    model: nn.Linear,
    optimizer: optim.SGD,
    payload: dict,
) -> int:
    model.load_state_dict(payload["model"])
    optimizer.load_state_dict(payload["optimizer"])
    return int(payload["step"])


def train_one_step(
    model: nn.Linear,
    optimizer: optim.SGD,
    step: int,
) -> float:
    model.train()
    optimizer.zero_grad()

    x, y = synthetic_batch(step)
    pred = model(x)
    loss_tensor = ((pred - y) ** 2).mean()
    loss_tensor.backward()
    optimizer.step()

    return float(loss_tensor.item())


def save_checkpoint(
    model: nn.Linear,
    optimizer: optim.SGD,
    step: int,
    loss: float,
) -> None:
    payload = make_payload(model, optimizer, step, loss)
    runtime.save_pickle_checkpoint(step, payload)
    print(f"Checkpoint saved at step {step} (loss={loss:.6f})")


def run_training(
    start_step: int,
    model: nn.Linear,
    optimizer: optim.SGD,
    *,
    simulate_crash: bool,
) -> None:
    for step in range(start_step, TOTAL_STEPS + 1):
        loss = train_one_step(model, optimizer, step)
        print(f"step={step} loss={loss:.6f}")

        if step % SAVE_EVERY == 0:
            save_checkpoint(model, optimizer, step, loss)

        if simulate_crash and step == CRASH_AT_STEP:
            print("Simulated crash.")
            raise SystemExit("Simulated crash.")

    print("Training complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Faultline PyTorch resume demo")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Load latest checkpoint and continue training",
    )
    args = parser.parse_args()

    model = build_model()
    optimizer = build_optimizer(model)

    if args.resume:
        payload = runtime.load_latest_pickle()
        last_step = restore_payload(model, optimizer, payload)
        print(f"Recovered from checkpoint step {last_step}")
        print(f"Resuming training from step {last_step + 1}")
        run_training(last_step + 1, model, optimizer, simulate_crash=False)
    else:
        print("Starting fresh training run")
        try:
            run_training(1, model, optimizer, simulate_crash=True)
        except SystemExit as exc:
            if str(exc) != "Simulated crash.":
                raise
            print("Run again with --resume to continue training.")


if __name__ == "__main__":
    main()
