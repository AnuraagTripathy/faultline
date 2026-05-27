"""OAuth and connected-provider API tests."""

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
from cloud.api.db import connect, init_db  # noqa: E402
from cloud.api.sessions import SESSION_COOKIE_NAME  # noqa: E402
from cloud.api.user_accounts import validate_email  # noqa: E402


class TestOAuthApi(unittest.TestCase):
    def setUp(self) -> None:
        self._db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._db.name
        conn = connect()
        init_db(conn)
        conn.close()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        Path(self._db.name).unlink(missing_ok=True)

    def test_validate_email_accepts_github_noreply(self) -> None:
        validate_email("12345678+anuraag-tripathy@users.noreply.github.com")
        validate_email("anuraag.t@terpmail.umd.edu")

    def test_validate_email_rejects_missing_at(self) -> None:
        with self.assertRaises(ValueError):
            validate_email("not-an-email")

    def test_oauth_start_missing_env_is_503(self) -> None:
        response = self.client.get(
            "/v1/auth/oauth/google/start",
            params={"redirect_uri": "http://localhost:3000/callback", "state": "abc123456"},
        )
        self.assertEqual(response.status_code, 503)

    def test_connected_providers_empty_for_password_user(self) -> None:
        signup = self.client.post(
            "/v1/auth/signup",
            json={"email": "oauth-empty@test.com", "password": "password12"},
        )
        token = signup.cookies.get(SESSION_COOKIE_NAME)
        self.assertTrue(token)
        listed = self.client.get("/v1/auth/providers", cookies={SESSION_COOKIE_NAME: token})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json(), [])


if __name__ == "__main__":
    unittest.main()
