"""Checkpoint storage abstraction tests."""

from __future__ import annotations

import hashlib
import os
import pickle
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from cloud.api.app import create_app  # noqa: E402
from cloud.api.database import reset_engine  # noqa: E402
from cloud.api.db import DEV_API_KEY, connect, init_db  # noqa: E402
from cloud.api.storage import (  # noqa: E402
    LocalCloudCheckpointStorage,
    MinioCloudCheckpointStorage,
    checkpoint_filename_for_step,
    get_checkpoint_storage,
)
from unittest.mock import MagicMock, patch  # noqa: E402

AUTH = {"Authorization": f"Bearer {DEV_API_KEY}"}


class TestLocalCloudCheckpointStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.storage = LocalCloudCheckpointStorage(root=Path(self._tmpdir))

    def test_save_read_exists_size(self) -> None:
        data = pickle.dumps({"step": 7})
        stored = self.storage.save_checkpoint(
            "user-1",
            "run-1",
            "ckpt-1",
            checkpoint_filename_for_step(7),
            data,
        )
        self.assertEqual(stored.storage_backend, "local")
        self.assertEqual(stored.storage_path, "user-1/run-1/step_7.pkl")
        self.assertEqual(stored.size_bytes, len(data))
        self.assertEqual(stored.checksum_sha256, hashlib.sha256(data).hexdigest())

        self.assertTrue(self.storage.exists(stored.storage_path))
        self.assertEqual(self.storage.size(stored.storage_path), len(data))
        self.assertEqual(self.storage.read_checkpoint(stored.storage_path), data)

    def test_delete_checkpoint(self) -> None:
        stored = self.storage.save_checkpoint(
            "u",
            "r",
            "c",
            "step_1.pkl",
            b"x",
        )
        self.assertTrue(self.storage.delete_checkpoint(stored.storage_path))
        self.assertFalse(self.storage.exists(stored.storage_path))

    def test_health_probe(self) -> None:
        status, error = self.storage.health_probe()
        self.assertEqual(status, "ok")
        self.assertIsNone(error)


class TestStorageFactory(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("FAULTLINE_CLOUD_STORAGE", None)

    def test_default_local(self) -> None:
        os.environ.pop("FAULTLINE_CLOUD_STORAGE", None)
        storage = get_checkpoint_storage()
        self.assertIsInstance(storage, LocalCloudCheckpointStorage)

    def test_minio_factory(self) -> None:
        os.environ["FAULTLINE_CLOUD_STORAGE"] = "minio"
        os.environ["FAULTLINE_S3_ENDPOINT"] = "http://127.0.0.1:9000"
        with patch("boto3.client", return_value=MagicMock()):
            storage = get_checkpoint_storage()
            self.assertIsInstance(storage, MinioCloudCheckpointStorage)

    def test_minio_save_and_read(self) -> None:
        with patch("boto3.client") as mock_client_factory:
            client = MagicMock()
            mock_client_factory.return_value = client
            body = {}

            def put_object(**kwargs):
                body["data"] = kwargs["Body"]

            def get_object(Bucket, Key):
                return {"Body": MagicMock(read=lambda: body["data"])}

            client.put_object.side_effect = put_object
            client.get_object.side_effect = get_object
            client.head_object.return_value = {"ContentLength": 5}

            storage = MinioCloudCheckpointStorage(
                endpoint_url="http://localhost:9000",
                bucket="faultline",
                access_key="k",
                secret_key="s",
            )
            stored = storage.save_checkpoint("u", "r", "c", "step_1.pkl", b"hello")
            self.assertTrue(stored.storage_path.startswith("checkpoints/"))
            self.assertEqual(storage.read_checkpoint(stored.storage_path), b"hello")

class TestCheckpointUploadViaStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._db.name
        os.environ["FAULTLINE_CLOUD_CHECKPOINTS_DIR"] = str(
            Path(self._tmpdir) / "checkpoints"
        )
        os.environ["FAULTLINE_CLOUD_STORAGE"] = "local"
        conn = connect()
        init_db(conn)
        conn.close()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ.pop("FAULTLINE_CLOUD_CHECKPOINTS_DIR", None)
        os.environ.pop("FAULTLINE_CLOUD_STORAGE", None)
        Path(self._db.name).unlink(missing_ok=True)

    def test_upload_stores_metadata_and_checksum(self) -> None:
        payload = {"step": 3}
        blob = pickle.dumps(payload)
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        upload = self.client.post(
            f"/v1/runs/{run_id}/checkpoints",
            headers=AUTH,
            data={"step": "3"},
            files={"file": ("c.pkl", blob, "application/octet-stream")},
        )
        self.assertEqual(upload.status_code, 200)
        body = upload.json()
        self.assertEqual(body["storage_backend"], "local")
        self.assertIn("storage_path", body)
        self.assertEqual(
            body["checksum_sha256"],
            hashlib.sha256(blob).hexdigest(),
        )

        conn = connect()
        row = conn.execute(
            "SELECT storage_backend, storage_path, checksum_sha256 FROM checkpoints WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row["storage_backend"], "local")
        self.assertTrue(str(row["storage_path"]).endswith("step_3.pkl"))
        self.assertEqual(row["checksum_sha256"], hashlib.sha256(blob).hexdigest())

    def test_download_latest_via_storage(self) -> None:
        blob = pickle.dumps({"x": 1})
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        self.client.post(
            f"/v1/runs/{run_id}/checkpoints",
            headers=AUTH,
            data={"step": "1"},
            files={"file": ("c.pkl", blob, "application/octet-stream")},
        )
        download = self.client.get(
            f"/v1/runs/{run_id}/checkpoints/latest/download",
            headers=AUTH,
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(pickle.loads(download.content), {"x": 1})

    def test_recovery_health_uses_storage(self) -> None:
        blob = pickle.dumps({"step": 2})
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        self.client.post(
            f"/v1/runs/{run_id}/checkpoints",
            headers=AUTH,
            data={"step": "2"},
            files={"file": ("c.pkl", blob, "application/octet-stream")},
        )
        recovery = self.client.get(f"/v1/runs/{run_id}/recovery", headers=AUTH)
        self.assertEqual(recovery.json()["checkpoint_health"], "ok")

        conn = connect()
        row = conn.execute(
            "SELECT storage_path FROM checkpoints WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        conn.close()
        storage = LocalCloudCheckpointStorage(
            root=Path(os.environ["FAULTLINE_CLOUD_CHECKPOINTS_DIR"])
        )
        storage.delete_checkpoint(str(row["storage_path"]))

        recovery2 = self.client.get(f"/v1/runs/{run_id}/recovery", headers=AUTH)
        self.assertEqual(recovery2.json()["checkpoint_health"], "missing_file")


if __name__ == "__main__":
    unittest.main()
