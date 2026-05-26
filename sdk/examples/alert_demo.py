"""
Demonstrate Faultline training-run alerts (stale run, metric threshold).

Prerequisites:
  cd runtime && cargo run -- serve-grpc --addr 127.0.0.1:50051
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faultline.grpc_client import GrpcAsyncRuntime


def print_alerts(result: dict) -> None:
    print(f"Active alerts: {result['active_count']}")
    for alert in result["alerts"]:
        run = alert.get("run_id") or "(global)"
        print(
            f"  [{alert['severity']}] {alert['alert_type']} run={run} "
            f"@ {alert['timestamp_ms']}: {alert['message']}"
        )
    if not result["alerts"]:
        print("  (none)")


def main() -> int:
    client = GrpcAsyncRuntime(addr="127.0.0.1:50051", start_server=False)
    client.start()

    try:
        run = client.create_run("alert-demo", "stale-and-loss")
        run_id = run["run_id"]
        print(f"Created run {run_id}")

        client.log_run_metrics(
            run_id,
            step=1,
            metrics={"loss": 2.0, "learning_rate": 0.01},
        )
        client.log_run_metrics(
            run_id,
            step=2,
            metrics={"loss": 15.0, "learning_rate": 0.01},
        )

        # High loss (15) triggers default metric_threshold (loss > 10).
        # Stale-run alerts need 60s without metrics on a running job (see README).
        print("\n--- evaluate_alerts (high loss) ---")
        print_alerts(client.evaluate_alerts())

        print("\n--- list_alerts (cached) ---")
        print_alerts(client.list_alerts())

        client.complete_run(run_id, status="completed")
        print(f"\nCompleted run {run_id}")

        print("\n--- evaluate_alerts (after complete; stale should clear) ---")
        print_alerts(client.evaluate_alerts())
    finally:
        client.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
