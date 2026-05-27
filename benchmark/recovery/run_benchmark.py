"""Recovery benchmarking for Faultline Cloud."""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from faultline.cloud_client import CloudIngestClient


def _ms(start: float, end: float) -> int:
    return int((end - start) * 1000)


def run_once(client: CloudIngestClient, project: str, run_name: str) -> dict[str, int]:
    run = client.start_run(project, run_name, tags=["benchmark", "recovery"])
    run_id = str(run["run_id"])
    client.log_metrics(run_id, step=100, metrics={"loss": 0.5})

    t0 = time.perf_counter()
    client.upload_checkpoint(run_id, step=100, data=b"x" * 1024 * 256)
    t1 = time.perf_counter()

    client.log_event(
        run_id,
        event_type="faultline.run.failed",
        level="error",
        message="benchmark failure event",
    )
    t2 = time.perf_counter()
    recovery = client.get_recovery(run_id)
    t3 = time.perf_counter()
    client.resume_run(run_id)
    t4 = time.perf_counter()

    return {
        "upload_latency_ms": _ms(t0, t1),
        "recovery_detection_ms": _ms(t2, t3),
        "resume_startup_ms": _ms(t3, t4),
        "estimated_lost_steps": int(recovery.get("estimated_lost_steps", 0)),
    }


def render_report(samples: list[dict[str, int]]) -> str:
    def avg(key: str) -> float:
        vals = [float(s[key]) for s in samples]
        return statistics.mean(vals) if vals else 0.0

    def latest(key: str) -> int:
        return int(samples[-1][key]) if samples else 0

    return (
        "# Recovery Benchmark Report\n\n"
        f"- Runs: {len(samples)}\n"
        f"- Avg checkpoint upload latency: {avg('upload_latency_ms'):.1f} ms\n"
        f"- Avg recovery detection time: {avg('recovery_detection_ms'):.1f} ms\n"
        f"- Avg resume startup time: {avg('resume_startup_ms'):.1f} ms\n"
        f"- Avg estimated lost progress: {avg('estimated_lost_steps'):.1f} steps\n"
        f"- Latest recovery latency sample: {latest('recovery_detection_ms')} ms\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Faultline recovery benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--api-key", default="fl_dev_local")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--project", default="recovery-benchmark")
    parser.add_argument("--output", default="benchmark/recovery/REPORT.md")
    args = parser.parse_args()

    client = CloudIngestClient(base_url=args.base_url, api_key=args.api_key)
    samples = [
        run_once(client, args.project, f"recovery-benchmark-{i + 1}")
        for i in range(max(1, args.runs))
    ]
    report = render_report(samples)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
