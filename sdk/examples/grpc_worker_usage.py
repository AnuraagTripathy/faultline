"""
Enqueue worker checkpoints over gRPC (serve-grpc) instead of stdin/stdout JSON.

Start the server manually:
  cd runtime && cargo run -- serve-grpc --addr 127.0.0.1:50051

Or let GrpcAsyncRuntime spawn it (default).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import GrpcAsyncRuntime

RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
WORKER_ID = 7
LOCAL_STEP = 5


def main() -> None:
    payload = {
        "worker_id": WORKER_ID,
        "local_step": LOCAL_STEP,
        "fake_loss": 0.25,
        "status": "running",
    }

    with GrpcAsyncRuntime(runtime_dir=str(RUNTIME_DIR), addr="127.0.0.1:50051") as runtime:
        print("Connected to Faultline gRPC service\n")

        message = runtime.enqueue_worker_pickle_checkpoint_via_file(
            WORKER_ID, LOCAL_STEP, payload
        )
        print(message)

        global_step = WORKER_ID * 1_000_000 + LOCAL_STEP
        while True:
            status = runtime.checkpoint_status(global_step)
            print(f"status: {status}")
            if status == "Committed":
                break
            if status.startswith("Failed"):
                raise RuntimeError(status)
            time.sleep(0.05)

        entry = runtime.latest_checkpoint_for_worker(WORKER_ID)
        print(f"\nlatest for worker {WORKER_ID}: {entry}")

        metrics = runtime.metrics()
        print("\nmetrics:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
