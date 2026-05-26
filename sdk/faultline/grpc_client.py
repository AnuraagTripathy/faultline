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
    ClaimNextShardRequest,
    CompleteRunRequest,
    CompleteShardRequest,
    CreateRunRequest,
    EnqueueWorkerBytesRequest,
    EnqueueWorkerFromFileRequest,
    GetRunRequest,
    GetRuntimeOverviewRequest,
    LatestForWorkerRequest,
    ListDatasetsRequest,
    ListEventsRequest,
    ListRunsRequest,
    ListShardsRequest,
    ListWorkersRequest,
    MetricsRequest,
    RegisterDatasetRequest,
    ReleaseStaleShardsRequest,
    ShutdownRequest,
    StatusRequest,
    UpdateRunMetricsRequest,
    LogRunMetricsRequest,
    ListRunMetricsRequest,
    ListAlertsRequest,
    EvaluateAlertsRequest,
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


def _alert_to_dict(alert: Any) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "rule_id": alert.rule_id,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "run_id": alert.run_id if alert.HasField("run_id") else None,
        "message": alert.message,
        "timestamp_ms": alert.timestamp_ms,
        "event_id": alert.event_id if alert.HasField("event_id") else None,
    }


def _run_metric_point_to_dict(point: Any) -> dict[str, Any]:
    return {
        "run_id": point.run_id,
        "step": point.step,
        "timestamp_ms": point.timestamp_ms,
        "metrics": dict(point.metrics),
    }


def _run_msg_to_dict(run: Any) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "project_name": run.project_name,
        "run_name": run.run_name,
        "created_at_ms": run.created_at_ms,
        "status": run.status,
        "total_workers_seen": run.total_workers_seen,
        "latest_step": run.latest_step,
        "latest_checkpoint_step": run.latest_checkpoint_step,
        "latest_metric_at_ms": run.latest_metric_at_ms,
        "latest_loss": run.latest_loss if run.HasField("latest_loss") else None,
        "tags": list(run.tags),
        "loss": run.loss if run.HasField("loss") else None,
        "learning_rate": run.learning_rate if run.HasField("learning_rate") else None,
        "throughput": run.throughput if run.HasField("throughput") else None,
    }


def _require_ok(response: Any, field: str = "error") -> None:
    if not response.ok:
        raise RuntimeError(getattr(response, field) or "unknown gRPC error")


def _shard_to_dict(shard: Any) -> dict[str, Any]:
    return {
        "shard_id": shard.shard_id,
        "dataset_name": shard.dataset_name,
        "start_sample": shard.start_sample,
        "end_sample": shard.end_sample,
        "status": shard.status,
        "claimed_by": shard.claimed_by if shard.HasField("claimed_by") else None,
        "claimed_at_ms": shard.claimed_at_ms
        if shard.HasField("claimed_at_ms")
        else None,
        "updated_at_ms": shard.updated_at_ms
        if shard.HasField("updated_at_ms")
        else None,
    }


