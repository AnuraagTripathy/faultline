"""Local filesystem checkpoint storage for cloud MVP."""

from __future__ import annotations

import os
from pathlib import Path

CLOUD_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
MAX_CHECKPOINT_BYTES = 50 * 1024 * 1024  # 50 MiB dev limit


def checkpoints_root() -> Path:
    raw = os.environ.get("FAULTLINE_CLOUD_CHECKPOINTS_DIR")
    if raw:
        return Path(raw)
    return CLOUD_DATA_ROOT / "checkpoints"


def checkpoint_path(user_id: str, run_id: str, step: int) -> Path:
    directory = checkpoints_root() / user_id / run_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"step_{step}.pkl"
