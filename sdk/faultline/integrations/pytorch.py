"""Lightweight PyTorch-style helpers for Faultline Cloud."""

from __future__ import annotations

from typing import Any

from faultline.cloud_run import CloudRun
from faultline.start import start


class FaultlineCallback:
    """Log metrics and optionally checkpoint on each training step."""

    def __init__(
        self,
        run: CloudRun,
        *,
        model: Any | None = None,
        optimizer: Any | None = None,
        checkpoint_every: int = 100,
        start_step: int = 0,
    ) -> None:
        self.run = run
        self.model = model
        self.optimizer = optimizer
        self.checkpoint_every = max(1, checkpoint_every)
        self.run._step_counter = start_step

    def on_step_end(self, step: int, **metrics: float) -> None:
        """Call after each training step with scalar metrics (e.g. loss=0.5)."""
        self.run.log(step=step, **metrics)
        if step > 0 and step % self.checkpoint_every == 0:
            self.run.save(step=step, model=self.model, optimizer=self.optimizer)

    def complete(self) -> dict[str, Any]:
        return self.run.complete()


def watch_training(
    model: Any,
    optimizer: Any,
    *,
    project: str,
    run_name: str,
    api_key: str = "fl_dev_local",
    base_url: str = "http://127.0.0.1:8080",
    checkpoint_every: int = 100,
    tags: list[str] | None = None,
) -> tuple[CloudRun, FaultlineCallback, int]:
    """
    Start a cloud run, restore the latest checkpoint, and return a step callback.

    Returns ``(run, callback, start_step)`` where ``start_step`` is the step to
    resume from (0 if no checkpoint).
    """
    run = start(
        run_name,
        project=project,
        api_key=api_key,
        base_url=base_url,
        tags=tags,
    )
    resume_step = run.restore_latest(model=model, optimizer=optimizer)
    callback = FaultlineCallback(
        run,
        model=model,
        optimizer=optimizer,
        checkpoint_every=checkpoint_every,
        start_step=resume_step,
    )
    return run, callback, resume_step
