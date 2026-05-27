"""HTTP client for the Faultline cloud ingestion API."""

from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.request
from typing import Any


class CloudIngestClient:
    """Thin REST client for ``cloud/api`` (v1 runs + metrics + events + checkpoints)."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"cloud API {method} {path} failed ({error.code}): {detail}"
            ) from error

    def _request_bytes(self, method: str, path: str) -> bytes:
        url = f"{self.base_url}{path}"
        request = urllib.request.Request(
            url,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"cloud API {method} {path} failed ({error.code}): {detail}"
            ) from error

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/v1/me")

    def usage(self) -> dict[str, Any]:
        return self._request("GET", "/v1/usage")

    def create_api_key(self, label: str = "dev-key") -> dict[str, Any]:
        return self._request("POST", f"/v1/api-keys?label={label}")

    def start_run(
        self,
        project: str,
        run_name: str,
        *,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/runs/start",
            {
                "project": project,
                "run_name": run_name,
                "tags": tags or [],
            },
        )

    def log_metrics(
        self,
        run_id: str,
        *,
        step: int,
        metrics: dict[str, float],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/runs/{run_id}/metrics",
            {"step": step, "metrics": metrics},
        )

    def log_event(
        self,
        run_id: str,
        *,
        event_type: str,
        level: str = "info",
        message: str = "",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/runs/{run_id}/events",
            {
                "event_type": event_type,
                "level": level,
                "message": message,
            },
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/runs/{run_id}")

    def get_recovery(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/runs/{run_id}/recovery")

    def register_launch_config(self, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/runs/{run_id}/launch-config",
            config,
        )

    def get_launch_config(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/runs/{run_id}/launch-config")

    def resume_run(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/runs/{run_id}/resume")

    def list_runs(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/runs")

    def list_metrics(self, run_id: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        return self._request("GET", f"/v1/runs/{run_id}/metrics?limit={limit}")

    def list_events(self, run_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._request("GET", f"/v1/runs/{run_id}/events?limit={limit}")

    def upload_checkpoint(
        self,
        run_id: str,
        *,
        step: int,
        data: bytes,
        metadata_json: str | None = None,
    ) -> dict[str, Any]:
        boundary = f"----Faultline{uuid.uuid4().hex}"
        parts: list[bytes] = []

        def add_field(name: str, value: str) -> None:
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )

        add_field("step", str(step))
        if metadata_json is not None:
            add_field("metadata_json", metadata_json)
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="checkpoint.pkl"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
        )
        parts.append(data)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        body = b"".join(parts)

        url = f"{self.base_url}/v1/runs/{run_id}/checkpoints"
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"cloud API POST /checkpoints failed ({error.code}): {detail}"
            ) from error

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/v1/runs/{run_id}/checkpoints")

    def latest_checkpoint(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/runs/{run_id}/checkpoints/latest")

    def download_latest_checkpoint(self, run_id: str) -> bytes:
        return self._request_bytes(
            "GET",
            f"/v1/runs/{run_id}/checkpoints/latest/download",
        )

    def download_checkpoint(self, run_id: str, checkpoint_id: str) -> bytes:
        return self._request_bytes(
            "GET",
            f"/v1/runs/{run_id}/checkpoints/{checkpoint_id}/download",
        )
