"""
Compare caller-visible latency for checkpoint persistence paths:

1. blocking torch.save() — full disk persistence before return
2. sync PersistentRuntime.save_pickle_checkpoint_via_file() — blocks until saved
3. async AsyncPersistentRuntime.enqueue_pickle_checkpoint_via_file() — returns after queue accept

Async enqueue measures caller stall time, not total persistence time.
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
STEP_OFFSET = 50_000

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "benchmarks" / "output"
BLOCKING_DIR = OUTPUT_DIR / "async_blocking_torch_save"
RUNTIME_DIR = REPO_ROOT / "runtime"

NOTE = (
    "Async enqueue timings measure caller stall (queue accept + temp file write), "
    "not total time until checkpoints are committed to disk."
)


def build_payload(step: int) -> dict:
    torch.manual_seed(step)
    return {
        "model_state": {
            f"tensor_{index}": torch.randn(128, 128) for index in range(16)
        },
        "optimizer_state": {"type": "adam", "lr": 0.001, "step": step},
        "step": step,
        "loss": 1.0 / (step + 1),
    }


def benchmark_blocking_saves() -> list[float]:
    BLOCKING_DIR.mkdir(parents=True, exist_ok=True)
    timings: list[float] = []

    for index in range(1, NUM_SAVES + 1):
        step = STEP_OFFSET + index
        payload = build_payload(step)
        path = BLOCKING_DIR / f"checkpoint_{step}.pt"

        start = time.perf_counter()
        torch.save(payload, path)
        timings.append((time.perf_counter() - start) * 1000)

    return timings


def benchmark_sync_file_saves() -> tuple[float, list[float]]:
    start = time.perf_counter()
    runtime = PersistentRuntime(runtime_dir=str(RUNTIME_DIR))
    runtime.start()
    startup_ms = (time.perf_counter() - start) * 1000

    try:
        timings: list[float] = []
        for index in range(1, NUM_SAVES + 1):
            step = STEP_OFFSET + 100 + index
            payload = build_payload(step)

            start = time.perf_counter()
            runtime.save_pickle_checkpoint_via_file(step, payload)
            timings.append((time.perf_counter() - start) * 1000)

        return startup_ms, timings
    finally:
        runtime.shutdown()


def benchmark_async_enqueues() -> tuple[float, list[float]]:
    runtime = AsyncPersistentRuntime(runtime_dir=str(RUNTIME_DIR))
    start = time.perf_counter()
    runtime.start()
    startup_ms = (time.perf_counter() - start) * 1000

    try:
        timings: list[float] = []
        for index in range(1, NUM_SAVES + 1):
            step = STEP_OFFSET + 200 + index
            payload = build_payload(step)

            start = time.perf_counter()
            runtime.enqueue_pickle_checkpoint_via_file(step, payload)
            timings.append((time.perf_counter() - start) * 1000)

        return startup_ms, timings
    finally:
        runtime.shutdown()


def summarize(label: str, timings: list[float], *, startup_ms: float = 0.0) -> dict:
    average = sum(timings) / len(timings)
    total = sum(timings)
    print(f"{label} average: {average:.2f} ms")
    print(f"{label} total: {total:.2f} ms")
    if startup_ms:
        print(f"{label} startup (excluded from per-call average): {startup_ms:.2f} ms")
    return {
        "label": label,
        "timings_ms": timings,
        "average_ms": average,
        "total_ms": total,
        "startup_ms": startup_ms,
    }


def write_results(
    blocking: dict,
    sync_file: dict,
    async_enqueue: dict,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload(0)
    pickled_len = len(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))

    results = {
        "num_saves": NUM_SAVES,
        "pickled_payload_bytes": pickled_len,
        "note": NOTE,
        "blocking_torch_save": blocking,
        "sync_persistent_file": sync_file,
        "async_enqueue": async_enqueue,
    }

    json_path = OUTPUT_DIR / "async_checkpoint_benchmark_results.json"
    summary_path = OUTPUT_DIR / "async_checkpoint_benchmark_summary.txt"

    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    summary_lines = [
        "Faultline async checkpoint benchmark",
        "",
        NOTE,
        "",
        f"Number of saves/enqueues per approach: {NUM_SAVES}",
        f"Pickled payload size: {pickled_len} bytes",
        "",
        f"Average torch.save time: {blocking['average_ms']:.2f} ms",
        f"Average sync file save time: {sync_file['average_ms']:.2f} ms",
        f"Average async enqueue time: {async_enqueue['average_ms']:.2f} ms",
        "",
        f"Total torch.save time: {blocking['total_ms']:.2f} ms",
        f"Total sync file save time: {sync_file['total_ms']:.2f} ms",
        f"Total async enqueue time: {async_enqueue['total_ms']:.2f} ms",
        "",
        f"Async service startup (excluded): {async_enqueue.get('startup_ms', 0):.2f} ms",
        "",
        f"JSON results: {json_path}",
    ]
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"\nWrote results under {OUTPUT_DIR}")
    print(f"Summary: {summary_path}")
    return summary_path


def main() -> None:
    print("Faultline async checkpoint benchmark\n")
    print(NOTE)
    print()

    payload = build_payload(0)
    print(f"Pickled payload size: {len(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))} bytes\n")

    print("=== 1. Blocking torch.save (full persistence) ===")
    blocking_summary = summarize("torch.save", benchmark_blocking_saves())
    print()

    print("=== 2. Sync PersistentRuntime file transport ===")
    sync_startup_ms, sync_timings = benchmark_sync_file_saves()
    sync_summary = summarize(
        "sync file save",
        sync_timings,
        startup_ms=sync_startup_ms,
    )
    print()

    print("=== 3. Async enqueue (caller stall only) ===")
    async_startup_ms, async_timings = benchmark_async_enqueues()
    async_summary = summarize(
        "async enqueue",
        async_timings,
        startup_ms=async_startup_ms,
    )
    print()

    write_results(blocking_summary, sync_summary, async_summary)


if __name__ == "__main__":
    main()
