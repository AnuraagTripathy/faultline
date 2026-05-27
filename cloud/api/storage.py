"""Checkpoint storage abstraction for Faultline Cloud."""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

CLOUD_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
MAX_CHECKPOINT_BYTES = 50 * 1024 * 1024  # 50 MiB dev limit


@dataclass(frozen=True)
class StoredObject:
    """Result of persisting a checkpoint blob."""

    storage_backend: str
    storage_path: str
    size_bytes: int
    checksum_sha256: str


class CloudCheckpointStorage(ABC):
    """Backend-agnostic checkpoint blob storage."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Identifier stored in DB (e.g. ``local``, ``minio``)."""

    @abstractmethod
    def save_checkpoint(
        self,
        user_id: str,
        run_id: str,
        checkpoint_id: str,
        filename: str,
        data: bytes,
    ) -> StoredObject:
        """Persist checkpoint bytes and return storage metadata."""

    @abstractmethod
    def read_checkpoint(self, stored_path: str) -> bytes:
        """Read checkpoint bytes by storage path."""

    @abstractmethod
    def exists(self, stored_path: str) -> bool:
        """Whether the object exists in storage."""

    @abstractmethod
    def size(self, stored_path: str) -> int:
        """Object size in bytes; raises ``FileNotFoundError`` if missing."""

    def delete_checkpoint(self, stored_path: str) -> bool:
        """Remove object if present. Optional; default no-op."""
        return False

    def health_probe(self) -> tuple[str, str | None]:
        """Liveness check for deployment health endpoints."""
        return "ok", None


