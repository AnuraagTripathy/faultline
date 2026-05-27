#!/usr/bin/env python3
"""Run pending Alembic migrations (production / CI / pre-deploy).

Usage:
  export FAULTLINE_DATABASE_URL=postgresql+psycopg://...
  export FAULTLINE_ENV=production
  python cloud/scripts/migrate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud.api.env_validation import validate_startup_config  # noqa: E402
from cloud.api.migrations import run_pending_migrations  # noqa: E402


def main() -> int:
    validate_startup_config()
    revision = run_pending_migrations()
    print(f"OK: database at revision {revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
