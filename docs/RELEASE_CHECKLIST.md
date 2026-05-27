# Faultline Cloud v24 — Release checklist

Use this before pointing a public DNS name at production or opening a broad beta.

## Secrets and auth

- [ ] `FAULTLINE_JWT_SECRET` is at least 32 random characters (not the Docker dev default)
- [ ] `FAULTLINE_SEED_DEMO` is **unset** or `0` (no demo user / seeded runs in prod)
- [ ] Google OAuth app: redirect URI `https://<your-domain>/api/auth/oauth/google/callback`
- [ ] GitHub OAuth app: redirect URI `https://<your-domain>/api/auth/oauth/github/callback`
- [ ] `NEXT_PUBLIC_APP_URL` matches the public web origin (HTTPS)
- [ ] `FAULTLINE_COOKIE_SECURE=true`
- [ ] `FAULTLINE_CORS_ORIGINS` lists only your real web origins (no `*`)

## Infrastructure

- [ ] Managed PostgreSQL provisioned; `FAULTLINE_DATABASE_URL` set
- [ ] Empty Postgres: first deploy runs migrations via API entrypoint or `python cloud/scripts/migrate.py`
- [ ] After code with new migrations: redeploy API image (startup runs `upgrade head` automatically)
- [ ] S3/R2/MinIO bucket configured; `FAULTLINE_CLOUD_STORAGE=s3` and keys set
- [ ] Postgres automated backups enabled
- [ ] Object storage versioning or replication considered for checkpoint bucket

## Application hardening

- [ ] `FAULTLINE_ENV=production`
- [ ] `FAULTLINE_RATE_LIMIT_ENABLED=true`
- [ ] HTTPS terminates at Caddy / load balancer / platform edge
- [ ] SMTP or webhooks configured if using alerts (`FAULTLINE_SMTP_*` or per-user webhooks)

## Verification

- [ ] `GET https://<api>/ready` returns 200
- [ ] `GET https://<api>/health` shows database and object storage `ok`
- [ ] Sign up / log in (email and OAuth) on production domain
- [ ] Create API key on Account page; run a short SDK smoke test
- [ ] `python -m unittest discover cloud/tests`
- [ ] `PYTHONPATH=sdk python -m unittest discover sdk/tests`
- [ ] `cd web && npm run build`

## UX / product

- [ ] Account page shows profile, API keys, usage, alerts — **not** Postgres/MinIO internals
- [ ] Operator infrastructure view: `/admin/infrastructure` (optional nav via `NEXT_PUBLIC_FAULTLINE_OPERATOR_NAV=true`)
- [ ] Landing media replaced or placeholders acceptable for beta

## Out of scope (v24)

- Billing / Stripe
- Teams / organizations
- Kubernetes operators
