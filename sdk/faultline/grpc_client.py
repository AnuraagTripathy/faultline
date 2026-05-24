"""gRPC client for the Faultline async checkpoint service."""

from __future__ import annotations

import os
import pickle
import subprocess
import tempfile
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator

import grpc

from faultline.grpc.faultline_pb2 import (
    CheckpointChunk,
    EnqueueWorkerBytesRequest,
    EnqueueWorkerFromFileRequest,
    LatestForWorkerRequest,
    MetricsRequest,
    ShutdownRequest,
    StatusRequest,
)
from faultline.grpc.faultline_pb2_grpc import FaultlineServiceStub
from faultline.runtime import global_step_for_worker, resolve_runtime_dir


def build_serve_grpc_command(
    addr: str,
    *,
    runtime_dir: str | None = None,
    binary_path: str | None = None,
    queue_capacity: int | None = None,
    write_delay_ms: int = 0,
) -> list[str]:
    """Build argv to start `serve-grpc` via release binary or `cargo run`."""
    if binary_path is not None:
        command = [str(Path(binary_path).resolve()), "serve-grpc", "--addr", addr]
    elif runtime_dir is not None:
        command = ["cargo", "run", "--", "serve-grpc", "--addr", addr]
    else:
        raise ValueError("Either runtime_dir or binary_path is required to start serve-grpc")

    if queue_capacity is not None:
        command.extend(["--queue-capacity", str(queue_capacity)])
    if write_delay_ms > 0:
        command.extend(["--write-delay-ms", str(write_delay_ms)])
    return command


def default_release_binary_path(runtime_dir: str | Path) -> Path:
    """Default release binary location under a runtime crate directory."""
    base = Path(runtime_dir) / "target" / "release"
    name = "runtime.exe" if os.name == "nt" else "runtime"
    return base / name


def checkpoint_chunk_count(payload_size: int, chunk_size: int) -> int:
    """Number of CheckpointChunk messages needed for a payload of given size."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if payload_size == 0:
        return 1
    return (payload_size + chunk_size - 1) // chunk_size


def iter_checkpoint_chunks(
    worker_id: int,
    local_step: int,
    data: bytes,
    chunk_size: int,
) -> Iterator[CheckpointChunk]:
    """Yield CheckpointChunk messages for a client-streaming enqueue."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    global_step = global_step_for_worker(worker_id, local_step)
    offset = 0
    chunk_index = 0

    while True:
        end = min(offset + chunk_size, len(data))
        chunk = data[offset:end]
        is_last = end >= len(data)
        yield CheckpointChunk(
            worker_id=worker_id,
            local_step=local_step,
            step=global_step,
            chunk_index=chunk_index,
            data=chunk,
            is_last=is_last,
        )
        if is_last:
            break
        offset = end
        chunk_index += 1


def _require_ok(response: Any, field: str = "error") -> None:
    if not response.ok:
        raise RuntimeError(getattr(response, field) or "unknown gRPC error")


