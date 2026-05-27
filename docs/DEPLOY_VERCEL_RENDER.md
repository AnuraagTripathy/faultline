# Deploy Faultline Cloud — Vercel + Render + Neon + R2

Recommended **free-tier beta** layout:

| Layer | Service | Role |
|-------|---------|------|
| **Web UI** | [Vercel Hobby](https://vercel.com) | Next.js dashboard + BFF (`/api/*` proxies to API) |
| **API** | [Render Free](https://render.com) | FastAPI (`Dockerfile.cloud-api`) |
| **Database** | [Neon Free Postgres](https://neon.tech) | Users, runs, metrics metadata |
| **Checkpoints** | [Cloudflare R2 Free](https://developers.cloudflare.com/r2/) | Checkpoint blobs (S3-compatible) |
| **Domain** | Optional later | Custom domain on Vercel + API subdomain |

```
Browser  →  Vercel (Next.js BFF, session cookie)
              ↓  server-side fetch
           Render (FastAPI)
              ↓                    ↓
           Neon Postgres        Cloudflare R2

Training script  →  Render API (API key, HTTPS)
```

---

## 0. Prerequisites

- GitHub repo pushed (see [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md))
- Google and/or GitHub OAuth apps (for browser login)
- ~30 minutes for first-time setup

Pick two URLs (replace in all steps):

| Name | Example |
|------|---------|
| **Web URL** | `https://faultline.vercel.app` |
| **API URL** | `https://faultline-api.onrender.com` |

---

## 1. Neon (Postgres)

1. Create a project → **Postgres 16**.
2. Copy the **connection string** (pooled or direct; Render works with either).
3. Convert to SQLAlchemy format if Neon gives `postgresql://`:

   ```text
   postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require
   ```

4. Keep this as `FAULTLINE_DATABASE_URL` (Render only — not Vercel).

**First schema:** empty database. On first API start, Render runs `alembic upgrade head` automatically (`FAULTLINE_ENV=production`).

Optional manual run from your laptop:

```bash
export FAULTLINE_ENV=production
export FAULTLINE_DATABASE_URL="postgresql+psycopg://..."
export FAULTLINE_JWT_SECRET="$(openssl rand -hex 32)"
export FAULTLINE_COOKIE_SECURE=true
python cloud/scripts/migrate.py
```

---

## 2. Cloudflare R2 (checkpoints)

1. R2 → **Create bucket** (e.g. `faultline-checkpoints`).
2. **Manage R2 API tokens** → Create token with read/write on that bucket.
3. Note:
   - **Account ID**
   - **Access Key ID** / **Secret Access Key**
   - Endpoint form: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`

API env (Render):

```env
FAULTLINE_CLOUD_STORAGE=r2
FAULTLINE_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
FAULTLINE_S3_BUCKET=faultline-checkpoints
FAULTLINE_S3_ACCESS_KEY=<r2 access key id>
FAULTLINE_S3_SECRET_KEY=<r2 secret>
FAULTLINE_S3_REGION=auto
```

---

## 3. Render (API)

### Create Web Service

1. [Render Dashboard](https://dashboard.render.com) → **New +** → **Web Service**.
2. Connect your GitHub repo.
3. Settings:

   | Field | Value |
   |-------|--------|
   | **Name** | `faultline-api` |
   | **Region** | Closest to you / users |
   | **Branch** | `main` |
   | **Runtime** | **Docker** |
   | **Dockerfile path** | `./Dockerfile.cloud-api` |
   | **Instance type** | Free |

4. **Health check path:** `/ready`
5. **Port:** `8080` (image `EXPOSE 8080`)

### Environment variables (Render)

```env
FAULTLINE_ENV=production
FAULTLINE_CLOUD_VERSION=24.0
FAULTLINE_DB_AUTO_CREATE=false

FAULTLINE_DATABASE_URL=postgresql+psycopg://...@...neon.tech/neondb?sslmode=require

FAULTLINE_CLOUD_STORAGE=r2
FAULTLINE_S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
FAULTLINE_S3_BUCKET=faultline-checkpoints
FAULTLINE_S3_ACCESS_KEY=...
FAULTLINE_S3_SECRET_KEY=...
FAULTLINE_S3_REGION=auto

FAULTLINE_JWT_SECRET=<openssl rand -hex 32 — at least 32 chars>
FAULTLINE_COOKIE_SECURE=true
FAULTLINE_CORS_ORIGINS=https://faultline.vercel.app

FAULTLINE_RATE_LIMIT_ENABLED=true

FAULTLINE_OAUTH_GOOGLE_CLIENT_ID=...
FAULTLINE_OAUTH_GOOGLE_CLIENT_SECRET=...
FAULTLINE_OAUTH_GITHUB_CLIENT_ID=...
FAULTLINE_OAUTH_GITHUB_CLIENT_SECRET=...
```

**Do not set** `FAULTLINE_SEED_DEMO`.

### Deploy

Save → Render builds and deploys. On each deploy, the container runs migrations then starts Uvicorn.

Verify:

```bash
curl https://faultline-api.onrender.com/ready
curl https://faultline-api.onrender.com/health
```

### Render Free caveats

- Service **sleeps** after ~15 min idle; first request may take **30–60s** (cold start).
- Not suitable for SLA demos without a paid plan or keep-alive ping.
- Local disk is ephemeral — **R2 is required** (you are already using it).

---

## 4. Vercel (Web UI)

### Import project

1. [Vercel](https://vercel.com) → **Add New Project** → import GitHub repo.
2. **Root Directory:** `web`
3. **Framework:** Next.js (auto-detected)
4. Build settings: default (`npm run build`)

### Environment variables (Vercel)

| Variable | Value |
|----------|--------|
| `FAULTLINE_API_URL` | `https://faultline-api.onrender.com` (no trailing slash) |
| `NEXT_PUBLIC_APP_URL` | `https://faultline.vercel.app` (your Vercel URL) |
| `NEXT_PUBLIC_FAULTLINE_API_URL` | Same as `FAULTLINE_API_URL` (training scripts / recovery snippets) |

Do **not** put `FAULTLINE_JWT_SECRET` or R2 keys on Vercel — the BFF uses the session cookie; secrets stay on Render.

Optional:

```env
NEXT_PUBLIC_FAULTLINE_OPERATOR_NAV=false
```

Deploy → note the production URL (e.g. `https://faultline-xxx.vercel.app`).

### Update Render CORS

Set `FAULTLINE_CORS_ORIGINS` on Render to your **exact** Vercel URL (comma-separated if preview + production):

```env
FAULTLINE_CORS_ORIGINS=https://faultline.vercel.app,https://faultline-git-main-youruser.vercel.app
```

Redeploy API after changing CORS.

---

## 5. OAuth (Google + GitHub)

Redirect URIs must hit **Vercel** (BFF), not Render.

### Google Cloud Console

Authorized redirect URI:

```text
https://<your-vercel-domain>/api/auth/oauth/google/callback
```

### GitHub OAuth App

Authorization callback URL:

```text
https://<your-vercel-domain>/api/auth/oauth/github/callback
```

Client ID/secret → Render env (`FAULTLINE_OAUTH_*`), same values you used locally in `.env.local`.

---

## 6. Smoke test (production)

1. Open `https://<vercel>/login` → sign up or OAuth.
2. **Account** → create API key.
3. From your laptop (SDK):

   ```python
   import faultline

   run = faultline.start(
       "smoke-test",
       project="prod",
       api_key="fl_...",
       base_url="https://faultline-api.onrender.com",
   )
   run.log_metrics(1, {"loss": 0.5})
   run.save(1, {"step": 1})
   ```

4. Refresh **Dashboard** on Vercel — run and checkpoint appear.
5. `/runs` → open run → recovery panel loads.

---

## 7. Custom domain (later)

1. **Vercel** → Project → Domains → add `app.yourdomain.com`.
2. Set `NEXT_PUBLIC_APP_URL=https://app.yourdomain.com` on Vercel.
3. Update OAuth redirect URIs to the new domain.
4. Update `FAULTLINE_CORS_ORIGINS` on Render.
5. Optional API subdomain `api.yourdomain.com` → Render custom domain (then update `FAULTLINE_API_URL` / `NEXT_PUBLIC_FAULTLINE_API_URL`).

---

## 8. Checklist

- [ ] Neon DB created; `FAULTLINE_DATABASE_URL` on Render
- [ ] R2 bucket + API token; storage env on Render
- [ ] `FAULTLINE_JWT_SECRET` ≥ 32 chars; `FAULTLINE_SEED_DEMO` unset
- [ ] Render `/ready` returns 200
- [ ] Vercel build green; `FAULTLINE_API_URL` points to Render
- [ ] `FAULTLINE_CORS_ORIGINS` includes Vercel URL
- [ ] OAuth callbacks use Vercel `/api/auth/oauth/.../callback`
- [ ] Login + API key + one training smoke test

See also: [PRODUCTION.md](PRODUCTION.md), [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
