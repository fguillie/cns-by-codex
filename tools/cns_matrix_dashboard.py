#!/usr/bin/env python3
# Generates the static CNS matrix dashboard from durable run artifacts.

from __future__ import annotations

import argparse
import html
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


DEFAULT_BASE_DIR = pathlib.Path("/var/lib/cns-matrix")
PHASE_LOGS = (
    ("install", "01-install.log"),
    ("rerun", "02-install-rerun.log"),
    ("uninstall", "03-uninstall.log"),
    ("cleanup", "04-uninstall-rerun.log"),
)
VALIDATION_LOGS = (
    "validate-node-ready.log",
    "validate-calico.log",
    "validate-admin-kubectl.log",
    "validate-gpu-helm.log",
    "validate-nfs-helm.log",
    "validate-metallb-helm.log",
)


def main() -> int:
    args = parse_args()
    base_dir = args.base_dir.resolve()
    web_dir = args.output_dir.resolve() if args.output_dir else base_dir / "www"
    generate_dashboard(base_dir, web_dir)
    return 0


def main_for_base(base_dir: pathlib.Path) -> None:
    generate_dashboard(base_dir.resolve(), base_dir.resolve() / "www")


def generate_dashboard(base_dir: pathlib.Path, web_dir: pathlib.Path) -> None:
    web_dir.mkdir(parents=True, exist_ok=True)
    ensure_runs_link(base_dir, web_dir)

    current = read_json(base_dir / "state" / "current.json")
    runs = collect_runs(base_dir)
    selected = selected_run(current, runs)
    index = render_dashboard(base_dir, current, selected, runs)
    (web_dir / "index.html").write_text(index, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the static CNS matrix dashboard.",
    )
    parser.add_argument(
        "--base-dir",
        type=pathlib.Path,
        default=DEFAULT_BASE_DIR,
        help="CNS matrix runtime directory.",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=None,
        help="Dashboard output directory. Defaults to <base-dir>/www.",
    )
    return parser.parse_args()


def ensure_runs_link(base_dir: pathlib.Path, web_dir: pathlib.Path) -> None:
    runs_dir = base_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    link_path = web_dir / "runs"
    if link_path.is_symlink() or link_path.exists():
        return
    link_path.symlink_to(runs_dir, target_is_directory=True)


def collect_runs(base_dir: pathlib.Path) -> list[dict[str, Any]]:
    runs_dir = base_dir / "runs"
    if not runs_dir.exists():
        return []

    runs = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        summary = read_json(run_dir / "summary.json")
        if not summary:
            summary = {
                "status": "unknown",
                "started_at": "",
                "updated_at": "",
                "cases_total": 0,
                "cases_completed": 0,
                "passed_cases": 0,
                "failed_cases": 0,
                "results": [],
            }
        summary["_run_id"] = run_dir.name
        summary["_run_dir"] = str(run_dir)
        summary["_mtime"] = (run_dir / "summary.json").stat().st_mtime if (
            run_dir / "summary.json"
        ).exists() else run_dir.stat().st_mtime
        runs.append(summary)

    return sorted(
        runs,
        key=lambda item: (str(item.get("started_at") or ""), item.get("_mtime", 0)),
        reverse=True,
    )