class GrpcAsyncRuntime:
    """Python client for Faultline `serve-grpc` (async checkpoint queue over gRPC)."""

    def __init__(
        self,
        runtime_dir: str = "../runtime",
        *,
        binary_path: str | None = None,
        addr: str = "127.0.0.1:50051",
        queue_capacity: int | None = 16,
        write_delay_ms: int = 0,
        start_server: bool = True,
    ) -> None:
        self.runtime_dir = resolve_runtime_dir(runtime_dir)
        self.binary_path = str(Path(binary_path).resolve()) if binary_path else None
        self.addr = addr
        self.queue_capacity = queue_capacity
        self.write_delay_ms = write_delay_ms
        self.start_server = start_server
        self._process: subprocess.Popen[str] | None = None
        self._channel: grpc.Channel | None = None
        self._stub: FaultlineServiceStub | None = None
        self._shutdown_done = False

    def start(self) -> None:
        if self._stub is not None:
            return

        self._shutdown_done = False
        if self.start_server:
            self._start_server_process()

        self._channel = grpc.insecure_channel(self.addr)
        deadline = time.time() + 30.0
        while time.time() < deadline:
            try:
                grpc.channel_ready_future(self._channel).result(timeout=1.0)
                break
            except grpc.FutureTimeoutError:
                if self._process is not None and self._process.poll() is not None:
                    raise RuntimeError("Faultline gRPC server exited before becoming ready")
        else:
            raise RuntimeError(f"gRPC channel not ready at {self.addr}")

        self._stub = FaultlineServiceStub(self._channel)

    def _start_server_process(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return

        if self.binary_path is not None and not Path(self.binary_path).is_file():
            raise FileNotFoundError(
                f"Faultline gRPC binary not found: {self.binary_path}. "
                "Run: cd runtime && cargo build --release"
            )

        command = build_serve_grpc_command(
            self.addr,
            runtime_dir=self.runtime_dir if self.binary_path is None else None,
            binary_path=self.binary_path,
            queue_capacity=self.queue_capacity,
            write_delay_ms=self.write_delay_ms,
        )

        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if self.binary_path is None:
            popen_kwargs["cwd"] = self.runtime_dir

        self._process = subprocess.Popen(command, **popen_kwargs)

    def _stub_or_raise(self) -> FaultlineServiceStub:
        if self._stub is None:
            raise RuntimeError("GrpcAsyncRuntime is not running; call start() first")
        return self._stub

    def enqueue_worker_checkpoint_file(
        self, worker_id: int, local_step: int, global_step: int, file_path: str
    ) -> str:
        resolved = str(Path(file_path).resolve())
        response = self._stub_or_raise().EnqueueWorkerFromFile(
            EnqueueWorkerFromFileRequest(
                worker_id=worker_id,
                local_step=local_step,
                step=global_step,
                path=resolved,
            )
        )
        _require_ok(response)
        return response.message or f"queued worker {worker_id} checkpoint local_step {local_step}"

    def enqueue_worker_pickle_checkpoint_via_file(
        self, worker_id: int, local_step: int, payload: object
    ) -> str:
        temp_path: str | None = None
        try:
            data = pickle.dumps(payload)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as handle:
                handle.write(data)
                temp_path = handle.name
            return self.enqueue_worker_checkpoint_file(
                worker_id,
                local_step,
                global_step_for_worker(worker_id, local_step),
                temp_path,
            )
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    def enqueue_worker_pickle_checkpoint_bytes(
        self, worker_id: int, local_step: int, payload: object
    ) -> str:
        data = pickle.dumps(payload)
        global_step = global_step_for_worker(worker_id, local_step)
        response = self._stub_or_raise().EnqueueWorkerBytes(
            EnqueueWorkerBytesRequest(
                worker_id=worker_id,
                local_step=local_step,
                step=global_step,
                data=data,
            )
        )
        _require_ok(response)
        return (
            response.message
            or f"queued worker {worker_id} checkpoint local_step {local_step}"
        )

    def enqueue_worker_pickle_checkpoint_stream(
        self,
        worker_id: int,
        local_step: int,
        payload: object,
        chunk_size: int = 256 * 1024,
    ) -> str:
        data = pickle.dumps(payload)
        chunks = iter_checkpoint_chunks(worker_id, local_step, data, chunk_size)
        response = self._stub_or_raise().EnqueueWorkerBytesStream(chunks)
        _require_ok(response)
        return (
            response.message
            or f"queued worker {worker_id} checkpoint local_step {local_step} (stream)"
        )

    def latest_checkpoint_for_worker(self, worker_id: int) -> dict[str, Any] | None:
        response = self._stub_or_raise().LatestForWorker(
            LatestForWorkerRequest(worker_id=worker_id)
        )
        _require_ok(response)
        if not response.HasField("checkpoint"):
            return None
        entry = response.checkpoint
        return {
            "step": entry.step,
            "path": entry.path,
            "status": entry.status,
            "worker_id": entry.worker_id if entry.HasField("worker_id") else None,
            "local_step": entry.local_step if entry.HasField("local_step") else None,
        }

    def checkpoint_status(self, step: int) -> str:
        response = self._stub_or_raise().Status(StatusRequest(step=step))
        _require_ok(response)
        if not response.status:
            raise RuntimeError(response.error or f"No status for step {step}")
        return response.status

    def metrics(self) -> dict[str, Any]:
        response = self._stub_or_raise().Metrics(MetricsRequest())
        _require_ok(response)
        result: dict[str, Any] = {
            "total_enqueued": response.total_enqueued,
            "total_committed": response.total_committed,
            "total_failed": response.total_failed,
            "total_dropped": response.total_dropped,
            "total_bytes_written": response.total_bytes_written,
            "total_write_time_ms": response.total_write_time_ms,
        }
        if response.HasField("average_write_time_ms"):
            result["average_write_time_ms"] = response.average_write_time_ms
        return result

    def shutdown(self) -> None:
        if self._shutdown_done:
            return

        if self._stub is not None:
            try:
                response = self._stub.Shutdown(ShutdownRequest())
                _require_ok(response)
            except RuntimeError:
                pass

        if self._channel is not None:
            self._channel.close()

        if self._process is not None and self._process.poll() is None:
            try:
                self._process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                self._process.wait(timeout=5)

        self._channel = None
        self._stub = None
        self._process = None
        self._shutdown_done = True

    def __enter__(self) -> "GrpcAsyncRuntime":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.shutdown()
