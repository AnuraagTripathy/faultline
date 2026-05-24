import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.grpc_client import (
    GrpcAsyncRuntime,
    build_serve_grpc_command,
    checkpoint_chunk_count,
    iter_checkpoint_chunks,
)
from faultline.grpc.faultline_pb2 import (
    CheckpointEntry,
    EnqueueWorkerBytesRequest,
    EnqueueWorkerFromFileRequest,
    LatestForWorkerResponse,
    MetricsResponse,
    StatusResponse,
)


class TestRuntimeGrpc(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = GrpcAsyncRuntime(runtime_dir="runtime", start_server=False)
        self.runtime._stub = MagicMock()

    def test_checkpoint_chunk_count(self) -> None:
        self.assertEqual(checkpoint_chunk_count(0, 1024), 1)
        self.assertEqual(checkpoint_chunk_count(1, 1024), 1)
        self.assertEqual(checkpoint_chunk_count(1025, 1024), 2)

    def test_iter_checkpoint_chunks_emits_expected_count(self) -> None:
        data = b"x" * 5000
        chunks = list(iter_checkpoint_chunks(1, 2, data, chunk_size=2000))
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertFalse(chunks[0].is_last)
        self.assertTrue(chunks[-1].is_last)
        self.assertEqual(b"".join(chunk.data for chunk in chunks), data)

    def test_enqueue_worker_stream_calls_stub(self) -> None:
        response = MagicMock()
        response.ok = True
        response.message = "streamed"
        self.runtime._stub.EnqueueWorkerBytesStream.return_value = response

        payload = {"value": list(range(100))}
        message = self.runtime.enqueue_worker_pickle_checkpoint_stream(
            3, 7, payload, chunk_size=64
        )

        self.assertEqual(message, "streamed")
        chunks = list(self.runtime._stub.EnqueueWorkerBytesStream.call_args.args[0])
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0].worker_id, 3)
        self.assertEqual(chunks[0].local_step, 7)
        self.assertEqual(chunks[0].step, 3_000_007)
        self.assertTrue(chunks[-1].is_last)

    def test_enqueue_worker_bytes_builds_request(self) -> None:
        response = MagicMock()
        response.ok = True
        response.message = "queued bytes"
        self.runtime._stub.EnqueueWorkerBytes.return_value = response

        payload = {"tensor": [1, 2, 3]}
        message = self.runtime.enqueue_worker_pickle_checkpoint_bytes(2, 5, payload)

        self.assertEqual(message, "queued bytes")
        request = self.runtime._stub.EnqueueWorkerBytes.call_args.args[0]
        self.assertIsInstance(request, EnqueueWorkerBytesRequest)
        self.assertEqual(request.worker_id, 2)
        self.assertEqual(request.local_step, 5)
        self.assertEqual(request.step, 2_000_005)
        self.assertTrue(len(request.data) > 0)

    def test_enqueue_worker_builds_request(self) -> None:
        response = MagicMock()
        response.ok = True
        response.message = "queued"
        self.runtime._stub.EnqueueWorkerFromFile.return_value = response

        message = self.runtime.enqueue_worker_checkpoint_file(1, 10, 1_000_010, "x.bin")

        self.assertEqual(message, "queued")
        request = self.runtime._stub.EnqueueWorkerFromFile.call_args.args[0]
        self.assertIsInstance(request, EnqueueWorkerFromFileRequest)
        self.assertEqual(request.worker_id, 1)
        self.assertEqual(request.local_step, 10)
        self.assertEqual(request.step, 1_000_010)

    def test_latest_for_worker_parses_entry(self) -> None:
        entry = CheckpointEntry(
            step=1_000_010,
            path="checkpoints/step_1000010.ckpt",
            status="committed",
            worker_id=1,
            local_step=10,
        )

        response = LatestForWorkerResponse(ok=True, error="", checkpoint=entry)
        self.runtime._stub.LatestForWorker.return_value = response

        parsed = self.runtime.latest_checkpoint_for_worker(1)
        assert parsed is not None
        self.assertEqual(parsed["local_step"], 10)

    def test_metrics_maps_fields(self) -> None:
        response = MetricsResponse(
            ok=True,
            error="",
            total_enqueued=3,
            total_committed=2,
            total_failed=0,
            total_dropped=0,
            total_bytes_written=100,
            total_write_time_ms=5,
            average_write_time_ms=2.5,
        )
        self.runtime._stub.Metrics.return_value = response

        metrics = self.runtime.metrics()
        self.assertEqual(metrics["total_enqueued"], 3)
        self.assertEqual(metrics["average_write_time_ms"], 2.5)

    def test_checkpoint_status(self) -> None:
        self.runtime._stub.Status.return_value = StatusResponse(
            ok=True, error="", status="Committed"
        )
        self.assertEqual(self.runtime.checkpoint_status(5), "Committed")

    def test_build_serve_grpc_command_cargo(self) -> None:
        command = build_serve_grpc_command(
            "127.0.0.1:50051",
            runtime_dir="runtime",
            queue_capacity=8,
        )
        self.assertEqual(
            command,
            [
                "cargo",
                "run",
                "--",
                "serve-grpc",
                "--addr",
                "127.0.0.1:50051",
                "--queue-capacity",
                "8",
            ],
        )

    def test_build_serve_grpc_command_binary_path(self) -> None:
        binary = Path("runtime/target/release/runtime.exe")
        command = build_serve_grpc_command(
            "127.0.0.1:50051",
            binary_path=str(binary),
            queue_capacity=16,
            write_delay_ms=100,
        )
        self.assertEqual(command[0], str(binary.resolve()))
        self.assertEqual(command[1:], ["serve-grpc", "--addr", "127.0.0.1:50051", "--queue-capacity", "16", "--write-delay-ms", "100"])

    @patch("faultline.grpc_client.subprocess.Popen")
    def test_start_server_uses_release_binary(self, mock_popen: MagicMock) -> None:
        binary = Path(__file__).resolve().parents[2] / "runtime" / "target" / "release" / "runtime.exe"
        if not binary.is_file():
            self.skipTest("release binary not built")

        runtime = GrpcAsyncRuntime(
            binary_path=str(binary),
            addr="127.0.0.1:50999",
            queue_capacity=4,
        )
        runtime._start_server_process()

        mock_popen.assert_called_once()
        command = mock_popen.call_args.args[0]
        self.assertEqual(command[0], str(binary.resolve()))
        self.assertEqual(command[1:4], ["serve-grpc", "--addr", "127.0.0.1:50999"])
        self.assertNotIn("cwd", mock_popen.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
