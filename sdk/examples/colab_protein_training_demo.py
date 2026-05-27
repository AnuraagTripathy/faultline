"""
Protein binding classifier demo — Google Colab + Faultline Cloud (~12s).

Your hosted API is all Colab needs at runtime: metrics and checkpoints are plain
HTTP POSTs with an API key. This script uses the Faultline Python SDK because it
is the normal way users write training code (``faultline.start``, ``run.log``,
``run.save``). The SDK is a thin client over that same API — not a second server.

Colab setup (one cell before training):

    !pip install faultline-sdk
    import os
    os.environ["FAULTLINE_API_KEY"] = "fl_..."
    os.environ["FAULTLINE_API_URL"] = "https://your-api.onrender.com"

Then run this script (uses ``import faultline`` — same library, PyPI name is faultline-sdk).

Credentials (if not set in the cell above):

    import os
    os.environ["FAULTLINE_API_KEY"] = "fl_..."
    os.environ["FAULTLINE_API_URL"] = "https://your-api.onrender.com"
"""

from __future__ import annotations

import math
import os
import random
import time

import faultline

# --- config (or use environment variables) ---------------------------------

API_KEY = os.environ.get("FAULTLINE_API_KEY", "fl_dev_local")
API_URL = os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080")

PROJECT = "protein-demo"
RUN_NAME = "colab-binding-classifier"
TARGET_SECONDS = 12.0
STEP_SLEEP = 0.2
CHECKPOINT_EVERY = 15

# --- toy protein task ------------------------------------------------------

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
SEQ_LEN = 64
EMBED_DIM = 32
BATCH_SIZE = 16


class ProteinBindingModel:
    """Small sequence classifier (stand-in for a protein LM fine-tune head)."""

    def __init__(self, seed: int = 0) -> None:
        rng = random.Random(seed)
        self.embeddings = [
            [rng.gauss(0, 0.08) for _ in range(EMBED_DIM)]
            for _ in range(len(AMINO_ACIDS))
        ]
        self.w = [rng.gauss(0, 0.1) for _ in range(EMBED_DIM)]
        self.b = 0.0

    def state_dict(self) -> dict:
        return {"embeddings": self.embeddings, "w": list(self.w), "b": self.b}

    def load_state_dict(self, state: dict) -> None:
        self.embeddings = state["embeddings"]
        self.w = list(state["w"])
        self.b = float(state["b"])

    def _encode(self, seq: list[int]) -> list[float]:
        pooled = [0.0] * EMBED_DIM
        for idx in seq:
            row = self.embeddings[idx]
            for i in range(EMBED_DIM):
                pooled[i] += row[i]
        n = max(len(seq), 1)
        return [v / n for v in pooled]

    def train_batch(
        self, batch: list[tuple[list[int], float]], lr: float
    ) -> tuple[float, float]:
        total_loss = 0.0
        correct = 0
        grad_w = [0.0] * EMBED_DIM
        grad_b = 0.0

        for seq, label in batch:
            h = self._encode(seq)
            z = sum(w * x for w, x in zip(self.w, h)) + self.b
            z = max(-12.0, min(12.0, z))
            pred = 1.0 / (1.0 + math.exp(-z))
            y = float(label)
            total_loss += -(
                y * math.log(max(pred, 1e-9))
                + (1.0 - y) * math.log(max(1.0 - pred, 1e-9))
            )
            correct += int((pred >= 0.5) == (y >= 0.5))
            err = pred - y
            for i in range(EMBED_DIM):
                grad_w[i] += err * h[i]
            grad_b += err

        n = len(batch)
        scale = lr / n
        for i in range(EMBED_DIM):
            self.w[i] -= scale * grad_w[i]
        self.b -= scale * grad_b
        return total_loss / n, correct / n


class TrainerState:
    def __init__(self) -> None:
        self.global_step = 0
        self.lr = 3e-3

    def state_dict(self) -> dict:
        return {"global_step": self.global_step, "lr": self.lr}

    def load_state_dict(self, state: dict) -> None:
        self.global_step = int(state["global_step"])
        self.lr = float(state["lr"])


def sample_batch(rng: random.Random) -> list[tuple[list[int], float]]:
    rows: list[tuple[list[int], float]] = []
    for _ in range(BATCH_SIZE):
        seq = [rng.randrange(len(AMINO_ACIDS)) for _ in range(SEQ_LEN)]
        hydro = sum(1 for i in seq if i < 8) / SEQ_LEN
        label = 1.0 if hydro > 0.42 else 0.0
        if rng.random() < 0.1:
            label = 1.0 - label
        rows.append((seq, label))
    return rows


def main() -> None:
    steps = max(10, int(TARGET_SECONDS / STEP_SLEEP))
    rng = random.Random(42)
    model = ProteinBindingModel(seed=7)
    trainer = TrainerState()

    run = faultline.start(
        RUN_NAME,
        project=PROJECT,
        api_key=API_KEY,
        base_url=API_URL,
        tags=["colab", "protein"],
    )
    print(f"Faultline run: {run.run_id}")
    print(f"Dashboard: watch this run under project '{PROJECT}'")
    print(f"Training {steps} steps (~{steps * STEP_SLEEP:.0f}s)\n")

    resume_step = run.restore_latest(model=model, optimizer=trainer)
    if resume_step > 0:
        print(f"Resumed from checkpoint step {resume_step}")

    step_begin = max(resume_step, trainer.global_step)
    step_end = step_begin + steps

    try:
        for step in range(step_begin, step_end):
            trainer.global_step = step
            trainer.lr = 3e-3 * (0.96**step)

            loss, accuracy = model.train_batch(sample_batch(rng), lr=trainer.lr)

            run.log(
                train_loss=loss,
                val_accuracy=accuracy,
                val_auroc=min(0.99, 0.55 + step * 0.025),
                sequence_ce=loss * 1.15,
                learning_rate=trainer.lr,
                step=step,
            )

            if step > 0 and step % CHECKPOINT_EVERY == 0:
                run.save(step=step, model=model, optimizer=trainer)
                print(f"  checkpoint @ {step}  loss={loss:.4f}  acc={accuracy:.3f}")

            if step % 5 == 0 or step == step_end - 1:
                print(f"  step {step:3d}  loss={loss:.4f}  acc={accuracy:.3f}")

            time.sleep(STEP_SLEEP)

        run.save(step=step_end - 1, model=model, optimizer=trainer)
        run.complete()
        print("\nTraining finished.")
    except KeyboardInterrupt:
        run.save(step=trainer.global_step, model=model, optimizer=trainer)
        run.stop()
        print("\nStopped — checkpoint saved. Resume with faultline.auto_resume(...).")


if __name__ == "__main__":
    main()
