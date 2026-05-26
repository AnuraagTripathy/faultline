"""
Dataset + shard coordination demo (Version 11.0).

Registers a fake dataset (100 samples, shard_size=10), runs 3 workers that
claim shards, checkpoint progress over gRPC, and complete shards. Worker 1
crashes mid-shard; stale-claim release lets another worker finish the shard.

Coordination demo only — not real multi-node deployment.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import GrpcAsyncRuntime

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "runtime"
DATASETS_DIR = REPO_ROOT / "datasets"
CHECKPOINTS_DIR = REPO_ROOT / "checkpoints"

DATASET_NAME = "fake-training"
TOTAL_SAMPLES = 100
SHARD_SIZE = 10
TOTAL_SHARDS = TOTAL_SAMPLES // SHARD_SIZE

NUM_WORKERS = 3
CRASH_WORKER_ID = 1
CRASH_SHARD_ID = 2
STALE_TIMEOUT_MS = 250
# Use the long-lived serve-grpc from Terminal 1 (dashboard listens on the same addr).
GRPC_ADDR = os.environ.get("FAULTLINE_GRPC_ADDR", "127.0.0.1:50051")


def register_or_reuse_dataset(
    runtime: GrpcAsyncRuntime, runtime_lock: threading.Lock
) -> dict[str, Any]:
    with runtime_lock:
        existing = next(
            (dataset for dataset in runtime.list_datasets() if dataset["name"] == DATASET_NAME),
            None,
        )
        if existing is not None:
            print(f"Dataset {DATASET_NAME!r} already registered in runtime — reusing it.\n")
            return existing
        try:
            return runtime.register_dataset(DATASET_NAME, TOTAL_SAMPLES, SHARD_SIZE)
        except RuntimeError as error:
            if "already registered" in str(error):
                print(
                    f"Dataset {DATASET_NAME!r} already in runtime memory. "
                    "Restart serve-grpc after FAULTLINE_CLEAN, or reusing.\n"
                )
                datasets = runtime.list_datasets()
                return next(
                    dataset for dataset in datasets if dataset["name"] == DATASET_NAME
                )
            raise


def build_checkpoint_payload(
    worker_id: int, shard: dict[str, Any], processed_samples: int
) -> dict[str, Any]:
    return {
        "worker_id": worker_id,
        "dataset": shard["dataset_name"],
        "shard_id": shard["shard_id"],
        "start_sample": shard["start_sample"],
        "end_sample": shard["end_sample"],
        "processed_samples": processed_samples,
        "timestamp": time.time(),
    }


def process_shard(
    worker_id: int,
    runtime: GrpcAsyncRuntime,
    runtime_lock: threading.Lock,
    shard: dict[str, Any],
    completed_counter: list[int],
    counter_lock: threading.Lock,
) -> None:
    shard_id = int(shard["shard_id"])
    sample_count = int(shard["end_sample"]) - int(shard["start_sample"])
    print(
        f"worker {worker_id} processing shard {shard_id} "
        f"(samples {shard['start_sample']}..{shard['end_sample']})"
    )

    for processed in range(1, sample_count + 1):
        time.sleep(0.02)

    local_step = shard_id
    with runtime_lock:
        runtime.enqueue_worker_pickle_checkpoint_bytes(
            worker_id,
            local_step,
            build_checkpoint_payload(worker_id, shard, sample_count),
        )
        runtime.complete_shard(worker_id, DATASET_NAME, shard_id)

    with counter_lock:
        completed_counter[0] += 1
        done = completed_counter[0]

    print(
        f"worker {worker_id} completed shard {shard_id} "
        f"({done}/{TOTAL_SHARDS} shards done)"
    )


def worker_loop(
    worker_id: int,
    runtime: GrpcAsyncRuntime,
    runtime_lock: threading.Lock,
    completed_counter: list[int],
    counter_lock: threading.Lock,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        with counter_lock:
            if completed_counter[0] >= TOTAL_SHARDS:
                return

        with runtime_lock:
            shard = runtime.claim_next_shard(worker_id, DATASET_NAME)

        if shard is None:
            time.sleep(0.05)
            continue

        shard_id = int(shard["shard_id"])
        print(
            f"worker {worker_id} claimed shard {shard_id} "
            f"(samples {shard['start_sample']}..{shard['end_sample']})"
        )
        process_shard(
            worker_id,
            runtime,
            runtime_lock,
            shard,
            completed_counter,
            counter_lock,
        )


def main() -> None:
    print("Faultline dataset + shard coordination demo\n")
    print(
        f"Dataset: {DATASET_NAME} ({TOTAL_SAMPLES} samples, "
        f"shard_size={SHARD_SIZE} -> {TOTAL_SHARDS} shards)\n"
    )

    if os.environ.get("FAULTLINE_CLEAN") == "1":
        if DATASETS_DIR.exists():
            shutil.rmtree(DATASETS_DIR)
        if CHECKPOINTS_DIR.exists():
            shutil.rmtree(CHECKPOINTS_DIR)
        print("Cleared datasets/ and checkpoints/ on disk.\n")
        print(
            "Next: restart serve-grpc (Terminal 1), then run: python sdk\\examples\\dataset_worker_simulation.py\n"
        )
        return
    else:
        print(
            f"Using gRPC at {GRPC_ADDR} (set FAULTLINE_CLEAN=1 to wipe disk first)\n"
        )

    completed_counter = [0]
    counter_lock = threading.Lock()
    runtime_lock = threading.Lock()
    stop_event = threading.Event()

    with GrpcAsyncRuntime(
        runtime_dir=str(RUNTIME_DIR),
        addr=GRPC_ADDR,
        queue_capacity=16,
        start_server=False,
    ) as runtime:
        metadata = register_or_reuse_dataset(runtime, runtime_lock)
        print(f"Using dataset: {metadata}\n")

        print("=== Phase 1: workers 0 and 2 finish shards 0 and 1 ===\n")
        for worker_id in (0, 2):
            with runtime_lock:
                shard = runtime.claim_next_shard(worker_id, DATASET_NAME)
            if shard is None:
                raise RuntimeError(f"expected shard for worker {worker_id}")
            process_shard(
                worker_id,
                runtime,
                runtime_lock,
                shard,
                completed_counter,
                counter_lock,
            )

        print(
            f"\n=== Phase 2: worker {CRASH_WORKER_ID} claims shard "
            f"{CRASH_SHARD_ID} and crashes mid-processing ===\n"
        )
        with runtime_lock:
            shard = runtime.claim_next_shard(CRASH_WORKER_ID, DATASET_NAME)
        if shard is None or int(shard["shard_id"]) != CRASH_SHARD_ID:
            raise RuntimeError(
                f"expected worker {CRASH_WORKER_ID} to claim shard {CRASH_SHARD_ID}, "
                f"got {shard}"
            )
        print(
            f"worker {CRASH_WORKER_ID} claimed shard {CRASH_SHARD_ID} "
            f"(samples {shard['start_sample']}..{shard['end_sample']})"
        )
        print(
            f"worker {CRASH_WORKER_ID} simulating crash mid-shard "
            f"(claim left open)\n"
        )
        time.sleep(0.2)

        print(
            f"=== Phase 3: release stale claims (timeout={STALE_TIMEOUT_MS} ms) ===\n"
        )
        time.sleep(STALE_TIMEOUT_MS / 1000.0 + 0.05)
        with runtime_lock:
            released = runtime.release_stale_shards(STALE_TIMEOUT_MS)
        print(f"Released {released} stale shard claim(s)\n")

        print("=== Phase 4: all workers drain remaining shards ===\n")
        threads: list[threading.Thread] = []
        for worker_id in range(NUM_WORKERS):
            thread = threading.Thread(
                target=worker_loop,
                args=(
                    worker_id,
                    runtime,
                    runtime_lock,
                    completed_counter,
                    counter_lock,
                    stop_event,
                ),
                name=f"worker-{worker_id}",
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join(timeout=60.0)
            if thread.is_alive():
                raise RuntimeError(f"{thread.name} did not finish in time")

        stop_event.set()

        with counter_lock:
            if completed_counter[0] != TOTAL_SHARDS:
                raise RuntimeError(
                    f"expected {TOTAL_SHARDS} completed shards, "
                    f"got {completed_counter[0]}"
                )

        with runtime_lock:
            datasets = runtime.list_datasets()

    print("Registered datasets:", datasets)
    print(f"\nAll {TOTAL_SHARDS} shards completed.")
    print(
        "Takeaway: crashed workers leave claims stale; release_stale_shards "
        "returns work to the pool for another worker."
    )


if __name__ == "__main__":
    main()
