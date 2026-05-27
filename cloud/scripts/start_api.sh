#!/bin/sh
set -e
cd /app

python -c "from cloud.api.env_validation import validate_startup_config; validate_startup_config()"

if [ "${FAULTLINE_ENV:-development}" = "production" ]; then
  python -c "from cloud.api.migrations import run_pending_migrations; run_pending_migrations()"
fi

exec uvicorn cloud.api.app:app --host 0.0.0.0 --port 8080
