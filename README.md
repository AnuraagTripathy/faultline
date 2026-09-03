# Faultline

Checkpointing and crash-to-resume for long ML training runs, so a preemption costs you minutes instead of days.

**Live: [faultline-eight.vercel.app](https://faultline-eight.vercel.app)** · **SDK: [`pip install faultline-sdk`](https://pypi.org/project/faultline-sdk/)**

## What is actually interesting here

`torch.save` on a local SSD is fast and this project does not try to beat it. The problem it addresses is what happens when the storage behind a checkpoint is slow, remote, or unreliable, and the training loop is blocked on it.

**The write is decoupled from the loop.** The Rust runtime (`runtime/`) takes a checkpoint onto a bounded async queue and returns immediately, so the caller stalls for tens of milliseconds instead of the full write. Against a storage backend with a 500ms injected delay, the caller-side cost drops from roughly 500 to 550ms down to roughly 24 to 40ms. Time-to-commit is still about 1.5 seconds; the win is that the training step is no longer waiting on it. Numbers are from `sdk/benchmarks/slow_storage_benchmark.py` on a developer machine and will vary.

**Metadata is the source of truth, not the blob.** A failed write must not advance `latest`. `cargo run -- failure-demo` injects storage failures and shows that it does not. The known hole is the reverse ordering: if the blob write succeeds and the metadata commit then fails, an orphan blob is left behind.

**Transport shape matters more than expected.** Handing the runtime a file path costs roughly 16 to 28ms per enqueue because of temp-file I/O; sending the payload inline as bytes over gRPC costs roughly 0.7 to 0.8ms for a 4.5KB pickle. Both paths exist (`sdk/benchmarks/grpc_bytes_benchmark.py`) because the tradeoff inverts as payloads get large.

**Two halves in one repo.** The Rust runtime with its storage trait, async queue, and gRPC service is the local systems half. The cloud half is a FastAPI API with Postgres and Cloudflare R2, a Next.js dashboard with OAuth, and the published Python SDK, which is what turns it from a benchmark into something with runs, projects, alerts, and a resume command.

## Stack

Rust (tokio, tonic, prost, aws-sdk-s3) for the persistence runtime. Python for the SDK, examples, and benchmarks, with PyTorch integration. FastAPI, SQLAlchemy, Alembic, and Postgres for the cloud API. Next.js and TypeScript for the dashboard. Cloudflare R2 for object storage, MinIO locally. Docker Compose for the local stack. Deployed across Vercel, Render, and Neon, with the SDK on PyPI.

## Running it locally

Rust via [rustup](https://rustup.rs/), and Python 3.11.

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install torch grpcio grpcio-tools
```

The Rust runtime and its tests:

```bash
cd runtime
cargo test
cargo build --release          # needed for the gRPC benchmarks
cargo run -- failure-demo      # injected storage failures, latest never advances
```

The Python side, from the repo root:

```bash
python -m unittest discover sdk/tests
python sdk/examples/pytorch_resume_demo.py            # train, crash
python sdk/examples/pytorch_resume_demo.py --resume   # pick up where it stopped
```

Local object storage (MinIO on ports 9000 and 9001, bucket created for you):

```bash
docker compose up -d
```

For the web app, copy `.env.local.example` to `.env.local` and fill in the Google and GitHub OAuth credentials, then run the dashboard from `web/`. `docker-compose.cloud.yml` brings up the cloud API stack.

`docs/RUNBOOK.md` has the exact command for every demo and benchmark.

## What is unfinished

- The runbook and several examples still say `conda activate faultline`. A plain venv works; only the conda name is assumed.
- The SDK is published to PyPI as `faultline-sdk`, but the packaging metadata (`pyproject.toml`) is not committed here, so you cannot build or publish the distribution from a clean clone.
- No distributed training support. There are no ranks, no collectives, and no shared remote store, so multi-worker behavior is a local simulation only.
- Orphan blobs are possible when a blob write commits and its metadata write does not. There is no reaper.
- `web/public/assets/videos/` holds roughly 18MB of committed demo footage, which dominates the clone size.
- The badges at the top are static images, not a CI status.
