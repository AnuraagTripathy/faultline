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

    @classmethod
    def attach(
        cls,
        run_id: str,
        *,
        api_key: str,
        base_url: str = "http://127.0.0.1:8080",
    ) -> CloudRun:
        """Connect to an existing cloud run (for resume after crash or Ctrl+C)."""
        client = CloudIngestClient(base_url=base_url, api_key=api_key)
        metadata = client.get_run(run_id)
        project = str(metadata.get("project_name", "default"))
        run_name = str(metadata.get("run_name", run_id))
        return cls(client, project=project, run_name=run_name, metadata=metadata)

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    @property
    def initial_resume_step(self) -> int:
        """Set when ``faultline.start(..., resume_if_available=True)``."""
        return int(getattr(self, "_initial_resume_step", 0))

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

    def log_progress(
        self,
        step: int,
        *,
        total_steps: int = 0,
        **metrics: float,
    ) -> dict[str, Any]:
        """Log metrics plus optional ``progress_pct`` when ``total_steps`` is set."""
        payload = {key: float(value) for key, value in metrics.items()}
        if total_steps > 0:
            payload["progress_pct"] = min(100.0, 100.0 * float(step) / float(total_steps))
        return self.log(step=step, **payload)

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

    def register_launch_command(
        self,
        command: list[str],
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Register how to relaunch this run locally (``subprocess``)."""
        body: dict[str, Any] = {
            "launch_type": "local_command",
            "command": command,
        }
        if working_dir is not None:
            body["working_dir"] = working_dir
        if environment is not None:
            body["environment"] = environment
        return self._client.register_launch_config(self.run_id, body)

    def register_slurm_script(
        self,
        script_path: str,
        *,
        working_dir: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Register a Slurm script path for ``sbatch`` relaunch."""
        body: dict[str, Any] = {
            "launch_type": "slurm_script",
            "script_path": script_path,
        }
        if working_dir is not None:
            body["working_dir"] = working_dir
        if environment is not None:
            body["environment"] = environment
        return self._client.register_launch_config(self.run_id, body)

    def resume(self) -> dict[str, Any]:
        """
        Relaunch this run using stored launch config (manual / API-triggered only).

        Requires a healthy latest checkpoint and a prior
        :meth:`register_launch_command` or :meth:`register_slurm_script`.
        """
        return self._client.resume_run(self.run_id)

    def restore_latest(
        self,
        *,
        model: Any | None = None,
        optimizer: Any | None = None,
    ) -> int:
        """
        Download the latest checkpoint and optionally restore ``model`` / ``optimizer``.

        Returns the step to continue training from (use as loop start), or ``0``
        if no checkpoint exists. Typical pattern::

            start_step = run.restore_latest(model=model, optimizer=optimizer)
            for step in range(start_step, max_steps):
                ...
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

    def recovery(self) -> dict[str, Any]:
        """Fetch crash-to-resume summary (checkpoint age, lost steps, resume snippets)."""
        return self._client.get_recovery(self.run_id)

    def print_resume_instructions(self, recovery: dict[str, Any] | None = None) -> None:
        """Print human-readable resume guidance after a failure or crash."""
        info = recovery if recovery is not None else self.recovery()
        print("=== Faultline recovery ===")
        print(f"Run:        {info.get('project_name')} / {info.get('run_name')} ({info.get('run_id')})")
        print(f"Status:     {info.get('status')}")
        print(f"Badge:      {info.get('recovery_badge')}")
        print(f"Restore:    {info.get('restore_status')}")
        print(f"Recommend:  {info.get('recommendation')}")
        print(f"Last step:  {info.get('latest_step')}")
        print(f"Checkpoint: step {info.get('latest_checkpoint_step')} (health: {info.get('checkpoint_health')})")
        print(f"Lost steps: {info.get('estimated_lost_steps')}")
        if info.get("checkpoint_age_ms") is not None:
            age_s = int(info["checkpoint_age_ms"]) / 1000.0
            print(f"Checkpoint age: {age_s:.1f}s ago")
        print()
        print("Inline restore:")
        print(info.get("inline_restore_snippet", "").rstrip())
        print()
        print("Full resume script:")
        print(info.get("resume_snippet", "").rstrip())
        print()

    def fail(
        self,
        reason: str | None = None,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Mark the run failed and preserve recovery metadata in the event message."""
        text = (reason or message or "run failed").strip()
        ckpt_step = int(self._metadata.get("latest_checkpoint_step", 0))
        if ckpt_step > 0:
            text = (
                f"{text} — resume from checkpoint step {ckpt_step} "
                f"(GET /v1/runs/{self.run_id}/recovery)"
            )
        self._metadata = self._client.log_event(
            self.run_id,
            event_type="faultline.run.failed",
            level="error",
            message=text,
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
