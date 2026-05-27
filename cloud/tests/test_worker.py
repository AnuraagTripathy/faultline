"""Background worker queue tests."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from cloud.api.database import connect, reset_engine
from cloud.api.db import init_db, get_or_create_project
from cloud.api.storage import LocalCloudCheckpointStorage
from cloud.api.worker import (
    TASK_VERIFY_CHECKPOINT,
    enqueue_task,
    start_worker,
    list_tasks,
)


class TestWorkerQueue(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        base = Path(self._tmpdir.name)
        os.environ["FAULTLINE_DATABASE_URL"] = f"sqlite:///{(base / 'w.db').as_posix()}"
        os.environ["FAULTLINE_CLOUD_CHECKPOINTS_DIR"] = str(base / "ckpts")
        os.environ["FAULTLINE_CLOUD_STORAGE"] = "local"
        reset_engine()
        conn = connect()
        init_db(conn)
        conn.close()
        start_worker()

    def tearDown(self) -> None:
        reset_engine()
        for key in (
            "FAULTLINE_DATABASE_URL",
            "FAULTLINE_CLOUD_CHECKPOINTS_DIR",
            "FAULTLINE_CLOUD_STORAGE",
        ):
            os.environ.pop(key, None)
        self._tmpdir.cleanup()

    def test_verify_checkpoint_task(self) -> None:
        user_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        ckpt_id = str(uuid.uuid4())
        storage = LocalCloudCheckpointStorage()
        stored = storage.save_checkpoint(
            user_id, run_id, ckpt_id, "step_1.pkl", b"payload"
        )
        conn = connect()
        try:
            project_id = get_or_create_project(conn, user_id, "p")
            conn.execute(
                """
                INSERT INTO runs (
                    id, project_id, name, status, tags_json,
                    latest_step, latest_loss, latest_checkpoint_step,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'r', 'running', '[]', 1, NULL, 1, 1, 1)
                """,
                (run_id, project_id),
            )
            conn.execute(
                """
                INSERT INTO checkpoints (
                    id, run_id, step, size_bytes, path, status,
                    metadata_json, created_at_ms, storage_backend, storage_path, checksum_sha256
                ) VALUES (?, ?, 1, ?, 'legacy', 'committed', NULL, 1, 'local', ?, ?)
                """,
                (
                    ckpt_id,
                    run_id,
                    stored.size_bytes,
                    stored.storage_path,
                    stored.checksum_sha256,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        task_id = enqueue_task(
            TASK_VERIFY_CHECKPOINT,
            {"checkpoint_id": ckpt_id},
            user_id=user_id,
        )

        deadline = time.time() + 5.0
        status = "queued"
        while time.time() < deadline:
            conn = connect()
            try:
                row = conn.execute(
                    "SELECT status FROM background_tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
                status = str(row["status"])
                if status in ("completed", "failed"):
                    break
            finally:
                conn.close()
            time.sleep(0.1)

        self.assertEqual(status, "completed")
        conn = connect()
        try:
            tasks = list_tasks(conn, user_id, limit=5)
            self.assertTrue(any(t["task_id"] == task_id for t in tasks))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
