import base64
import json
import pickle
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any

WORKER_STEP_SCALE = 1_000_000


def resolve_runtime_dir(runtime_dir: str) -> str:
    path = Path(runtime_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path.resolve())


def build_serve_command(
    mode: str,
    write_delay_ms: int = 0,
    *,
    queue_capacity: int | None = None,
) -> list[str]:
    """Build `cargo run -- <mode>` args, optionally with slow-storage or queue tuning."""
    args = ["cargo", "run", "--", mode]
    if write_delay_ms > 0:
        args.extend(["--write-delay-ms", str(write_delay_ms)])
    if mode == "serve-async" and queue_capacity is not None:
        args.extend(["--queue-capacity", str(queue_capacity)])
    return args


def global_step_for_worker(worker_id: int, local_step: int) -> int:
    """Map (worker_id, local_step) to a unique global checkpoint step."""
    return worker_id * WORKER_STEP_SCALE + local_step


def unwrap_checkpoint_data(data: Any) -> str | None:
    """Normalize service `data` field (string or JSON null) for load helpers."""
    if data is None:
        return None
    return str(data)


def checkpoint_data_to_text(data: str | bytes | None) -> str | None:
    if data is None:
        return None
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "Checkpoint data bytes must be valid UTF-8 for CLI transport"
            ) from exc
    return data


def parse_latest_json(raw: str) -> dict:
    trimmed = raw.strip()
    if trimmed == "No latest checkpoint found." or trimmed == "":
        raise ValueError("No latest checkpoint found")

    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Latest checkpoint is not valid JSON: {raw!r}") from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Latest checkpoint JSON must be an object, got {type(parsed).__name__}"
        )
    return parsed


def parse_latest_pickle(raw: str) -> object:
    trimmed = raw.strip()
    if trimmed == "No latest checkpoint found." or trimmed == "":
        raise ValueError("No latest checkpoint found")

    try:
        pickled = base64.b64decode(trimmed.encode("ascii"), validate=True)
        return pickle.loads(pickled)
    except Exception:
        pass

    try:
        return pickle.loads(trimmed.encode("latin-1"))
    except Exception as exc:
        raise ValueError("Latest checkpoint bytes could not be unpickled") from exc


def format_checkpoint_list(checkpoints: list[dict[str, Any]]) -> str:
    if not checkpoints:
        return "No checkpoints found."
    lines = [
        f"step {entry['step']} | path {entry['path']} | status {entry['status']}"
        for entry in checkpoints
    ]
    return "\n".join(lines)


def format_latest_checkpoint(checkpoint: dict[str, Any] | None) -> str:
    if checkpoint is None:
        return "No latest checkpoint found."
    return f"latest step: {checkpoint['step']}\npath: {checkpoint['path']}"


