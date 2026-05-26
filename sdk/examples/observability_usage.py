"""
Observability APIs demo (Version 12.0).

Registers a small dataset, runs a few shard claims/completions with checkpoints,
then prints runtime overview, worker table, and shard table.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline import GrpcAsyncRuntime

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "runtime"
DATASETS_DIR = REPO_ROOT / "datasets"
CHECKPOINTS_DIR = REPO_ROOT / "checkpoints"

DATASET_NAME = "obs-demo"
TOTAL_SAMPLES = 30
SHARD_SIZE = 10
GRPC_ADDR = "127.0.0.1:50062"


def print_overview(overview: dict) -> None:
    print("=== Runtime overview ===")
    for key in (
        "total_datasets",
        "total_shards",
        "pending_shards",
        "claimed_shards",
        "completed_shards",
        "failed_shards",
        "total_checkpoints",
        "workers_seen",
    ):
        print(f"  {key}: {overview[key]}")
    print("  async_metrics:")
    for key, value in overview.get("async_metrics", {}).items():
        print(f"    {key}: {value}")
    print()


def print_workers(workers: list[dict]) -> None:
    print("=== Workers ===")
    if not workers:
        print("  (none)")
        print()
        return

    header = (
        f"{'worker':>6}  {'latest_step':>12}  {'local':>6}  "
        f"{'ckpts':>6}  {'claimed':>8}  {'done':>6}"
    )
    print(header)
    print("-" * len(header))
    for worker in workers:
        latest_step = worker.get("latest_checkpoint_step")
        latest_local = worker.get("latest_local_step")
        print(
            f"{worker['worker_id']:>6}  "
            f"{latest_step if latest_step is not None else '-':>12}  "
            f"{latest_local if latest_local is not None else '-':>6}  "
            f"{worker['committed_checkpoints']:>6}  "
            f"{worker['claimed_shards']:>8}  "
            f"{worker['completed_shards']:>6}"
        )
    print()


def print_shards(title: str, shards: list[dict]) -> None:
    print(title)
    if not shards:
        print("  (none)")
        print()
        return

    header = f"{'id':>3}  {'start':>5}  {'end':>5}  {'status':>10}  {'worker':>6}  {'updated_at':>12}"
    print(header)
    print("-" * len(header))
    for shard in shards:
        print(
            f"{shard['shard_id']:>3}  "
            f"{shard['start']:>5}  "
            f"{shard['end']:>5}  "
            f"{shard['status']:>10}  "
            f"{shard.get('worker_id') or '-':>6}  "
            f"{shard.get('updated_at_ms') or '-':>12}"
        )
    print()


def main() -> None:
    print("Faultline observability demo\n")

    if DATASETS_DIR.exists():
        shutil.rmtree(DATASETS_DIR)
    if CHECKPOINTS_DIR.exists():
        shutil.rmtree(CHECKPOINTS_DIR)

    with GrpcAsyncRuntime(
        runtime_dir=str(RUNTIME_DIR),
        addr=GRPC_ADDR,
        queue_capacity=8,
    ) as runtime:
        runtime.register_dataset(DATASET_NAME, TOTAL_SAMPLES, SHARD_SIZE)
        print(f"Registered dataset {DATASET_NAME!r}\n")

        shard0 = runtime.claim_next_shard(0, DATASET_NAME)
        assert shard0 is not None
        runtime.enqueue_worker_pickle_checkpoint_bytes(
            0, int(shard0["shard_id"]), {"shard": shard0["shard_id"], "worker": 0}
        )
        runtime.complete_shard(0, DATASET_NAME, int(shard0["shard_id"]))

        shard1 = runtime.claim_next_shard(1, DATASET_NAME)
        assert shard1 is not None
        runtime.enqueue_worker_pickle_checkpoint_bytes(
            1, int(shard1["shard_id"]), {"shard": shard1["shard_id"], "worker": 1}
        )
        runtime.complete_shard(1, DATASET_NAME, int(shard1["shard_id"]))

        runtime.claim_next_shard(2, DATASET_NAME)
        time.sleep(0.05)

        overview = runtime.get_runtime_overview()
        workers = runtime.list_workers()
        all_shards = runtime.list_shards(DATASET_NAME)
        pending_shards = runtime.list_shards(DATASET_NAME, status="pending")
        claimed_shards = runtime.list_shards(DATASET_NAME, status="claimed")

    print_overview(overview)
    print_workers(workers)
    print_shards("=== All shards ===", all_shards)
    print_shards("=== Pending shards ===", pending_shards)
    print_shards("=== Claimed shards ===", claimed_shards)
    print("Observability demo complete.")


if __name__ == "__main__":
    main()
