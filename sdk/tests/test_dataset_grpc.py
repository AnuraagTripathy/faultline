import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.grpc_client import GrpcAsyncRuntime
from faultline.grpc.faultline_pb2 import (
    ClaimNextShardResponse,
    CompleteShardResponse,
    RegisterDatasetResponse,
    ReleaseStaleShardsResponse,
    ShardMetadataMsg,
)


class TestDatasetGrpc(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = GrpcAsyncRuntime(runtime_dir="runtime", start_server=False)
        self.runtime._stub = MagicMock()

    def test_register_dataset(self) -> None:
        response = RegisterDatasetResponse(
            ok=True,
            dataset={
                "name": "train",
                "total_samples": 100,
                "shard_size": 10,
                "total_shards": 10,
            },
        )
        self.runtime._stub.RegisterDataset.return_value = response

        metadata = self.runtime.register_dataset("train", 100, 10)
        self.assertEqual(metadata["total_shards"], 10)

    def test_claim_next_shard_none(self) -> None:
        self.runtime._stub.ClaimNextShard.return_value = ClaimNextShardResponse(
            ok=True, claimed=False
        )
        self.assertIsNone(self.runtime.claim_next_shard(1, "train"))

    def test_claim_next_shard_returns_dict(self) -> None:
        shard = ShardMetadataMsg(
            shard_id=2,
            dataset_name="train",
            start_sample=20,
            end_sample=30,
            status="claimed",
            claimed_by=1,
        )
        self.runtime._stub.ClaimNextShard.return_value = ClaimNextShardResponse(
            ok=True, claimed=True, shard=shard
        )
        result = self.runtime.claim_next_shard(1, "train")
        assert result is not None
        self.assertEqual(result["shard_id"], 2)
        self.assertEqual(result["status"], "claimed")

    def test_complete_shard(self) -> None:
        shard = ShardMetadataMsg(
            shard_id=1,
            dataset_name="train",
            start_sample=10,
            end_sample=20,
            status="completed",
        )
        self.runtime._stub.CompleteShard.return_value = CompleteShardResponse(
            ok=True, shard=shard
        )
        result = self.runtime.complete_shard(1, "train", 1)
        self.assertEqual(result["status"], "completed")

    def test_release_stale_shards(self) -> None:
        self.runtime._stub.ReleaseStaleShards.return_value = ReleaseStaleShardsResponse(
            ok=True, released_count=1
        )
        self.assertEqual(self.runtime.release_stale_shards(500), 1)


if __name__ == "__main__":
    unittest.main()
