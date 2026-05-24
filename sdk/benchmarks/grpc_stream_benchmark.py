"""
Compare gRPC unary bytes vs client-streaming bytes enqueue latency.

Runs small/medium and larger payloads with the same chunk size for streaming.
"""

from __future__ import annotations

import os
import pickle
import sys
import time
from pathlib import Path

import grpc

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import GrpcAsyncRuntime
from faultline.grpc_client import default_release_binary_path

NUM_ENQUEUES = 3
CHUNK_SIZE = 256 * 1024
RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
RELEASE_BINARY = default_release_binary_path(RUNTIME_DIR)

# (label, num_floats) — float32 tensor bytes ≈ num_floats * 4
PAYLOAD_SIZES = [
    ("small/medium (~32x32 tensor)", 32 * 32),
    ("large (~3 MiB tensor, multi-chunk)", 3 * 256 * 1024),
]

GRPC_ADDR_UNARY = "127.0.0.1:50058"
GRPC_ADDR_STREAM = "127.0.0.1:50059"


def runtime_kwargs(addr: str) -> dict:
    kwargs: dict = {"addr": addr, "queue_capacity": 8, "start_server": True}
    if RELEASE_BINARY.is_file():
        kwargs["binary_path"] = str(RELEASE_BINARY)
    else:
        kwargs["runtime_dir"] = str(RUNTIME_DIR)
    return kwargs


def build_payload(num_floats: int, local_step: int) -> dict:
    torch.manual_seed(local_step)
    return {
        "worker_id": 0,
        "local_step": local_step,
        "tensor": torch.randn(num_floats),
    }


def payload_byte_size(payload: dict) -> int:
    return len(pickle.dumps(payload))


def benchmark_unary(num_floats: int, base_local_step: int) -> list[float] | None:
    runtime = GrpcAsyncRuntime(**runtime_kwargs(GRPC_ADDR_UNARY))
    runtime.start()
    timings: list[float] = []
    try:
        for index in range(1, NUM_ENQUEUES + 1):
            local_step = base_local_step + index
            payload = build_payload(num_floats, local_step)
            begin = time.perf_counter()
            try:
                runtime.enqueue_worker_pickle_checkpoint_bytes(0, local_step, payload)
            except grpc.RpcError as error:
                if error.code() == grpc.StatusCode.OUT_OF_RANGE:
                    return None
                raise
            timings.append((time.perf_counter() - begin) * 1000)
    finally:
        runtime.shutdown()
    return timings


def benchmark_stream(num_floats: int, base_local_step: int) -> list[float]:
    runtime = GrpcAsyncRuntime(**runtime_kwargs(GRPC_ADDR_STREAM))
    runtime.start()
    timings: list[float] = []
    try:
        for index in range(1, NUM_ENQUEUES + 1):
            local_step = base_local_step + 100 + index
            payload = build_payload(num_floats, local_step)
            begin = time.perf_counter()
            runtime.enqueue_worker_pickle_checkpoint_stream(
                0, local_step, payload, chunk_size=CHUNK_SIZE
            )
            timings.append((time.perf_counter() - begin) * 1000)
    finally:
        runtime.shutdown()
    return timings


def avg(timings: list[float]) -> float:
    return sum(timings) / len(timings)


def main() -> None:
    print("Faultline gRPC benchmark: unary bytes vs streaming bytes\n")
    if not RELEASE_BINARY.is_file():
        print(
            "Release binary not found. Using cargo run (build release for steadier numbers):\n"
            "  cd runtime && cargo build --release\n"
        )

    for label_index, (label, num_floats) in enumerate(PAYLOAD_SIZES):
        sample = build_payload(num_floats, 1)
        size_bytes = payload_byte_size(sample)
        print(f"=== {label} ===")
        print(f"payload size (pickled): {size_bytes:,} bytes ({size_bytes / (1024 * 1024):.2f} MiB)")
        print(f"chunk size: {CHUNK_SIZE:,} bytes")
        print()

        unary_timings = benchmark_unary(num_floats, base_local_step=label_index * 1000)
        stream_timings = benchmark_stream(num_floats, base_local_step=label_index * 1000 + 500)

        if unary_timings is None:
            print("unary enqueue latency: N/A (payload exceeds default gRPC 4 MiB message limit)")
        else:
            print(
                f"unary enqueue latency (avg of {NUM_ENQUEUES}): "
                f"{avg(unary_timings):.2f} ms"
            )
        stream_avg = avg(stream_timings)
        print(f"streaming enqueue latency (avg of {NUM_ENQUEUES}): {stream_avg:.2f} ms")

        if unary_timings is not None:
            unary_avg = avg(unary_timings)
            delta = unary_avg - stream_avg
            if delta > 0:
                print(f"streaming faster by {delta:.2f} ms per enqueue\n")
            elif delta < 0:
                print(f"unary faster by {-delta:.2f} ms per enqueue\n")
            else:
                print("same average enqueue latency\n")
        else:
            print("streaming succeeds where unary hits the default message size cap\n")


if __name__ == "__main__":
    main()
