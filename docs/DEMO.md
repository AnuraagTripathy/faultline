# Faultline demos (v22.0)

Faultline is an **ML training continuity and recovery platform** — not experiment tracking.

## Prerequisites

```bash
cp .env.local.example .env.local   # then add OAuth creds (file is gitignored)
docker compose -f docker-compose.cloud.yml up --build
```

OAuth (optional): copy `.env.local.example` → `.env.local` and set Google/GitHub client ID/secret.
Redirect URIs must be `http://localhost:3000/api/auth/oauth/google/callback` and
`http://localhost:3000/api/auth/oauth/github/callback`. Do not commit `.env.local`.

- Dashboard: http://localhost:3000
- **Live demo (no signup):** http://localhost:3000/demo
- **Pre-seeded account:** `demo@faultline.local` / `faultlinedemo`
- API: http://127.0.0.1:8080
- Dev API key: `fl_dev_local` (also has seeded runs)

## 1. Zero-code Docker demo (recommended)

1. `docker compose -f docker-compose.cloud.yml up --build`
2. Open http://localhost:3000/demo for interactive walkthrough
3. Log in with `demo@faultline.local` / `faultlinedemo`
4. Open **Runs** — see running, failed (recoverable), and completed jobs

## 2. CLI live simulation

```bash
export FAULTLINE_API_KEY=fl_dev_local
export FAULTLINE_API_URL=http://127.0.0.1:8080
PYTHONPATH=sdk python -m faultline.cli demo --open
```

### Failure simulation suite

```bash
PYTHONPATH=sdk python -m faultline.cli demo crash --scenario process_kill_resume
PYTHONPATH=sdk python -m faultline.cli demo crash --scenario spot_gpu_interruption
```

Scenarios live in `sdk/examples/failure_scenarios/`.

## 3. Local laptop demo

```bash
export FAULTLINE_API_KEY=fl_your_key
python -m faultline.cli init
python train.py
```

## 2. Simulated crash demo

```bash
PYTHONPATH=sdk python sdk/examples/demo_crash_resume.py
# after simulated crash:
PYTHONPATH=sdk python sdk/examples/demo_crash_resume.py --run-id <RUN_ID>
```

## 3. Auto-resume demo

```python
import faultline

run, start_step = faultline.auto_resume(
    run_id="...",
    model=model,
    optimizer=optimizer,
    api_key="fl_...",
)
```

Or `faultline.start(..., resume_if_available=True, model=model, optimizer=optimizer)`.

## 4. Slurm / HPC walkthrough

1. Register launch config in your training script: `run.register_slurm_script("job.slurm")`
2. Train on the cluster with `base_url` pointing at your deployed API
3. After failure, use the dashboard **Resume Run** (API host relaunch) or `run.resume()` from the SDK

See `sdk/examples/slurm_resume_example.py`.

## 5. Docker deployment

Full stack: `docker-compose.cloud.yml` (Postgres + MinIO + API + web).

Production notes: [PRODUCTION.md](./PRODUCTION.md)

## 6. Public deployment checklist

- [ ] Set strong `FAULTLINE_JWT_SECRET` and database password
- [ ] Configure S3/MinIO credentials and bucket
- [ ] Enable HTTPS termination (reverse proxy)
- [ ] Set `FAULTLINE_API_URL` / `NEXT_PUBLIC_FAULTLINE_API_URL` to public API URL
- [ ] Configure alert webhooks (Slack/Discord/email)
- [ ] Schedule Postgres backups and object-storage lifecycle rules
- [ ] Configure OAuth providers (Google/GitHub) in API env vars
- [ ] Pin Docker images (`faultline/cloud-api:20.0`, `faultline/web:20.0` when published)

## Framework demos

- Hugging Face: `sdk/examples/demo_huggingface.py`
- Lightning: `sdk/examples/demo_lightning.py`
