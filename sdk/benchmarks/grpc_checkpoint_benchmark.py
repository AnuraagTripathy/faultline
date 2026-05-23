"""
Compare async enqueue caller latency: stdin/stdout JSON vs gRPC (cargo run vs release binary).

Measures how long the Python caller waits to enqueue (not total persistence time).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import AsyncPersistentRuntime, GrpcAsyncRuntime
from faultline.grpc_client import default_release_binary_path

NUM_ENQUEUES = 5
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
RELEASE_BINARY = default_release_binary_path(RUNTIME_DIR)
GRPC_ADDR_CARGO = "127.0.0.1:50052"
GRPC_ADDR_RELEASE = "127.0.0.1:50053"

NOTE = (
    "Compares caller stall for enqueue_worker_pickle_checkpoint_via_file. "
    "gRPC avoids subprocess stdin/stdout JSON per command; release binary avoids cargo run startup."
)


def build_payload(step: int) -> dict:
    torch.manual_seed(step)
    return {
        "worker_id": 0,
        "local_step": step,
        "tensor": torch.randn(32, 32),
    }


def benchmark_json_transport() -> tuple[float, list[float]]:
    start = time.perf_counter()
    runtime = AsyncPersistentRuntime(runtime_dir=str(RUNTIME_DIR), queue_capacity=16)
    runtime.start()
    startup_ms = (time.perf_counter() - start) * 1000

    timings: list[float] = []
    try:
        for index in range(1, NUM_ENQUEUES + 1):
            local_step = index
            begin = time.perf_counter()
            runtime.enqueue_worker_pickle_checkpoint_via_file(0, local_step, build_payload(local_step))
            timings.append((time.perf_counter() - begin) * 1000)
    finally:
        runtime.shutdown()

    return startup_ms, timings


def benchmark_grpc_cargo() -> tuple[float, list[float]]:
    start = time.perf_counter()
    runtime = GrpcAsyncRuntime(
        runtime_dir=str(RUNTIME_DIR),
        addr=GRPC_ADDR_CARGO,
        queue_capacity=16,
        start_server=True,
    )
    runtime.start()
    startup_ms = (time.perf_counter() - start) * 1000

    timings: list[float] = []
    try:
        for index in range(1, NUM_ENQUEUES + 1):
            local_step = 100 + index
            begin = time.perf_counter()
            runtime.enqueue_worker_pickle_checkpoint_via_file(0, local_step, build_payload(local_step))
            timings.append((time.perf_counter() - begin) * 1000)
    finally:
        runtime.shutdown()

    return startup_ms, timings


def benchmark_grpc_release() -> tuple[float, list[float]] | None:
    if not RELEASE_BINARY.is_file():
        print(
            "Release binary not found. Run cd runtime && cargo build --release "
            "to enable this benchmark path."
        )
        return None

    start = time.perf_counter()
    runtime = GrpcAsyncRuntime(
        binary_path=str(RELEASE_BINARY),
        addr=GRPC_ADDR_RELEASE,
        queue_capacity=16,
        start_server=True,
    )
    runtime.start()
    startup_ms = (time.perf_counter() - start) * 1000

    timings: list[float] = []
    try:
        for index in range(1, NUM_ENQUEUES + 1):
            local_step = 200 + index
            begin = time.perf_counter()
            runtime.enqueue_worker_pickle_checkpoint_via_file(0, local_step, build_payload(local_step))
            timings.append((time.perf_counter() - begin) * 1000)
    finally:
        runtime.shutdown()

    return startup_ms, timings


def summarize(label: str, timings: list[float], *, startup_ms: float = 0.0) -> None:
    average = sum(timings) / len(timings)
    total = sum(timings)
    print(f"{label} average enqueue: {average:.2f} ms")
    print(f"{label} total enqueue: {total:.2f} ms")
    if startup_ms:
        print(f"{label} startup (excluded): {startup_ms:.2f} ms")


def main() -> None:
    print("Faultline transport benchmark: JSON vs gRPC (cargo run vs release binary)\n")
    print(NOTE)
    print()

    print("=== AsyncPersistentRuntime (stdin/stdout JSON) ===")
    json_startup, json_timings = benchmark_json_transport()
    summarize("JSON", json_timings, startup_ms=json_startup)
    print()

    print(f"=== GrpcAsyncRuntime cargo run ({GRPC_ADDR_CARGO}) ===")
    grpc_cargo_startup, grpc_cargo_timings = benchmark_grpc_cargo()
    summarize("gRPC cargo", grpc_cargo_timings, startup_ms=grpc_cargo_startup)
    print()

    print(f"=== GrpcAsyncRuntime release binary ({GRPC_ADDR_RELEASE}) ===")
    release_result = benchmark_grpc_release()
    if release_result is not None:
        release_startup, release_timings = release_result
        summarize("gRPC release", release_timings, startup_ms=release_startup)
        print()

        json_avg = sum(json_timings) / len(json_timings)
        cargo_avg = sum(grpc_cargo_timings) / len(grpc_cargo_timings)
        release_avg = sum(release_timings) / len(release_timings)
        print(
            f"JSON avg: {json_avg:.2f} ms | "
            f"gRPC cargo avg: {cargo_avg:.2f} ms | "
            f"gRPC release avg: {release_avg:.2f} ms"
        )
    else:
        json_avg = sum(json_timings) / len(json_timings)
        cargo_avg = sum(grpc_cargo_timings) / len(grpc_cargo_timings)
        print(f"JSON avg: {json_avg:.2f} ms | gRPC cargo avg: {cargo_avg:.2f} ms")


if __name__ == "__main__":
    main()
