"""In-memory per-process rate limiting (single-instance deployments only)."""

from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict, deque
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from cloud.api.env_validation import is_production

_WINDOW_SECONDS = 60.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


def rate_limit_enabled() -> bool:
    if os.environ.get("FAULTLINE_RATE_LIMIT_ENABLED", "").strip():
        return _env_bool("FAULTLINE_RATE_LIMIT_ENABLED", False)
    return is_production()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


class RateLimitConfig:
    def __init__(self) -> None:
        self.enabled = rate_limit_enabled()
        self.default_rpm = _env_int("FAULTLINE_RATE_LIMIT_REQUESTS_PER_MINUTE", 120)
        self.auth_rpm = _env_int("FAULTLINE_RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE", 20)
        self.upload_rpm = _env_int("FAULTLINE_RATE_LIMIT_UPLOADS_PER_MINUTE", 10)


def _route_bucket(method: str, path: str) -> str | None:
    if method != "POST":
        return None
    if path in ("/v1/auth/signup", "/v1/auth/login"):
        return "auth"
    if path.startswith("/v1/auth/oauth/") and path.endswith("/callback"):
        return "auth"
    if path == "/v1/api-keys":
        return "auth"
    if re.match(r"^/v1/runs/[^/]+/checkpoints$", path):
        return "upload"
    if re.match(r"^/v1/runs/[^/]+/resume$", path):
        return "auth"
    return None


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client is not None:
        return request.client.host
    return "unknown"


class InMemoryRateLimiter:
    """Sliding window limiter keyed by (client, bucket)."""

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def _limit_for(self, bucket: str) -> int:
        if bucket == "auth":
            return self.config.auth_rpm
        if bucket == "upload":
            return self.config.upload_rpm
        return self.config.default_rpm

    def check(self, client: str, bucket: str) -> tuple[bool, int, int, int]:
        """Return allowed, limit, remaining, retry_after_seconds."""
        limit = self._limit_for(bucket)
        key = f"{client}:{bucket}"
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        with self._lock:
            window = self._hits[key]
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= limit:
                retry_after = max(1, int(_WINDOW_SECONDS - (now - window[0]) + 1))
                return False, limit, 0, retry_after
            window.append(now)
            remaining = max(0, limit - len(window))
            return True, limit, remaining, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, config: RateLimitConfig | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.config = config or RateLimitConfig()
        self.limiter = InMemoryRateLimiter(self.config)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if not self.config.enabled:
            return await call_next(request)

        path = request.url.path
        if path in ("/health", "/ready"):
            return await call_next(request)

        bucket = _route_bucket(request.method, path)
        if bucket is None:
            bucket = "default"

        client = _client_key(request)
        allowed, limit, remaining, retry_after = self.limiter.check(client, bucket)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "Retry-After": str(retry_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
