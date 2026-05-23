"""
Simulated slow storage benchmark (write_delay_ms = 500).

Compares caller-visible time for:
A. Sync PersistentRuntime file save — blocks on the artificial delay
B. AsyncPersistentRuntime enqueue — returns after queue accept
C. Async time-to-commit — wall time from enqueue until status is Committed

With slow storage, sync save blocks on the delay while async enqueue returns quickly
and persistence finishes in the background.
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import AsyncPersistentRuntime, PersistentRuntime

NUM_SAVES = 5
WRITE_DELAY_MS = 500
STEP_OFFSET = 60_000

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "benchmarks" / "output"
RUNTIME_DIR = REPO_ROOT / "runtime"

NARRATIVE = (
    "With simulated slow storage (write_delay_ms=500), sync save blocks on the delay "
    "while async enqueue returns after accepting the job and persistence finishes "
    "in the background."
)


def build_payload(step: int) -> dict:
    torch.manual_seed(step)
    return {
        "step": step,
        "model_state": {f"t_{i}": torch.randn(32, 32) for i in range(4)},
        "loss": 1.0 / step,
    }


def benchmark_sync_file_saves() -> list[float]:
    runtime = PersistentRuntime(
        runtime_dir=str(RUNTIME_DIR), write_delay_ms=WRITE_DELAY_MS
    )
    runtime.start()
    try:
        timings: list[float] = []
        for index in range(1, NUM_SAVES + 1):
            step = STEP_OFFSET + index
            payload = build_payload(step)

            start = time.perf_counter()
            runtime.save_pickle_checkpoint_via_file(step, payload)
            timings.append((time.perf_counter() - start) * 1000)

        return timings
    finally:
        runtime.shutdown()


def benchmark_async_enqueues_and_commits() -> tuple[list[float], list[float]]:
    runtime = AsyncPersistentRuntime(
        runtime_dir=str(RUNTIME_DIR), write_delay_ms=WRITE_DELAY_MS
    )
    runtime.start()

    enqueue_times_ms: list[float] = []
    commit_times_ms: list[float] = []
    enqueue_starts: dict[int, float] = {}

    try:
        for index in range(1, NUM_SAVES + 1):
            step = STEP_OFFSET + 100 + index
            payload = build_payload(step)

            start = time.perf_counter()
            runtime.enqueue_pickle_checkpoint_via_file(step, payload)
            enqueue_times_ms.append((time.perf_counter() - start) * 1000)
            enqueue_starts[step] = start

        for step in enqueue_starts:
            while True:
                status = runtime.checkpoint_status(step)
                if status == "Committed":
                    commit_times_ms.append(
                        (time.perf_counter() - enqueue_starts[step]) * 1000
                    )
                    break
                if status.startswith("Failed"):
                    raise RuntimeError(f"step {step} failed: {status}")
                time.sleep(0.02)

        return enqueue_times_ms, commit_times_ms
    finally:
        runtime.shutdown()


def summarize(label: str, timings: list[float]) -> dict:
    average = sum(timings) / len(timings)
    total = sum(timings)
    print(f"{label} average: {average:.2f} ms")
    print(f"{label} total: {total:.2f} ms")
    return {
        "label": label,
        "timings_ms": timings,
        "average_ms": average,
        "total_ms": total,
    }


def write_results(
    sync: dict,
    async_enqueue: dict,
    async_commit: dict,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload(1)
    pickled_len = len(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))

    results = {
        "write_delay_ms": WRITE_DELAY_MS,
        "num_saves": NUM_SAVES,
        "pickled_payload_bytes": pickled_len,
        "narrative": NARRATIVE,
        "sync_persistent_file": sync,
        "async_enqueue": async_enqueue,
        "async_time_to_commit": async_commit,
    }

    json_path = OUTPUT_DIR / "slow_storage_benchmark_results.json"
    summary_path = OUTPUT_DIR / "slow_storage_benchmark_summary.txt"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = [
        "Faultline slow storage benchmark",
        "",
        NARRATIVE,
        "",
        f"Simulated write delay: {WRITE_DELAY_MS} ms per save",
        f"Number of saves/enqueues: {NUM_SAVES}",
        f"Pickled payload size: {pickled_len} bytes",
        "",
        f"Average sync caller wait: {sync['average_ms']:.2f} ms",
        f"Average async enqueue caller wait: {async_enqueue['average_ms']:.2f} ms",
        f"Average async time-to-commit: {async_commit['average_ms']:.2f} ms",
        "",
        f"Total sync caller wait: {sync['total_ms']:.2f} ms",
        f"Total async enqueue caller wait: {async_enqueue['total_ms']:.2f} ms",
        f"Total async time-to-commit (max per step): {async_commit['total_ms']:.2f} ms",
        "",
        f"JSON results: {json_path}",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nWrote results under {OUTPUT_DIR}")
    print(f"Summary: {summary_path}")
    return summary_path


def main() -> None:
    print("Faultline slow storage benchmark\n")
    print(NARRATIVE)
    print(f"\nwrite_delay_ms = {WRITE_DELAY_MS}\n")

    print("=== A. Sync PersistentRuntime file save ===")
    sync_summary = summarize("sync caller wait", benchmark_sync_file_saves())
    print()

    print("=== B. Async enqueue + C. time-to-commit ===")
    enqueue_timings, commit_timings = benchmark_async_enqueues_and_commits()
    async_enqueue_summary = summarize("async enqueue caller wait", enqueue_timings)
    print()
    async_commit_summary = summarize("async time-to-commit", commit_timings)
    print()

    write_results(sync_summary, async_enqueue_summary, async_commit_summary)


if __name__ == "__main__":
    main()
