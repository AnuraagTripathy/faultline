"""
Demonstrate async checkpoint retries after a transient storage failure.

Runs the Rust `retry-demo` harness (in-memory FailureInjectingStorageBackend).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "runtime"


def main() -> int:
    print("Faultline retry demo (Rust in-memory failure injection)\n")
    result = subprocess.run(
        ["cargo", "run", "--quiet", "--", "retry-demo"],
        cwd=RUNTIME_DIR,
        check=False,
    )
    if result.returncode != 0:
        print("retry-demo failed; run from repo root with Rust toolchain installed.", file=sys.stderr)
        return result.returncode

    print(
        "\nExpected timeline: checkpoint_queued -> checkpoint_failed -> "
        "checkpoint_retrying -> checkpoint_committed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
