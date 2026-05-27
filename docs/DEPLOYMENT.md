# Deploying Faultline Cloud

**Current version: v24.0.** For production hosting, secrets, migrations, and rate limiting, use **[PRODUCTION.md](PRODUCTION.md)** as the source of truth.

---

## Local development (Docker Compose)

From the repository root:

```bash
docker compose -f docker-compose.cloud.yml up --build
```

| URL | Service |
|-----|---------|
| http://localhost:3000 | Next.js dashboard |
| http://localhost:8080 | FastAPI API |
| http://localhost:8080/health | Liveness |
| http://localhost:8080/ready | Readiness |

Development defaults:

- `FAULTLINE_ENV=development` — schema auto-created via `init_db` (no Alembic required)
- `FAULTLINE_RATE_LIMIT_ENABLED=false` — rate limiting off for local UX
- `FAULTLINE_SEED_DEMO=1` — demo workspace (`demo@faultline.local` / `faultlinedemo`)
- Dev JWT secret in compose — **not for production**

OAuth and other secrets: copy `.env.local.example` to `.env.local` (gitignored).

Stop:

```bash
docker compose -f docker-compose.cloud.yml down
```

---

## Production-oriented Compose

Requires external Postgres and S3/R2 credentials. See **[PRODUCTION.md](PRODUCTION.md)**.

```bash
docker compose -f docker-compose.production.yml up --build -d
```

The API container runs `alembic upgrade head` then starts Uvicorn. Demo seed and weak JWT defaults are **not** included.

---

## Manual image build

```bash
docker build -f Dockerfile.cloud-api -t faultline-cloud-api .
docker build -f web/Dockerfile -t faultline-web .
```

---

## Database migrations (Alembic)

Apply schema on an **empty** production database (pick one):

```bash
# Recommended: same logic the API runs on startup
export FAULTLINE_ENV=production
export FAULTLINE_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/faultline
export FAULTLINE_JWT_SECRET=<32+ char secret>
export FAULTLINE_COOKIE_SECURE=true
python cloud/scripts/migrate.py
```

Or let the API container run migrations on first start (`cloud/scripts/start_api.sh`).

**Later deploys:** redeploy the API; each start runs pending migrations automatically.

Manual CLI:

```bash
export FAULTLINE_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/faultline
alembic -c cloud/alembic.ini upgrade head
```

Create a new revision after changing `cloud/api/db.py` schema:

```bash
alembic -c cloud/alembic.ini revision -m "describe_change"
# Edit cloud/alembic/versions/<file>.py, then:
alembic -c cloud/alembic.ini upgrade head
```

**Development:** `init_db` auto-creates tables when `FAULTLINE_ENV` is not `production` (see `FAULTLINE_DB_AUTO_CREATE`). **Production:** use Alembic only; do not rely on auto-create.

### Existing database already has tables (`table users already exists`)

This happens when Docker or `init_db` created the schema before you ran Alembic. The schema is already there; Alembic just needs to record the revision.

**Do not run `upgrade head` again** on that database. Stamp the current revision instead:

```bash
# Point at the same DB your stack uses, then:
alembic -c cloud/alembic.ini stamp head
```

Examples:

```bash
# Local SQLite (default path cloud/data/faultline.db)
alembic -c cloud/alembic.ini stamp head

# Docker Postgres on localhost
set FAULTLINE_DATABASE_URL=postgresql+psycopg://faultline:faultline@localhost:5432/faultline
alembic -c cloud/alembic.ini stamp head
```

Verify: `alembic -c cloud/alembic.ini current` should show `24_001 (head)`.

**Fresh database** (empty Postgres or new SQLite file): use `upgrade head`, not `stamp`.

---

## Pre-launch checklist

See **[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)**.
