"""User authentication tests (v18.5)."""

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
from cloud.api.sessions import SESSION_COOKIE_NAME  # noqa: E402

AUTH = {"Authorization": f"Bearer {DEV_API_KEY}"}


class TestUserAuth(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._db.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._db.name
        os.environ["FAULTLINE_CLOUD_CHECKPOINTS_DIR"] = str(
            Path(self._tmpdir) / "checkpoints"
        )
        os.environ["FAULTLINE_JWT_SECRET"] = "test-jwt-secret"
        conn = connect()
        init_db(conn)
        conn.close()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        os.environ.pop("FAULTLINE_CLOUD_CHECKPOINTS_DIR", None)
        os.environ.pop("FAULTLINE_JWT_SECRET", None)
        Path(self._db.name).unlink(missing_ok=True)

    def test_signup_login_and_session_me(self) -> None:
        signup = self.client.post(
            "/v1/auth/signup",
            json={"email": "alice@example.com", "password": "secretpass"},
        )
        self.assertEqual(signup.status_code, 200)
        body = signup.json()
        self.assertEqual(body["email"], "alice@example.com")
        self.assertIn(SESSION_COOKIE_NAME, signup.cookies)

        conn = connect()
        row = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?",
            ("alice@example.com",),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertNotEqual(row["password_hash"], "secretpass")
        self.assertTrue(str(row["password_hash"]).startswith("$2"))

        login = self.client.post(
            "/v1/auth/login",
            json={"email": "alice@example.com", "password": "secretpass"},
        )
        self.assertEqual(login.status_code, 200)
        token = login.cookies.get(SESSION_COOKIE_NAME)
        self.assertTrue(token)

        me = self.client.get(
            "/v1/auth/me",
            cookies={SESSION_COOKIE_NAME: token},
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "alice@example.com")

    def test_api_key_auth_still_works(self) -> None:
        response = self.client.get("/v1/runs", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    def test_user_isolation(self) -> None:
        client_a = TestClient(create_app())
        client_a.post(
            "/v1/auth/signup",
            json={"email": "user-a@test.com", "password": "password-a1"},
        )
        start = client_a.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "private-run"},
        )
        self.assertEqual(start.status_code, 200)
        run_id = start.json()["run_id"]

        client_b = TestClient(create_app())
        client_b.post(
            "/v1/auth/signup",
            json={"email": "user-b@test.com", "password": "password-b1"},
        )
        listed = client_b.get("/v1/runs")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json(), [])

        forbidden = client_b.get(f"/v1/runs/{run_id}")
        self.assertEqual(forbidden.status_code, 404)

    def test_session_can_create_api_key(self) -> None:
        signup = self.client.post(
            "/v1/auth/signup",
            json={"email": "keys@test.com", "password": "password12"},
        )
        token = signup.cookies.get(SESSION_COOKIE_NAME)
        created = self.client.post(
            "/v1/api-keys?label=laptop",
            cookies={SESSION_COOKIE_NAME: token},
        )
        self.assertEqual(created.status_code, 200)
        self.assertTrue(created.json()["api_key"].startswith("fl_"))

        listed = self.client.get(
            "/v1/api-keys",
            cookies={SESSION_COOKIE_NAME: token},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertGreaterEqual(len(listed.json()), 1)

    def test_session_jwt_bearer_lists_runs(self) -> None:
        signup = self.client.post(
            "/v1/auth/signup",
            json={"email": "runs-bearer@test.com", "password": "password12"},
        )
        token = signup.cookies.get(SESSION_COOKIE_NAME)
        self.assertTrue(token)
        start = self.client.post(
            "/v1/runs/start",
            json={"project": "p", "run_name": "session-run"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(start.status_code, 200)
        listed = self.client.get(
            "/v1/runs",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["run_name"], "session-run")


if __name__ == "__main__":
    unittest.main()
