import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.grpc_client import GrpcAsyncRuntime
from faultline.grpc.faultline_pb2 import (
    AsyncMetricsMsg,
    GetRuntimeOverviewResponse,
    ListEventsResponse,
    ListShardsResponse,
    ListWorkersResponse,
    RuntimeEventMsg,
    ShardViewMsg,
    WorkerInfoMsg,
)


class TestObservabilityGrpc(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = GrpcAsyncRuntime(runtime_dir="runtime", start_server=False)
        self.runtime._stub = MagicMock()

    def test_get_runtime_overview(self) -> None:
        response = GetRuntimeOverviewResponse(
            ok=True,
            total_datasets=1,
            total_shards=3,
            pending_shards=2,
            claimed_shards=1,
            completed_shards=0,
            failed_shards=0,
            total_checkpoints=2,
            workers_seen=2,
            async_metrics=AsyncMetricsMsg(
                total_enqueued=2,
                total_committed=2,
                total_failed=0,
                total_dropped=0,
                total_bytes_written=128,
                average_write_time_ms=4.5,
            ),
        )
        self.runtime._stub.GetRuntimeOverview.return_value = response

        overview = self.runtime.get_runtime_overview()
        self.assertEqual(overview["total_shards"], 3)
        self.assertEqual(overview["async_metrics"]["total_committed"], 2)

    def test_list_workers(self) -> None:
        response = ListWorkersResponse(
            ok=True,
            workers=[
                WorkerInfoMsg(
                    worker_id=1,
                    latest_checkpoint_step=1_000_001,
                    latest_local_step=1,
                    committed_checkpoints=1,
                    claimed_shards=0,
                    completed_shards=1,
                )
            ],
        )
        self.runtime._stub.ListWorkers.return_value = response

        workers = self.runtime.list_workers()
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0]["worker_id"], 1)
        self.assertEqual(workers[0]["latest_local_step"], 1)

    def test_list_events(self) -> None:
        response = ListEventsResponse(
            ok=True,
            events=[
                RuntimeEventMsg(
                    event_id=1,
                    timestamp_ms=1000,
                    level="INFO",
                    event_type="dataset_registered",
                    dataset_name="train",
                    message="registered dataset train",
                )
            ],
        )
        self.runtime._stub.ListEvents.return_value = response

        events = self.runtime.list_events(limit=50)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "dataset_registered")
        request = self.runtime._stub.ListEvents.call_args.args[0]
        self.assertEqual(request.limit, 50)

    def test_list_shards_with_status_filter(self) -> None:
        response = ListShardsResponse(
            ok=True,
            shards=[
                ShardViewMsg(
                    shard_id=2,
                    start=20,
                    end=30,
                    status="claimed",
                    worker_id=2,
                    updated_at_ms=12345,
                )
            ],
        )
        self.runtime._stub.ListShards.return_value = response

        shards = self.runtime.list_shards("train", status="claimed")
        self.assertEqual(len(shards), 1)
        self.assertEqual(shards[0]["status"], "claimed")
        request = self.runtime._stub.ListShards.call_args.args[0]
        self.assertEqual(request.dataset_name, "train")
        self.assertEqual(request.status, "claimed")


if __name__ == "__main__":
    unittest.main()
