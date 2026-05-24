"""
Enqueue a large worker checkpoint over gRPC client streaming (chunked bytes).

Uses EnqueueWorkerBytesStream to avoid a single giant unary message.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import GrpcAsyncRuntime
from faultline.grpc_client import default_release_binary_path
from faultline.runtime import global_step_for_worker

RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
WORKER_ID = 11
LOCAL_STEP = 3
CHUNK_SIZE = 256 * 1024
# ~8 MiB of tensor data (plus pickle overhead)
PAYLOAD_MB = 8
RELEASE_BINARY = default_release_binary_path(RUNTIME_DIR)


def main() -> None:
    torch.manual_seed(42)
    tensor = torch.randn(PAYLOAD_MB * 256 * 1024 // 4)  # float32 ~ PAYLOAD_MB MiB
    payload = {
        "worker_id": WORKER_ID,
        "local_step": LOCAL_STEP,
        "tensor": tensor,
        "transport": "grpc-stream",
    }

    kwargs: dict = {"addr": "127.0.0.1:50057", "queue_capacity": 8}
    if RELEASE_BINARY.is_file():
        kwargs["binary_path"] = str(RELEASE_BINARY)
    else:
        kwargs["runtime_dir"] = str(RUNTIME_DIR)

    with GrpcAsyncRuntime(**kwargs) as runtime:
        print(f"Streaming checkpoint (~{PAYLOAD_MB} MiB tensor), chunk_size={CHUNK_SIZE}\n")

        message = runtime.enqueue_worker_pickle_checkpoint_stream(
            WORKER_ID, LOCAL_STEP, payload, chunk_size=CHUNK_SIZE
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
        print(f"\nlatest for worker {WORKER_ID}: step={entry['step'] if entry else None}")

        metrics = runtime.metrics()
        print("\nmetrics:")
        for key, value in metrics.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
