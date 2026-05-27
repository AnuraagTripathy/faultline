# Faultline Cloud architecture (v22.0)

## Product positioning

**Faultline** is an ML training **continuity and recovery** platform:

- Stream metrics and checkpoints from training scripts
- Survive crashes with checkpoint-backed resume
- Alert on stale runs, missing checkpoints, and recovery opportunities

It is not positioned as a lightweight experiment tracker only.

## Request flow

```
Browser → Next.js /api/* (BFF, session JWT)
              → Cloud API /v1/*

SDK     → Cloud API /v1/* (Bearer API key)
```

## Data stores

| Store | Contents |
|-------|----------|
| **PostgreSQL** | Users, API keys, projects, runs, metrics, events, checkpoints metadata, launch configs, tasks, alert settings |
| **Object storage** | Checkpoint pickle blobs |

SQLite remains supported for local dev via `FAULTLINE_DATABASE_URL=sqlite:///...`.

## Checkpoint path

1. SDK `POST /v1/runs/{id}/checkpoints` (multipart)
2. `CloudCheckpointStorage.save_checkpoint()` → local dir or S3 key `checkpoints/{user}/{run}/step_N.pkl`
3. Row in `checkpoints` with `storage_backend`, `storage_path`, `checksum_sha256`
4. Background task `verify_checkpoint` validates blob health

## Background worker

In-process queue (thread + `queue.Queue`):

| Task | Purpose |
|------|---------|
| `verify_checkpoint` | Post-upload integrity check |
| `evaluate_alerts` | Scan runs; send email/Discord/Slack |
| `resume_run` | Optional async resume relaunch |

Task state in `background_tasks` table.

## Recovery

`GET /v1/runs/{id}/recovery` computes stale/failed/recoverable state from metrics age + checkpoint health. UI recovery panel unchanged; storage abstraction used for health checks.

## Alerts

Per-user settings: email, Discord webhook, Slack webhook. Delivery via SMTP / HTTP webhooks. Deduped per run + alert type (1 hour window).

## Auth model

- Browser: email/password or OAuth (Google/GitHub) session cookie
- SDK/training: API keys only (`fl_...`)
- Browser sessions and machine API keys are intentionally separated

## Recovery credibility signals

- Failure simulation suite: `sdk/examples/failure_scenarios/`
- Recovery benchmark reports: `benchmark/recovery/REPORT.md`
- Dashboard recovery stats: average lost steps, successful resumes, latest latency

## Version history (cloud)

- **16–17** — API, recovery, launch/resume
- **18** — Next.js UI, auth, API keys, live polling
- **19** — Postgres, MinIO/S3, worker, outbound alerts, infrastructure status
- **22** — OAuth, public deployment hardening, failure simulation suite, recovery benchmarks
