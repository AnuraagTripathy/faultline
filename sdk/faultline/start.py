"""Friendly entry point for Faultline Cloud runs."""

from __future__ import annotations

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
    return run
