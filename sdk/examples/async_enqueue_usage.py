import pickle
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import AsyncPersistentRuntime

runtime_dir = Path(__file__).resolve().parents[2] / "runtime"
STEP_OFFSET = 40_000


def build_payload(step: int) -> dict:
    torch.manual_seed(step)
    return {
        "step": step,
        "model_state": {f"t_{i}": torch.randn(64, 64) for i in range(8)},
        "loss": 1.0 / step,
    }


def wait_until_committed(runtime: AsyncPersistentRuntime, step: int) -> None:
    while True:
        status = runtime.checkpoint_status(step)
        if status == "Committed":
            return
        if status.startswith("Failed"):
            raise RuntimeError(f"Checkpoint step {step} failed: {status}")
        print(f"  step {step}: {status}...")
        time.sleep(0.05)


def main() -> None:
    with AsyncPersistentRuntime(runtime_dir=str(runtime_dir)) as runtime:
        enqueue_times_ms: list[float] = []

        wall_start = time.perf_counter()
        for index in range(1, 6):
            step = STEP_OFFSET + index
            payload = build_payload(step)

            start = time.perf_counter()
            message = runtime.enqueue_pickle_checkpoint_via_file(step, payload)
            elapsed_ms = (time.perf_counter() - start) * 1000
            enqueue_times_ms.append(elapsed_ms)
            print(f"step {step}: {message} ({elapsed_ms:.2f} ms enqueue)")

        enqueue_wall_ms = (time.perf_counter() - wall_start) * 1000
        print(f"\nEnqueued 5 checkpoints in {enqueue_wall_ms:.2f} ms wall time")
        print(
            f"Average per-enqueue caller time: "
            f"{sum(enqueue_times_ms) / len(enqueue_times_ms):.2f} ms"
        )

        print("\nPolling statuses until committed...")
        for index in range(1, 6):
            step = STEP_OFFSET + index
            wait_until_committed(runtime, step)
            print(f"step {step}: Committed")

        metrics = runtime.metrics()
        print("\nRuntime metrics:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")

    print("\nAsync service shut down after draining the queue.")


if __name__ == "__main__":
    main()
