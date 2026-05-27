"""Optional framework integrations for Faultline."""

from faultline.integrations.pytorch import FaultlineCallback, watch_training

__all__ = [
    "FaultlineCallback",
    "watch_training",
    "FaultlineTrainerCallback",
    "FaultlineLightningCallback",
]

try:
    from faultline.integrations.huggingface import FaultlineTrainerCallback
except ImportError:
    FaultlineTrainerCallback = None  # type: ignore[misc, assignment]

try:
    from faultline.integrations.lightning import FaultlineLightningCallback
except ImportError:
    FaultlineLightningCallback = None  # type: ignore[misc, assignment]
