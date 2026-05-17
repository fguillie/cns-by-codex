#!/usr/bin/env python3
# Runs the CNS matrix under systemd and maintains dashboard state files.

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any

import cns_matrix_dashboard


DEFAULT_BASE_DIR = pathlib.Path("/var/lib/cns-matrix")
DEFAULT_HOST = "10.86.6.94"
DEFAULT_USER = "nvidia"


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    base_dir = args.base_dir.resolve()
    runtime = prepare_runtime(base_dir)

    host = os.environ.get("CNS_MATRIX_HOST", DEFAULT_HOST)
    user = os.environ.get("CNS_MATRIX_USER", DEFAULT_USER)
    extra_args = shlex.split(os.environ.get("CNS_MATRIX_ARGS", ""))
    run_id = utc_stamp()
    run_dir = runtime["runs_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    matrix_log_path = run_dir / "matrix.log"
    started_at = utc_timestamp()

    command = [
        sys.executable,
        str(repo_root / "tests" / "test_cns_matrix.py"),
        "--repo-root",
        str(repo_root),
        "--host",
        host,
        "--user",
        user,
        "--log-dir",
        str(run_dir),
        "--result-json",
        str(summary_path),
        *extra_args,
    ]
    state = {
        "schema_version": 1,
        "status": "running",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "result_json": str(summary_path),
        "matrix_log": str(matrix_log_path),
        "command": command,
        "command_display": " ".join(shlex.quote(part) for part in command),
        "started_at": started_at,
        "updated_at": started_at,
        "finished_at": None,
        "exit_code": None,
        "target": {
            "host": host,
            "user": user,
        },
        "repo_root": str(repo_root),
        "extra_args": extra_args,
    }
    write_json_atomic(runtime["current_json"], state)
    write_json_atomic(run_dir / "service.json", state)
    generate_dashboard(base_dir)

    rc = run_matrix(command, repo_root, matrix_log_path, base_dir)
    finished_at = utc_timestamp()
    status = "passed" if rc == 0 else "failed"
    state.update(
        {
            "status": status,
            "updated_at": finished_at,
            "finished_at": finished_at,
            "exit_code": rc,
        }
    )
    write_json_atomic(runtime["current_json"], state)
    write_json_atomic(run_dir / "service.json", state)
    ensure_summary_exists(summary_path, state)
    generate_dashboard(base_dir)
    return rc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run test_cns_matrix.py and publish dashboard state.",
    )
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1],
        help="CNS repository root.",
    )
    parser.add_argument(
        "--base-dir",
        type=pathlib.Path,
        default=DEFAULT_BASE_DIR,
        help="CNS matrix runtime directory.",
    )
    return parser.parse_args()


def prepare_runtime(base_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    runs_dir = base_dir / "runs"
    state_dir = base_dir / "state"
    web_dir = base_dir / "www"
    for path in (runs_dir, state_dir, web_dir):
        path.mkdir(parents=True, exist_ok=True)
    cns_matrix_dashboard.ensure_runs_link(base_dir, web_dir)
    return {
        "runs_dir": runs_dir,
        "state_dir": state_dir,
        "web_dir": web_dir,
        "current_json": state_dir / "current.json",
    }


def run_matrix(
    command: list[str],
    repo_root: pathlib.Path,
    matrix_log_path: pathlib.Path,
    base_dir: pathlib.Path,
) -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = service_path(env.get("PATH", ""))
    matrix_log_path.parent.mkdir(parents=True, exist_ok=True)
    with matrix_log_path.open("w", encoding="utf-8") as log_file:
        log_file.write("# CNS matrix service run\n")
        log_file.write("$ " + " ".join(shlex.quote(part) for part in command) + "\n\n")
        log_file.flush()
        process = subprocess.Popen(
            command,
            cwd=repo_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        last_dashboard = 0.0
        assert process.stdout is not None
        for line in process.stdout:
            log_file.write(line)
            log_file.flush()
            now = time.monotonic()
            if now - last_dashboard >= 5:
                generate_dashboard(base_dir)
                last_dashboard = now
        rc = process.wait()
        log_file.write(f"\n# exit_code={rc}\n")
        log_file.flush()
    return rc


def service_path(existing_path: str) -> str:
    entries = [
        str(pathlib.Path.home() / ".local" / "bin"),
        "/usr/local/sbin",
        "/usr/local/bin",
        "/usr/sbin",
        "/usr/bin",
        "/sbin",
        "/bin",
    ]
    entries.extend(path for path in existing_path.split(os.pathsep) if path)
    deduped = list(dict.fromkeys(entries))
    return os.pathsep.join(deduped)


def ensure_summary_exists(path: pathlib.Path, state: dict[str, Any]) -> None:
    if path.exists():
        return
    payload = {
        "schema_version": 1,
        "status": state["status"],
        "started_at": state["started_at"],
        "updated_at": state["updated_at"],
        "finished_at": state["finished_at"],
        "exit_code": state["exit_code"],
        "repo_root": state.get("repo_root", ""),
        "target": state["target"],
        "stacks": [],
        "stack_overrides": {},
        "stack_overrides_label": "unknown",
        "fail_fast": False,
        "pre_clean": True,
        "log_dir": state["run_dir"],
        "cases_total": 0,
        "cases_completed": 0,
        "failed_cases": 1 if state["exit_code"] else 0,
        "passed_cases": 0,
        "results": [],
        "reason": "matrix runner exited before writing a summary",
    }
    write_json_atomic(path, payload)


def generate_dashboard(base_dir: pathlib.Path) -> None:
    cns_matrix_dashboard.main_for_base(base_dir)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def write_json_atomic(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
