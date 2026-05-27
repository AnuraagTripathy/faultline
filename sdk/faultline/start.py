"""Friendly entry point for Faultline Cloud runs."""

from __future__ import annotations

from typing import Any

from faultline.cloud_run import CloudRun
from faultline.run import init

DEFAULT_API_KEY = "fl_dev_local"
DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_PROJECT = "default"


def start(
    run_name: str,
    *,
    project: str = DEFAULT_PROJECT,
    api_key: str = DEFAULT_API_KEY,
    base_url: str = DEFAULT_BASE_URL,
    tags: list[str] | None = None,
    resume_if_available: bool = False,
    model: Any | None = None,
    optimizer: Any | None = None,
) -> CloudRun:
    """
    Start a cloud training run (alias for ``init(..., mode="cloud")``).

    Example::

        run = faultline.start(
            "my-run",
            project="my-project",
            api_key="fl_dev_local",
        )
        run.log(loss=0.5, step=1)
    """
    run = init(
        project=project,
        run_name=run_name,
        mode="cloud",
        api_key=api_key,
        base_url=base_url,
        tags=tags,
    )
    if not isinstance(run, CloudRun):
        raise TypeError("start() requires cloud mode")
    if resume_if_available:
        run._initial_resume_step = run.restore_latest(  # type: ignore[attr-defined]
            model=model,
            optimizer=optimizer,
        )
    return run


def attach(
    run_id: str,
    *,
    api_key: str = DEFAULT_API_KEY,
    base_url: str = DEFAULT_BASE_URL,
) -> CloudRun:
    """Resume an existing cloud run by id (loads checkpoints from that run)."""
    return CloudRun.attach(run_id, api_key=api_key, base_url=base_url)
