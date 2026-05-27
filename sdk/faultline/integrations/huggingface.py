"""Hugging Face ``Trainer`` integration for Faultline Cloud."""

from __future__ import annotations

from typing import Any

from faultline.cloud_run import CloudRun
from faultline.start import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_PROJECT, start

try:
    from transformers import TrainerCallback, TrainerControl, TrainerState
    from transformers.training_args import TrainingArguments
except ImportError:  # pragma: no cover - optional dependency
    TrainerCallback = object  # type: ignore[misc, assignment]
    TrainerControl = Any  # type: ignore[misc, assignment]
    TrainerState = Any  # type: ignore[misc, assignment]
    TrainingArguments = Any  # type: ignore[misc, assignment]


def _scalar_metrics(logs: dict[str, Any] | None) -> dict[str, float]:
    if not logs:
        return {}
    out: dict[str, float] = {}
    for key, value in logs.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = float(value)
    return out


class FaultlineTrainerCallback(TrainerCallback):
    """
    Log metrics, upload checkpoints, and optionally auto-resume via Faultline Cloud.

    Requires ``transformers`` installed.
    """

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
        register_launch: bool = False,
        launch_command: list[str] | None = None,
    ) -> None:
        if TrainerCallback is object:
            raise ImportError(
                "FaultlineTrainerCallback requires `pip install transformers`"
            )
        self.project = project
        self.run_name = run_name
        self.api_key = api_key
        self.base_url = base_url
        self.upload_checkpoints = upload_checkpoints
        self.auto_resume = auto_resume
        self.model = model
        self.optimizer = optimizer
        self.register_launch = register_launch
        self.launch_command = launch_command
        merged = list(tags or [])
        if "integration:huggingface" not in merged:
            merged.append("integration:huggingface")
        self.tags = merged
        self._run: CloudRun | None = None
        self._start_step = 0

    @property
    def run(self) -> CloudRun:
        if self._run is None:
            raise RuntimeError("Callback has not started training yet")
        return self._run

    def _bind_run(self, *, model: Any | None = None) -> None:
        if self._run is not None:
            return
        self._run = start(
            self.run_name,
            project=self.project,
            api_key=self.api_key,
            base_url=self.base_url,
            tags=self.tags,
        )
        if self.register_launch and self.launch_command:
            self._run.register_launch_command(self.launch_command)
        active_model = self.model if self.model is not None else model
        if self.auto_resume:
            self._start_step = self._run.restore_latest(
                model=active_model,
                optimizer=self.optimizer,
            )

    def on_train_begin(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        model: Any | None = None,
        **kwargs: Any,
    ) -> TrainerControl:
        self._bind_run(model=model)
        if self._start_step > 0:
            state.global_step = self._start_step
        return control

    def on_log(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        logs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> TrainerControl:
        if self._run is None:
            return control
        metrics = _scalar_metrics(logs)
        if metrics:
            step = int(state.global_step)
            self._run.log(step=step, **metrics)
            self._run.log_progress(step=step, total_steps=int(state.max_steps or 0))
        return control

    def on_save(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        model: Any | None = None,
        **kwargs: Any,
    ) -> TrainerControl:
        if not self.upload_checkpoints or self._run is None:
            return control
        active_model = self.model if self.model is not None else model
        self._run.save(
            step=int(state.global_step),
            model=active_model,
            optimizer=self.optimizer,
        )
        return control

    def on_train_end(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs: Any,
    ) -> TrainerControl:
        if self._run is not None:
            self._run.complete()
        return control

    def on_train_error(
        self,
        args: TrainingArguments,
        state: TrainerState,
        control: TrainerControl,
        **kwargs: Any,
    ) -> TrainerControl:
        if self._run is not None:
            exc = kwargs.get("exception") or kwargs.get("error")
            message = str(exc) if exc else "training error"
            self._run.fail(message=message)
        return control
