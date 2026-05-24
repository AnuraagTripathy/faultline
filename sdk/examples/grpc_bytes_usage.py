"""
Enqueue worker checkpoints over gRPC with inline bytes (no temp file).

Uses EnqueueWorkerBytes: pickle → bytes on the wire → Rust async queue.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import GrpcAsyncRuntime
from faultline.grpc_client import default_release_binary_path
from faultline.runtime import global_step_for_worker

RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
WORKER_ID = 9
LOCAL_STEP = 12
RELEASE_BINARY = default_release_binary_path(RUNTIME_DIR)


def main() -> None:
    payload = {
        "worker_id": WORKER_ID,
        "local_step": LOCAL_STEP,
        "fake_loss": 0.12,
        "transport": "grpc-bytes",
    }

    kwargs: dict = {"addr": "127.0.0.1:50054", "queue_capacity": 16}
    if RELEASE_BINARY.is_file():
        kwargs["binary_path"] = str(RELEASE_BINARY)
    else:
        kwargs["runtime_dir"] = str(RUNTIME_DIR)

    with GrpcAsyncRuntime(**kwargs) as runtime:
        print("Connected to Faultline gRPC (bytes transport)\n")

        message = runtime.enqueue_worker_pickle_checkpoint_bytes(
            WORKER_ID, LOCAL_STEP, payload
        )
        print(message)

        global_step = global_step_for_worker(WORKER_ID, LOCAL_STEP)
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


if __name__ == "__main__":
    main()
