# Faultline runbook

Exact commands to set up, test, run demos, and clean artifacts. Run from repo root unless noted.

---

## Setup (conda)

```bash
conda create -n faultline python=3.11 -y
conda activate faultline
```

Optional for PyTorch demos and benchmarks:

```bash
pip install torch grpcio grpcio-tools
```

Rust: install [rustup](https://rustup.rs/) so `cargo` is on `PATH`.

---

## Build release binary (optional, for gRPC benchmarks)

```bash
cd runtime
cargo build --release
```

Binary (Windows): `runtime/target/release/runtime.exe`  
Binary (Unix): `runtime/target/release/runtime`

---

## Run tests

```bash
cd runtime
cargo test
```

```bash
conda activate faultline
python -m unittest discover sdk/tests
```

One-liner from repo root:

```bash
cd runtime && cargo test && cd .. && python -m unittest discover sdk/tests
```

---

## Python path

Most examples add `sdk` to `sys.path` internally. Alternatively:

```bash
conda activate faultline
set PYTHONPATH=sdk          # Windows cmd
# export PYTHONPATH=sdk     # bash
```

---

## Demos (recommended reviewer order)

### 1. PyTorch crash / resume

```bash
conda activate faultline
python sdk/examples/pytorch_resume_demo.py
python sdk/examples/pytorch_resume_demo.py --resume
```

### 2. Slow storage benchmark

Simulated 500 ms write delay; compares sync blocking vs async enqueue.

```bash
conda activate faultline
python sdk/benchmarks/slow_storage_benchmark.py
```

Summary: `benchmarks/output/slow_storage_benchmark_summary.txt`

### 3. gRPC bytes vs file transport benchmark

```bash
conda activate faultline
cd runtime && cargo build --release && cd ..
python sdk/benchmarks/grpc_bytes_benchmark.py
```

### 4. Worker simulation

```bash
python sdk/examples/worker_simulation.py
```

### 5. Local dashboard

```bash
# Terminal 1
cd runtime
cargo build --release
target/release/runtime.exe serve-grpc --addr 127.0.0.1:50051

# Terminal 2 (optional data)
python sdk/examples/observability_usage.py

# Terminal 3 (repo root)
pip install fastapi uvicorn
uvicorn dashboard.app:app --reload
```

Open http://127.0.0.1:8000

### 6. Observability APIs

```bash
conda activate faultline
python sdk/examples/observability_usage.py
```

### 7. Dataset + shard coordination

```bash
conda activate faultline
python sdk/examples/dataset_worker_simulation.py
```

### 8. Failure injection demo

```bash
cd runtime
cargo run -- failure-demo
```

Summary: `benchmarks/output/failure_demo_summary.txt`

---

## Other useful demos

| Command | Shows |
|---------|--------|
| `python sdk/examples/basic_usage.py` | JSON via one-shot CLI |
| `python sdk/examples/async_enqueue_usage.py` | Async enqueue + status |
| `python sdk/examples/grpc_bytes_usage.py` | gRPC inline bytes |
| `python sdk/examples/grpc_stream_usage.py` | gRPC chunked stream (~8 MiB) |
| `python sdk/examples/grpc_worker_usage.py` | gRPC worker enqueue |

---

## Rust CLI smoke test

```bash
cd runtime
cargo run -- save 1 --data "hello"
cargo run -- list
cargo run -- latest
cargo run -- load-latest
```

---

## Long-running services

Sync JSON service:

```bash
cd runtime
cargo run -- serve
```

Async JSON service:

```bash
cargo run -- serve-async --queue-capacity 16
```

gRPC service:

```bash
cargo run -- serve-grpc --addr 127.0.0.1:50051
# or: target/release/runtime.exe serve-grpc --addr 127.0.0.1:50051
```

---

## Clean checkpoints and benchmark output

From repo root (PowerShell):

```powershell
Remove-Item -Recurse -Force checkpoints -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force datasets -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force benchmarks\output -ErrorAction SilentlyContinue
```

Unix:

```bash
rm -rf checkpoints datasets benchmarks/output
```

Re-create output dir if needed:

```bash
mkdir -p benchmarks/output
```

---

## Regenerate gRPC Python stubs

After editing `proto/faultline.proto`:

```bash
python -m grpc_tools.protoc -I proto --python_out=sdk/faultline/grpc --grpc_python_out=sdk/faultline/grpc proto/faultline.proto
```

Then fix the import in `sdk/faultline/grpc/faultline_pb2_grpc.py`:

`import faultline_pb2` → `from . import faultline_pb2`

Or use `sdk/scripts/generate_grpc_stubs.sh` on Unix.

---

## Cloud mode MVP (Version 16.2–16.3)

Separate product layer — does **not** replace local `serve-grpc` or the dashboard on port 8000.

```bash
pip install fastapi uvicorn pydantic
uvicorn cloud.api.app:app --reload --port 8080
```

```bash
set PYTHONPATH=sdk
python sdk/examples/cloud_run_demo.py
python sdk/examples/cloud_checkpoint_demo.py
```

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8080/ | Landing page |
| http://127.0.0.1:8080/getting-started | Connect guide |
| http://127.0.0.1:8080/dashboard | Runs, metrics, checkpoints, usage |

Dev API key: `fl_dev_local` (`Authorization: Bearer fl_dev_local`).

Checkpoint files: `cloud/data/checkpoints/<user_id>/<run_id>/step_<N>.pkl` (override with `FAULTLINE_CLOUD_CHECKPOINTS_DIR`).

```bash
python -m unittest discover cloud/tests
```

---

## Docs index

- [../README.md](../README.md) — project overview
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [ROADMAP.md](ROADMAP.md) — done / next / future
- [../sdk/README.md](../sdk/README.md) — Python API reference
