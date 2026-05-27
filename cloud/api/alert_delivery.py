"""Outbound alert delivery — SMTP, Discord, Slack."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any


def smtp_configured() -> bool:
    return bool(os.environ.get("FAULTLINE_SMTP_HOST", "").strip())


def send_email_alert(*, to_email: str, subject: str, body: str) -> None:
    host = os.environ.get("FAULTLINE_SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("SMTP not configured (FAULTLINE_SMTP_HOST)")
    port = int(os.environ.get("FAULTLINE_SMTP_PORT", "587"))
    user = os.environ.get("FAULTLINE_SMTP_USER", "").strip()
    password = os.environ.get("FAULTLINE_SMTP_PASSWORD", "")
    from_email = os.environ.get(
        "FAULTLINE_ALERT_FROM_EMAIL", "faultline@localhost"
    ).strip()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        if port != 25:
            smtp.starttls(context=context)
            smtp.ehlo()
        if user:
            smtp.login(user, password)
        smtp.send_message(message)


def send_discord_webhook(webhook_url: str, content: str) -> None:
    payload = json.dumps({"content": content}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 400:
                raise RuntimeError(f"Discord webhook HTTP {response.status}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord webhook failed ({error.code}): {detail}") from error


def send_slack_webhook(webhook_url: str, text: str) -> None:
    payload = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 400:
                raise RuntimeError(f"Slack webhook HTTP {response.status}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Slack webhook failed ({error.code}): {detail}") from error


def format_alert_message(
    *,
    alert_type: str,
    run_name: str,
    project_name: str,
    status: str,
    latest_checkpoint_step: int | None = None,
    extra: str | None = None,
) -> str:
    lines = [
        "⚠️ Faultline Alert",
        f"Run: {run_name}",
        f"Project: {project_name}",
        f"Status: {status}",
        f"Type: {alert_type}",
    ]
    if latest_checkpoint_step is not None:
        lines.append(f"Latest checkpoint: step {latest_checkpoint_step}")
    if extra:
        lines.append(extra)
    if alert_type in ("recoverable", "recovery_available"):
        lines.append("Recovery available.")
    return "\n".join(lines)


def deliver_user_alert(
    settings: dict[str, Any],
    *,
    subject: str,
    message: str,
) -> list[tuple[str, str]]:
    """Send alert on configured channels. Returns list of (channel, status)."""
    results: list[tuple[str, str]] = []
    email = settings.get("alert_email")
    if email:
        try:
            send_email_alert(to_email=str(email), subject=subject, body=message)
            results.append(("email", "sent"))
        except Exception as error:  # noqa: BLE001
            results.append(("email", f"failed: {error}"))

    discord = settings.get("discord_webhook_url")
    if discord:
        try:
            send_discord_webhook(str(discord), message)
            results.append(("discord", "sent"))
        except Exception as error:  # noqa: BLE001
            results.append(("discord", f"failed: {error}"))

    slack = settings.get("slack_webhook_url")
    if slack:
        try:
            send_slack_webhook(str(slack), message)
            results.append(("slack", "sent"))
        except Exception as error:  # noqa: BLE001
            results.append(("slack", f"failed: {error}"))

    return results
