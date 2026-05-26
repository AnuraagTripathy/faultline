"""High-level Faultline training run / session API."""



from __future__ import annotations



import time

from contextlib import contextmanager

from typing import Any, Iterator



from faultline.grpc_client import GrpcAsyncRuntime
from faultline.cloud_run import CloudRun

from faultline.telemetry import (

    build_progress_metrics,

    collect_system_metrics,

    try_collect_system_metrics,

)





class FaultlineRun:

    """A Faultline training run backed by the gRPC runtime."""



    def __init__(

        self,

        client: GrpcAsyncRuntime,

        *,

        project: str,

        run_name: str,

        tags: list[str] | None = None,

        worker_id: int = 0,

    ) -> None:

        self._client = client

        self.project = project

        self.run_name = run_name

        self.worker_id = worker_id

        self._metadata = client.create_run(project, run_name, tags=tags or [])

        self.run_id = self._metadata["run_id"]

        self._client.attach_worker_to_run(self.run_id, worker_id)



    @classmethod

    def start(

        cls,

        *,

        project: str,

        run_name: str,

        tags: list[str] | None = None,

        worker_id: int = 0,

        addr: str = "127.0.0.1:50051",

        runtime_dir: str = "../runtime",

        binary_path: str | None = None,

        start_server: bool = False,

    ) -> FaultlineRun:

        client = GrpcAsyncRuntime(

            runtime_dir=runtime_dir,

            binary_path=binary_path,

            addr=addr,

            start_server=start_server,

        )

        client.start()

        return cls(

            client,

            project=project,

            run_name=run_name,

            tags=tags,

            worker_id=worker_id,

        )



    @property

    def metadata(self) -> dict[str, Any]:

        return dict(self._metadata)



    def refresh(self) -> dict[str, Any]:

        self._metadata = self._client.get_run(self.run_id)

        return dict(self._metadata)



    def log_metrics(self, metrics: dict[str, float], *, step: int) -> dict[str, Any]:

        self._metadata = self._client.log_run_metrics(

            self.run_id,

            step=step,

            metrics=metrics,

            worker_id=self.worker_id,

        )

        return dict(self._metadata)



    def log_progress(

        self,

        step: int,

        *,

        loss: float | None = None,

        learning_rate: float | None = None,

        samples_per_sec: float | None = None,

        step_time_ms: float | None = None,

    ) -> dict[str, Any]:

        """Log training progress scalars (loss, LR, timing, throughput)."""

        metrics = build_progress_metrics(

            loss=loss,

            learning_rate=learning_rate,

            samples_per_sec=samples_per_sec,

            step_time_ms=step_time_ms,

        )

        if not metrics:

            return dict(self._metadata)

        return self.log_metrics(metrics, step=step)



    def log_system_metrics(self, step: int | None = None) -> dict[str, Any] | None:

        """

        Log host/process telemetry (CPU, memory, optional GPU).



        Returns None if psutil is not installed (skipped gracefully).

        """

        payload = try_collect_system_metrics()

        if payload is None:

            return None

        resolved_step = step if step is not None else int(self._metadata.get("latest_step", 0))

        return self.log_metrics(payload, step=resolved_step)



    @contextmanager

    def track_step(

        self,

        step: int,

        *,

        num_samples: int | None = None,

    ) -> Iterator[None]:

        """

        Time a training step and log ``step_time_ms`` (and optional throughput).



        Example::



            with run.track_step(step, num_samples=batch_size):

                loss = train_one_step()

            run.log_progress(step, loss=loss)

        """

        started = time.perf_counter()

        try:

            yield

        finally:

            elapsed_ms = (time.perf_counter() - started) * 1000.0

            samples_per_sec = None

            if num_samples is not None and elapsed_ms > 0:

                samples_per_sec = float(num_samples) / (elapsed_ms / 1000.0)

            self.log_progress(

                step,

                step_time_ms=elapsed_ms,

                samples_per_sec=samples_per_sec,

            )



    def metrics(self, limit: int = 1000) -> list[dict[str, Any]]:

        return self._client.list_run_metrics(self.run_id, limit=limit)



    def checkpoint(self, payload: object, *, step: int) -> str:

        self._client.attach_worker_to_run(self.run_id, self.worker_id)

        message = self._client.enqueue_worker_pickle_checkpoint_bytes(

            self.worker_id,

            step,

            payload,

        )

        self._metadata = self._client.update_run_metrics(

            self.run_id,

            latest_step=step,

            latest_checkpoint_step=step,

            worker_id=self.worker_id,

        )

        return message



    def complete(self) -> dict[str, Any]:

        self._metadata = self._client.complete_run(self.run_id, status="completed")

        return dict(self._metadata)



    def fail(self, message: str = "run failed") -> dict[str, Any]:

        self._metadata = self._client.complete_run(

            self.run_id,

            status="failed",

            message=message,

        )

        return dict(self._metadata)



    def stop(self) -> dict[str, Any]:

        self._metadata = self._client.complete_run(self.run_id, status="stopped")

        return dict(self._metadata)



    def shutdown(self) -> None:

        self._client.shutdown()





def init(
    project: str,
    run_name: str,
    *,
    mode: str = "local",
    tags: list[str] | None = None,
    worker_id: int = 0,
    addr: str = "127.0.0.1:50051",
    runtime_dir: str = "../runtime",
    binary_path: str | None = None,
    start_server: bool = False,
    api_key: str | None = None,
    base_url: str = "http://127.0.0.1:8080",
) -> FaultlineRun | CloudRun:
    """Create and start a Faultline training run (local gRPC or cloud ingestion)."""
    if mode == "cloud":
        if not api_key:
            raise ValueError("mode='cloud' requires api_key")
        return CloudRun.start(
            project=project,
            run_name=run_name,
            api_key=api_key,
            base_url=base_url,
            tags=tags,
        )

    if mode != "local":
        raise ValueError(f"unknown init mode: {mode!r} (use 'local' or 'cloud')")

    return FaultlineRun.start(
        project=project,
        run_name=run_name,
        tags=tags,
        worker_id=worker_id,
        addr=addr,
        runtime_dir=runtime_dir,
        binary_path=binary_path,
        start_server=start_server,
    )


