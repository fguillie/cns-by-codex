#!/usr/bin/env python3
# Generates the static CNS matrix dashboard from durable run artifacts.

from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import shlex
from datetime import datetime, timezone
from typing import Any


DEFAULT_BASE_DIR = pathlib.Path("/var/lib/cns-matrix")
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
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
CONSOLE_HEADERS = (
    "STACK",
    "GPU_OPERATOR",
    "CUDA_DRIVER",
    "NFS_LOCAL_PROVISIONER",
    "METALLB",
    "METALLB_RANGE",
    "CONTAINERD",
    "INSTALL",
    "RERUN",
    "VALIDATE",
    "UNINSTALL",
    "CLEANUP",
    "SECONDS",
    "RESULT",
    "REASON",
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
    queue = read_queue(base_dir / "state" / "queue.json")
    runs = collect_runs(base_dir)
    selected = selected_run(current, runs)
    index = render_dashboard(base_dir, current, selected, runs, queue)
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
        service = read_json(run_dir / "service.json")
        summary["_extra_args"] = service.get("extra_args", [])
        summary["_queue_request"] = service.get("queue_request", {})
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
    queue: list[dict[str, Any]],
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
    if selected is None:
        body = "\n".join(
            (
                empty_state(generated_at),
                run_configuration_section(),
                queue_table(queue),
            )
        )
    else:
        body = "\n".join(
            (
                hero_section(selected, generated_at),
                summary_grid(selected),
                run_configuration_section(),
                queue_table(queue),
                console_matrix_section(base_dir, selected),
                case_table(base_dir, selected),
                recent_runs_table(runs, current),
            )
        )
    current_status = html.escape(str(current.get("status", "idle")))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
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
    .header-row {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }}
    .refresh-button {{
      background: #ffffff;
      color: #1d2733;
      border-color: #ffffff;
      white-space: nowrap;
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
    .badge.unknown, .pill.unknown, .pill.skip, .pill.stopped, .badge.stopped {{ background: #e9edf3; color: var(--skip); }}
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
    .config-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-top: 10px;
    }}
    .config-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }}
    fieldset {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px 12px;
      margin: 0;
      min-width: 0;
    }}
    legend {{
      color: #445064;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 0 4px;
    }}
    label.option {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 8px;
    }}
    .field {{ margin-top: 9px; }}
    .field label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: 4px;
    }}
    select, input[type="text"], textarea {{
      width: 100%;
      min-height: 34px;
      border: 1px solid #c9d2df;
      border-radius: 6px;
      padding: 6px 8px;
      color: var(--ink);
      background: #fff;
      font: inherit;
    }}
    textarea {{ min-height: 70px; resize: vertical; }}
    .command-block {{
      width: 100%;
      min-height: 96px;
      margin: 8px 0 0;
      background: #111820;
      color: #e9eef5;
      border: 1px solid #2a3542;
      border-radius: 8px;
      padding: 10px;
      font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      white-space: pre;
      overflow-x: auto;
    }}
    .button-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .warning {{
      color: var(--fail);
      font-weight: 700;
      margin-top: 8px;
    }}
    button {{
      min-height: 34px;
      border: 1px solid #b9c4d2;
      border-radius: 6px;
      background: #f9fbfd;
      color: var(--ink);
      padding: 6px 10px;
      font-weight: 700;
      cursor: pointer;
    }}
    button:hover {{ background: #eef4fb; }}
    button:disabled {{
      cursor: not-allowed;
      opacity: .45;
      background: #edf1f5;
    }}
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
    .console {{
      background: #111820;
      color: #e9eef5;
      border-radius: 8px;
      border: 1px solid #2a3542;
      padding: 14px;
      overflow-x: auto;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
    }}
    .console pre {{
      margin: 0;
      font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      white-space: pre;
      tab-size: 2;
    }}
    footer {{ margin-top: 28px; color: var(--muted); font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <div class="header-row">
      <h1>CNS Matrix Dashboard</h1>
      <button type="button" class="refresh-button" onclick="window.location.reload()">Refresh</button>
    </div>
    <div class="topline">
      <span>Web status: {current_status}</span>
      <span>Auto-refreshes every 1 minute</span>
    </div>
  </header>
  <main>
    {body}
    <footer>Generated {html.escape(generated_at)}</footer>
    {dashboard_script()}
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
    matrix_log = log_view_link("matrix.log", f"runs/{url_escape(run_id)}/matrix.log")
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


def run_configuration_section() -> str:
    options = dashboard_config_options()
    options_json = html.escape(json.dumps(options), quote=False)
    stack_inputs = "\n".join(
        f'<label class="option"><input type="checkbox" name="stack" value="{html.escape(stack)}" checked> {html.escape(stack)}</label>'
        for stack in options["stacks"]
    )
    driver_placeholder = ", ".join(options["cuda_driver_versions"])
    containerd_placeholder = ", ".join(options["containerd_versions"])
    metallb_placeholder = options["metallb_load_balancer_ip_range"]
    return f"""
<section>
  <h2>Run Configuration</h2>
  <div class="config-panel">
    <form id="matrix-config-form">
      <div class="config-grid">
        <fieldset>
          <legend>Stacks</legend>
          <label class="option"><input type="checkbox" id="all-stacks" checked> All discovered stacks</label>
          <div id="stack-options">{stack_inputs}</div>
        </fieldset>
        <fieldset>
          <legend>Components</legend>
          {select_field("install-gpu", "GPU Operator", "install_gpu_operator")}
          {select_field("install-nfs", "NFS provisioner", "install_nfs_provisioner")}
          {select_field("install-metallb", "MetalLB", "install_metallb")}
        </fieldset>
        <fieldset>
          <legend>Version Matrix</legend>
          <div class="field">
            <label for="cuda-driver-values">CUDA driver containers</label>
            <textarea id="cuda-driver-values" placeholder="{html.escape(driver_placeholder)}"></textarea>
          </div>
          <div class="field">
            <label for="containerd-values">containerd versions</label>
            <textarea id="containerd-values" placeholder="{html.escape(containerd_placeholder)}"></textarea>
          </div>
        </fieldset>
        <fieldset>
          <legend>Options</legend>
          <div class="field">
            <label for="metallb-range">MetalLB IP range</label>
            <input id="metallb-range" type="text" placeholder="{html.escape(metallb_placeholder)}">
          </div>
          <label class="option"><input type="checkbox" id="fail-fast"> Fail fast</label>
          <label class="option"><input type="checkbox" id="pre-clean" checked> Run pre-clean uninstall</label>
        </fieldset>
      </div>
      <div class="field">
        <label for="generated-args">Generated CNS_MATRIX_ARGS</label>
        <textarea id="generated-args" class="command-block" readonly></textarea>
      </div>
      <div class="field">
        <label for="generated-command">Apply and start command</label>
        <textarea id="generated-command" class="command-block" readonly></textarea>
      </div>
      <div id="config-warning" class="warning"></div>
      <div class="button-row">
        <button type="button" id="start-test">Start test</button>
        <button type="button" id="stop-test">Stop test</button>
        <button type="button" id="copy-args">Copy args</button>
        <button type="button" id="copy-command">Copy command</button>
        <button type="button" id="reset-config">Reset</button>
      </div>
      <div id="control-status" class="muted"></div>
    </form>
    <script id="matrix-config-options" type="application/json">{options_json}</script>
  </div>
</section>
"""


def select_field(field_id: str, label: str, key: str) -> str:
    return f"""
<div class="field">
  <label for="{field_id}">{html.escape(label)}</label>
  <select id="{field_id}" data-set-key="{html.escape(key)}">
    <option value="">Stack default</option>
    <option value="true">Force enabled</option>
    <option value="false">Force disabled</option>
  </select>
</div>
"""


def dashboard_config_options() -> dict[str, Any]:
    stacks = []
    cuda_versions = set()
    containerd_versions = set()
    metallb_ranges = set()
    for path in sorted((REPO_ROOT / "stacks").glob("*.yml")):
        data = parse_simple_yaml(path)
        stacks.append(data.get("cns_stack_version", path.stem))
        add_if_present(cuda_versions, data, "cuda_driver_container_version")
        add_if_present(containerd_versions, data, "containerd_version")
        add_if_present(metallb_ranges, data, "metallb_load_balancer_ip_range")

    cuda_versions.update(("580.159.03", "595.71.05"))
    containerd_versions.update(("2.2.3", "2.1.7"))
    return {
        "repo_root": str(REPO_ROOT),
        "stacks": stacks or ["1.36"],
        "cuda_driver_versions": sorted(cuda_versions) or ["580.126.20"],
        "containerd_versions": sorted(containerd_versions) or ["2.3.0"],
        "metallb_load_balancer_ip_range": sorted(metallb_ranges)[0]
        if metallb_ranges
        else "10.86.6.94/32",
    }


def parse_simple_yaml(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    pattern = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped == "---" or stripped.startswith("#"):
            continue
        match = pattern.match(stripped)
        if not match:
            continue
        key, value = match.groups()
        value = value.split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def add_if_present(values: set[str], data: dict[str, str], key: str) -> None:
    value = data.get(key)
    if value:
        values.add(value)


def console_matrix_section(base_dir: pathlib.Path, run: dict[str, Any]) -> str:
    current = run.get("current_case")
    current_line = current_case_line(current) or live_current_line_from_log(
        base_dir,
        run,
    )
    console_rows = console_result_rows(run)
    if current_line or console_rows:
        console = "\n".join(
            item for item in (current_line, format_console_table(console_rows)) if item
        )
    else:
        console = live_console_from_log(base_dir, run)
    return f"""
<section>
  <h2>Live Matrix Output</h2>
  <div class="console"><pre>{html.escape(console)}</pre></div>
</section>
"""


def current_case_line(current: object) -> str:
    if not isinstance(current, dict):
        return ""
    index = current.get("index")
    total = current.get("total")
    name = current.get("name")
    if index is None or total is None or not name:
        return ""
    return f"[{index}/{total}] {name}"


def console_result_rows(run: dict[str, Any]) -> list[dict[str, Any]]:
    rows = run.get("results", [])
    results = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    current = run.get("current_case")
    if not isinstance(current, dict):
        return results
    current_result = current.get("result")
    if not isinstance(current_result, dict):
        return results
    current_case_name = str(current_result.get("case_name") or "")
    if not results or str(results[-1].get("case_name") or "") != current_case_name:
        return [*results, current_result]
    if str(current_result.get("result") or "") == "running":
        return [*results[:-1], current_result]
    return results


def live_console_from_log(base_dir: pathlib.Path, run: dict[str, Any]) -> str:
    run_id = str(run.get("_run_id") or "")
    if not run_id:
        return format_console_table([])
    log_path = base_dir / "runs" / run_id / "matrix.log"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return format_console_table([])

    current_line = ""
    for line in reversed(lines):
        if re.match(r"^\[\d+/\d+\]\s+", line):
            current_line = line
            break

    table_lines = latest_console_table(lines)
    return "\n".join(item for item in (current_line, table_lines) if item)


def live_current_line_from_log(base_dir: pathlib.Path, run: dict[str, Any]) -> str:
    run_id = str(run.get("_run_id") or "")
    if not run_id:
        return ""
    log_path = base_dir / "runs" / run_id / "matrix.log"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        if re.match(r"^\[\d+/\d+\]\s+", line):
            return line
    return ""


def latest_console_table(lines: list[str]) -> str:
    header_index = -1
    for index, line in enumerate(lines):
        if line.startswith("STACK | GPU_OPERATOR"):
            header_index = index
    if header_index < 0:
        return format_console_table([])

    table = []
    for line in lines[header_index:]:
        if not line.strip():
            break
        if table and re.match(r"^\[\d+/\d+\]\s+", line):
            break
        table.append(line)
    return "\n".join(table)


def format_console_table(results: list[dict[str, Any]]) -> str:
    rows = [console_row(result) for result in results]
    widths = [
        max(len(CONSOLE_HEADERS[index]), *(len(row[index]) for row in rows))
        if rows
        else len(CONSOLE_HEADERS[index])
        for index in range(len(CONSOLE_HEADERS))
    ]
    header = " | ".join(
        CONSOLE_HEADERS[index].ljust(widths[index])
        for index in range(len(CONSOLE_HEADERS))
    )
    separator = "-+-".join("-" * width for width in widths)
    rendered_rows = [
        " | ".join(row[index].ljust(widths[index]) for index in range(len(row)))
        for row in rows
    ]
    return "\n".join([header, separator, *rendered_rows])


def console_row(result: dict[str, Any]) -> list[str]:
    return [
        str(result.get("stack") or ""),
        str(result.get("gpu_operator_version") or ""),
        str(result.get("cuda_driver_version") or ""),
        str(result.get("nfs_provisioner_version") or ""),
        str(result.get("metallb_version") or ""),
        str(result.get("metallb_ip_range") or ""),
        str(result.get("containerd_version") or ""),
        str(result.get("install") or ""),
        str(result.get("rerun") or ""),
        str(result.get("validate") or ""),
        str(result.get("uninstall") or ""),
        str(result.get("cleanup") or ""),
        seconds_value(result.get("seconds")),
        str(result.get("result") or ""),
        console_truncate(str(result.get("reason") or ""), 72),
    ]


def seconds_value(value: object) -> str:
    try:
        return f"{float(value):.0f}"
    except (TypeError, ValueError):
        return "0"


def console_truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


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
    return log_view_link(label, href)


def queue_table(queue: list[dict[str, Any]]) -> str:
    if not queue:
        return """
<section>
  <h2>Queued Runs</h2>
  <div class="empty muted">No queued runs.</div>
</section>
"""

    rows = []
    for index, item in enumerate(queue, start=1):
        queue_id = str(item.get("id") or "")
        args_text = str(item.get("args_text") or "")
        source_run_id = str(item.get("source_run_id") or "-") or "-"
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{html.escape(str(item.get('created_at') or '-'))}</td>"
            f"<td>{html.escape(source_run_id)}</td>"
            f"<td><code>{html.escape(args_text or '(stack defaults)')}</code></td>"
            f'<td><button type="button" class="remove-queued-run" data-queue-id="{html.escape(queue_id, quote=True)}">Stop</button></td>'
            "</tr>"
        )
    return f"""
<section>
  <h2>Queued Runs</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Queued</th>
          <th>Source Run</th>
          <th>Args</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def recent_runs_table(runs: list[dict[str, Any]], current: dict[str, Any]) -> str:
    if not runs:
        return ""
    rows = []
    current_run_id = str(current.get("run_id") or "")
    current_status = str(current.get("status") or "")
    for run in runs[:20]:
        run_id = str(run.get("_run_id", "unknown"))
        args_text = run_args_text(run)
        run_status = str(run.get("status") or "")
        start_disabled = " disabled" if run_status == "running" else ""
        stop_disabled = (
            ""
            if run_id == current_run_id and current_status == "running"
            else " disabled"
        )
        rows.append(
            "<tr>"
            f"<td>{link(run_id, f'runs/{url_escape(run_id)}/summary.json')}</td>"
            f"<td>{status_pill(run.get('status'))}</td>"
            f"<td>{html.escape(str(run.get('cases_completed', 0)))} / {html.escape(str(run.get('cases_total', 0)))}</td>"
            f"<td>{html.escape(str(run.get('passed_cases', 0)))}</td>"
            f"<td>{html.escape(str(run.get('failed_cases', 0)))}</td>"
            f"<td>{html.escape(duration_label(run))}</td>"
            f"<td>{html.escape(str(run.get('started_at') or '-'))}</td>"
            "<td>"
            f'<button type="button" class="start-run" data-run-id="{html.escape(run_id, quote=True)}" data-args="{html.escape(args_text, quote=True)}"{start_disabled}>Start</button> '
            f'<button type="button" class="stop-run" data-run-id="{html.escape(run_id, quote=True)}"{stop_disabled}>Stop</button>'
            "</td>"
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
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </div>
</section>
"""


def run_args_text(run: dict[str, Any]) -> str:
    queue_request = run.get("_queue_request")
    if isinstance(queue_request, dict) and isinstance(queue_request.get("args_text"), str):
        return str(queue_request["args_text"])
    extra_args = run.get("_extra_args", [])
    if isinstance(extra_args, list):
        return shlex.join(str(item) for item in extra_args)
    return ""


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def read_queue(path: pathlib.Path) -> list[dict[str, Any]]:
    data = read_json(path)
    items = data.get("items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


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
    if status == "stopped":
        return "stopped"
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


def link_new_tab(label: str, href: str) -> str:
    escaped_href = html.escape(href, quote=True)
    escaped_label = html.escape(label)
    return f'<a href="{escaped_href}" target="_blank" rel="noopener noreferrer">{escaped_label}</a>'


def log_view_link(label: str, href: str) -> str:
    viewer_href = f"/view-log?path={html.escape(href, quote=True)}"
    escaped_label = html.escape(label)
    return f'<a href="{viewer_href}" target="_blank" rel="noopener noreferrer">{escaped_label}</a>'


def url_escape(value: str) -> str:
    return value.replace("%", "%25").replace("/", "%2F").replace(" ", "%20")


def dashboard_script() -> str:
    return r"""
<script>
(function () {
  const optionsElement = document.getElementById("matrix-config-options");
  const form = document.getElementById("matrix-config-form");
  if (!optionsElement || !form) {
    return;
  }

  const options = JSON.parse(optionsElement.textContent || "{}");
  const storageKey = "cns-matrix-run-config-v1";
  const controls = {
    allStacks: document.getElementById("all-stacks"),
    stacks: Array.from(document.querySelectorAll('input[name="stack"]')),
    installGpu: document.getElementById("install-gpu"),
    installNfs: document.getElementById("install-nfs"),
    installMetallb: document.getElementById("install-metallb"),
    cudaDrivers: document.getElementById("cuda-driver-values"),
    containerdVersions: document.getElementById("containerd-values"),
    metallbRange: document.getElementById("metallb-range"),
    failFast: document.getElementById("fail-fast"),
    preClean: document.getElementById("pre-clean"),
    generatedArgs: document.getElementById("generated-args"),
    generatedCommand: document.getElementById("generated-command"),
    warning: document.getElementById("config-warning"),
    controlStatus: document.getElementById("control-status"),
    startTest: document.getElementById("start-test"),
    stopTest: document.getElementById("stop-test")
  };

  function splitValues(value) {
    return value.split(/[\s,]+/).map((item) => item.trim()).filter(Boolean);
  }

  function shellQuote(value) {
    if (value === "") {
      return "''";
    }
    return "'" + value.replace(/'/g, "'\"'\"'") + "'";
  }

  function formatArg(value) {
    return /^[A-Za-z0-9_./:=+-]+$/.test(value) ? value : shellQuote(value);
  }

  function saveConfig() {
    const data = {
      allStacks: controls.allStacks.checked,
      stacks: controls.stacks.filter((item) => item.checked).map((item) => item.value),
      installGpu: controls.installGpu.value,
      installNfs: controls.installNfs.value,
      installMetallb: controls.installMetallb.value,
      cudaDrivers: controls.cudaDrivers.value,
      containerdVersions: controls.containerdVersions.value,
      metallbRange: controls.metallbRange.value,
      failFast: controls.failFast.checked,
      preClean: controls.preClean.checked
    };
    localStorage.setItem(storageKey, JSON.stringify(data));
  }

  function loadConfig() {
    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      return;
    }
    try {
      const data = JSON.parse(raw);
      controls.allStacks.checked = data.allStacks !== false;
      const selectedStacks = new Set(data.stacks || []);
      controls.stacks.forEach((item) => {
        item.checked = selectedStacks.size === 0 || selectedStacks.has(item.value);
      });
      controls.installGpu.value = data.installGpu || "";
      controls.installNfs.value = data.installNfs || "";
      controls.installMetallb.value = data.installMetallb || "";
      controls.cudaDrivers.value = data.cudaDrivers || "";
      controls.containerdVersions.value = data.containerdVersions || "";
      controls.metallbRange.value = data.metallbRange || "";
      controls.failFast.checked = Boolean(data.failFast);
      controls.preClean.checked = data.preClean !== false;
    } catch (_error) {
      localStorage.removeItem(storageKey);
    }
  }

  function addSet(tokens, key, value) {
    if (value) {
      tokens.push("--set", key + "=" + value);
    }
  }

  function buildArgs() {
    const tokens = [];
    if (!controls.allStacks.checked) {
      const selected = controls.stacks.filter((item) => item.checked).map((item) => item.value);
      selected.forEach((stack) => tokens.push("--stack", stack));
    }
    addSet(tokens, "install_gpu_operator", controls.installGpu.value);
    addSet(tokens, "install_nfs_provisioner", controls.installNfs.value);
    addSet(tokens, "install_metallb", controls.installMetallb.value);
    splitValues(controls.cudaDrivers.value).forEach((value) => {
      addSet(tokens, "cuda_driver_container_version", value);
    });
    splitValues(controls.containerdVersions.value).forEach((value) => {
      addSet(tokens, "containerd_version", value);
    });
    const metallbRange = controls.metallbRange.value.trim();
    if (metallbRange) {
      addSet(tokens, "metallb_load_balancer_ip_range", metallbRange);
    }
    if (controls.failFast.checked) {
      tokens.push("--fail-fast");
    }
    if (!controls.preClean.checked) {
      tokens.push("--no-pre-clean");
    }
    return tokens.map(formatArg).join(" ");
  }

  function render() {
    const args = buildArgs();
    controls.generatedArgs.value = "CNS_MATRIX_ARGS=" + shellQuote(args);
    controls.generatedCommand.value = [
      "cd " + shellQuote(options.repo_root || "."),
      "sudo ./tools/set_cns_matrix_args.sh " + shellQuote(args),
      "sudo systemctl start --no-block cns-matrix.service"
    ].join("\n");
    controls.warning.textContent =
      controls.installGpu.value === "false" && splitValues(controls.cudaDrivers.value).length > 0
        ? "cuda_driver_container_version requires GPU Operator. Set GPU Operator to stack default or force enabled, or clear CUDA driver containers."
        : "";
    saveConfig();
  }

  function resetConfig() {
    localStorage.removeItem(storageKey);
    controls.allStacks.checked = true;
    controls.stacks.forEach((item) => {
      item.checked = true;
    });
    controls.installGpu.value = "";
    controls.installNfs.value = "";
    controls.installMetallb.value = "";
    controls.cudaDrivers.value = "";
    controls.containerdVersions.value = "";
    controls.metallbRange.value = "";
    controls.failFast.checked = false;
    controls.preClean.checked = true;
    render();
  }

  function copyValue(element) {
    if (!navigator.clipboard) {
      element.focus();
      element.select();
      return;
    }
    navigator.clipboard.writeText(element.value);
  }

  async function postControl(path, payload) {
    controls.controlStatus.textContent = "Sending request...";
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload || {})
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(data.message || "request failed");
      }
      controls.controlStatus.textContent = data.message || "request accepted";
      window.setTimeout(() => window.location.reload(), 1000);
    } catch (error) {
      controls.controlStatus.textContent = "Control request failed: " + error.message;
    }
  }

  form.addEventListener("input", render);
  form.addEventListener("change", render);
  document.getElementById("copy-args").addEventListener("click", () => {
    copyValue(controls.generatedArgs);
  });
  document.getElementById("copy-command").addEventListener("click", () => {
    copyValue(controls.generatedCommand);
  });
  document.getElementById("reset-config").addEventListener("click", resetConfig);
  controls.startTest.addEventListener("click", () => {
    postControl("/api/start", {args: buildArgs()});
  });
  controls.stopTest.addEventListener("click", () => {
    postControl("/api/stop", {});
  });
  document.querySelectorAll(".start-run").forEach((button) => {
    button.addEventListener("click", () => {
      postControl("/api/start", {
        args: button.dataset.args || "",
        source_run_id: button.dataset.runId || ""
      });
    });
  });
  document.querySelectorAll(".stop-run").forEach((button) => {
    button.addEventListener("click", () => {
      postControl("/api/stop", {run_id: button.dataset.runId || ""});
    });
  });
  document.querySelectorAll(".remove-queued-run").forEach((button) => {
    button.addEventListener("click", () => {
      postControl("/api/stop", {queue_id: button.dataset.queueId || ""});
    });
  });

  loadConfig();
  render();

  window.setInterval(() => {
    if (form.contains(document.activeElement)) {
      return;
    }
    window.location.reload();
  }, 60000);

})();
</script>
"""


if __name__ == "__main__":
    raise SystemExit(main())
