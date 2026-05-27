"""Local CLI configuration (~/.faultline/config.json)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("FAULTLINE_CONFIG_DIR", Path.home() / ".faultline"))
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.is_file():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_api_key() -> str | None:
    env = os.environ.get("FAULTLINE_API_KEY")
    if env:
        return env.strip()
    cfg = load_config()
    key = cfg.get("api_key")
    return str(key).strip() if key else None


def get_base_url() -> str:
    env = os.environ.get("FAULTLINE_API_URL") or os.environ.get("FAULTLINE_BASE_URL")
    if env:
        return env.rstrip("/")
    cfg = load_config()
    url = cfg.get("base_url")
    if url:
        return str(url).rstrip("/")
    return "http://127.0.0.1:8080"


def get_session_token() -> str | None:
    cfg = load_config()
    token = cfg.get("access_token")
    return str(token).strip() if token else None
