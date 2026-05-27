"""Auto-resume helpers for Faultline Cloud runs."""

from __future__ import annotations

from typing import Any

from faultline.cloud_run import CloudRun
from faultline.start import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_PROJECT, attach, start


def auto_resume(
    *,
    project: str = DEFAULT_PROJECT,
    run_name: str | None = None,
    run_id: str | None = None,
    model: Any | None = None,
    optimizer: Any | None = None,
    api_key: str = DEFAULT_API_KEY,
    base_url: str = DEFAULT_BASE_URL,
    tags: list[str] | None = None,
) -> tuple[CloudRun, int]:
    """
    Connect to a run, restore the latest checkpoint if present, and return ``(run, start_step)``.

    Provide ``run_id`` to attach to an existing run (recommended after a crash).
    Provide ``run_name`` to start a new run or use with ``run_id`` for clarity only.
    """
    if run_id:
        run = attach(run_id, api_key=api_key, base_url=base_url)
    else:
        if not run_name:
            raise ValueError("auto_resume requires run_id or run_name")
        run = start(
            run_name,
            project=project,
            api_key=api_key,
            base_url=base_url,
            tags=tags,
        )

    start_step = 0
    try:
        summary = run.recovery()
        if summary.get("has_checkpoint") and summary.get("checkpoint_health") == "ok":
            start_step = run.restore_latest(model=model, optimizer=optimizer)
    except Exception:
        start_step = run.restore_latest(model=model, optimizer=optimizer)

    return run, start_step
