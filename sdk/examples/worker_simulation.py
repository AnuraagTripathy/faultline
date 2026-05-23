"""
Simulate multiple training workers enqueueing checkpoints through one
AsyncPersistentRuntime — including a crash and resume for worker 1.

Worker identity is stored in Rust metadata (worker_id, local_step) as well as
encoded in the global checkpoint step used for filenames.

This is a coordination demo only, not real distributed training.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import AsyncPersistentRuntime
from faultline.runtime import WORKER_STEP_SCALE, global_step_for_worker

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "runtime"

NUM_WORKERS = 3
TOTAL_STEPS = 20
SAVE_EVERY = 5
CRASH_WORKER_ID = 1
CRASH_AT_LOCAL_STEP = 12
QUEUE_CAPACITY = 16


def build_payload(worker_id: int, local_step: int) -> dict[str, Any]:
    return {
        "worker_id": worker_id,
        "local_step": local_step,
        "fake_loss": 1.0 / (local_step + worker_id + 1),
        "timestamp": time.time(),
        "status": "running",
    }


def wait_until_committed(
    runtime: AsyncPersistentRuntime,
    runtime_lock: threading.Lock,
    steps: list[int],
) -> None:
    pending = set(steps)
    while pending:
        for step in list(pending):
            with runtime_lock:
                status = runtime.checkpoint_status(step)
            if status == "Committed":
                pending.remove(step)
            elif status.startswith("Failed"):
                raise RuntimeError(f"checkpoint step {step} failed: {status}")
        if pending:
            time.sleep(0.05)


def run_worker(
    worker_id: int,
    runtime: AsyncPersistentRuntime,
    runtime_lock: threading.Lock,
    enqueued_steps: list[int],
    *,
    start_local_step: int = 1,
    crash_at_local_step: int | None = None,
) -> int | None:
    """Run training steps. Returns crash local step if simulated crash occurred."""
    for local_step in range(start_local_step, TOTAL_STEPS + 1):
        if crash_at_local_step is not None and local_step == crash_at_local_step:
            print(f"worker {worker_id} crashed at step {local_step}")
            return local_step

        loss = 1.0 / (local_step + worker_id + 1)
        print(
            f"worker {worker_id} training step {local_step}/{TOTAL_STEPS} "
            f"(loss={loss:.4f})"
        )

        if local_step % SAVE_EVERY == 0:
            gs = global_step_for_worker(worker_id, local_step)
            with runtime_lock:
                message = runtime.enqueue_worker_pickle_checkpoint_via_file(
                    worker_id, local_step, build_payload(worker_id, local_step)
                )
                enqueued_steps.append(gs)
            print(
                f"worker {worker_id} enqueued checkpoint "
                f"local_step={local_step} global_step={gs}: {message}"
            )

        time.sleep(0.02)

    print(f"worker {worker_id} finished all {TOTAL_STEPS} steps")
    return None


def main() -> None:
    print("Faultline worker simulation (3 workers, shared async runtime)\n")
    print(
        f"Global step encoding: worker_id * {WORKER_STEP_SCALE:,} + local_step\n"
        "Rust metadata stores worker_id and local_step explicitly.\n"
    )

    enqueued_steps: list[int] = []
    runtime_lock = threading.Lock()

    with AsyncPersistentRuntime(
        runtime_dir=str(RUNTIME_DIR), queue_capacity=QUEUE_CAPACITY
    ) as runtime:
        print(f"Started serve-async (queue_capacity={QUEUE_CAPACITY})\n")
        print("=== Phase 1: workers 0, 1, 2 run (worker 1 will crash) ===\n")

        threads: list[threading.Thread] = []
        for worker_id in range(NUM_WORKERS):
            crash_at = CRASH_AT_LOCAL_STEP if worker_id == CRASH_WORKER_ID else None
            thread = threading.Thread(
                target=run_worker,
                args=(worker_id, runtime, runtime_lock, enqueued_steps),
                kwargs={"crash_at_local_step": crash_at},
                name=f"worker-{worker_id}",
            )
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        print("\n=== Phase 2: wait for all enqueued checkpoints to commit ===\n")
        wait_until_committed(runtime, runtime_lock, enqueued_steps)
        print(f"All {len(enqueued_steps)} enqueued checkpoints are Committed.\n")

        print("=== Phase 3: worker 1 latest checkpoint via service API ===\n")
        with runtime_lock:
            entry = runtime.latest_checkpoint_for_worker(CRASH_WORKER_ID)
        if entry is None:
            raise RuntimeError("No checkpoint found for worker 1")

        resume_local_step = int(entry["local_step"]) + 1
        print(
            f"worker 1 latest checkpoint: global_step={entry['step']}, "
            f"worker_id={entry.get('worker_id')}, local_step={entry.get('local_step')}, "
            f"path={entry['path']}"
        )
        print(f"worker 1 resuming from local step {resume_local_step}\n")

        print("=== Phase 4: restart worker 1 until step 20 ===\n")
        resume_enqueued: list[int] = []
        run_worker(
            CRASH_WORKER_ID,
            runtime,
            runtime_lock,
            resume_enqueued,
            start_local_step=resume_local_step,
        )
        enqueued_steps.extend(resume_enqueued)

        print("\n=== Phase 5: wait for resume checkpoints to commit ===\n")
        wait_until_committed(runtime, runtime_lock, resume_enqueued)
        print(f"Resume enqueues ({len(resume_enqueued)}) are Committed.\n")

        print("=== Phase 6: prune to keep latest 1 checkpoint per worker ===\n")
        with runtime_lock:
            prune_message = runtime.prune_per_worker(1)
        print(prune_message)
        print("\nRemaining latest checkpoint per worker:")
        for worker_id in range(NUM_WORKERS):
            with runtime_lock:
                entry = runtime.latest_checkpoint_for_worker(worker_id)
            if entry is None:
                print(f"  worker {worker_id}: (none)")
            else:
                print(
                    f"  worker {worker_id}: global_step={entry['step']}, "
                    f"local_step={entry.get('local_step')}, path={entry['path']}"
                )
        print()

        with runtime_lock:
            metrics = runtime.metrics()

    print("=== Final runtime metrics ===")
    for key, value in metrics.items():
        print(f"  {key}: {value}")

    print("\nWorker simulation complete.")


if __name__ == "__main__":
    main()
