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

### 5. Failure injection demo

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
Remove-Item -Recurse -Force benchmarks\output -ErrorAction SilentlyContinue
```

Unix:

```bash
rm -rf checkpoints benchmarks/output
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

## Docs index

- [../README.md](../README.md) — project overview
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [ROADMAP.md](ROADMAP.md) — done / next / future
- [../sdk/README.md](../sdk/README.md) — Python API reference
