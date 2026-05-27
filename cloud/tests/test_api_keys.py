"""API key management tests."""

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


class TestApiKeys(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        os.environ["FAULTLINE_CLOUD_DB"] = self._tmp.name
        conn = connect()
        init_db(conn)
        conn.close()
        self.client = TestClient(create_app())

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_create_api_key_with_label(self) -> None:
        response = self.client.post(
            "/v1/api-keys?label=my-laptop",
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["api_key"].startswith("fl_"))
        self.assertEqual(body["label"], "my-laptop")
        self.assertIn("prefix", body)
        self.assertIn("created_at_ms", body)

    def test_list_api_keys_excludes_full_key(self) -> None:
        created = self.client.post(
            "/v1/api-keys?label=listed-key",
            headers=AUTH,
        ).json()
        full_key = created["api_key"]

        listed = self.client.get("/v1/api-keys", headers=AUTH)
        self.assertEqual(listed.status_code, 200)
        keys = listed.json()
        self.assertGreaterEqual(len(keys), 2)
        for item in keys:
            self.assertNotIn("api_key", item)
            self.assertNotIn("key_value", item)
            self.assertIn("prefix", item)
            self.assertIn("label", item)
            self.assertIn("created_at_ms", item)

        match = next(k for k in keys if k["label"] == "listed-key")
        self.assertTrue(match["prefix"].startswith("fl_"))
        self.assertNotIn(full_key, str(keys))

    def test_created_key_can_authenticate(self) -> None:
        created = self.client.post(
            "/v1/api-keys?label=auth-test",
            headers=AUTH,
        ).json()
        new_auth = {"Authorization": f"Bearer {created['api_key']}"}

        me = self.client.get("/v1/me", headers=new_auth)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["email"], "dev@faultline.local")

        start = self.client.post(
            "/v1/runs/start",
            json={"project": "keys", "run_name": "auth-run"},
            headers=new_auth,
        )
        self.assertEqual(start.status_code, 200)
        self.assertEqual(start.json()["run_name"], "auth-run")

    def test_usage_includes_key_prefix(self) -> None:
        response = self.client.get("/v1/usage", headers=AUTH)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("api_key_prefix", body)
        self.assertIn("fl_dev", body["api_key_prefix"])


if __name__ == "__main__":
    unittest.main()
