"""Alert delivery tests (mocked)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from cloud.api.alert_delivery import (
    deliver_user_alert,
    format_alert_message,
    send_discord_webhook,
)
from cloud.api.database import connect, reset_engine
from cloud.api.db import init_db


class TestAlertDelivery(unittest.TestCase):
    def test_format_message(self) -> None:
        text = format_alert_message(
            alert_type="stale_run",
            run_name="llama-7b",
            project_name="demo",
            status="stale",
            latest_checkpoint_step=12400,
        )
        self.assertIn("Faultline Alert", text)
        self.assertIn("llama-7b", text)
        self.assertIn("12400", text)

    @patch("cloud.api.alert_delivery.urllib.request.urlopen")
    def test_discord_webhook(self, mock_open) -> None:
        mock_open.return_value.__enter__.return_value.status = 204
        send_discord_webhook("https://discord.test/webhook", "hello")
        mock_open.assert_called_once()

    @patch("cloud.api.alert_delivery.send_email_alert")
    def test_deliver_user_alert_email(self, mock_email) -> None:
        settings = {"alert_email": "user@example.com"}
        results = deliver_user_alert(
            settings,
            subject="Test",
            message="Body",
        )
        mock_email.assert_called_once()
        self.assertEqual(results[0][0], "email")


class TestAlertSettingsDb(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["FAULTLINE_DATABASE_URL"] = (
            f"sqlite:///{Path(self._tmpdir.name) / 'alerts.db'}"
        )
        reset_engine()
        conn = connect()
        init_db(conn)
        conn.close()

    def tearDown(self) -> None:
        reset_engine()
        os.environ.pop("FAULTLINE_DATABASE_URL", None)
        self._tmpdir.cleanup()

    def test_upsert_settings(self) -> None:
        from cloud.api.alerts import get_alert_settings, upsert_alert_settings

        conn = connect()
        try:
            upsert_alert_settings(
                conn,
                "user-1",
                alert_email="a@b.com",
                discord_webhook_url="https://discord.test/hook",
            )
            settings = get_alert_settings(conn, "user-1")
            self.assertEqual(settings["alert_email"], "a@b.com")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
