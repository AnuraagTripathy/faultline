"""Optional framework integrations for Faultline."""

from faultline.integrations.pytorch import FaultlineCallback, watch_training

__all__ = ["FaultlineCallback", "watch_training"]
