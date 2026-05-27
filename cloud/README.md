# Faultline Cloud API (Version 24.0)

**ML training continuity and recovery platform** — hosted ingestion for projects, runs, metrics, events, and checkpoints. **FastAPI + PostgreSQL + object storage** in Docker; SQLite for lightweight local API-only dev.

Local Rust `serve-grpc` mode is unchanged; use `faultline.init(..., mode="local")` (default) for the gRPC runtime and port-8000 observability dashboard.

## Quick start

From the **repo root**:

```bash
# Product preview (API + Next.js UI)
docker compose -f docker-compose.cloud.yml up --build
# → http://localhost:3000  (web)  http://localhost:8080  (API)

pip install fastapi uvicorn pydantic python-multipart bcrypt PyJWT

# 1. Cloud API only (dev)
uvicorn cloud.api.app:app --reload --port 8080

# 2. Longer training demo (runs on your laptop; streams to the dashboard)
set PYTHONPATH=sdk
python sdk/examples/cloud_pytorch_easy.py

# Shorter smoke test:
# python sdk/examples/cloud_run_demo.py

# 3. Checkpoint-only demo
# python sdk/examples/cloud_checkpoint_demo.py

# 4. Open UI
# Next.js (recommended): cd web && npm run dev → http://localhost:3000
# Legacy static UI: http://127.0.0.1:8080/dashboard
```

Dev bootstrap key (seeded on first startup): **`fl_dev_local`** (local preview only).

## Authentication (v18.5)

Two paths:

| Use case | Auth |
|----------|------|
| **Browser dashboard** | Sign up / log in → HttpOnly `faultline_session` JWT cookie |
| **SDK / training scripts** | `Authorization: Bearer <api_key>` |

### User accounts (browser)

```http
POST /v1/auth/signup   { "email", "password" }   # min 8 char password
POST /v1/auth/login    { "email", "password" }
POST /v1/auth/logout
GET  /v1/auth/me        # session cookie or Bearer
```

Passwords stored as **bcrypt** hashes (`pip install bcrypt`). Set `FAULTLINE_JWT_SECRET` in production.

### API keys (SDK)

```http
Authorization: Bearer <your-api-key>
```

Create a key while logged in (session cookie) or with an existing key (full value returned once):

```http
POST /v1/api-keys?label=my-laptop
Authorization: Bearer <existing-key>
```

Use it in training:

```python
run = faultline.start("my-run", project="demo", api_key="fl_...", base_url="http://127.0.0.1:8080")
```

- `GET /v1/me` — user, active key prefix, usage totals
- `GET /v1/usage` — usage totals + active key prefix
- `GET /v1/api-keys` — list keys (prefix, label, created_at, last_used_at; never full key)
- `POST /v1/api-keys?label=…` — create key (optional JSON body `{ "label": "…" }`)

Database: `cloud/data/faultline.db` (`FAULTLINE_CLOUD_DB`).  
Checkpoints: `cloud/data/checkpoints/` (`FAULTLINE_CLOUD_CHECKPOINTS_DIR`).

## Database (v19.0)

| Variable | Default | Description |
|----------|---------|-------------|
| `FAULTLINE_DATABASE_URL` | SQLite file from `FAULTLINE_CLOUD_DB` | SQLAlchemy URL (`sqlite:///…` or `postgresql+psycopg://…`) |

Docker Compose uses PostgreSQL automatically.

## Checkpoint storage (v19.0)

Checkpoints go through `CloudCheckpointStorage` (`cloud/api/storage.py`).

| Variable | Default | Description |
|----------|---------|-------------|
| `FAULTLINE_CLOUD_STORAGE` | `local` | `local`, `minio`, `s3`, `r2` |
| `FAULTLINE_CLOUD_CHECKPOINTS_DIR` | `cloud/data/checkpoints` | Local root (when `local`) |
| `FAULTLINE_S3_ENDPOINT` | — | MinIO/S3 endpoint |
| `FAULTLINE_S3_BUCKET` | `faultline` | Bucket name |
| `FAULTLINE_S3_ACCESS_KEY` / `FAULTLINE_S3_SECRET_KEY` | — | Credentials |

**Local:** `<root>/<user_id>/<run_id>/step_<N>.pkl`  
**MinIO/S3:** `checkpoints/<user_id>/<run_id>/step_<N>.pkl`

Each checkpoint row stores `storage_backend`, `storage_path`, `size_bytes`, and `checksum_sha256` (SHA-256 of uploaded bytes). Recovery health checks use `storage.exists` / `size` / `read` instead of raw filesystem paths.

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
| `GET` | `/v1/api-keys` | List API keys (no full key) |
| `POST` | `/v1/api-keys` | Create API key |
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
| `GET` | `/v1/runs/{run_id}/recovery` | Crash-to-resume summary (v17.1) |
| `POST` | `/v1/runs/{run_id}/launch-config` | Register local command or Slurm script (v17.2) |
| `GET` | `/v1/runs/{run_id}/launch-config` | Get launch config |
| `POST` | `/v1/runs/{run_id}/resume` | Manual relaunch (local `Popen` or `sbatch`) |

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

# After a crash (v17.1)
recovery = run.recovery()
run.print_resume_instructions(recovery)
step = run.restore_latest(model=model, optimizer=optimizer)
```

Recovery demo: `python sdk/examples/cloud_failure_recovery_demo.py`

Auto-resume (v17.2):

```python
run.register_launch_command(["python", "train.py", "--config", "llama.yaml"])
# or: run.register_slurm_script("train.slurm")
run.fail("node preempted")
run.resume()  # API-triggered relaunch only — no background scheduler
```

Demo: `python sdk/examples/auto_resume_demo.py`

## Production deployment (v24)

- **Source of truth:** [docs/PRODUCTION.md](../docs/PRODUCTION.md)
- **Migrations:** `alembic -c cloud/alembic.ini upgrade head`
- **Rate limiting:** in-memory per process; see env vars in PRODUCTION.md
- **Pre-launch:** [docs/RELEASE_CHECKLIST.md](../docs/RELEASE_CHECKLIST.md)

## Limitations

- No Stripe / billing
- No teams/orgs
- Rate limiter is single-process (not Redis-backed yet)
- 50 MiB max per checkpoint upload
- No multipart upload for huge files

## Tests

```bash
python -m unittest discover cloud/tests
```

Uses temporary SQLite and checkpoint dirs via env vars in tests.
