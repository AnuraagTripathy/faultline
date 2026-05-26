"""
Faultline local dashboard — FastAPI backend over read-only gRPC observability APIs.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

REPO_ROOT = Path(__file__).resolve().parent.parent
SDK_DIR = REPO_ROOT / "sdk"
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from faultline import GrpcAsyncRuntime  # noqa: E402

DEFAULT_GRPC_ADDR = "127.0.0.1:50051"
GRPC_ADDR = os.environ.get("FAULTLINE_GRPC_ADDR", DEFAULT_GRPC_ADDR)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ObservabilityClient(Protocol):
    def get_runtime_overview(self) -> dict[str, Any]: ...
    def list_workers(self) -> list[dict[str, Any]]: ...
    def list_datasets(self) -> list[dict[str, Any]]: ...
    def list_shards(
        self, dataset_name: str, status: str | None = None
    ) -> list[dict[str, Any]]: ...
    def list_events(self, limit: int = 100) -> list[dict[str, Any]]: ...
    def list_runs(self) -> list[dict[str, Any]]: ...
    def list_run_metrics(self, run_id: str, *, limit: int = 1000) -> list[dict[str, Any]]: ...
    def evaluate_alerts(self) -> dict[str, Any]: ...
    def list_alerts(self) -> dict[str, Any]: ...


_grpc_client: ObservabilityClient | None = None


def normalize_status_filter(status: str | None) -> str | None:
    if status is None or status.strip() == "":
        return None
    return status.strip().lower()


def get_grpc_client() -> ObservabilityClient:
    if _grpc_client is None:
        raise HTTPException(status_code=503, detail="gRPC client is not connected")
    return _grpc_client


def set_grpc_client(client: ObservabilityClient | None) -> None:
    global _grpc_client
    _grpc_client = client


@asynccontextmanager
async def lifespan(_app: FastAPI) -> Iterator[None]:
    runtime = GrpcAsyncRuntime(addr=GRPC_ADDR, start_server=False)
    try:
        runtime.start()
        set_grpc_client(runtime)
        yield
    finally:
        runtime.shutdown()
        set_grpc_client(None)


def create_app(
    *,
    grpc_client_factory: Callable[[], ObservabilityClient] | None = None,
    use_lifespan: bool = True,
) -> FastAPI:
    lifespan_ctx = lifespan if use_lifespan and grpc_client_factory is None else None
    application = FastAPI(title="Faultline Dashboard", lifespan=lifespan_ctx)

    if grpc_client_factory is not None:
        set_grpc_client(grpc_client_factory())

    def resolve_client() -> ObservabilityClient:
        if grpc_client_factory is not None:
            return grpc_client_factory()
        return get_grpc_client()

    @application.get("/health")
    def health() -> dict[str, str]:
        try:
            resolve_client()
        except HTTPException:
            return {"status": "disconnected", "grpc_addr": GRPC_ADDR}
        return {"status": "ok", "grpc_addr": GRPC_ADDR}

    @application.get("/api/overview")
    def api_overview(
        client: ObservabilityClient = Depends(resolve_client),
    ) -> dict[str, Any]:
        try:
            return client.get_runtime_overview()
        except Exception as error:  # noqa: BLE001 — surface gRPC errors to UI
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/api/workers")
    def api_workers(
        client: ObservabilityClient = Depends(resolve_client),
    ) -> list[dict[str, Any]]:
        try:
            return client.list_workers()
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/api/datasets")
    def api_datasets(
        client: ObservabilityClient = Depends(resolve_client),
    ) -> list[dict[str, Any]]:
        try:
            return client.list_datasets()
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/api/shards/{dataset_name}")
    def api_shards(
        dataset_name: str,
        status: str | None = Query(default=None),
        client: ObservabilityClient = Depends(resolve_client),
    ) -> list[dict[str, Any]]:
        try:
            return client.list_shards(dataset_name, status=normalize_status_filter(status))
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/api/runs")
    def api_runs(
        client: ObservabilityClient = Depends(resolve_client),
    ) -> list[dict[str, Any]]:
        try:
            return client.list_runs()
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/api/runs/{run_id}/metrics")
    def api_run_metrics(
        run_id: str,
        limit: int = Query(default=1000, ge=1, le=10_000),
        client: ObservabilityClient = Depends(resolve_client),
    ) -> list[dict[str, Any]]:
        try:
            return client.list_run_metrics(run_id, limit=limit)
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/api/events")
    def api_events(
        limit: int = Query(default=100, ge=1, le=500),
        client: ObservabilityClient = Depends(resolve_client),
    ) -> list[dict[str, Any]]:
        try:
            return client.list_events(limit=limit)
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/api/alerts")
    def api_alerts(
        client: ObservabilityClient = Depends(resolve_client),
    ) -> dict[str, Any]:
        try:
            return client.evaluate_alerts()
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @application.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return application


app = create_app()
