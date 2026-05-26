"""Build checkpoint payloads from training state."""

from __future__ import annotations

from typing import Any


def _has_state_dict(obj: Any) -> bool:
    return obj is not None and callable(getattr(obj, "state_dict", None))


def build_checkpoint_payload(
    *,
    step: int,
    model: Any | None = None,
    optimizer: Any | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a checkpoint dict for cloud upload."""
    payload: dict[str, Any] = {"step": step}
    if state:
        payload.update(state)
    if model is not None:
        if _has_state_dict(model):
            payload["model_state"] = model.state_dict()
        else:
            payload["model_state"] = model
    if optimizer is not None:
        if _has_state_dict(optimizer):
            payload["optimizer_state"] = optimizer.state_dict()
        else:
            payload["optimizer_state"] = optimizer
    return payload


def restore_checkpoint_into_modules(
    state: dict[str, Any],
    *,
    model: Any | None = None,
    optimizer: Any | None = None,
) -> int:
    """Load model/optimizer state from a checkpoint dict; return saved step."""
    step = int(state.get("step", 0))
    if model is not None and "model_state" in state:
        model_state = state["model_state"]
        if hasattr(model, "load_state_dict"):
            model.load_state_dict(model_state)
        else:
            raise TypeError("model does not support load_state_dict")
    if optimizer is not None and "optimizer_state" in state:
        opt_state = state["optimizer_state"]
        if hasattr(optimizer, "load_state_dict"):
            optimizer.load_state_dict(opt_state)
        else:
            raise TypeError("optimizer does not support load_state_dict")
    return step
