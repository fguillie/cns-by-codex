#!/usr/bin/env python3
# Serves the CNS matrix dashboard and handles start/stop control requests.

from __future__ import annotations

import argparse
import http.server
import html
import json
import pathlib
import shlex
import subprocess
import urllib.parse
import uuid
from typing import Any

import cns_matrix_dashboard
import cns_matrix_service


DEFAULT_BASE_DIR = pathlib.Path("/var/lib/cns-matrix")


class MatrixDashboardHandler(http.server.SimpleHTTPRequestHandler):
    base_dir: pathlib.Path
    repo_root: pathlib.Path
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".log": "text/plain; charset=utf-8",
    }

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            cns_matrix_dashboard.main_for_base(self.base_dir)
        if self.path == "/api/status":
            self.write_json(
                {
                    "ok": True,
                    "service": service_state("cns-matrix.service"),
                    "web_service": service_state("cns-matrix-web.service"),
                }
            )
            return
        if self.path.startswith("/view-log?"):
            self.handle_view_log()
            return
        if self.path.startswith("/view-json?"):
            self.handle_view_json()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.path.startswith("/view-log?"):
            self.handle_view_log(head_only=True)
            return
        if self.path.startswith("/view-json?"):
            self.handle_view_json(head_only=True)
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        if self.path == "/api/start":
            self.handle_start()
            return
        if self.path == "/api/stop":
            self.handle_stop()
            return
        self.send_error(404, "unknown endpoint")

    def handle_start(self) -> None:
        payload = self.read_json_payload()
        args = str(payload.get("args", ""))
        item = enqueue_run(
            self.base_dir,
            args=args,
            source_run_id=str(payload.get("source_run_id", "")),
        )
        service = service_state("cns-matrix.service")
        if service not in ("active", "activating"):
            start = run_command(
                [
                    "sudo",
                    "-n",
                    "systemctl",
                    "start",
                    "--no-block",
                    "cns-matrix.service",
                ],
            )
            if start.returncode != 0:
                remove_queue_item(self.base_dir, item["id"])
                self.write_command_error("failed to start cns-matrix.service", start)
                return
            message = "run queued and cns-matrix.service start requested"
        else:
            message = "run queued behind the active matrix run"
        cns_matrix_dashboard.main_for_base(self.base_dir)
        self.write_json({"ok": True, "message": message, "queue_item": item})

    def handle_stop(self) -> None:
        payload = self.read_json_payload()
        queue_id = str(payload.get("queue_id", ""))
        if queue_id:
            removed = remove_queue_item(self.base_dir, queue_id)
            cns_matrix_dashboard.main_for_base(self.base_dir)
            self.write_json(
                {
                    "ok": True,
                    "message": "queued run removed" if removed else "queued run not found",
                }
            )
            return

        stop = run_command(["sudo", "-n", "systemctl", "stop", "cns-matrix.service"])
        if stop.returncode != 0:
            self.write_command_error("failed to stop cns-matrix.service", stop)
            return
        cns_matrix_dashboard.main_for_base(self.base_dir)
        self.write_json({"ok": True, "message": "cns-matrix.service stopped"})

    def handle_view_log(self, *, head_only: bool = False) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        requested = query.get("path", [""])[0]
        log_path = safe_log_path(self.base_dir / "www", requested)
        if log_path is None:
            self.send_error(404, "log not found")
            return
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.send_error(404, "log not found")
            return

        title = html.escape(requested)
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      background: #111820;
      color: #e9eef5;
      font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }}
    header {{
      position: sticky;
      top: 0;
      background: #1d2733;
      border-bottom: 1px solid #354252;
      padding: 10px 14px;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    pre {{
      margin: 0;
      padding: 14px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
  </style>
</head>
<body>
  <header>{title}</header>
  <pre>{html.escape(content)}</pre>
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        if not head_only:
            self.wfile.write(encoded)

    def handle_view_json(self, *, head_only: bool = False) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        requested = query.get("path", [""])[0]
        json_path = safe_json_path(self.base_dir / "www", requested)
        if json_path is None:
            self.send_error(404, "json not found")
            return
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            content = json.dumps(data, indent=2, sort_keys=True)
        except (OSError, json.JSONDecodeError):
            self.send_error(404, "json not found")
            return

        title = html.escape(requested)
        body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      background: #111820;
      color: #e9eef5;
      font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }}
    header {{
      position: sticky;
      top: 0;
      background: #1d2733;
      border-bottom: 1px solid #354252;
      padding: 10px 14px;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    pre {{
      margin: 0;
      padding: 14px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}
  </style>
</head>
<body>
  <header>{title}</header>
  <pre>{html.escape(content)}</pre>
</body>
</html>
"""
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        if not head_only:
            self.wfile.write(encoded)

    def read_json_payload(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def write_command_error(self, message: str, result: subprocess.CompletedProcess[str]) -> None:
        self.write_json(
            {
                "ok": False,
                "message": message,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            status=500,
        )

    def write_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    args = parse_args()
    base_dir = args.base_dir.resolve()
    repo_root = args.repo_root.resolve()
    web_dir = base_dir / "www"
    cns_matrix_dashboard.main_for_base(base_dir)

    handler = lambda *handler_args, **handler_kwargs: MatrixDashboardHandler(
        *handler_args,
        directory=str(web_dir),
        **handler_kwargs,
    )
    MatrixDashboardHandler.base_dir = base_dir
    MatrixDashboardHandler.repo_root = repo_root
    with http.server.ThreadingHTTPServer((args.bind, args.port), handler) as server:
        server.serve_forever()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the CNS matrix dashboard.")
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--base-dir", type=pathlib.Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8888)
    return parser.parse_args()


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )


def safe_log_path(web_dir: pathlib.Path, requested: str) -> pathlib.Path | None:
    decoded = urllib.parse.unquote(requested).lstrip("/")
    if not decoded.startswith("runs/") or not decoded.endswith(".log"):
        return None
    candidate = (web_dir / decoded).resolve()
    runs_root = (web_dir / "runs").resolve()
    try:
        candidate.relative_to(runs_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def safe_json_path(web_dir: pathlib.Path, requested: str) -> pathlib.Path | None:
    decoded = urllib.parse.unquote(requested).lstrip("/")
    if not decoded.startswith("runs/") or not decoded.endswith(".json"):
        return None
    candidate = (web_dir / decoded).resolve()
    runs_root = (web_dir / "runs").resolve()
    try:
        candidate.relative_to(runs_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def enqueue_run(
    base_dir: pathlib.Path,
    *,
    args: str,
    source_run_id: str,
) -> dict[str, Any]:
    queue_path = base_dir / "state" / "queue.json"
    queue = cns_matrix_service.read_queue(queue_path)
    item = {
        "id": uuid.uuid4().hex,
        "created_at": cns_matrix_service.utc_timestamp(),
        "args": shlex.split(args),
        "args_text": args,
        "source_run_id": source_run_id,
    }
    queue.append(item)
    cns_matrix_service.write_json_atomic(
        queue_path,
        {"schema_version": 1, "items": queue},
    )
    return item


def remove_queue_item(base_dir: pathlib.Path, queue_id: str) -> bool:
    queue_path = base_dir / "state" / "queue.json"
    queue = cns_matrix_service.read_queue(queue_path)
    remaining = [item for item in queue if item.get("id") != queue_id]
    cns_matrix_service.write_json_atomic(
        queue_path,
        {"schema_version": 1, "items": remaining},
    )
    return len(remaining) != len(queue)


def service_state(name: str) -> str:
    result = run_command(["systemctl", "is-active", name])
    return result.stdout.strip() or "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
