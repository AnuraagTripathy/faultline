# Faultline Cloud — Production deployment (v24.0)

Faultline is an **ML training continuity and recovery platform**: metrics, checkpoints, crash-to-resume, and alerts — not just experiment tracking.

## Architecture

```
Training script (SDK)
        ↓  HTTPS + API key
Cloud API (FastAPI)
        ↓
PostgreSQL  +  S3-compatible object storage (MinIO / R2 / AWS)
        ↓
Next.js dashboard + recovery + alerts
```

## Components

| Component | Role |
|-----------|------|
| **cloud-api** | Ingestion, auth, recovery, background worker |
| **web** | Next.js BFF + dashboard |
| **PostgreSQL** | Users, runs, metrics, tasks, alert settings |
| **Object storage** | Checkpoint blobs (`checkpoints/<user>/<run>/step_N.pkl`) |

## Environment variables

### API (required in production)

| Variable | Example |
|----------|---------|
| `FAULTLINE_DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/faultline` |
| `FAULTLINE_CLOUD_STORAGE` | `minio` or `s3` |
| `FAULTLINE_S3_ENDPOINT` | `https://s3.amazonaws.com` or R2 URL |
| `FAULTLINE_S3_BUCKET` | `faultline-prod` |
| `FAULTLINE_S3_ACCESS_KEY` | (secret) |
| `FAULTLINE_S3_SECRET_KEY` | (secret) |
| `FAULTLINE_S3_REGION` | `us-east-1` |
| `FAULTLINE_JWT_SECRET` | long random string (rotate periodically) |
| `FAULTLINE_CORS_ORIGINS` | `https://app.yourdomain.com` |
| `FAULTLINE_COOKIE_SECURE` | `true` |
| `FAULTLINE_ENV` | `production` |
| `FAULTLINE_OAUTH_GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `FAULTLINE_OAUTH_GOOGLE_CLIENT_SECRET` | Google OAuth secret |
| `FAULTLINE_OAUTH_GITHUB_CLIENT_ID` | GitHub OAuth client ID |
| `FAULTLINE_OAUTH_GITHUB_CLIENT_SECRET` | GitHub OAuth secret |
| `FAULTLINE_RATE_LIMIT_ENABLED` | `true` in production |
| `FAULTLINE_RATE_LIMIT_REQUESTS_PER_MINUTE` | Default `120` (general traffic) |
| `FAULTLINE_RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE` | Default `20` (login, signup, OAuth, API keys, resume) |
| `FAULTLINE_RATE_LIMIT_UPLOADS_PER_MINUTE` | Default `10` (checkpoint uploads) |

**Do not set in production:** `FAULTLINE_SEED_DEMO`, weak `FAULTLINE_JWT_SECRET`, or `fl_dev_local` as your primary auth model.

### Alerts (optional)

| Variable | Purpose |
|----------|---------|
| `FAULTLINE_SMTP_HOST` | SMTP server |
| `FAULTLINE_SMTP_PORT` | Usually `587` |
| `FAULTLINE_SMTP_USER` / `FAULTLINE_SMTP_PASSWORD` | SMTP auth |
| `FAULTLINE_ALERT_FROM_EMAIL` | From address |

Per-user Discord/Slack webhooks are stored in the database (Account page).

### Web (BFF)

| Variable | Purpose |
|----------|---------|
| `FAULTLINE_API_URL` | Internal API URL (e.g. `http://cloud-api:8080`) |
| `NEXT_PUBLIC_FAULTLINE_API_URL` | Public API URL for training scripts |
| `NEXT_PUBLIC_APP_URL` | Public web origin (OAuth callbacks) |
| `NEXT_PUBLIC_FAULTLINE_OPERATOR_NAV` | Optional `true` to show Infrastructure in sidebar |

## Startup validation (production)

When `FAULTLINE_ENV=production`, the API **fails fast** if:

- `FAULTLINE_JWT_SECRET` is missing or shorter than 32 characters
- `FAULTLINE_SEED_DEMO` is enabled
- `FAULTLINE_COOKIE_SECURE` is not true

Every production API start (and the standalone migrate script) runs **`alembic upgrade head`** before Uvicorn. Later deploys with new migration files apply only the diff automatically.

## Rate limiting

In-memory, **single-process** limiter (documented limitation — use one API replica or accept per-instance limits until Redis is added).

| Bucket | Routes | Default RPM |
|--------|--------|-------------|
| Auth | signup, login, OAuth callback, API key create, resume | 20 |
| Upload | checkpoint POST | 10 |
| Default | all other requests | 120 |

Blocked clients receive `429` with `{"detail":"rate limit exceeded"}` and `Retry-After` / `X-RateLimit-*` headers.

Disable locally: `FAULTLINE_RATE_LIMIT_ENABLED=false` (set in `docker-compose.cloud.yml`).

## Database migrations (Alembic)

