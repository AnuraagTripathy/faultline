# Checkpoint storage backends

Faultline persists checkpoint blobs and `metadata.json` through the Rust `StorageBackend` trait. The checkpoint **format** (metadata JSON schema, `step_NNNN.ckpt` filenames, logical paths like `checkpoints/step_0001.ckpt`) is the same for every backend.

## Local filesystem (`LocalStorageBackend`)

**Used by:** default `serve-grpc --storage local`, CLI `save` / `list` / `prune`, JSON `serve` / `serve-async`.

**Layout on disk:**

- Blobs: `<checkpoint_dir>/step_NNNN.ckpt`
- Metadata: `<checkpoint_dir>/metadata.json`
- Metadata paths stored in JSON: `checkpoints/step_NNNN.ckpt`

**Atomicity:** `write_atomic` writes a `.tmp` file, fsyncs, then `rename`s to the final name. Metadata is updated only after the blob commit succeeds. This matches typical filesystem atomic-rename semantics.

## In-memory (`InMemoryStorageBackend`)

**Used by:** unit tests, `failure-demo`, failure-injection tests.

**Behavior:** Hash map keyed by metadata-relative paths. No durability across process restarts.

**Atomicity:** Single-process, in-memory updates; used to simulate failures, not production.

## Failure injection (`FailureInjectingStorageBackend`)

**Used by:** `cargo run -- failure-demo` and storage tests.

Wraps another backend and can fail the next `write_atomic`, `write_metadata`, `read`, or `delete` call. Demonstrates that **metadata remains the source of truth**: a blob without metadata is not a committed checkpoint.

## S3-compatible (`S3StorageBackend`)

**Used by:** `serve-grpc --storage s3` with MinIO or any S3-compatible endpoint. No real AWS account is required for local MinIO.

**Configuration (CLI flags):**

| Flag | Purpose |
|------|---------|
| `--s3-endpoint-url` | API endpoint (MinIO: `http://127.0.0.1:9000`) |
| `--s3-bucket` | Bucket name |
| `--s3-access-key` / `--s3-secret-key` | Credentials (MinIO defaults: `minioadmin`) |
| `--s3-region` | Region string (MinIO often accepts `us-east-1`) |
| `--s3-prefix` | Key prefix inside the bucket |

**Object layout:**

- Blobs: `<prefix>/checkpoints/step_NNNN.ckpt`
- Metadata: `<prefix>/metadata.json`
- Metadata paths in JSON: still `checkpoints/step_NNNN.ckpt` (same as local)

**Atomicity caveat:** Object stores do not provide POSIX-style atomic rename. The S3 backend:

1. `PUT`s the checkpoint directly to its **final** object key.
2. Updates `metadata.json` only after the blob upload succeeds (handled by `CheckpointManager`).

If the process crashes **after** the blob `PUT` but **before** metadata is written, an orphan object may exist; it will not appear in `list` / `latest` because metadata is authoritative. Concurrent writers can also observe last-writer-wins on metadata without rename isolation. For strict commit semantics, use the local backend or an external coordination layer.

Path-style addressing is enabled for MinIO compatibility.

## Quick start: MinIO + gRPC

```bash
# Terminal 1 — object store
docker compose up -d

# Terminal 2 — gRPC runtime (from repo root)
cd runtime
cargo run -- serve-grpc --storage s3 \
  --s3-endpoint-url http://127.0.0.1:9000 \
  --s3-bucket faultline \
  --s3-access-key minioadmin \
  --s3-secret-key minioadmin \
  --s3-region us-east-1 \
  --s3-prefix faultline \
  --addr 127.0.0.1:50051
```

Verify objects (MinIO console: http://127.0.0.1:9001, or `mc ls local/faultline` inside the `create-bucket` container):

```bash
cd sdk
python examples/grpc_stream_usage.py
# Expect keys under faultline/checkpoints/ and faultline/metadata.json
```

Dataset registry and dashboard still use **local** `datasets/` on disk; only checkpoint blobs/metadata use S3 when `--storage s3` is set.

## Integration testing with MinIO

Normal `cargo test` and `python -m unittest discover sdk/tests` do **not** require MinIO.

Optional manual / CI integration flow:

1. `docker compose up -d` and wait for `create-bucket` to finish.
2. Start `serve-grpc` with `--storage s3` as above.
3. Run `python sdk/examples/grpc_stream_usage.py` (or `grpc_worker_usage.py`).
4. Confirm objects in bucket `faultline` under prefix `faultline/`.

Optional automated integration (not wired into default CI): add a `#[ignore]` test that reads `FAULTLINE_S3_ENDPOINT` and skips when unset.

## Choosing a backend

| Backend | Durability | Best for |
|---------|------------|----------|
| Local | Disk | Dev, single-node, strongest local atomicity |
| In-memory | None | Tests |
| Failure inject | Depends on inner | Chaos / recovery demos |
| S3 / MinIO | Object store | ML-style remote checkpoint persistence |
