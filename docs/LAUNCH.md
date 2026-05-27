# Faultline launch kit (v21.0)

Faultline is an **ML training continuity and recovery platform** — not experiment tracking.

## Launch tweet

> We built Faultline so you never lose days of GPU training to a spot preemption or Slurm eviction again.
> Checkpoints, crash recovery, and one-line resume for PyTorch, HuggingFace, and Lightning.
> Try the live demo: [your-url]/demo
> `docker compose -f docker-compose.cloud.yml up --build`

## Hacker News (Show HN)

**Title:** Show HN: Faultline – recover long-running ML training after crashes (checkpoints + auto-resume)

**Body outline:**
- Problem: multi-day training jobs die on laptops, HPC, cloud GPUs
- What we built: Cloud API + dashboard + SDK integrations
- Demo: pre-seeded Docker stack, no code required
- Not: another W&B clone — we focus on *which step to resume* and *how to relaunch*
- Ask: feedback on recovery UX and HPC launch configs

## Reddit (r/MachineLearning)

**Title:** [P] Faultline – open-source training continuity platform (crash recovery, not experiment tracking)

Link to GitHub + live demo. Emphasize Slurm/HPC and `faultline auto_resume()`.

## Demo flow (2 minutes)

1. `docker compose -f docker-compose.cloud.yml up --build`
2. Open http://localhost:3000/demo (no signup)
3. Log in: `demo@faultline.local` / `faultlinedemo`
4. Dashboard → see 3 seeded runs
5. Open failed run → recovery panel + resume command
6. Optional: `PYTHONPATH=sdk python -m faultline.cli demo --open`

## Screenshots needed

- [ ] Hero dashboard with loss curve (`assets/screenshots/dashboard.png`)
- [ ] Recovery panel on failed run
- [ ] Checkpoint timeline
- [ ] Homepage product mock (`assets/screenshots/product-hero.png`)
- [ ] CLI demo terminal output

## GIF checklist

- [ ] Crash → dashboard shows failed + recoverable
- [ ] `faultline demo` streaming metrics
- [ ] Resume command copy-paste
- [ ] Quickstart wizard changing framework tabs

## Portfolio bullets

- Built full-stack ML infrastructure: FastAPI, Postgres, MinIO, Next.js
- Designed recovery-first UX (not chart-first experiment tracking)
- HuggingFace + Lightning integrations with auto-resume
- Docker Compose one-command demo with seeded data

## Recruiter explanation (30 seconds)

"Faultline is infrastructure for ML engineers who run training jobs for hours or days. When a GPU gets preempted or a cluster node dies, you lose progress unless checkpoints and restart logic are bulletproof. Faultline streams metrics and checkpoints to a cloud API, verifies checkpoint health, and tells you exactly how to resume — including Slurm relaunch. I built the backend, storage layer, SDK, and product UI."

## What makes Faultline different

| Experiment trackers | Faultline |
|----------------------|-----------|
| Compare runs visually | Recover a specific run after failure |
| Manual artifact uploads | Automatic checkpoint pipeline |
| "What was the loss?" | "What step do I restart from?" |
