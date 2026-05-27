# Faultline Python SDK

## Install (Faultline Cloud customers)

```bash
pip install faultline-sdk
```

```python
import faultline   # PyPI name: faultline-sdk
```

Set `FAULTLINE_API_KEY` and `FAULTLINE_API_URL` on the machine where training runs. See [../docs/PYPI.md](../docs/PYPI.md).

**Contributors** working in this monorepo: `pip install -e sdk` or `PYTHONPATH=sdk` instead of PyPI.

---

**Start here:** [../README.md](../README.md) (overview, benchmark highlights, demo path).

**Operations:** [../docs/RUNBOOK.md](../docs/RUNBOOK.md) · **Design:** [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)

This package also talks to the Rust `runtime` crate via subprocess (`cargo run` or a release binary) and optional **gRPC** (`GrpcAsyncRuntime` + `serve-grpc`) for local experiments.

## Requirements

- Python 3.10+
- Rust toolchain (`cargo`)
- The `runtime/` crate in this repo

## Run the example

From the repo root:

```bash
python sdk/examples/basic_usage.py
```

The example resolves `runtime/` from the repo layout (`faultline/runtime`), so it works from any working directory.

## Quick usage

```python
from faultline import Runtime

runtime = Runtime(runtime_dir="runtime")  # path to the Rust crate

# Save real UTF-8 payload through the CLI (--data)
runtime.save_checkpoint(1, data="checkpoint payload from Python step 1")
runtime.save_checkpoint(2, data="checkpoint payload from Python step 2")

# Omit data to use Rust's fake placeholder string
runtime.save_checkpoint(3)

print(runtime.list_checkpoints())
print(runtime.latest_checkpoint())
print(runtime.load_latest())  # e.g. step 2 payload if that is latest
print(runtime.prune(keep_last=1))
```

`save_checkpoint` accepts `str`, `bytes` (UTF-8 only for now), or `None`.

## JSON checkpoints

Save and load Python dicts as JSON payloads:

```python
runtime.save_json_checkpoint(1, {
    "step": 1,
    "loss": 0.95,
    "model": "toy-model",
    "weights": [0.1, 0.2, 0.3],
})

latest = runtime.load_latest_json()
print(latest["step"], latest["loss"])
```

`load_latest_json()` raises `ValueError` if there is no checkpoint or the payload is not valid JSON object text.

## Pickle checkpoints

Save and load arbitrary Python objects. Pickle bytes are base64-encoded for the Rust CLI `--data` string transport:

```python
runtime.save_pickle_checkpoint(5, {
    "step": 5,
    "loss": 0.42,
    "optimizer": {"lr": 0.001, "momentum": 0.9},
})

latest = runtime.load_latest_pickle()
```

**Warning:** `pickle` is convenient for local experiments, but **never load checkpoints from untrusted sources** — malicious pickle data can execute arbitrary code.

Run the pickle example:

```bash
python sdk/examples/pickle_usage.py
```

## PyTorch resume demo (Version 4)

Requires PyTorch:

```bash
pip install torch
```

**First run** — trains, saves checkpoints every 5 steps, then simulates a crash at step 12:

```bash
python sdk/examples/pytorch_resume_demo.py
```

**Second run** — loads the latest pickle checkpoint and continues training:

```bash
python sdk/examples/pytorch_resume_demo.py --resume
```

The demo uses `save_pickle_checkpoint` with `model.state_dict()`, `optimizer.state_dict()`, `step`, and `loss`. After the crash, the latest checkpoint is usually from step 10; resume continues from step 11.

## Benchmark (Version 4.1)

Compare save paths (5 saves each): `torch.save()`, one-shot `Runtime`, `PersistentRuntime` JSON/base64, and `PersistentRuntime` file transport:

```bash
conda activate faultline
pip install torch
python sdk/benchmarks/checkpoint_benchmark.py
```

Results are written to `benchmarks/output/` (gitignored), including per-save timings in JSON.

Large payloads use `save_pickle_checkpoint_via_file` / `save_from_file` to avoid CLI size limits. PersistentRuntime startup is reported separately and excluded from per-save averages.

## File transport (Version 5.3)

```python
with PersistentRuntime(runtime_dir="runtime") as runtime:
    runtime.save_pickle_checkpoint_via_file(step, large_payload)
```

Example:

```bash
conda activate faultline
python sdk/examples/file_transport_usage.py
```

## Persistent service mode (Version 5.1)

Keep one `cargo run -- serve` process open instead of spawning per command:

```python
from faultline import PersistentRuntime

with PersistentRuntime(runtime_dir="runtime") as runtime:
    runtime.save_pickle_checkpoint(1, {"step": 1})
    print(runtime.load_latest_pickle())
```

Example:

```bash
conda activate faultline
python sdk/examples/persistent_usage.py
```

## Worker simulation demo (Version 7.0)

Three threaded “workers” enqueue checkpoints into one shared async service; worker 1 crashes and resumes:

```bash
python sdk/examples/worker_simulation.py
```

