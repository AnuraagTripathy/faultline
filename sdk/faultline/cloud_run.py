"""Cloud-hosted training run (HTTP ingestion, no local checkpoint runtime)."""

from __future__ import annotations

import json
import pickle
import time
import warnings
from typing import Any

from faultline.checkpoint_payload import (
    build_checkpoint_payload,
    restore_checkpoint_into_modules,
)
from faultline.cloud_client import CloudIngestClient


class CloudRun:
    """A Faultline training run backed by the cloud ingestion API."""

    def __init__(
        self,
        client: CloudIngestClient,
        *,
        project: str,
        run_name: str,
        metadata: dict[str, Any],
    ) -> None:
        self._client = client
        self.project = project
        self.run_name = run_name
        self._metadata = dict(metadata)
        self.run_id = str(metadata["run_id"])
        self._step_counter = int(metadata.get("latest_step", 0))

    @classmethod
    def start(
        cls,
        *,
        project: str,
        run_name: str,
        api_key: str,
        base_url: str = "http://127.0.0.1:8080",
        tags: list[str] | None = None,
    ) -> CloudRun:
        client = CloudIngestClient(base_url=base_url, api_key=api_key)
        metadata = client.start_run(project, run_name, tags=tags)
        return cls(client, project=project, run_name=run_name, metadata=metadata)

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def refresh(self) -> dict[str, Any]:
        self._metadata = self._client.get_run(self.run_id)
        return dict(self._metadata)

    def log_metrics(self, metrics: dict[str, float], *, step: int) -> dict[str, Any]:
        self._metadata = self._client.log_metrics(
            self.run_id,
            step=step,
            metrics=metrics,
        )
        self._step_counter = max(self._step_counter, step)
        return dict(self._metadata)

    def log(self, *, step: int | None = None, **metrics: float) -> dict[str, Any]:
        """
        Log training metrics as keyword arguments.

        If ``step`` is omitted, uses an auto-incrementing counter (starts after
        ``latest_step`` from the run metadata).
        """
        if not metrics:
            raise ValueError("log() requires at least one metric keyword")
        resolved_step = step if step is not None else self._next_step()
        return self.log_metrics({key: float(value) for key, value in metrics.items()}, step=resolved_step)

    def _next_step(self) -> int:
        self._step_counter += 1
        return self._step_counter

    def metrics(self, limit: int = 1000) -> list[dict[str, Any]]:
        return self._client.list_metrics(self.run_id, limit=limit)

    def checkpoint(self, payload: object, *, step: int) -> dict[str, Any]:
        """Upload a pickled checkpoint to cloud storage (dev: local filesystem)."""
        data = pickle.dumps(payload)
        meta: dict[str, Any] = {
            "step": step,
            "client_timestamp_ms": int(time.time() * 1000),
        }
        if isinstance(payload, dict):
            meta["payload_keys"] = list(payload.keys())
        result = self._client.upload_checkpoint(
            self.run_id,
            step=step,
            data=data,
            metadata_json=json.dumps(meta),
        )
        self._step_counter = max(self._step_counter, step)
        self.refresh()
        return result

    def save(
        self,
        *,
        step: int,
        model: Any | None = None,
        optimizer: Any | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Upload a checkpoint (friendly alias for :meth:`checkpoint`).

        Detects PyTorch ``state_dict()`` on ``model`` / ``optimizer`` when present.
        """
        payload = build_checkpoint_payload(
            step=step,
            model=model,
            optimizer=optimizer,
            state=state,
        )
        return self.checkpoint(payload, step=step)

    def restore_latest(
        self,
        *,
        model: Any | None = None,
        optimizer: Any | None = None,
    ) -> int:
        """
        Download the latest checkpoint and optionally restore ``model`` / ``optimizer``.

        Returns the checkpoint step, or ``0`` if no checkpoint exists.
        """
        state = self.load_latest_checkpoint_or_none()
        if state is None or not isinstance(state, dict):
            return 0
        step = restore_checkpoint_into_modules(state, model=model, optimizer=optimizer)
        self._step_counter = step
        return step

    def list_checkpoints(self) -> list[dict[str, Any]]:
        return self._client.list_checkpoints(self.run_id)

    def latest_checkpoint(self) -> dict[str, Any]:
        return self._client.latest_checkpoint(self.run_id)

    def download_latest_checkpoint(self) -> bytes:
        return self._client.download_latest_checkpoint(self.run_id)

    def load_latest_checkpoint(self) -> Any:
        """
        Download and unpickle the latest checkpoint.

        Warning: pickle can execute arbitrary code — only load checkpoints you trust.
        """
        warnings.warn(
            "load_latest_checkpoint uses pickle; only load checkpoints you created yourself",
            UserWarning,
            stacklevel=2,
        )
        return pickle.loads(self.download_latest_checkpoint())

    def load_latest_checkpoint_or_none(self) -> Any | None:
        """Return latest checkpoint object, or None if the run has no checkpoints."""
        try:
            return self.load_latest_checkpoint()
        except RuntimeError as error:
            if "404" in str(error) or "no checkpoints" in str(error).lower():
                return None
            raise

    def resume_if_available(self) -> tuple[Any | None, dict[str, Any] | None]:
        """
        If a checkpoint exists, load it and return ``(state, latest_metadata)``.

        Otherwise return ``(None, None)``.
        """
        try:
            meta = self.latest_checkpoint()
        except RuntimeError as error:
            if "404" in str(error) or "no checkpoints" in str(error).lower():
                return None, None
            raise
        state = self.load_latest_checkpoint()
        return state, meta

    def complete(self) -> dict[str, Any]:
        self._metadata = self._client.log_event(
            self.run_id,
            event_type="faultline.run.completed",
            level="info",
            message="run completed",
        )
        return dict(self._metadata)

    def fail(self, message: str = "run failed") -> dict[str, Any]:
        self._metadata = self._client.log_event(
            self.run_id,
            event_type="faultline.run.failed",
            level="error",
            message=message,
        )
        return dict(self._metadata)

    def stop(self) -> dict[str, Any]:
        self._metadata = self._client.log_event(
            self.run_id,
            event_type="faultline.run.stopped",
            level="warn",
            message="run stopped",
        )
        return dict(self._metadata)

    def shutdown(self) -> None:
        """No persistent connection to close for HTTP mode."""
        return None
