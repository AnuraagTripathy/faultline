"""Faultline CLI (``python -m faultline.cli``)."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import sys
import webbrowser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from faultline.config import (
    get_api_key,
    get_base_url,
    get_session_token,
    load_config,
    save_config,
)
from faultline.demo_simulator import run_live_demo
from faultline.start import DEFAULT_API_KEY

STARTER_TRAIN = '''"""Faultline starter training script.

Install: pip install faultline-sdk
"""
import os

import faultline

API_KEY = os.environ.get("FAULTLINE_API_KEY", "fl_dev_local")
BASE_URL = os.environ.get("FAULTLINE_API_URL", "http://127.0.0.1:8080")

run = faultline.quickstart(project="demo", api_key=API_KEY, base_url=BASE_URL)

for step in range(50):
    loss = 1.0 / (step + 1)
    faultline.log_progress(run, step, loss=loss)
    if step % 10 == 0 and step > 0:
        run.save(step=step)

run.complete()
print("Done — view the run in the Faultline dashboard")
'''

ENV_TEMPLATE = """# Faultline Cloud
FAULTLINE_API_KEY=fl_dev_local
FAULTLINE_API_URL=http://127.0.0.1:8080
"""


def _http_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else None
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"request failed: {error}") from error


def cmd_init(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    train_py = target / "train.py"
    env_file = target / ".env.example"
    if not train_py.exists():
        train_py.write_text(STARTER_TRAIN, encoding="utf-8")
        print(f"wrote {train_py}")
    if not env_file.exists():
        env_file.write_text(ENV_TEMPLATE, encoding="utf-8")
        print(f"wrote {env_file}")
    print(
        "\nNext steps:\n"
        "  1. pip install faultline-sdk   (or pip install -e sdk from the repo)\n"
        "  2. Copy .env.example to .env and set FAULTLINE_API_KEY\n"
        "  3. docker compose -f docker-compose.cloud.yml up --build\n"
        "  4. python train.py\n"
        "  5. Open http://localhost:3000\n"
    )
    return 0


def cmd_resume(run_id: str) -> int:
    print(
        f"Resume on your machine:\n\n"
        f"  import faultline\n"
        f"  run = faultline.attach({run_id!r})\n"
        f"  start_step = run.restore_latest(model=model, optimizer=optimizer)\n"
    )
    return 0


def cmd_login(email: str, password: str, base_url: str) -> int:
    payload = _http_json(
        "POST",
        f"{base_url}/v1/auth/login",
        body={"email": email, "password": password},
    )
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        print("login failed: no access token", file=sys.stderr)
        return 1
    cfg = load_config()
    cfg["email"] = email
    cfg["access_token"] = token
    cfg["base_url"] = base_url
    save_config(cfg)
    print(f"Logged in as {email}")
    print(f"Config saved to ~/.faultline/config.json")
    return 0


def cmd_whoami(base_url: str) -> int:
    token = get_session_token()
    api_key = get_api_key()
    if token:
        payload = _http_json("GET", f"{base_url}/v1/auth/me", token=token)
        print(f"Session: {payload.get('email')} ({payload.get('user_id')})")
    elif api_key:
        payload = _http_json("GET", f"{base_url}/v1/me", token=api_key)
        user = payload.get("user", {})
        print(f"API key: {user.get('email')} ({user.get('user_id')})")
        usage = payload.get("usage", {})
        print(f"  runs: {usage.get('runs_created')}  checkpoints: {usage.get('checkpoints_created')}")
    else:
        print("Not logged in. Run: faultline login --email you@example.com")
        return 1
    return 0


def cmd_demo(
    *,
    api_key: str,
    base_url: str,
    open_browser: bool,
    no_crash: bool,
) -> int:
    print("Faultline live demo — streaming metrics to Cloud API...")
    result = run_live_demo(
        api_key=api_key,
        base_url=base_url,
        crash_at=None if no_crash else 45,
    )
    url = f"http://localhost:3000/runs/{result['run_id']}"
    print(f"Dashboard: {url}")
    if open_browser:
        webbrowser.open(url)
    return 0


def cmd_demo_crash(scenario: str) -> int:
    base_dir = Path(__file__).resolve().parents[1] / "examples" / "failure_scenarios"
    mapping = {
        "spot_gpu_interruption": "spot_gpu_interruption.py",
        "slurm_preemption": "slurm_preemption.py",
        "corrupted_checkpoint": "corrupted_checkpoint.py",
        "network_disconnect": "network_disconnect.py",
        "process_kill_resume": "process_kill_resume.py",
    }
    target = mapping.get(scenario)
    if target is None:
        print(f"unknown scenario: {scenario}", file=sys.stderr)
        return 1
    runpy.run_path(str(base_dir / target), run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="faultline",
        description="Faultline — ML training continuity and recovery",
    )
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Generate starter train.py and .env template")
    init_p.add_argument("--dir", default=".", help="Output directory")

    resume_p = sub.add_parser("resume", help="Print resume instructions for a run")
    resume_p.add_argument("run_id")

    login_p = sub.add_parser("login", help="Save browser session token locally")
    login_p.add_argument("--email", required=True)
    login_p.add_argument("--password", required=True)
    login_p.add_argument("--base-url", default=None)

    whoami_p = sub.add_parser("whoami", help="Show current login or API key identity")
    whoami_p.add_argument("--base-url", default=None)

    demo_p = sub.add_parser("demo", help="Simulate training + crash against Cloud API")
    demo_p.add_argument("--api-key", default=None)
    demo_p.add_argument("--base-url", default=None)
    demo_p.add_argument("--open", action="store_true", help="Open dashboard in browser")
    demo_p.add_argument("--no-crash", action="store_true", help="Complete without simulating crash")
    demo_sub = demo_p.add_subparsers(dest="demo_subcommand")
    crash_p = demo_sub.add_parser("crash", help="Run realistic failure simulation scenario")
    crash_p.add_argument(
        "--scenario",
        default="process_kill_resume",
        choices=[
            "spot_gpu_interruption",
            "slurm_preemption",
            "corrupted_checkpoint",
            "network_disconnect",
            "process_kill_resume",
        ],
    )

    args = parser.parse_args(argv)
    base_url = (
        getattr(args, "base_url", None) or get_base_url()
    ).rstrip("/")

    if args.command == "init":
        return cmd_init(Path(args.dir).resolve())
    if args.command == "resume":
        return cmd_resume(args.run_id)
    if args.command == "login":
        return cmd_login(args.email, args.password, base_url)
    if args.command == "whoami":
        return cmd_whoami(base_url)
    if args.command == "demo":
        if getattr(args, "demo_subcommand", None) == "crash":
            return cmd_demo_crash(args.scenario)
        key = args.api_key or get_api_key() or DEFAULT_API_KEY
        return cmd_demo(
            api_key=key,
            base_url=base_url,
            open_browser=args.open,
            no_crash=args.no_crash,
        )
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
