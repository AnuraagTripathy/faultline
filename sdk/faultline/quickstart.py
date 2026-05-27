"""Beginner-friendly Faultline Cloud helpers."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from faultline.cloud_run import CloudRun
from faultline.start import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_PROJECT, start


def _resolve_api_key(api_key: str | None) -> str:
    return (api_key or os.environ.get("FAULTLINE_API_KEY") or DEFAULT_API_KEY).strip()


def _resolve_base_url(base_url: str | None) -> str:
    return (
        base_url
        or os.environ.get("FAULTLINE_API_URL")
        or os.environ.get("FAULTLINE_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def quickstart(
    project: str = "demo",
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    run_name: str | None = None,
    resume_if_available: bool = False,
    model: Any | None = None,
    optimizer: Any | None = None,
) -> CloudRun:
    """
    Start a cloud run with sensible defaults for first-time users.

    Auto-generates a run name when omitted. Set ``FAULTLINE_API_KEY`` in the environment
    or pass ``api_key`` explicitly.
    """
    name = run_name or f"quickstart-{uuid.uuid4().hex[:8]}"
    run = start(
        name,
        project=project,
        api_key=_resolve_api_key(api_key),
        base_url=_resolve_base_url(base_url),
        tags=["quickstart", "sdk-v20"],
        resume_if_available=resume_if_available,
        model=model,
        optimizer=optimizer,
    )
    return run


def log_progress(
    run: CloudRun,
    step: int,
    *,
    loss: float | None = None,
    **metrics: float,
) -> None:
    """Log training metrics plus lightweight system hints."""
    payload: dict[str, float] = dict(metrics)
    if loss is not None:
        payload["loss"] = float(loss)
    payload.setdefault("progress_pct", min(100.0, float(step)))
    run.log(step=step, **payload)


def training_loop(
    run: CloudRun,
    start_step: int,
    max_steps: int,
    *,
    step_fn: Any,
    checkpoint_every: int = 25,
    sleep_s: float = 0.0,
) -> None:
    """
    Minimal training loop helper: ``step_fn(step) -> dict`` returns metric kwargs for ``run.log``.
    """
    for step in range(start_step, max_steps):
        metrics = step_fn(step) or {}
        if isinstance(metrics, dict):
            run.log(step=step, **{k: float(v) for k, v in metrics.items()})
        if checkpoint_every > 0 and step > 0 and step % checkpoint_every == 0:
            if hasattr(step_fn, "__self__"):
                run.save(step=step)
        if sleep_s > 0:
            time.sleep(sleep_s)
    run.complete()