class Runtime:
    """Python wrapper around the Faultline Rust CLI (one subprocess per command)."""

    def __init__(self, runtime_dir: str = "../runtime") -> None:
        self.runtime_dir = resolve_runtime_dir(runtime_dir)

    def _run_command(self, args: list[str]) -> str:
        command = ["cargo", "run", "--", *args]
        result = subprocess.run(
            command,
            cwd=self.runtime_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            details = stderr or stdout or "unknown error"
            raise RuntimeError(
                f"Faultline command failed ({' '.join(command)}): {details}"
            )

        return result.stdout

    def save_checkpoint(self, step: int, data: str | bytes | None = None) -> str:
        args = ["save", str(step)]
        text = checkpoint_data_to_text(data)
        if text is not None:
            args.extend(["--data", text])
        return self._run_command(args)

    def save_json_checkpoint(self, step: int, payload: dict) -> str:
        return self.save_checkpoint(step, data=json.dumps(payload))

    def save_pickle_checkpoint(self, step: int, payload: object) -> str:
        encoded = base64.b64encode(pickle.dumps(payload)).decode("ascii")
        return self.save_checkpoint(step, data=encoded)

    def list_checkpoints(self) -> str:
        return self._run_command(["list"])

    def latest_checkpoint(self) -> str:
        return self._run_command(["latest"])

    def load_latest(self) -> str:
        return self._run_command(["load-latest"])

    def load_latest_json(self) -> dict:
        return parse_latest_json(self.load_latest())

    def load_latest_pickle(self) -> object:
        return parse_latest_pickle(self.load_latest())

    def prune(self, keep_last: int) -> str:
        return self._run_command(["prune", str(keep_last)])


class PersistentRuntime:
    """Python wrapper around the long-running Faultline `serve` process."""

    def __init__(
        self, runtime_dir: str = "../runtime", *, write_delay_ms: int = 0
    ) -> None:
        self.runtime_dir = resolve_runtime_dir(runtime_dir)
        self.write_delay_ms = write_delay_ms
        self._process: subprocess.Popen[str] | None = None
        self._shutdown_done = False

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return

        self._shutdown_done = False
        self._process = subprocess.Popen(
            build_serve_command("serve", self.write_delay_ms),
            cwd=self.runtime_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def _send_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError("PersistentRuntime is not running; call start() first")

        assert self._process.stdin is not None
        assert self._process.stdout is not None

        line = json.dumps(payload)
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

        response_line = self._process.stdout.readline()
        if response_line == "":
            raise RuntimeError("Faultline service closed stdout before responding")

        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Faultline service returned invalid JSON: {response_line!r}"
            ) from exc

        if not response.get("ok"):
            raise RuntimeError(response.get("error", "unknown service error"))

        return response

    def save_checkpoint(self, step: int, data: str | bytes | None = None) -> str:
        text = checkpoint_data_to_text(data)
        if text is None:
            text = f"fake checkpoint data for step {step}"
        response = self._send_command({"cmd": "save", "step": step, "data": text})
        return response.get("message", f"saved checkpoint step {step}")

    def save_json_checkpoint(self, step: int, payload: dict) -> str:
        return self.save_checkpoint(step, data=json.dumps(payload))

    def save_pickle_checkpoint(self, step: int, payload: object) -> str:
        encoded = base64.b64encode(pickle.dumps(payload)).decode("ascii")
        return self.save_checkpoint(step, data=encoded)

    def save_checkpoint_file(self, step: int, file_path: str) -> str:
        resolved = str(Path(file_path).resolve())
        response = self._send_command(
            {"cmd": "save_from_file", "step": step, "path": resolved}
        )
        return response.get("message", f"saved checkpoint step {step} from file")

    def save_pickle_checkpoint_via_file(self, step: int, payload: object) -> str:
        temp_path: str | None = None
        try:
            data = pickle.dumps(payload)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as handle:
                handle.write(data)
                temp_path = handle.name
            return self.save_checkpoint_file(step, temp_path)
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    def list_checkpoints(self) -> str:
        response = self._send_command({"cmd": "list"})
        return format_checkpoint_list(response.get("checkpoints", []))

    def latest_checkpoint(self) -> str:
        response = self._send_command({"cmd": "latest"})
        return format_latest_checkpoint(response.get("checkpoint"))

    def load_latest(self) -> str:
        response = self._send_command({"cmd": "load_latest"})
        data = unwrap_checkpoint_data(response.get("data"))
        if data is None:
            return "No latest checkpoint found."
        return data

    def load_latest_json(self) -> dict:
        return parse_latest_json(self.load_latest())

    def load_latest_pickle(self) -> object:
        return parse_latest_pickle(self.load_latest())

    def save_worker_pickle_checkpoint_via_file(
        self, worker_id: int, local_step: int, payload: object
    ) -> str:
        temp_path: str | None = None
        try:
            data = pickle.dumps(payload)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as handle:
                handle.write(data)
                temp_path = handle.name
            return self.save_worker_checkpoint_file(
                worker_id, local_step, global_step_for_worker(worker_id, local_step), temp_path
            )
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    def save_worker_checkpoint_file(
        self, worker_id: int, local_step: int, global_step: int, file_path: str
    ) -> str:
        resolved = str(Path(file_path).resolve())
        response = self._send_command(
            {
                "cmd": "save_worker_from_file",
                "worker_id": worker_id,
                "local_step": local_step,
                "step": global_step,
                "path": resolved,
            }
        )
        return response.get(
            "message",
            f"saved worker {worker_id} checkpoint local_step {local_step}",
        )

    def latest_checkpoint_for_worker(self, worker_id: int) -> dict[str, Any] | None:
        response = self._send_command(
            {"cmd": "latest_for_worker", "worker_id": worker_id}
        )
        checkpoint = response.get("checkpoint")
        if checkpoint is None:
            return None
        return checkpoint

    def load_latest_pickle_for_worker(self, worker_id: int) -> object:
        response = self._send_command(
            {"cmd": "load_latest_for_worker", "worker_id": worker_id}
        )
        data = unwrap_checkpoint_data(response.get("data"))
        if data is None:
            raise ValueError(f"No checkpoint found for worker {worker_id}")
        return parse_latest_pickle(data)

    def prune(self, keep_last: int) -> str:
        response = self._send_command({"cmd": "prune", "keep_last": keep_last})
        deleted = response.get("deleted", 0)
        return f"Deleted {deleted} checkpoint file(s)."

    def prune_per_worker(self, keep_last_per_worker: int) -> str:
        response = self._send_command(
            {"cmd": "prune_per_worker", "keep_last_per_worker": keep_last_per_worker}
        )
        deleted = response.get("deleted", 0)
        return f"Deleted {deleted} checkpoint file(s) (per-worker retention)."

    def shutdown(self) -> None:
        if self._shutdown_done:
            return

        if self._process is not None and self._process.poll() is None:
            try:
                self._send_command({"cmd": "shutdown"})
            except RuntimeError:
                pass
            finally:
                self._process.wait(timeout=30)

        self._process = None
        self._shutdown_done = True

    def __enter__(self) -> "PersistentRuntime":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.shutdown()


class AsyncPersistentRuntime:
    """Python wrapper around the long-running Faultline `serve-async` process."""

    def __init__(
        self,
        runtime_dir: str = "../runtime",
        *,
        write_delay_ms: int = 0,
        queue_capacity: int | None = None,
    ) -> None:
        self.runtime_dir = resolve_runtime_dir(runtime_dir)
        self.write_delay_ms = write_delay_ms
        self.queue_capacity = queue_capacity
        self._process: subprocess.Popen[str] | None = None
        self._shutdown_done = False

    def start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return

        self._shutdown_done = False
        self._process = subprocess.Popen(
            build_serve_command(
                "serve-async",
                self.write_delay_ms,
                queue_capacity=self.queue_capacity,
            ),
            cwd=self.runtime_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def _send_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._process is None or self._process.poll() is not None:
            raise RuntimeError(
                "AsyncPersistentRuntime is not running; call start() first"
            )

        assert self._process.stdin is not None
        assert self._process.stdout is not None

        line = json.dumps(payload)
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()

        response_line = self._process.stdout.readline()
        if response_line == "":
            raise RuntimeError("Faultline async service closed stdout before responding")

        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Faultline async service returned invalid JSON: {response_line!r}"
            ) from exc

        if not response.get("ok"):
            raise RuntimeError(response.get("error", "unknown async service error"))

        return response

    def enqueue_checkpoint_file(self, step: int, file_path: str) -> str:
        resolved = str(Path(file_path).resolve())
        response = self._send_command(
            {"cmd": "enqueue_from_file", "step": step, "path": resolved}
        )
        return response.get("message", f"queued checkpoint step {step}")

    def try_enqueue_checkpoint_file(self, step: int, file_path: str) -> bool:
        resolved = str(Path(file_path).resolve())
        response = self._send_command(
            {"cmd": "try_enqueue_from_file", "step": step, "path": resolved}
        )
        return bool(response.get("queued", False))

    def enqueue_pickle_checkpoint_via_file(self, step: int, payload: object) -> str:
        temp_path: str | None = None
        try:
            data = pickle.dumps(payload)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as handle:
                handle.write(data)
                temp_path = handle.name
            return self.enqueue_checkpoint_file(step, temp_path)
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    def try_enqueue_pickle_checkpoint_via_file(self, step: int, payload: object) -> bool:
        temp_path: str | None = None
        try:
            data = pickle.dumps(payload)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as handle:
                handle.write(data)
                temp_path = handle.name
            return self.try_enqueue_checkpoint_file(step, temp_path)
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    def checkpoint_status(self, step: int) -> str:
        response = self._send_command({"cmd": "status", "step": step})
        status = response.get("status")
        if status is None:
            raise RuntimeError(f"No status returned for step {step}")
        return str(status)

    def metrics(self) -> dict[str, Any]:
        response = self._send_command({"cmd": "metrics"})
        metrics = response.get("metrics")
        if metrics is None:
            raise RuntimeError("No metrics returned from async service")
        return metrics

    def enqueue_worker_pickle_checkpoint_via_file(
        self, worker_id: int, local_step: int, payload: object
    ) -> str:
        temp_path: str | None = None
        try:
            data = pickle.dumps(payload)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as handle:
                handle.write(data)
                temp_path = handle.name
            return self.enqueue_worker_checkpoint_file(
                worker_id,
                local_step,
                global_step_for_worker(worker_id, local_step),
                temp_path,
            )
        finally:
            if temp_path is not None:
                Path(temp_path).unlink(missing_ok=True)

    def enqueue_worker_checkpoint_file(
        self, worker_id: int, local_step: int, global_step: int, file_path: str
    ) -> str:
        resolved = str(Path(file_path).resolve())
        response = self._send_command(
            {
                "cmd": "enqueue_worker_from_file",
                "worker_id": worker_id,
                "local_step": local_step,
                "step": global_step,
                "path": resolved,
            }
        )
        return response.get(
            "message",
            f"queued worker {worker_id} checkpoint local_step {local_step}",
        )

    def latest_checkpoint_for_worker(self, worker_id: int) -> dict[str, Any] | None:
        response = self._send_command(
            {"cmd": "latest_for_worker", "worker_id": worker_id}
        )
        checkpoint = response.get("checkpoint")
        if checkpoint is None:
            return None
        return checkpoint

    def prune_per_worker(self, keep_last_per_worker: int) -> str:
        """Prune worker checkpoints. Call after queued writes have committed."""
        response = self._send_command(
            {"cmd": "prune_per_worker", "keep_last_per_worker": keep_last_per_worker}
        )
        deleted = response.get("deleted", 0)
        return f"Deleted {deleted} checkpoint file(s) (per-worker retention)."

    def shutdown(self) -> None:
        if self._shutdown_done:
            return

        if self._process is not None and self._process.poll() is None:
            try:
                self._send_command({"cmd": "shutdown"})
            except RuntimeError:
                pass
            finally:
                self._process.wait(timeout=60)

        self._process = None
        self._shutdown_done = True

    def __enter__(self) -> "AsyncPersistentRuntime":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.shutdown()
