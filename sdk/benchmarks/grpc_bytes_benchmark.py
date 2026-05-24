"""
Compare gRPC enqueue latency: temp-file path vs inline bytes transport.

Uses the same payload size as grpc_checkpoint_benchmark (32x32 tensor pickle).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import GrpcAsyncRuntime
from faultline.grpc_client import default_release_binary_path

NUM_ENQUEUES = 5
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
RELEASE_BINARY = default_release_binary_path(RUNTIME_DIR)
GRPC_ADDR_FILE = "127.0.0.1:50055"
GRPC_ADDR_BYTES = "127.0.0.1:50056"

NOTE = (
    "Compares caller stall for enqueue_worker_pickle_checkpoint_via_file vs "
    "enqueue_worker_pickle_checkpoint_bytes (same payload)."
)


def build_payload(step: int) -> dict:
    torch.manual_seed(step)
    return {
        "worker_id": 0,
        "local_step": step,
        "tensor": torch.randn(32, 32),
    }


def runtime_kwargs(addr: str) -> dict:
    kwargs: dict = {"addr": addr, "queue_capacity": 16, "start_server": True}
    if RELEASE_BINARY.is_file():
        kwargs["binary_path"] = str(RELEASE_BINARY)
    else:
        kwargs["runtime_dir"] = str(RUNTIME_DIR)
    return kwargs


def benchmark_file_transport() -> tuple[float, list[float]]:
    start = time.perf_counter()
    runtime = GrpcAsyncRuntime(**runtime_kwargs(GRPC_ADDR_FILE))
    runtime.start()
    startup_ms = (time.perf_counter() - start) * 1000

    timings: list[float] = []
    try:
        for index in range(1, NUM_ENQUEUES + 1):
            local_step = 300 + index
            begin = time.perf_counter()
            runtime.enqueue_worker_pickle_checkpoint_via_file(
                0, local_step, build_payload(local_step)
            )
            timings.append((time.perf_counter() - begin) * 1000)
    finally:
        runtime.shutdown()

    return startup_ms, timings


def benchmark_bytes_transport() -> tuple[float, list[float]]:
    start = time.perf_counter()
    runtime = GrpcAsyncRuntime(**runtime_kwargs(GRPC_ADDR_BYTES))
    runtime.start()
    startup_ms = (time.perf_counter() - start) * 1000

    timings: list[float] = []
    try:
        for index in range(1, NUM_ENQUEUES + 1):
            local_step = 400 + index
            begin = time.perf_counter()
            runtime.enqueue_worker_pickle_checkpoint_bytes(
                0, local_step, build_payload(local_step)
            )
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
    print("Faultline gRPC benchmark: file path vs bytes transport\n")
    print(NOTE)
    if not RELEASE_BINARY.is_file():
        print(
            "\n(Using cargo run; build release binary for steadier startup: "
            "cd runtime && cargo build --release)\n"
        )
    print()

    print(f"=== gRPC file transport ({GRPC_ADDR_FILE}) ===")
    file_startup, file_timings = benchmark_file_transport()
    summarize("gRPC file", file_timings, startup_ms=file_startup)
    print()

    print(f"=== gRPC bytes transport ({GRPC_ADDR_BYTES}) ===")
    bytes_startup, bytes_timings = benchmark_bytes_transport()
    summarize("gRPC bytes", bytes_timings, startup_ms=bytes_startup)
    print()

    file_avg = sum(file_timings) / len(file_timings)
    bytes_avg = sum(bytes_timings) / len(bytes_timings)
    delta = file_avg - bytes_avg
    print(f"gRPC file avg: {file_avg:.2f} ms | gRPC bytes avg: {bytes_avg:.2f} ms")
    if delta > 0:
        print(f"bytes transport is {delta:.2f} ms faster per enqueue on average")
    elif delta < 0:
        print(f"bytes transport is {-delta:.2f} ms slower per enqueue on average")
    else:
        print("average enqueue latency is the same")


if __name__ == "__main__":
    main()
