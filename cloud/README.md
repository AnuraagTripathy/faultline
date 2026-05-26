# Faultline Cloud API (Version 16.0–16.3)

Hosted ingestion layer for projects, runs, metrics, events, and checkpoints. **FastAPI + SQLite** — local development only (not deployed yet).

Local Rust `serve-grpc` mode is unchanged; use `faultline.init(..., mode="local")` (default) for the gRPC runtime and port-8000 observability dashboard.

## Quick start

From the **repo root**:

```bash
pip install fastapi uvicorn pydantic python-multipart

# 1. Cloud API + dashboard
uvicorn cloud.api.app:app --reload --port 8080

# 2. Longer training demo (runs on your laptop; streams to the dashboard)
set PYTHONPATH=sdk
python sdk/examples/cloud_pytorch_easy.py

# Shorter smoke test:
# python sdk/examples/cloud_run_demo.py

# 3. Checkpoint-only demo
# python sdk/examples/cloud_checkpoint_demo.py

# 4. Open UI
# http://127.0.0.1:8080/
# http://127.0.0.1:8080/dashboard
```

Dev API key (seeded on first startup): **`fl_dev_local`** (stored in plaintext for local dev only).

Database: `cloud/data/faultline.db` (`FAULTLINE_CLOUD_DB`).  
Checkpoints: `cloud/data/checkpoints/` (`FAULTLINE_CLOUD_CHECKPOINTS_DIR`).

## Authentication

```http
Authorization: Bearer fl_dev_local
```

- `GET /v1/me` — user, API key prefix, usage totals
- `GET /v1/usage` — usage only
- `POST /v1/api-keys?label=dev` — create another dev key (full key returned once)

## Usage counters

Per user (updated on authenticated requests):

| Counter | Incremented when |
|---------|------------------|
| `runs_created` | `POST /v1/runs/start` |
| `metric_points_ingested` | `POST /v1/runs/{id}/metrics` (+1 per request, one step sample) |
| `events_ingested` | `POST /v1/runs/{id}/events` |
| `checkpoints_created` | `POST /v1/runs/{id}/checkpoints` |
| `checkpoint_bytes_uploaded` | bytes written per checkpoint upload |
| `last_used_at_ms` | any authenticated call |

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Product landing page |
| `GET` | `/getting-started` | Connect guide |
| `GET` | `/dashboard` | Cloud runs dashboard |
| `GET` | `/health` | Liveness |
| `GET` | `/v1/me` | Account + usage |
| `GET` | `/v1/usage` | Usage totals |
| `POST` | `/v1/api-keys` | Create dev API key |
| `POST` | `/v1/runs/start` | Start a run |
| `GET` | `/v1/runs` | List runs |
| `GET` | `/v1/runs/{run_id}` | Get run |
| `POST` | `/v1/runs/{run_id}/metrics` | Log metrics |
| `GET` | `/v1/runs/{run_id}/metrics` | Metric history |
| `POST` | `/v1/runs/{run_id}/events` | Log event / lifecycle |
| `GET` | `/v1/runs/{run_id}/events` | List events |
| `POST` | `/v1/runs/{run_id}/checkpoints` | Upload checkpoint (multipart) |
| `GET` | `/v1/runs/{run_id}/checkpoints` | List checkpoints |
| `GET` | `/v1/runs/{run_id}/checkpoints/latest` | Latest checkpoint metadata |
| `GET` | `/v1/runs/{run_id}/checkpoints/latest/download` | Download latest file |
| `GET` | `/v1/runs/{run_id}/checkpoints/{id}/download` | Download by id |

Lifecycle events (`POST .../events`):

| `event_type` | Sets run status |
|--------------|-----------------|
| `faultline.run.completed` | `completed` |
| `faultline.run.failed` | `failed` |
| `faultline.run.stopped` | `stopped` |

## Python SDK (cloud mode)

```python
import faultline

run = faultline.init(
    project="protein-model",
    run_name="experiment-1",
    mode="cloud",
    api_key="fl_dev_local",
    base_url="http://127.0.0.1:8080",
)

run.log_metrics({"loss": 0.5}, step=1)

run.checkpoint({"model_state": state, "step": step}, step=step)

state = run.load_latest_checkpoint_or_none()  # pickle — trust your own checkpoints only

run.complete()
```

## Cloud mode MVP limitations

- No Stripe / billing
- No login UI (dev API keys in plaintext SQLite)
- No teams/orgs
- Checkpoint storage is **local filesystem**, not S3/R2
- 50 MiB max per checkpoint upload (dev limit)
- No multipart upload for huge files

## Tests

```bash
python -m unittest discover cloud/tests
```

Uses temporary SQLite and checkpoint dirs via env vars in tests.
