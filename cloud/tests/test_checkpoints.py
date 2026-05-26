"""Cloud checkpoint API tests."""

from __future__ import annotations

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
from cloud.api.db import DEV_API_KEY, connect, init_db  # noqa: E402

AUTH = {"Authorization": f"Bearer {DEV_API_KEY}"}


class TestCloudCheckpoints(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._db.name
        os.environ["FAULTLINE_CLOUD_CHECKPOINTS_DIR"] = str(
            Path(self._tmpdir) / "checkpoints"
        )
        conn = connect()
        init_db(conn)
        conn.close()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ.pop("FAULTLINE_CLOUD_CHECKPOINTS_DIR", None)
        Path(self._db.name).unlink(missing_ok=True)

    def test_upload_requires_auth(self) -> None:
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        run_id = start.json()["run_id"]
        response = self.client.post(
            f"/v1/runs/{run_id}/checkpoints",
            data={"step": "1"},
            files={"file": ("c.pkl", b"data", "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 401)

    def test_upload_list_latest_download_usage(self) -> None:
        payload = {"step": 5, "value": 42}
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
            data={"step": "5", "metadata_json": '{"step":5}'},
            files={"file": ("checkpoint.pkl", blob, "application/octet-stream")},
        )
        self.assertEqual(upload.status_code, 200)
        body = upload.json()
        self.assertEqual(body["step"], 5)
        self.assertEqual(body["size_bytes"], len(blob))
        self.assertEqual(body["status"], "committed")
        checkpoint_id = body["checkpoint_id"]

        listed = self.client.get(
            f"/v1/runs/{run_id}/checkpoints",
            headers=AUTH,
        )
        self.assertEqual(len(listed.json()), 1)

        latest = self.client.get(
            f"/v1/runs/{run_id}/checkpoints/latest",
            headers=AUTH,
        )
        self.assertEqual(latest.json()["step"], 5)

        run_row = self.client.get(f"/v1/runs/{run_id}", headers=AUTH).json()
        self.assertEqual(run_row["latest_checkpoint_step"], 5)

        download = self.client.get(
            f"/v1/runs/{run_id}/checkpoints/latest/download",
            headers=AUTH,
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(pickle.loads(download.content), payload)

        by_id = self.client.get(
            f"/v1/runs/{run_id}/checkpoints/{checkpoint_id}/download",
            headers=AUTH,
        )
        self.assertEqual(by_id.status_code, 200)

        usage = self.client.get("/v1/usage", headers=AUTH).json()
        self.assertGreaterEqual(usage["checkpoints_created"], 1)
        self.assertGreaterEqual(usage["checkpoint_bytes_uploaded"], len(blob))


if __name__ == "__main__":
    unittest.main()
