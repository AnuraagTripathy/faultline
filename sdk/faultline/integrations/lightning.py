"""PyTorch Lightning integration for Faultline Cloud."""

from __future__ import annotations

from typing import Any

from faultline.cloud_run import CloudRun
from faultline.start import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_PROJECT, start

try:
    from lightning.pytorch.callbacks import Callback as LightningCallback
except ImportError:
    try:
        from pytorch_lightning.callbacks import Callback as LightningCallback
    except ImportError:  # pragma: no cover
        LightningCallback = object  # type: ignore[misc, assignment]


def _callback_metrics(trainer: Any) -> dict[str, float]:
    logged = getattr(trainer, "callback_metrics", None) or {}
    out: dict[str, float] = {}
    for key, value in dict(logged).items():
        if hasattr(value, "item"):
            try:
                out[str(key)] = float(value.item())
                continue
            except Exception:
                pass
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(key)] = float(value)
    return out


class FaultlineLightningCallback(LightningCallback):
    """Metrics, checkpoints, auto-resume, and lifecycle events for Lightning ``Trainer``."""

    def __init__(
        self,
        *,
        project: str = DEFAULT_PROJECT,
        run_name: str,
        api_key: str = DEFAULT_API_KEY,
        base_url: str = DEFAULT_BASE_URL,
        upload_checkpoints: bool = True,
        auto_resume: bool = True,
        model: Any | None = None,
        optimizer: Any | None = None,
        tags: list[str] | None = None,
    ) -> None:
        if LightningCallback is object:
            raise ImportError(
                "FaultlineLightningCallback requires `pip install lightning` or pytorch-lightning"
            )
        self.project = project
        self.run_name = run_name
        self.api_key = api_key
        self.base_url = base_url
        self.upload_checkpoints = upload_checkpoints
        self.auto_resume = auto_resume
        self.model = model
        self.optimizer = optimizer
        merged = list(tags or [])
        if "integration:lightning" not in merged:
            merged.append("integration:lightning")
        self.tags = merged
        self._run: CloudRun | None = None
        self._start_step = 0

    @property
    def run(self) -> CloudRun:
        if self._run is None:
            raise RuntimeError("Callback has not started training yet")
        return self._run

    def on_train_start(self, trainer: Any, pl_module: Any) -> None:
        self._run = start(
            self.run_name,
            project=self.project,
            api_key=self.api_key,
            base_url=self.base_url,
            tags=self.tags,
        )
        target = self.model if self.model is not None else pl_module
        opt = self.optimizer
        if opt is None and getattr(trainer, "optimizers", None):
            opts = trainer.optimizers
            opt = opts[0] if isinstance(opts, list) and opts else opts
        if self.auto_resume:
            self._start_step = self._run.restore_latest(model=target, optimizer=opt)
            if self._start_step > 0 and hasattr(trainer, "fit_loop"):
                try:
                    trainer.fit_loop.epoch_loop.batch_progress.current.completed = (
                        self._start_step
                    )
                except Exception:
                    pass

    def on_train_batch_end(
        self,
        trainer: Any,
        pl_module: Any,
        outputs: Any,
        batch: Any,
        batch_idx: int,
    ) -> None:
        if self._run is None:
            return
        metrics = _callback_metrics(trainer)
        if not metrics and outputs is not None and hasattr(outputs, "get"):
            loss = outputs.get("loss")
            if hasattr(loss, "item"):
                metrics["loss"] = float(loss.item())
        if metrics:
            step = int(getattr(trainer, "global_step", batch_idx))
            self._run.log(step=step, **metrics)
            max_steps = getattr(trainer, "max_steps", None) or getattr(
                trainer, "estimated_stepping_batches", 0
            )
            if max_steps:
                self._run.log_progress(step=step, total_steps=int(max_steps))

    def on_save_checkpoint(
        self,
        trainer: Any,
        pl_module: Any,
        checkpoint: dict[str, Any],
    ) -> None:
        if not self.upload_checkpoints or self._run is None:
            return
        step = int(getattr(trainer, "global_step", 0))
        target = self.model if self.model is not None else pl_module
        opt = self.optimizer
        if opt is None and getattr(trainer, "optimizers", None):
            opts = trainer.optimizers
            opt = opts[0] if isinstance(opts, list) and opts else opts
        self._run.save(step=step, model=target, optimizer=opt)

    def on_train_end(self, trainer: Any, pl_module: Any) -> None:
        if self._run is not None:
            self._run.complete()

    def on_exception(self, trainer: Any, pl_module: Any, exception: BaseException) -> None:
        if self._run is not None:
            self._run.fail(message=str(exception))
