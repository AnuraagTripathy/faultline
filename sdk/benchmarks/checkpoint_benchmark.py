"""
Compare checkpoint save latency across four paths:

1. blocking torch.save()
2. one-shot Runtime.save_pickle_checkpoint() (cargo run per save)
3. PersistentRuntime.save_pickle_checkpoint() (JSON/base64 in serve protocol)
4. PersistentRuntime.save_pickle_checkpoint_via_file() (save_from_file)
"""

from __future__ import annotations

import base64
import json
import os
import pickle
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import PersistentRuntime, Runtime

NUM_SAVES = 5
ONE_SHOT_STEP_OFFSET = 10_000
PERSISTENT_JSON_OFFSET = 20_000
PERSISTENT_FILE_OFFSET = 30_000

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "benchmarks" / "output"
BLOCKING_DIR = OUTPUT_DIR / "blocking_torch_save"
RUNTIME_DIR = REPO_ROOT / "runtime"

MAX_ENCODED_CLI_BYTES = 24_000

EXPLANATION = """
Approaches compared:
- torch.save: direct local file write from Python.
- one_shot_runtime: subprocess cargo run per save (CLI --data transport).
- persistent_runtime_json: serve process with JSON/base64 inline data (CLI size limits).
- persistent_runtime_file: serve process with save_from_file (path to temp payload file).

PersistentRuntime per-save timings exclude startup. File transport still writes a
temp file in Python before Rust reads it; it removes JSON/base64 size limits.
""".strip()

NOTE = (
    "File transport simulates a realistic boundary for large payloads. "
    "It may not beat torch.save because Python writes a temp file first. "
    "This is not final gRPC performance."
)


def build_large_payload(step: int) -> dict:
    """Larger payload that exceeds CLI-safe JSON/base64 transport limits."""
    torch.manual_seed(step)
    return {
        "model_state": {
            f"tensor_{index}": torch.randn(128, 128) for index in range(16)
        },
        "optimizer_state": {"type": "adam", "lr": 0.001, "step": step},
        "step": step,
        "loss": 1.0 / (step + 1),
    }


def print_payload_sizes() -> None:
    payload = build_large_payload(0)
    pickled_len = len(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    encoded_len = len(base64.b64encode(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)))
    print(f"Pickled payload size: {pickled_len} bytes")
    print(f"JSON/base64 encoded size: {encoded_len} bytes (CLI limit reference {MAX_ENCODED_CLI_BYTES})")


def benchmark_blocking_saves() -> list[float]:
    BLOCKING_DIR.mkdir(parents=True, exist_ok=True)
    timings: list[float] = []

    for i in range(1, NUM_SAVES + 1):
        payload = build_large_payload(i)
        path = BLOCKING_DIR / f"checkpoint_step_{i:04}.pt"

        start = time.perf_counter()
        torch.save(payload, path)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings.append(elapsed_ms)
        print(f"[torch.save] save {i}: {elapsed_ms:.2f} ms")

    return timings