See the [project README](../README.md#worker-simulation-demo-version-70) for the full narrative.

## Worker-aware metadata (Version 7.1)

Rust `CheckpointEntry` includes optional `worker_id` and `local_step`. Sync and async services support worker commands:

```python
runtime.enqueue_worker_pickle_checkpoint_via_file(worker_id, local_step, payload)
entry = runtime.latest_checkpoint_for_worker(worker_id)
```

`PersistentRuntime` also provides `save_worker_pickle_checkpoint_via_file` and `load_latest_pickle_for_worker`.

Per-worker pruning (after writes have committed):

```python
runtime.prune_per_worker(keep_last_per_worker=1)
```

On the async service, call `prune_per_worker` only after the queue has drained to avoid racing with active writes.

## gRPC transport (Version 8.0+)

```bash
pip install grpcio grpcio-tools
cd runtime && cargo run -- serve-grpc --addr 127.0.0.1:50051
```

Release binary (recommended for benchmarks and long-running jobs):

```bash
cd runtime
cargo build --release
target/release/runtime.exe serve-grpc --addr 127.0.0.1:50051
```

```python
from faultline import GrpcAsyncRuntime

# cargo run (default)
with GrpcAsyncRuntime(runtime_dir="runtime", addr="127.0.0.1:50051") as runtime:
    ...

# release binary
with GrpcAsyncRuntime(
    binary_path="runtime/target/release/runtime.exe",
    addr="127.0.0.1:50051",
) as runtime:
    runtime.enqueue_worker_pickle_checkpoint_via_file(worker_id, local_step, payload)
    runtime.checkpoint_status(global_step)
    runtime.latest_checkpoint_for_worker(worker_id)
    runtime.metrics()
```

**Bytes transport (Version 8.2)** — send pickled payload inline (no temp file):

```python
runtime.enqueue_worker_pickle_checkpoint_bytes(worker_id, local_step, payload)
```

**Streaming bytes (Version 8.3)** — chunk large payloads over client streaming:

```python
runtime.enqueue_worker_pickle_checkpoint_stream(
    worker_id, local_step, payload, chunk_size=256 * 1024
)
```

**Dataset registry (Version 11.0)** — shard assignment on the same gRPC server:

```python
runtime.register_dataset("fake-training", total_samples=100, shard_size=10)
shard = runtime.claim_next_shard(worker_id=0, dataset_name="fake-training")
runtime.complete_shard(worker_id=0, dataset_name="fake-training", shard_id=shard["shard_id"])
released = runtime.release_stale_shards(timeout_ms=500)
```

Example: `python sdk/examples/dataset_worker_simulation.py`

**Observability (Version 12.0)** — read-only runtime inspection:

```python
overview = runtime.get_runtime_overview()
workers = runtime.list_workers()
shards = runtime.list_shards("fake-training", status="pending")
```

Example: `python sdk/examples/observability_usage.py`

**Event log (Version 12.2)** — recent runtime timeline:

```python
events = runtime.list_events(limit=100)
```

Example: `python sdk/examples/grpc_bytes_usage.py`  
Example: `python sdk/examples/grpc_stream_usage.py`  
Benchmark: `python sdk/benchmarks/grpc_bytes_benchmark.py` (file path vs bytes)  
Benchmark: `python sdk/benchmarks/grpc_stream_benchmark.py` (unary vs streaming)  
Benchmark: `python sdk/benchmarks/grpc_checkpoint_benchmark.py` (JSON vs gRPC cargo vs gRPC release)

Regenerate stubs after editing `proto/faultline.proto`:

```bash
python -m grpc_tools.protoc -I proto --python_out=sdk/faultline/grpc --grpc_python_out=sdk/faultline/grpc proto/faultline.proto
```

## Async service mode (Version 6.0)

Enqueue checkpoints without waiting for disk persistence:

```python
from faultline import AsyncPersistentRuntime

with AsyncPersistentRuntime(runtime_dir="runtime") as runtime:
    runtime.enqueue_pickle_checkpoint_via_file(step, payload)
    print(runtime.checkpoint_status(step))  # Queued, Writing, Committed, ...
    print(runtime.metrics())
```

Example:

```bash
python sdk/examples/async_enqueue_usage.py
python sdk/benchmarks/async_checkpoint_benchmark.py
```

## Simulated slow storage (Version 6.1)

Benchmarks can add an artificial per-save delay to mimic network or object storage latency:

```python
with PersistentRuntime(runtime_dir="runtime", write_delay_ms=500) as runtime:
    runtime.save_pickle_checkpoint_via_file(step, payload)

with AsyncPersistentRuntime(runtime_dir="runtime", write_delay_ms=500) as runtime:
    runtime.enqueue_pickle_checkpoint_via_file(step, payload)
```

Rust CLI:

```bash
cargo run -- serve --write-delay-ms 500
cargo run -- serve-async --write-delay-ms 500
```

Compare sync blocking vs async enqueue under slow storage:

```bash
conda activate faultline
python sdk/benchmarks/slow_storage_benchmark.py
```

With `write_delay_ms=500`, sync save blocks on the delay while async enqueue returns after accepting the job and persistence finishes in the background. Results are written to `benchmarks/output/slow_storage_benchmark_summary.txt`.

## Tests

```bash
conda activate faultline
python -m unittest discover sdk/tests
```

Add the `sdk` directory to `PYTHONPATH` or run from a layout where `faultline` is importable (e.g. `PYTHONPATH=sdk`).