class LocalCloudCheckpointStorage(CloudCheckpointStorage):
    """
    Local filesystem storage.

    Layout: ``<checkpoints_root>/<user_id>/<run_id>/<filename>``
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else checkpoints_root()

    @property
    def backend_name(self) -> str:
        return "local"

    @property
    def root(self) -> Path:
        return self._root

    def _full_path(self, stored_path: str) -> Path:
        return self._root / stored_path

    def save_checkpoint(
        self,
        user_id: str,
        run_id: str,
        checkpoint_id: str,
        filename: str,
        data: bytes,
    ) -> StoredObject:
        del checkpoint_id
        stored_path = f"{user_id}/{run_id}/{filename}"
        path = self._full_path(stored_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        checksum = hashlib.sha256(data).hexdigest()
        return StoredObject(
            storage_backend=self.backend_name,
            storage_path=stored_path,
            size_bytes=len(data),
            checksum_sha256=checksum,
        )

    def read_checkpoint(self, stored_path: str) -> bytes:
        path = self._full_path(stored_path)
        if not path.is_file():
            raise FileNotFoundError(stored_path)
        return path.read_bytes()

    def exists(self, stored_path: str) -> bool:
        return self._full_path(stored_path).is_file()

    def size(self, stored_path: str) -> int:
        path = self._full_path(stored_path)
        if not path.is_file():
            raise FileNotFoundError(stored_path)
        return path.stat().st_size

    def delete_checkpoint(self, stored_path: str) -> bool:
        path = self._full_path(stored_path)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def health_probe(self) -> tuple[str, str | None]:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            probe = self._root / ".health_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return "ok", None
        except OSError as error:
            return "error", str(error)


class MinioCloudCheckpointStorage(CloudCheckpointStorage):
    """
    S3-compatible object storage (MinIO, AWS S3, Cloudflare R2).

    Object layout: ``checkpoints/<user_id>/<run_id>/<filename>``
    """

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
    ) -> None:
        import boto3
        from botocore.client import Config

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url.rstrip("/"),
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4"),
        )

    @property
    def backend_name(self) -> str:
        return "minio"

    def _object_key(self, user_id: str, run_id: str, filename: str) -> str:
        return f"checkpoints/{user_id}/{run_id}/{filename}"

    def _key_from_stored_path(self, stored_path: str) -> str:
        if stored_path.startswith("checkpoints/"):
            return stored_path
        return f"checkpoints/{stored_path}"

    def save_checkpoint(
        self,
        user_id: str,
        run_id: str,
        checkpoint_id: str,
        filename: str,
        data: bytes,
    ) -> StoredObject:
        del checkpoint_id
        key = self._object_key(user_id, run_id, filename)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        checksum = hashlib.sha256(data).hexdigest()
        return StoredObject(
            storage_backend=self.backend_name,
            storage_path=key,
            size_bytes=len(data),
            checksum_sha256=checksum,
        )

    def read_checkpoint(self, stored_path: str) -> bytes:
        from botocore.exceptions import ClientError

        key = self._key_from_stored_path(stored_path)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                raise FileNotFoundError(stored_path) from error
            raise

    def exists(self, stored_path: str) -> bool:
        key = self._key_from_stored_path(stored_path)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def size(self, stored_path: str) -> int:
        key = self._key_from_stored_path(stored_path)
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
            return int(response["ContentLength"])
        except Exception as error:
            raise FileNotFoundError(stored_path) from error

    def delete_checkpoint(self, stored_path: str) -> bool:
        key = self._key_from_stored_path(stored_path)
        if not self.exists(stored_path):
            return False
        self._client.delete_object(Bucket=self._bucket, Key=key)
        return True

    def health_probe(self) -> tuple[str, str | None]:
        try:
            probe_key = ".health_probe"
            self._client.put_object(
                Bucket=self._bucket,
                Key=probe_key,
                Body=b"ok",
            )
            self._client.delete_object(Bucket=self._bucket, Key=probe_key)
            return "ok", None
        except Exception as error:  # noqa: BLE001
            return "error", str(error)


class S3CloudCheckpointStorage(MinioCloudCheckpointStorage):
    """Alias for AWS S3 — same implementation as MinIO."""

    @property
    def backend_name(self) -> str:
        return "s3"


def checkpoints_root() -> Path:
    raw = os.environ.get("FAULTLINE_CLOUD_CHECKPOINTS_DIR") or os.environ.get(
        "FAULTLINE_CHECKPOINT_DIR"
    )
    if raw:
        return Path(raw)
    return CLOUD_DATA_ROOT / "checkpoints"


def storage_backend_name() -> str:
    return os.environ.get("FAULTLINE_CLOUD_STORAGE", "local").strip().lower() or "local"


def get_checkpoint_storage() -> CloudCheckpointStorage:
    """Factory for the configured checkpoint storage backend."""
    backend = storage_backend_name()
    if backend == "local":
        return LocalCloudCheckpointStorage()
    if backend in ("minio", "s3", "r2"):
        endpoint = os.environ.get(
            "FAULTLINE_S3_ENDPOINT", "http://127.0.0.1:9000"
        )
        bucket = os.environ.get("FAULTLINE_S3_BUCKET", "faultline")
        access_key = os.environ.get("FAULTLINE_S3_ACCESS_KEY", "minioadmin")
        secret_key = os.environ.get("FAULTLINE_S3_SECRET_KEY", "minioadmin")
        region = os.environ.get("FAULTLINE_S3_REGION", "us-east-1")
        storage: CloudCheckpointStorage = MinioCloudCheckpointStorage(
            endpoint_url=endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            region=region,
        )
        if backend == "s3":
            return S3CloudCheckpointStorage(
                endpoint_url=endpoint,
                bucket=bucket,
                access_key=access_key,
                secret_key=secret_key,
                region=region,
            )
        return storage
    raise ValueError(
        f"Unknown FAULTLINE_CLOUD_STORAGE={backend!r}. "
        "Supported: local (default), minio, s3, r2."
    )


def checkpoint_filename_for_step(step: int) -> str:
    return f"step_{step}.pkl"


def checkpoint_storage_path(row: object) -> str | None:
    """Resolve storage path from a DB row (supports legacy ``path`` column)."""
    keys = row.keys() if hasattr(row, "keys") else ()
    if "storage_path" in keys and row["storage_path"]:
        return str(row["storage_path"])
    if "path" in keys and row["path"]:
        return str(row["path"])
    return None
