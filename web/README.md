# Faultline Cloud — Next.js frontend (v24.0)

SaaS-style UI for the Faultline **ML training continuity and recovery** platform. The legacy static dashboard at `http://127.0.0.1:8080/dashboard` remains available.

## Browser login vs API keys

| | Browser dashboard | Training scripts (SDK) |
|--|-------------------|------------------------|
| **Auth** | Sign up / log in at `/signup` and `/login` | API key in `faultline.start(..., api_key=...)` |
| **How** | HttpOnly session cookie via Next.js BFF | `Authorization: Bearer fl_...` |
| **Create key** | Account page after login | Same — copy key into your trainer |

You do **not** need `FAULTLINE_API_KEY` in `web/.env.local` for browser use. The Next.js BFF proxies `/api/*` to the Cloud API using your HttpOnly session cookie — the API key never belongs in the browser.

**Account page:** profile, API keys, usage, alert settings. **Operator infrastructure** (Postgres/MinIO/worker): `/admin/infrastructure` (optional sidebar link with `NEXT_PUBLIC_FAULTLINE_OPERATOR_NAV=true`).

**Production deploy:** [docs/PRODUCTION.md](../docs/PRODUCTION.md)

## Onboarding

1. Start the stack: `docker compose -f docker-compose.cloud.yml up --build`
2. **Sign up** at http://localhost:3000/signup
3. **Account** → Create an API key
4. **Quickstart** → paste key → copy snippet → run your trainer with `base_url="http://127.0.0.1:8080"`

```python
run = faultline.quickstart(project="demo", api_key="fl_...")  # from Account page
```

## Prerequisites

- Node.js 18+
- Python env with FastAPI cloud API running (`bcrypt`, `PyJWT`)

## Environment (optional)

```powershell
cd web
copy .env.example .env.local
```

```env
FAULTLINE_API_URL=http://127.0.0.1:8080
NEXT_PUBLIC_FAULTLINE_API_URL=http://127.0.0.1:8080
```

## Run (Docker)

From repo root:

```powershell
docker compose -f docker-compose.cloud.yml up --build
```

Open http://localhost:3000 — sign up, then create an API key.

Training scripts and the dashboard both use the same API at http://127.0.0.1:8080.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Product landing |
| `/signup`, `/login` | User accounts |
| `/dashboard` | Overview (requires login) |
| `/runs` | Runs table |
| `/runs/[runId]` | Metrics, checkpoints, recovery |
| `/quickstart` | Setup guide + snippet |
| `/account` | API keys & usage |
| `/alerts` | Failed/recoverable runs |

## Build

```powershell
npm run build
npm start
```

## Architecture

- Browser → Next.js `/api/*` BFF (session JWT as Bearer)
- BFF → FastAPI at `FAULTLINE_API_URL` (Docker: `http://cloud-api:8080`)
- SDK → FastAPI directly with Bearer API key on port 8080

## Stack

- Next.js 15 (App Router)
- TypeScript, Tailwind, Recharts, lucide-react
