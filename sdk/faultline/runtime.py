import subprocess
from pathlib import Path


class Runtime:
    """Python wrapper around the Faultline Rust CLI (subprocess-based)."""

    def __init__(self, runtime_dir: str = "../runtime") -> None:
        path = Path(runtime_dir)
        if not path.is_absolute():
            path = Path.cwd() / path
        self.runtime_dir = str(path.resolve())

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
        if data is not None:
            if isinstance(data, bytes):
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(
                        "Checkpoint data bytes must be valid UTF-8 for CLI transport"
                    ) from exc
            else:
                text = data
            args.extend(["--data", text])
        return self._run_command(args)

    def list_checkpoints(self) -> str:
        return self._run_command(["list"])

    def latest_checkpoint(self) -> str:
        return self._run_command(["latest"])

    def load_latest(self) -> str:
        return self._run_command(["load-latest"])

    def prune(self, keep_last: int) -> str:
        return self._run_command(["prune", str(keep_last)])
