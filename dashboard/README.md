# Faultline local dashboard

Lightweight read-only UI for runtime observability. The dashboard is a **FastAPI** app that queries the Rust runtime over **gRPC** (same APIs as `GrpcAsyncRuntime.get_runtime_overview()`, `list_workers()`, `list_shards()`).

No auth, no accounts, no deployment — local development only.

## Prerequisites

- Python 3.10+
- Faultline SDK on `PYTHONPATH` (run commands from repo root; `dashboard/app.py` adds `sdk/`)
- `grpcio` (same as SDK demos)
- A running `serve-grpc` process

## 1. Start the Rust runtime

From the repo root:

```bash
cd runtime
cargo build --release
```

Windows:

```bash
target\release\runtime.exe serve-grpc --addr 127.0.0.1:50051
```

Unix:

```bash
./target/release/runtime serve-grpc --addr 127.0.0.1:50051
```

Optional: point the dashboard at another address:

```bash
set FAULTLINE_GRPC_ADDR=127.0.0.1:50055
```

## 2. Create some data (optional)

In another terminal, with the gRPC server still running:

```bash
conda activate faultline
pip install grpcio fastapi uvicorn

python sdk/examples/observability_usage.py
```

Or:

```bash
python sdk/examples/dataset_worker_simulation.py
```

Note: demos that start their **own** gRPC server use a different port (e.g. `50061`). Either run them against `50051` or set `FAULTLINE_GRPC_ADDR` to match the demo port.

## 3. Start the dashboard

From the **repo root**:

```bash
pip install fastapi uvicorn
uvicorn dashboard.app:app --reload
```

## 4. Open the UI

http://127.0.0.1:8000

- Overview cards (datasets, shards, checkpoints, workers, async metrics)
- Worker table
- **Recent events** timeline (checkpoint, dataset, shard, prune activity)
- Dataset / shard table with status filter
- **Refresh** and **auto-refresh every 2 seconds**
- **Alerts** panel (severity, run, message) and **Active alerts** overview card (Version 15.3)

## API (backend)

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Dashboard + gRPC client status |
| `GET /api/overview` | `GetRuntimeOverview` |
| `GET /api/workers` | `ListWorkers` |
| `GET /api/datasets` | `ListDatasets` |
| `GET /api/shards/{dataset_name}?status=pending` | `ListShards` (status optional, case-insensitive) |
| `GET /api/events?limit=100` | `ListEvents` (newest first, max 500) |
| `GET /api/runs` | `ListRuns` |
| `GET /api/runs/{run_id}/metrics` | `ListRunMetrics` |
| `GET /api/alerts` | `EvaluateAlerts` (refreshes in-memory alerts) |

## Tests

```bash
python -m unittest discover dashboard/tests
```

Uses FastAPI `TestClient` with a mocked gRPC client (no live runtime required).
