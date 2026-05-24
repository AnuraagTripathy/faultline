# Faultline roadmap

## Done

- Atomic checkpoint writes (temp file → fsync → rename) and `metadata.json`
- Rust CLI: save, list, latest, load, prune
- Python SDK: `Runtime`, `PersistentRuntime`, `AsyncPersistentRuntime`
- Sync/async JSON stdin/stdout services (`serve`, `serve-async`)
- File transport for large payloads (temp file + `save_from_file`)
- Simulated slow storage (`write_delay_ms`) and benchmarks
- Worker-aware metadata (`worker_id`, `local_step`, per-worker latest/prune)
- gRPC transport: unary file, unary bytes, client streaming
- Release binary support for `serve-grpc` (`binary_path` in Python)
- `StorageBackend` trait + `LocalStorageBackend`
- Metadata I/O behind storage abstraction
- `InMemoryStorageBackend` for tests
- `FailureInjectingStorageBackend` for reliability tests
- Failure injection demo (`cargo run -- failure-demo`)
- PyTorch crash/resume and multi-worker simulation examples
- 66+ Rust tests, 40 Python unit tests (see runbook)

## Next

- Failure simulation **benchmark** (automated sweeps over injected failures)
- PyO3 or in-process Rust API (reduce subprocess overhead)
- Checkpoint format versioning / migration notes
- CI workflow (Rust + Python on push)
- Publish Python package (`pip install -e sdk`)

## Future

- S3-compatible (or GCS/NFS) `StorageBackend` implementation
- Distributed / multi-rank checkpoint coordination
- Production hardening: auth on gRPC, TLS, configurable limits
- Durable queue across process restarts
- Cross-language checkpoint payloads (beyond pickle)

## Explicitly out of scope (for now)

- Full distributed training framework
- Replacement for `torch.save` on fast local SSD
- Multi-tenant cloud checkpoint service