def selected_run(
    current: dict[str, Any],
    runs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    current_run_id = current.get("run_id")
    if isinstance(current_run_id, str):
        for run in runs:
            if run.get("_run_id") == current_run_id:
                merged = dict(run)
                merged["_current_status"] = current.get("status")
                return merged
        if current:
            return {
                "_run_id": current_run_id,
                "_run_dir": current.get("run_dir", ""),
                "status": current.get("status", "running"),
                "started_at": current.get("started_at", ""),
                "updated_at": current.get("updated_at", ""),
                "target": current.get("target", {}),
                "stacks": [],
                "stack_overrides_label": "unknown",
                "cases_total": 0,
                "cases_completed": 0,
                "passed_cases": 0,
                "failed_cases": 0,
                "results": [],
            }
    return runs[0] if runs else None


def render_dashboard(
    base_dir: pathlib.Path,
    current: dict[str, Any],
    selected: dict[str, Any] | None,
    runs: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
    if selected is None:
        body = empty_state(generated_at)
    else:
        body = "\n".join(
            (
                hero_section(selected, generated_at),
                summary_grid(selected),
                case_table(base_dir, selected),
                recent_runs_table(runs),
            )
        )
    current_status = html.escape(str(current.get("status", "idle")))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="30">
  <title>CNS Matrix Dashboard</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --panel: #ffffff;
      --line: #d8dee8;
      --ink: #18202b;
      --muted: #647084;
      --pass: #0f7b4a;
      --fail: #b42318;
      --run: #946200;
      --skip: #627084;
      --link: #165dba;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      background: #1d2733;
      color: #fff;
      padding: 22px clamp(16px, 4vw, 48px);
      border-bottom: 4px solid #2f855a;
    }}
    main {{
      width: min(1440px, 100%);
      margin: 0 auto;
      padding: 22px clamp(14px, 3vw, 36px) 40px;
    }}
    h1, h2 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: 28px; font-weight: 720; }}
    h2 {{ font-size: 17px; margin: 26px 0 10px; }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .topline {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      align-items: baseline;
      margin-top: 8px;
      color: #dce4ee;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 9px;
      border-radius: 999px;
      font-weight: 700;
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: .04em;
    }}
    .badge.pass, .pill.pass {{ background: #dff3e9; color: var(--pass); }}
    .badge.fail, .pill.fail {{ background: #fde7e5; color: var(--fail); }}
    .badge.running, .pill.running {{ background: #fff1cc; color: var(--run); }}
    .badge.unknown, .pill.unknown, .pill.skip {{ background: #e9edf3; color: var(--skip); }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px 14px;
    }}
    .metric .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    .metric .value {{ display: block; margin-top: 5px; font-size: 19px; font-weight: 720; overflow-wrap: anywhere; }}
    .progress {{
      height: 12px;
      background: #e3e8ef;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 18px;
      border: 1px solid var(--line);
    }}
    .progress span {{ display: block; height: 100%; background: #2f855a; }}
    .table-wrap {{
      overflow-x: auto;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{ width: 100%; border-collapse: collapse; min-width: 980px; }}
    th, td {{ padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: #445064; font-size: 12px; text-transform: uppercase; background: #eef2f7; }}
    tr:last-child td {{ border-bottom: 0; }}
    .pill {{
      display: inline-flex;
      min-width: 56px;
      justify-content: center;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 12px;
      text-transform: uppercase;
    }}
    .logs {{ display: flex; flex-wrap: wrap; gap: 7px; }}
    .logs a {{ white-space: nowrap; }}
    .muted {{ color: var(--muted); }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 22px;
      margin-top: 18px;
    }}
    footer {{ margin-top: 28px; color: var(--muted); font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <h1>CNS Matrix Dashboard</h1>
    <div class="topline">
      <span>Web status: {current_status}</span>
      <span>Auto-refreshes every 30 seconds</span>
    </div>
  </header>
  <main>
    {body}
    <footer>Generated {html.escape(generated_at)}</footer>
  </main>
</body>
</html>
"""


def empty_state(generated_at: str) -> str:
    return (
        '<section class="empty">'
        "<h2>No Matrix Runs Yet</h2>"
        f'<p class="muted">Dashboard generated {html.escape(generated_at)}. '
        "Start cns-matrix.service to create the first run.</p>"
        "</section>"
    )


def hero_section(run: dict[str, Any], generated_at: str) -> str:
    status = normalized_status(run.get("_current_status") or run.get("status"))
    run_id = str(run.get("_run_id", "unknown"))
    target = run.get("target", {})
    target_label = ""
    if isinstance(target, dict):
        user = target.get("user", "")
        host = target.get("host", "")
        target_label = f"{user}@{host}" if user or host else ""
    stacks = ", ".join(str(item) for item in run.get("stacks", [])) or "-"
    overrides = str(run.get("stack_overrides_label") or "none")
    progress = progress_percent(run)
    matrix_log = link("matrix.log", f"runs/{url_escape(run_id)}/matrix.log")
    summary_json = link("summary.json", f"runs/{url_escape(run_id)}/summary.json")
    return f"""
<section>
  <div class="badge {status}">{html.escape(status)}</div>
  <h2>{html.escape(run_id)}</h2>
  <div class="topline muted">
    <span>Target: {html.escape(target_label or "-")}</span>
    <span>Stacks: {html.escape(stacks)}</span>
    <span>Overrides: {html.escape(overrides)}</span>
    <span>{matrix_log}</span>
    <span>{summary_json}</span>
  </div>
  <div class="progress" aria-label="case progress">
    <span style="width: {progress}%"></span>
  </div>
</section>
"""


def summary_grid(run: dict[str, Any]) -> str:
    total = int_value(run.get("cases_total"))
    complete = int_value(run.get("cases_completed"))
    passed = int_value(run.get("passed_cases"))
    failed = int_value(run.get("failed_cases"))
    duration = duration_label(run)
    values = (
        ("Cases", f"{complete} / {total}"),
        ("Passed", str(passed)),
        ("Failed", str(failed)),
        ("Duration", duration),
        ("Started", str(run.get("started_at") or "-")),
        ("Updated", str(run.get("updated_at") or "-")),
    )
    metrics = "\n".join(
        f'<div class="metric"><span class="label">{html.escape(label)}</span>'
        f'<span class="value">{html.escape(value)}</span></div>'
        for label, value in values
    )
    return f'<section class="summary">{metrics}</section>'


def case_table(base_dir: pathlib.Path, run: dict[str, Any]) -> str:
    rows = run.get("results", [])
    if not isinstance(rows, list) or not rows:
        return '<section><h2>Cases</h2><div class="empty muted">No completed cases yet.</div></section>'

    run_id = str(run.get("_run_id", ""))
    rendered_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered_rows.append(case_row(base_dir, run_id, row))
    return f"""
<section>
  <h2>Cases</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Case</th>
          <th>Stack</th>
          <th>GPU</th>
          <th>NFS</th>
          <th>MetalLB</th>
          <th>Containerd</th>
          <th>Install</th>
          <th>Rerun</th>
          <th>Validate</th>
          <th>Uninstall</th>
          <th>Cleanup</th>
          <th>Result</th>
          <th>Logs</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rendered_rows)}
      </tbody>
    </table>
  </div>
</section>
"""


def case_row(base_dir: pathlib.Path, run_id: str, row: dict[str, Any]) -> str:
    case_name = str(row.get("case_name") or "")
    log_links = case_log_links(base_dir, run_id, case_name)
    return f"""
<tr>
  <td>{html.escape(case_name or "-")}</td>
  <td>{html.escape(str(row.get("stack", "-")))}</td>
  <td>{html.escape(str(row.get("cuda_driver_version", "-")))}</td>
  <td>{html.escape(str(row.get("nfs_provisioner_version", "-")))}</td>
  <td>{html.escape(str(row.get("metallb_version", "-")))}</td>
  <td>{html.escape(str(row.get("containerd_version", "-")))}</td>
  <td>{status_pill(row.get("install"))}</td>
  <td>{status_pill(row.get("rerun"))}</td>
  <td>{status_pill(row.get("validate"))}</td>
  <td>{status_pill(row.get("uninstall"))}</td>
  <td>{status_pill(row.get("cleanup"))}</td>
  <td>{status_pill(row.get("result"))}</td>
  <td><div class="logs">{log_links}</div></td>
  <td>{html.escape(str(row.get("reason") or ""))}</td>
</tr>
"""


def case_log_links(base_dir: pathlib.Path, run_id: str, case_name: str) -> str:
    if not run_id:
        return '<span class="muted">-</span>'
    links = []
    if case_name == "pre-clean":
        links.append(log_link_if_exists(base_dir, run_id, ("pre-clean-uninstall.log",), "pre-clean"))
    elif case_name:
        for label, filename in PHASE_LOGS:
            links.append(log_link_if_exists(base_dir, run_id, (case_name, filename), label))
        for filename in VALIDATION_LOGS:
            links.append(
                log_link_if_exists(
                    base_dir,
                    run_id,
                    (case_name, filename),
                    filename.removesuffix(".log").replace("validate-", ""),
                )
            )
    links = [item for item in links if item]
    return "\n".join(links) if links else '<span class="muted">pending</span>'


def log_link_if_exists(
    base_dir: pathlib.Path,
    run_id: str,
    parts: tuple[str, ...],
    label: str,
) -> str:
    path = base_dir / "runs" / run_id
    for part in parts:
        path = path / part
    if not path.exists():
        return ""
    href = "/".join(["runs", url_escape(run_id), *(url_escape(part) for part in parts)])
    return link(label, href)


def recent_runs_table(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return ""
    rows = []
    for run in runs[:20]:
        run_id = str(run.get("_run_id", "unknown"))
        rows.append(
            "<tr>"
            f"<td>{link(run_id, f'runs/{url_escape(run_id)}/summary.json')}</td>"
            f"<td>{status_pill(run.get('status'))}</td>"
            f"<td>{html.escape(str(run.get('cases_completed', 0)))} / {html.escape(str(run.get('cases_total', 0)))}</td>"
            f"<td>{html.escape(str(run.get('passed_cases', 0)))}</td>"
            f"<td>{html.escape(str(run.get('failed_cases', 0)))}</td>"
            f"<td>{html.escape(duration_label(run))}</td>"
            f"<td>{html.escape(str(run.get('started_at') or '-'))}</td>"
            "</tr>"
        )
    return f"""
<section>
  <h2>Recent Runs</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Run</th>
          <th>Status</th>
          <th>Cases</th>
          <th>Passed</th>
          <th>Failed</th>
          <th>Duration</th>
          <th>Started</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def progress_percent(run: dict[str, Any]) -> int:
    total = int_value(run.get("cases_total"))
    if total <= 0:
        return 0
    complete = min(int_value(run.get("cases_completed")), total)
    return round((complete / total) * 100)


def duration_label(run: dict[str, Any]) -> str:
    started = parse_timestamp(run.get("started_at"))
    finished = parse_timestamp(run.get("finished_at")) or parse_timestamp(
        run.get("updated_at")
    )
    if not started or not finished:
        return "-"
    seconds = max(0, int((finished - started).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def status_pill(value: object) -> str:
    status = normalized_status(value)
    return f'<span class="pill {status}">{html.escape(status)}</span>'


def normalized_status(value: object) -> str:
    status = str(value or "unknown").lower()
    if status in ("pass", "passed"):
        return "pass"
    if status in ("fail", "failed"):
        return "fail"
    if status in ("running", "pending"):
        return "running"
    if status == "skip":
        return "skip"
    return "unknown"


def int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def link(label: str, href: str) -> str:
    return f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'


def url_escape(value: str) -> str:
    return value.replace("%", "%25").replace("/", "%2F").replace(" ", "%20")


if __name__ == "__main__":
    raise SystemExit(main())