Production must apply migrations; do not rely on `init_db` auto-create.

**First deploy (empty Postgres):** migrations run automatically when the API container starts. You can also run them once before traffic:

```bash
export FAULTLINE_ENV=production
export FAULTLINE_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/faultline
export FAULTLINE_JWT_SECRET=...   # 32+ chars (required for migrate.py validation)
export FAULTLINE_COOKIE_SECURE=true
python cloud/scripts/migrate.py
```

**Later deploys:** ship the new image/revision; on startup the API runs `upgrade head` again (no-op if already current, applies new revisions if not).

CLI equivalent:

```bash
alembic -c cloud/alembic.ini upgrade head
```

New revision (developers):

```bash
alembic -c cloud/alembic.ini revision -m "your_change"
# edit cloud/alembic/versions/*.py
alembic -c cloud/alembic.ini upgrade head
```

Development (`FAULTLINE_ENV=development`) may still auto-create schema via `init_db` on startup.

## Docker Compose

**Local development** (demo seed, dev JWT, rate limit off):

```bash
docker compose -f docker-compose.cloud.yml up --build
```

**Production-oriented** (external Postgres + S3, required secrets, Alembic on start, rate limit on):

```bash
docker compose -f docker-compose.production.yml up --build -d
```

Services: **reverse-proxy** (Caddy), **cloud-api**, **web**. Provision Postgres and object storage separately.

## Hosted deployment patterns

**Step-by-step (Vercel + Render + Neon + R2):** [DEPLOY_VERCEL_RENDER.md](DEPLOY_VERCEL_RENDER.md)

### Frontend — Vercel

1. Deploy `web/` as a Next.js project.
2. Set `FAULTLINE_API_URL` to your private API URL (if using server-side BFF only).
3. Set `NEXT_PUBLIC_FAULTLINE_API_URL` to the public API URL for SDK snippets.
4. Enable HTTPS (default on Vercel).
5. Set `NEXT_PUBLIC_APP_URL` to your public web origin (OAuth callback target).

### API — Railway / Render / Fly.io

1. Deploy `Dockerfile.cloud-api`.
2. Attach **managed PostgreSQL**; set `FAULTLINE_DATABASE_URL`.
3. Use **S3**, **Cloudflare R2**, or **MinIO** for checkpoints — not local disk.
4. Set secrets via platform secret manager.
5. Expose port `8080`; configure health check on `/ready`.

### Database

- Use managed Postgres (RDS, Neon, Supabase, Railway Postgres).
- Backups enabled; connection pooling recommended for serverless API.

### Object storage

- **AWS S3** or **Cloudflare R2**: set `FAULTLINE_CLOUD_STORAGE=s3`, endpoint, bucket, keys.
- Ensure bucket policy allows put/get/head/delete from API role.
- Checkpoints are **not** stored in Postgres — only metadata.

## HTTPS & secrets

- Terminate TLS at load balancer or platform edge.
- Never commit `FAULTLINE_JWT_SECRET` or S3 keys.
- Rotate JWT secret by issuing new logins (existing sessions invalidate).
- Keep OAuth secrets in platform secret manager only.
- Configure `FAULTLINE_CORS_ORIGINS` with explicit production domains.

## Health checks

- `GET /health` — database + storage + worker status
- `GET /ready` — database only (use for load balancer)

## Docker Hub images (placeholders)

When published:

- `faultline/cloud-api:20.0`
- `faultline/web:20.0`

Build locally: `docker build -f Dockerfile.cloud-api -t faultline/cloud-api:20.0 .` and `docker build -f web/Dockerfile -t faultline/web:20.0 web/`

## Platform quick deploy snippets

### Railway / Fly (API)

- Set `FAULTLINE_DATABASE_URL`, S3/MinIO vars, `FAULTLINE_JWT_SECRET`, `FAULTLINE_CORS_ORIGINS`
- Health check: `GET /ready`
- Example Fly: `fly deploy` with `internal_port = 8080`

### Vercel (web)

- Set `FAULTLINE_API_URL` to your public API origin
- Next.js BFF proxies `/api/*` to the backend

## Backups

| Asset | Recommendation |
|-------|----------------|
| **PostgreSQL** | Daily automated snapshots + point-in-time recovery |
| **Object storage** | Versioning or cross-region replication for checkpoint bucket |
| **Secrets** | Store in platform secret manager; rotate quarterly |

## Health monitoring

- Alert on `/ready` failures (database connectivity)
- Alert on `/health` `object_storage.status != ok`
- Monitor background worker queue depth via `/v1/infrastructure` (operator route: `/admin/infrastructure` in the web UI)

## Pre-launch checklist

See **[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)**.

## What remains before monetization

- Stripe / billing
- Teams and organizations
- Kubernetes operators / distributed schedulers
- Distributed rate limiting (Redis) for multi-replica API
- Multi-region HA