def _shard_view_to_dict(shard: Any) -> dict[str, Any]:
    return {
        "shard_id": shard.shard_id,
        "start": shard.start,
        "end": shard.end,
        "status": shard.status,
        "worker_id": shard.worker_id if shard.HasField("worker_id") else None,
        "updated_at_ms": shard.updated_at_ms
        if shard.HasField("updated_at_ms")
        else None,
    }


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

    def register_dataset(
        self, name: str, total_samples: int, shard_size: int
    ) -> dict[str, Any]:
        response = self._stub_or_raise().RegisterDataset(
            RegisterDatasetRequest(
                name=name,
                total_samples=total_samples,
                shard_size=shard_size,
            )
        )
        _require_ok(response)
        if not response.HasField("dataset"):
            raise RuntimeError("RegisterDataset returned no dataset metadata")
        dataset = response.dataset
        return {
            "name": dataset.name,
            "total_samples": dataset.total_samples,
            "shard_size": dataset.shard_size,
            "total_shards": dataset.total_shards,
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        response = self._stub_or_raise().ListDatasets(ListDatasetsRequest())
        _require_ok(response)
        return [
            {
                "name": dataset.name,
                "total_samples": dataset.total_samples,
                "shard_size": dataset.shard_size,
                "total_shards": dataset.total_shards,
            }
            for dataset in response.datasets
        ]

    def claim_next_shard(
        self, worker_id: int, dataset_name: str
    ) -> dict[str, Any] | None:
        response = self._stub_or_raise().ClaimNextShard(
            ClaimNextShardRequest(worker_id=worker_id, dataset_name=dataset_name)
        )
        _require_ok(response)
        if not response.claimed or not response.HasField("shard"):
            return None
        return _shard_to_dict(response.shard)

    def complete_shard(
        self, worker_id: int, dataset_name: str, shard_id: int
    ) -> dict[str, Any]:
        response = self._stub_or_raise().CompleteShard(
            CompleteShardRequest(
                worker_id=worker_id,
                dataset_name=dataset_name,
                shard_id=shard_id,
            )
        )
        _require_ok(response)
        if not response.HasField("shard"):
            raise RuntimeError("CompleteShard returned no shard metadata")
        return _shard_to_dict(response.shard)

    def release_stale_shards(self, timeout_ms: int) -> int:
        response = self._stub_or_raise().ReleaseStaleShards(
            ReleaseStaleShardsRequest(timeout_ms=timeout_ms)
        )
        _require_ok(response)
        return int(response.released_count)

    def get_runtime_overview(self) -> dict[str, Any]:
        response = self._stub_or_raise().GetRuntimeOverview(
            GetRuntimeOverviewRequest()
        )
        _require_ok(response)
        async_metrics: dict[str, Any] = {}
        if response.HasField("async_metrics"):
            metrics = response.async_metrics
            async_metrics = {
                "total_enqueued": metrics.total_enqueued,
                "total_committed": metrics.total_committed,
                "total_failed": metrics.total_failed,
                "total_dropped": metrics.total_dropped,
                "total_bytes_written": metrics.total_bytes_written,
                "total_retries": metrics.total_retries,
                "total_permanent_failures": metrics.total_permanent_failures,
            }
            if metrics.HasField("average_write_time_ms"):
                async_metrics["average_write_time_ms"] = metrics.average_write_time_ms

        return {
            "total_datasets": response.total_datasets,
            "total_shards": response.total_shards,
            "pending_shards": response.pending_shards,
            "claimed_shards": response.claimed_shards,
            "completed_shards": response.completed_shards,
            "failed_shards": response.failed_shards,
            "total_checkpoints": response.total_checkpoints,
            "workers_seen": response.workers_seen,
            "async_metrics": async_metrics,
        }

    def list_workers(self) -> list[dict[str, Any]]:
        response = self._stub_or_raise().ListWorkers(ListWorkersRequest())
        _require_ok(response)
        workers: list[dict[str, Any]] = []
        for worker in response.workers:
            workers.append(
                {
                    "worker_id": worker.worker_id,
                    "latest_checkpoint_step": worker.latest_checkpoint_step
                    if worker.HasField("latest_checkpoint_step")
                    else None,
                    "latest_local_step": worker.latest_local_step
                    if worker.HasField("latest_local_step")
                    else None,
                    "committed_checkpoints": worker.committed_checkpoints,
                    "claimed_shards": worker.claimed_shards,
                    "completed_shards": worker.completed_shards,
                }
            )
        return workers

    def list_shards(
        self, dataset_name: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        request = ListShardsRequest(dataset_name=dataset_name)
        if status is not None:
            request.status = status
        response = self._stub_or_raise().ListShards(request)
        _require_ok(response)
        return [_shard_view_to_dict(shard) for shard in response.shards]

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        response = self._stub_or_raise().ListEvents(
            ListEventsRequest(limit=max(1, limit))
        )
        _require_ok(response)
        events: list[dict[str, Any]] = []
        for event in response.events:
            events.append(
                {
                    "event_id": event.event_id,
                    "timestamp_ms": event.timestamp_ms,
                    "level": event.level,
                    "event_type": event.event_type,
                    "worker_id": event.worker_id if event.HasField("worker_id") else None,
                    "dataset_name": event.dataset_name
                    if event.HasField("dataset_name")
                    else None,
                    "shard_id": event.shard_id if event.HasField("shard_id") else None,
                    "step": event.step if event.HasField("step") else None,
                    "message": event.message,
                }
            )
        return events

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
            "total_retries": response.total_retries,
            "total_permanent_failures": response.total_permanent_failures,
        }
        if response.HasField("average_write_time_ms"):
            result["average_write_time_ms"] = response.average_write_time_ms
        return result

    def create_run(
        self,
        project_name: str,
        run_name: str,
        *,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        response = self._stub_or_raise().CreateRun(
            CreateRunRequest(
                project_name=project_name,
                run_name=run_name,
                tags=tags or [],
            )
        )
        _require_ok(response)
        return _run_msg_to_dict(response.run)

    def list_runs(self) -> list[dict[str, Any]]:
        response = self._stub_or_raise().ListRuns(ListRunsRequest())
        _require_ok(response)
        return [_run_msg_to_dict(run) for run in response.runs]

    def get_run(self, run_id: str) -> dict[str, Any]:
        response = self._stub_or_raise().GetRun(GetRunRequest(run_id=run_id))
        _require_ok(response)
        return _run_msg_to_dict(response.run)

    def attach_worker_to_run(self, run_id: str, worker_id: int) -> dict[str, Any]:
        current = self.get_run(run_id)
        return self.update_run_metrics(
            run_id,
            latest_step=int(current["latest_step"]),
            worker_id=worker_id,
        )

    def update_run_metrics(
        self,
        run_id: str,
        *,
        latest_step: int,
        latest_loss: float | None = None,
        loss: float | None = None,
        learning_rate: float | None = None,
        throughput: float | None = None,
        worker_id: int | None = None,
        latest_checkpoint_step: int | None = None,
    ) -> dict[str, Any]:
        request = UpdateRunMetricsRequest(
            run_id=run_id,
            latest_step=latest_step,
        )
        if latest_loss is not None:
            request.latest_loss = latest_loss
        if loss is not None:
            request.loss = loss
        if learning_rate is not None:
            request.learning_rate = learning_rate
        if throughput is not None:
            request.throughput = throughput
        if worker_id is not None:
            request.worker_id = worker_id
        if latest_checkpoint_step is not None:
            request.latest_checkpoint_step = latest_checkpoint_step

        response = self._stub_or_raise().UpdateRunMetrics(request)
        _require_ok(response)
        return _run_msg_to_dict(response.run)

    def log_run_metrics(
        self,
        run_id: str,
        *,
        step: int,
        metrics: dict[str, float],
        worker_id: int | None = None,
    ) -> dict[str, Any]:
        request = LogRunMetricsRequest(run_id=run_id, step=step, metrics=metrics)
        if worker_id is not None:
            request.worker_id = worker_id
        response = self._stub_or_raise().LogRunMetrics(request)
        _require_ok(response)
        return _run_msg_to_dict(response.run)

    def list_run_metrics(
        self, run_id: str, *, limit: int = 1000
    ) -> list[dict[str, Any]]:
        response = self._stub_or_raise().ListRunMetrics(
            ListRunMetricsRequest(run_id=run_id, limit=max(1, limit))
        )
        _require_ok(response)
        return [_run_metric_point_to_dict(point) for point in response.points]

    def list_alerts(self) -> dict[str, Any]:
        """Return the last evaluated alerts without re-scanning."""
        response = self._stub_or_raise().ListAlerts(ListAlertsRequest())
        _require_ok(response)
        return {
            "alerts": [_alert_to_dict(alert) for alert in response.alerts],
            "active_count": int(response.active_count),
        }

    def evaluate_alerts(self) -> dict[str, Any]:
        """Scan runs, metrics, and events; refresh in-memory alerts."""
        response = self._stub_or_raise().EvaluateAlerts(EvaluateAlertsRequest())
        _require_ok(response)
        return {
            "alerts": [_alert_to_dict(alert) for alert in response.alerts],
            "active_count": int(response.active_count),
        }

    def complete_run(
        self,
        run_id: str,
        *,
        status: str = "completed",
        message: str | None = None,
    ) -> dict[str, Any]:
        request = CompleteRunRequest(run_id=run_id, status=status)
        if message is not None:
            request.message = message
        response = self._stub_or_raise().CompleteRun(request)
        _require_ok(response)
        return _run_msg_to_dict(response.run)

    def shutdown(self) -> None:
        if self._shutdown_done:
            return

        # Only stop the server process we spawned; do not send Shutdown to a shared
        # long-lived serve-grpc instance (dashboard / external runtime).
        if self._stub is not None and self.start_server:
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
