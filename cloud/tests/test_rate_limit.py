"""Rate limiting middleware tests."""

from __future__ import annotations

import os
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

AUTH = {"Authorization": f"Bearer {DEV_API_KEY}"}


class TestRateLimit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._tmp.name
        os.environ["FAULTLINE_ENV"] = "development"
        conn = connect()
        init_db(conn)
        conn.close()
        self._env_backup = {
            "FAULTLINE_RATE_LIMIT_ENABLED": os.environ.get("FAULTLINE_RATE_LIMIT_ENABLED"),
            "FAULTLINE_RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE": os.environ.get(
                "FAULTLINE_RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE"
            ),
            "FAULTLINE_RATE_LIMIT_UPLOADS_PER_MINUTE": os.environ.get(
                "FAULTLINE_RATE_LIMIT_UPLOADS_PER_MINUTE"
            ),
        }

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ.pop("FAULTLINE_ENV", None)
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        Path(self._tmp.name).unlink(missing_ok=True)

    def _client(self) -> TestClient:
        return TestClient(create_app())

    def test_login_rate_limit_triggers(self) -> None:
        os.environ["FAULTLINE_RATE_LIMIT_ENABLED"] = "true"
        os.environ["FAULTLINE_RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE"] = "3"
        client = self._client()
        for _ in range(3):
            response = client.post(
                "/v1/auth/login",
                json={"email": "nobody@test.com", "password": "wrong-password"},
            )
            self.assertIn(response.status_code, (401, 400))
        blocked = client.post(
            "/v1/auth/login",
            json={"email": "nobody@test.com", "password": "wrong-password"},
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["detail"], "rate limit exceeded")
        self.assertIn("Retry-After", blocked.headers)

    def test_checkpoint_upload_rate_limit_triggers(self) -> None:
        os.environ["FAULTLINE_RATE_LIMIT_ENABLED"] = "true"
        os.environ["FAULTLINE_RATE_LIMIT_UPLOADS_PER_MINUTE"] = "2"
        client = self._client()
        started = client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "r"},
            headers=AUTH,
        )
        self.assertEqual(started.status_code, 200)
        run_id = started.json()["run_id"]
        for step in range(2):
            ok = client.post(
                f"/v1/runs/{run_id}/checkpoints",
                headers=AUTH,
                data={"step": str(step)},
                files={"file": ("ckpt.pkl", b"x", "application/octet-stream")},
            )
            self.assertEqual(ok.status_code, 200)
        blocked = client.post(
            f"/v1/runs/{run_id}/checkpoints",
            headers=AUTH,
            data={"step": "99"},
            files={"file": ("ckpt.pkl", b"x", "application/octet-stream")},
        )
        self.assertEqual(blocked.status_code, 429)

    def test_disabled_limiter_does_not_block(self) -> None:
        os.environ["FAULTLINE_RATE_LIMIT_ENABLED"] = "false"
        os.environ["FAULTLINE_RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE"] = "2"
        client = self._client()
        for _ in range(5):
            response = client.post(
                "/v1/auth/login",
                json={"email": "nobody@test.com", "password": "wrong-password"},
            )
            self.assertNotEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