def payload_exceeds_cli_limit(step: int) -> bool:
    payload = build_large_payload(step)
    encoded_len = len(
        base64.b64encode(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    )
    return encoded_len > MAX_ENCODED_CLI_BYTES


def benchmark_one_shot_saves(runtime: Runtime) -> list[float] | None:
    if payload_exceeds_cli_limit(ONE_SHOT_STEP_OFFSET + 1):
        print(
            "[one-shot Runtime] skipped: payload exceeds CLI --data size limits"
        )
        return None

    timings: list[float] = []

    for i in range(1, NUM_SAVES + 1):
        step = ONE_SHOT_STEP_OFFSET + i
        payload = build_large_payload(step)

        start = time.perf_counter()
        try:
            runtime.save_pickle_checkpoint(step, payload)
        except RuntimeError as error:
            print(f"[one-shot Runtime] save {i} failed: {error}")
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings.append(elapsed_ms)
        print(f"[one-shot Runtime] save {i} (step {step}): {elapsed_ms:.2f} ms")

    return timings


def benchmark_persistent_json_saves() -> tuple[float, list[float]] | None:
    if payload_exceeds_cli_limit(PERSISTENT_JSON_OFFSET + 1):
        print(
            "[PersistentRuntime JSON] skipped: payload exceeds CLI --data size limits"
        )
        return None

    runtime = PersistentRuntime(runtime_dir=str(RUNTIME_DIR))

    startup_start = time.perf_counter()
    runtime.start()
    startup_ms = (time.perf_counter() - startup_start) * 1000.0
    print(
        f"[PersistentRuntime JSON] startup: {startup_ms:.2f} ms "
        "(not included in per-save times)"
    )

    timings: list[float] = []
    try:
        for i in range(1, NUM_SAVES + 1):
            step = PERSISTENT_JSON_OFFSET + i
            payload = build_large_payload(step)

            start = time.perf_counter()
            try:
                runtime.save_pickle_checkpoint(step, payload)
            except RuntimeError as error:
                print(f"[PersistentRuntime JSON] save {i} failed: {error}")
                raise
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            timings.append(elapsed_ms)
            print(f"[PersistentRuntime JSON] save {i} (step {step}): {elapsed_ms:.2f} ms")
    finally:
        runtime.shutdown()

    return startup_ms, timings


def benchmark_persistent_file_saves() -> tuple[float, list[float]]:
    runtime = PersistentRuntime(runtime_dir=str(RUNTIME_DIR))

    startup_start = time.perf_counter()
    runtime.start()
    startup_ms = (time.perf_counter() - startup_start) * 1000.0
    print(
        f"[PersistentRuntime file] startup: {startup_ms:.2f} ms "
        "(not included in per-save times)"
    )

    timings: list[float] = []
    try:
        for i in range(1, NUM_SAVES + 1):
            step = PERSISTENT_FILE_OFFSET + i
            payload = build_large_payload(step)

            start = time.perf_counter()
            runtime.save_pickle_checkpoint_via_file(step, payload)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            timings.append(elapsed_ms)
            print(f"[PersistentRuntime file] save {i} (step {step}): {elapsed_ms:.2f} ms")
    finally:
        runtime.shutdown()

    return startup_ms, timings


def summarize(label: str, timings: list[float], **extra: float) -> dict:
    total_ms = sum(timings)
    average_ms = total_ms / len(timings)
    print(f"{label} average: {average_ms:.2f} ms")
    print(f"{label} total: {total_ms:.2f} ms")
    result = {
        "label": label,
        "timings_ms": timings,
        "average_ms": average_ms,
        "total_ms": total_ms,
    }
    result.update(extra)
    return result


def skipped_summary(label: str, reason: str) -> dict:
    print(f"{label}: skipped ({reason})")
    return {
        "label": label,
        "skipped": True,
        "reason": reason,
        "timings_ms": [],
        "average_ms": 0.0,
        "total_ms": 0.0,
    }


def _format_result_line(
    label: str, result: dict | None, *, total: bool = False
) -> str:
    if result is None or result.get("skipped"):
        return f"{label}: skipped (CLI payload too large)"
    key = "total_ms" if total else "average_ms"
    return f"{label}: {result[key]:.2f} ms"


def _format_startup_line(label: str, result: dict | None) -> str:
    if result is None or result.get("skipped"):
        return f"{label}: skipped"
    return f"{label}: {result.get('startup_ms', 0):.2f} ms"


def write_results(
    blocking: dict,
    one_shot: dict | None,
    persistent_json: dict | None,
    persistent_file: dict,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results_path = OUTPUT_DIR / "checkpoint_benchmark_results.json"

    payload = {
        "note": NOTE,
        "explanation": EXPLANATION,
        "num_saves": NUM_SAVES,
        "torch_save": blocking,
        "one_shot_runtime": one_shot or {"skipped": True},
        "persistent_runtime_json": persistent_json or {"skipped": True},
        "persistent_runtime_file": persistent_file,
    }
    results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary_path = OUTPUT_DIR / "checkpoint_benchmark_summary.txt"
    summary_path.write_text(
        "\n".join(
            [
                "Faultline checkpoint benchmark (four-way)",
                "",
                EXPLANATION,
                "",
                NOTE,
                "",
                f"Number of saves per approach: {NUM_SAVES}",
                "",
                f"Average torch.save time: {blocking['average_ms']:.2f} ms",
                _format_result_line("Average one-shot Runtime time", one_shot),
                _format_result_line("Average PersistentRuntime JSON time", persistent_json),
                f"Average PersistentRuntime file time: {persistent_file['average_ms']:.2f} ms",
                "",
                f"Total torch.save time: {blocking['total_ms']:.2f} ms",
                _format_result_line("Total one-shot Runtime time", one_shot, total=True),
                _format_result_line("Total PersistentRuntime JSON time", persistent_json, total=True),
                f"Total PersistentRuntime file time: {persistent_file['total_ms']:.2f} ms",
                "",
                _format_startup_line("PersistentRuntime JSON startup (excluded)", persistent_json),
                f"PersistentRuntime file startup (excluded): {persistent_file.get('startup_ms', 0):.2f} ms",
                "",
                f"JSON results: {results_path}",
            ]
        ),
        encoding="utf-8",
    )

    return summary_path


def main() -> None:
    print("Faultline checkpoint benchmark (four-way)")
    print(EXPLANATION)
    print()
    print(NOTE)
    print()

    print_payload_sizes()
    print()

    print("=== 1. Blocking torch.save ===")
    blocking_summary = summarize("torch.save", benchmark_blocking_saves())
    print()

    print("=== 2. One-shot Runtime ===")
    one_shot_runtime = Runtime(runtime_dir=str(RUNTIME_DIR))
    one_shot_timings = benchmark_one_shot_saves(one_shot_runtime)
    one_shot_summary = (
        summarize("one-shot Runtime", one_shot_timings)
        if one_shot_timings is not None
        else skipped_summary("one-shot Runtime", "CLI payload too large")
    )
    print()

    print("=== 3. PersistentRuntime JSON/base64 ===")
    json_result = benchmark_persistent_json_saves()
    if json_result is None:
        persistent_json_summary = skipped_summary(
            "PersistentRuntime JSON", "CLI payload too large"
        )
    else:
        json_startup_ms, json_timings = json_result
        persistent_json_summary = summarize(
            "PersistentRuntime JSON",
            json_timings,
            startup_ms=json_startup_ms,
        )
    print()

    print("=== 4. PersistentRuntime file transport ===")
    file_startup_ms, file_timings = benchmark_persistent_file_saves()
    persistent_file_summary = summarize(
        "PersistentRuntime file",
        file_timings,
        startup_ms=file_startup_ms,
    )
    print()

    summary_path = write_results(
        blocking_summary,
        one_shot_summary,
        persistent_json_summary,
        persistent_file_summary,
    )
    print(f"Wrote results under {OUTPUT_DIR}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
