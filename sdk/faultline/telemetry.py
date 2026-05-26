"""System and training progress telemetry helpers for Faultline runs."""

from __future__ import annotations

import time
from typing import Any

_PSUTIL_INSTALL_HINT = (
    "System metrics require psutil. Install with: pip install psutil"
)


def collect_system_metrics() -> dict[str, float]:
    """Collect host/process telemetry (requires psutil)."""
    try:
        import psutil
    except ImportError as error:
        raise ImportError(_PSUTIL_INSTALL_HINT) from error

    process = psutil.Process()
    memory = psutil.virtual_memory()
    metrics: dict[str, float] = {
        "client_timestamp_ms": float(time.time() * 1000.0),
        "cpu_percent": float(psutil.cpu_percent(interval=None)),
        "memory_percent": float(memory.percent),
        "process_rss_mb": float(process.memory_info().rss) / (1024.0 * 1024.0),
    }

    try:
        import torch

        if torch.cuda.is_available():
            metrics["gpu_memory_allocated_mb"] = float(
                torch.cuda.memory_allocated() / (1024.0 * 1024.0)
            )
            metrics["gpu_memory_reserved_mb"] = float(
                torch.cuda.memory_reserved() / (1024.0 * 1024.0)
            )
    except ImportError:
        pass

    return metrics


def try_collect_system_metrics() -> dict[str, float] | None:
    """Return system metrics, or None if psutil is not installed."""
    try:
        return collect_system_metrics()
    except ImportError:
        return None


def build_progress_metrics(
    *,
    loss: float | None = None,
    learning_rate: float | None = None,
    samples_per_sec: float | None = None,
    step_time_ms: float | None = None,
) -> dict[str, float]:
    """Build a metric payload for training progress logging."""
    metrics: dict[str, float] = {}
    if loss is not None:
        metrics["loss"] = float(loss)
    if learning_rate is not None:
        metrics["learning_rate"] = float(learning_rate)
    if samples_per_sec is not None:
        metrics["samples_per_sec"] = float(samples_per_sec)
    if step_time_ms is not None:
        metrics["step_time_ms"] = float(step_time_ms)
    return metrics
