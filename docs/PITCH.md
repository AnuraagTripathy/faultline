# Faultline Pitch (v22.0)

## 30-second explanation

Faultline is an ML training continuity and recovery platform. When long-running jobs fail from
spot interruptions, Slurm preemption, or process crashes, Faultline preserves checkpoints, records
failure events, and gives a verified path to resume quickly.

## Recruiter explanation

Built a production-style ML reliability platform across FastAPI, Next.js, Postgres, S3-compatible
storage, and Python SDK integrations. Implemented auth, checkpoint durability, failure simulation,
recovery analytics, and dashboard UX for operational confidence.

## Why not W&B?

W&B is excellent for experiment tracking and model comparison. Faultline is focused on
crash-to-resume continuity: checkpoint durability, stale detection, launch/relaunch semantics, and
recovery outcomes.

## Architecture summary

- SDK/callbacks ingest metrics/events/checkpoints into Cloud API
- Postgres stores run, event, and recovery metadata
- S3/R2/MinIO stores checkpoint blobs + checksums
- Web BFF uses secure browser sessions for dashboard access
- API keys remain the auth model for training scripts

## Infra highlights

- Browser auth with email/password + OAuth (Google/GitHub)
- Object storage abstraction (local, MinIO, S3)
- Background worker for checkpoint verification and alerts
- Public demo workspace with realistic failures and recoveries
- Recovery benchmark reports for credibility

## Pain point addressed

Teams lose expensive GPU progress because failures are common but recovery paths are scattered.
Faultline centralizes failure evidence and resume instructions.

## Differentiation

- Not just metrics visualizations
- Recovery-first product semantics
- Explicit guarantees and known limitations
- Demo and benchmark evidence for reliability claims

## Resume bullets

- Built fault-tolerant ML training continuity platform (FastAPI + Next.js + Postgres + S3)
- Implemented OAuth + API-key dual auth model for browser and training workloads
- Shipped failure simulation suite and recovery benchmarking pipeline
- Designed reliability-focused dashboard UX with recovery stats and timelines

## Interview talking points

- Why separate browser session auth from API-key machine auth
- How checkpoint durability and checksum validation reduce operational risk
- Trade-offs between local Docker simplicity and production hardening
- What recovery semantics can and cannot guarantee in distributed training environments
