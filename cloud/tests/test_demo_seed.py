"""Demo seed for Docker onboarding (v21.0)."""

from __future__ import annotations

import os
import tempfile
import unittest

from cloud.api.app import create_app
from cloud.api.db import DEV_API_KEY, connect, init_db, resolve_user_id
from cloud.api.demo_seed import DEMO_EMAIL, DEMO_PROJECT, seed_demo_data
from fastapi.testclient import TestClient


class TestDemoSeed(unittest.TestCase):
    def setUp(self) -> None:
        from cloud.api.database import reset_engine

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._prev = os.environ.get("FAULTLINE_CLOUD_DB")
        os.environ["FAULTLINE_CLOUD_DB"] = self._tmp.name
        reset_engine()
        self.conn = connect()
        init_db(self.conn)

    def tearDown(self) -> None:
        from cloud.api.database import reset_engine

        self.conn.close()
        reset_engine()
        os.environ.pop("FAULTLINE_CLOUD_DB", None)
        if self._prev is not None:
            os.environ["FAULTLINE_CLOUD_DB"] = self._prev
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_seed_idempotent(self) -> None:
        first = seed_demo_data(self.conn)
        second = seed_demo_data(self.conn)
        self.assertGreater(len(first["run_ids"]), 0)
        self.assertTrue(first["seeded"])
        self.assertFalse(second["seeded"])
        self.assertEqual(second["run_ids"], [])

    def test_demo_user_exists(self) -> None:
        seed_demo_data(self.conn)
        from cloud.api.user_accounts import get_user_by_email

        row = get_user_by_email(self.conn, DEMO_EMAIL)
        self.assertIsNotNone(row)

    def test_seeded_runs_listable_via_api(self) -> None:
        from cloud.api.database import reset_engine

        seed_demo_data(self.conn)
        reset_engine()
        app = create_app()
        client = TestClient(app)
        response = client.get(
            "/v1/runs",
            headers={"Authorization": f"Bearer {DEV_API_KEY}"},
        )
        self.assertEqual(response.status_code, 200)
        names = [r["run_name"] for r in response.json()]
        self.assertTrue(any("resnet" in n for n in names))


if __name__ == "__main__":
    unittest.main()
