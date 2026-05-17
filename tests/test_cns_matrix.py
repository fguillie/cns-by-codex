#!/usr/bin/env python3
# Runs the live CNS Ansible validation matrix against a single target host.

from __future__ import annotations

import argparse
import ipaddress
import itertools
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable


DEFAULT_HOST = "10.86.6.94"
DEFAULT_USER = "nvidia"
DEFAULT_COMMAND_TIMEOUT = 7200
DEFAULT_WAIT_INTERVAL = 10
CUDA_DRIVER_CONTAINER_VERSION_KEY = "cuda_driver_container_version"
INSTALL_GPU_OPERATOR_KEY = "install_gpu_operator"
INSTALL_NFS_PROVISIONER_KEY = "install_nfs_provisioner"
INSTALL_METALLB_KEY = "install_metallb"
STACK_BOOL_KEYS = frozenset(
    (INSTALL_GPU_OPERATOR_KEY, INSTALL_NFS_PROVISIONER_KEY, INSTALL_METALLB_KEY)
)
KUBECONFIG = "/etc/kubernetes/admin.conf"
NFS_NAMESPACE = "nfs-provisioner"
NFS_RELEASE = "nfs-subdir-external-provisioner"
NFS_STORAGE_CLASS = "nfs-client"
NFS_CHART_PREFIX = "nfs-subdir-external-provisioner-"
METALLB_NAMESPACE = "metallb-system"
METALLB_RELEASE = "metallb"
METALLB_CHART_PREFIX = "metallb-"
METALLB_IP_ADDRESS_POOL = "cns-load-balancer-pool"
METALLB_L2_ADVERTISEMENT = "cns-l2-advertisement"
METALLB_TEST_NAMESPACE = "cns-test-metallb"
METALLB_TEST_SERVICE = "cns-test-load-balancer"
GPU_NAMESPACE = "gpu-operator"
GPU_RELEASE = "gpu-operator"
GPU_CHART_PREFIX = "gpu-operator-"
GPU_DRIVER_KERNEL_MODULE_TYPE = "proprietary"
GPU_DRIVER_KERNEL_MODULE_CONFIG_NAME = "cns-nvidia-driver-kernel-module-config"
NFS_EXPORT_FILE = "/etc/exports.d/cns-nfs-provisioner.exports"
NFS_EXPORT_PATH = "/srv/cns/nfs"


@dataclass(frozen=True)
class Stack:
    version: str
    path: pathlib.Path
    parameters: dict[str, str]
    gpu_operator_version: str
    cuda_driver_container_version: str
    nfs_provisioner_version: str
    metallb_version: str
    metallb_load_balancer_ip_range: str


@dataclass(frozen=True)
class StackConfig:
    install_gpu_operator: bool
    install_nfs_provisioner: bool
    install_metallb: bool
    containerd_version: str
    gpu_operator_version: str
    cuda_driver_container_version: str
    nfs_provisioner_version: str
    metallb_version: str
    metallb_load_balancer_ip_range: str


@dataclass
class CommandResult:
    rc: int
    stdout: str
    stderr: str
    seconds: float
    log_path: pathlib.Path | None = None


@dataclass
class CaseResult:
    stack: str
    gpu_operator_version: str
    nfs_provisioner_version: str
    metallb_version: str
    metallb_ip_range: str
    containerd_version: str
    cuda_driver_version: str
    install: str = "skip"
    rerun: str = "skip"
    validate: str = "skip"
    uninstall: str = "skip"
    cleanup: str = "skip"
    seconds: float = 0.0
    result: str = "fail"
    reason: str = ""
    case_name: str = ""


class Runner:
    def __init__(
        self,
        *,
        repo_root: pathlib.Path,
        inventory_path: pathlib.Path,
        host: str,
        user: str,
        password: str,
        log_dir: pathlib.Path,
        command_timeout: int,
        wait_interval: int,
    ) -> None:
        self.repo_root = repo_root
        self.ansible_dir = repo_root / "ansible"
        self.inventory_path = inventory_path
        self.host = host
        self.user = user
        self.password = password
        self.log_dir = log_dir
        self.command_timeout = command_timeout
        self.wait_interval = wait_interval

    def run_ansible(
        self,
        label: str,
        args: list[str],
        log_path: pathlib.Path,
    ) -> CommandResult:
        env = os.environ.copy()
        env["ANSIBLE_CONFIG"] = str(self.ansible_dir / "ansible.cfg")
        command = [
            "ansible-playbook",
            "-i",
            str(self.inventory_path),
            "site.yml",
            *args,
        ]
        return run_command(
            label=label,
            command=command,
            cwd=self.ansible_dir,
            env=env,
            timeout=self.command_timeout,
            log_path=log_path,
        )

    def run_install(
        self,
        stack: Stack,
        overrides: dict[str, str],
        log_path: pathlib.Path,
    ) -> CommandResult:
        args = [
            "-e",
            "cns_action=install",
            "-e",
            f"cns_stack_version={stack.version}",
            "-e",
            f"@{stack.path}",
        ]
        args.extend(stack_override_args(stack, overrides))
        return self.run_ansible(
            "install",
            args,
            log_path,
        )

    def run_uninstall(self, log_path: pathlib.Path) -> CommandResult:
        return self.run_ansible(
            "uninstall",
            ["-e", "cns_action=uninstall"],
            log_path,
        )

    def ssh(
        self,
        command: str,
        *,
        sudo: bool,
        log_path: pathlib.Path | None = None,
        timeout: int | None = None,
    ) -> CommandResult:
        remote_command = "sh -lc " + shlex.quote(command)
        stdin = None
        if sudo:
            remote_command = "sudo -S -p '' sh -lc " + shlex.quote(command)
            stdin = self.password + "\n"

        env = os.environ.copy()
        env["SSHPASS"] = self.password
        ssh_command = [
            "sshpass",
            "-e",
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "ConnectTimeout=20",
            f"{self.user}@{self.host}",
            remote_command,
        ]
        return run_command(
            label="ssh",
            command=ssh_command,
            env=env,
            input_text=stdin,
            timeout=timeout or self.command_timeout,
            log_path=log_path,
        )

    def wait_for(
        self,
        description: str,
        command: str,
        predicate: Callable[[CommandResult], bool],
        *,
        sudo: bool = True,
        timeout: int = 600,
        log_path: pathlib.Path | None = None,
    ) -> CommandResult:
        deadline = time.monotonic() + timeout
        last_result: CommandResult | None = None
        while time.monotonic() < deadline:
            last_result = self.ssh(
                command,
                sudo=sudo,
                log_path=log_path,
                timeout=min(120, self.command_timeout),
            )
            if predicate(last_result):
                return last_result
            time.sleep(self.wait_interval)

        if last_result is None:
            raise RuntimeError(f"Timed out waiting for {description}.")
        raise RuntimeError(
            f"Timed out waiting for {description}: "
            f"rc={last_result.rc}, stdout={last_result.stdout.strip()!r}, "
            f"stderr={last_result.stderr.strip()!r}"
        )


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    args = parse_args(repo_root)
    repo_root = args.repo_root.resolve()
    require_tools(["ansible-playbook", "sshpass", "ssh"])

    password = args.password or os.environ.get("CNS_TEST_PASSWORD", "")
    if not password:
        print(
            "Password required. Set CNS_TEST_PASSWORD or pass --password.",
            file=sys.stderr,
        )
        return 2

    stacks = select_stacks(discover_stacks(repo_root), args.stack)
    override_sets = parse_set_overrides(args.set_overrides)
    cases = build_cases(stacks, override_sets)
    log_dir = make_log_dir(args.log_dir)
    started_at = utc_timestamp()
    result_json = args.result_json.resolve() if args.result_json else None
    results: list[CaseResult] = []
    emit_matrix_result(
        result_json,
        status="running",
        repo_root=repo_root,
        args=args,
        stacks=stacks,
        override_sets=override_sets,
        cases_total=len(cases),
        log_dir=log_dir,
        started_at=started_at,
        finished_at=None,
        exit_code=None,
        results=results,
        current_case=None,
    )

    with tempfile.TemporaryDirectory(prefix="cns-inventory-") as inventory_dir:
        inventory_path = pathlib.Path(inventory_dir) / "hosts.ini"
        write_inventory(inventory_path, args.host, args.user, password)

        runner = Runner(
            repo_root=repo_root,
            inventory_path=inventory_path,
            host=args.host,
            user=args.user,
            password=password,
            log_dir=log_dir,
            command_timeout=args.command_timeout,
            wait_interval=args.wait_interval,
        )

        print(f"Repository: {repo_root}")
        print(f"Target: {args.user}@{args.host}")
        print(f"Stacks: {', '.join(stack.version for stack in stacks)}")
        print(f"Stack overrides: {format_stack_overrides(override_sets)}")
        print(f"Logs: {log_dir}")
        print()

        if args.pre_clean:
            print("Pre-clean: running CNS uninstall before the matrix.")
            pre_clean = runner.run_uninstall(log_dir / "pre-clean-uninstall.log")
            if pre_clean.rc != 0:
                print("Pre-clean uninstall failed; see log for details.")
                results = [
                    CaseResult(
                        stack="-",
                        gpu_operator_version="-",
                        nfs_provisioner_version="-",
                        metallb_version="-",
                        metallb_ip_range="-",
                        containerd_version="-",
                        cuda_driver_version="-",
                        cleanup="fail",
                        reason="pre-clean uninstall failed",
                        case_name="pre-clean",
                    )
                ]
                print_table(
                    results
                )
                emit_matrix_result(
                    result_json,
                    status="failed",
                    repo_root=repo_root,
                    args=args,
                    stacks=stacks,
                    override_sets=override_sets,
                    cases_total=len(cases),
                    log_dir=log_dir,
                    started_at=started_at,
                    finished_at=utc_timestamp(),
                    exit_code=1,
                    results=results,
                    current_case=None,
                )
                return 1

        for index, (stack, case_overrides) in enumerate(
            cases,
            start=1,
        ):
            config = effective_stack_config(stack, case_overrides)
            case_name = case_id(
                index,
                stack.version,
                config,
                case_overrides,
            )
            print(f"[{index}/{len(cases)}] {case_name}")

            def emit_case_progress(case_result: CaseResult) -> None:
                emit_matrix_result(
                    result_json,
                    status="running",
                    repo_root=repo_root,
                    args=args,
                    stacks=stacks,
                    override_sets=override_sets,
                    cases_total=len(cases),
                    log_dir=log_dir,
                    started_at=started_at,
                    finished_at=None,
                    exit_code=None,
                    results=results,
                    current_case={
                        "index": index,
                        "total": len(cases),
                        "name": case_name,
                        "result": asdict(case_result),
                    },
                )

            result = run_case(
                runner,
                case_name,
                stack,
                case_overrides,
                progress=emit_case_progress,
            )
            results.append(result)
            print_table(results)
            print()
            emit_matrix_result(
                result_json,
                status="running",
                repo_root=repo_root,
                args=args,
                stacks=stacks,
                override_sets=override_sets,
                cases_total=len(cases),
                log_dir=log_dir,
                started_at=started_at,
                finished_at=None,
                exit_code=None,
                results=results,
                current_case={
                    "index": index,
                    "total": len(cases),
                    "name": case_name,
                    "result": asdict(result),
                },
            )
            if args.fail_fast and result.result != "pass":
                break

    print_table(results)
    failed = [result for result in results if result.result != "pass"]
    if failed:
        print(f"\nFailed cases: {len(failed)} of {len(results)}")
        emit_matrix_result(
            result_json,
            status="failed",
            repo_root=repo_root,
            args=args,
            stacks=stacks,
            override_sets=override_sets,
            cases_total=len(cases),
            log_dir=log_dir,
            started_at=started_at,
            finished_at=utc_timestamp(),
            exit_code=1,
            results=results,
            current_case=None,
        )
        return 1

    print(f"\nAll cases passed: {len(results)}")
    emit_matrix_result(
        result_json,
        status="passed",
        repo_root=repo_root,
        args=args,
        stacks=stacks,
        override_sets=override_sets,
        cases_total=len(cases),
        log_dir=log_dir,
        started_at=started_at,
        finished_at=utc_timestamp(),
        exit_code=0,
        results=results,
        current_case=None,
    )
    return 0


def parse_args(repo_root: pathlib.Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the live CNS release and stack-parameter validation matrix.",
    )
    parser.add_argument("--repo-root", type=pathlib.Path, default=repo_root)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument(
        "--password",
        default="",
        help="Target SSH password. Prefer CNS_TEST_PASSWORD to avoid shell history.",
    )
    parser.add_argument(
        "--stack",
        action="append",
        default=[],
        help="Stack version to test. May be repeated. Defaults to all stacks.",
    )
    parser.add_argument(
        "--set",
        dest="set_overrides",
        metavar="KEY=VALUE",
        action="append",
        default=[],
        help=(
            "Override a top-level key defined in each selected stack file. "
            "Repeat the same key to test multiple values."
        ),
    )
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--pre-clean",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run uninstall before the matrix starts.",
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT,
        help="Per-command timeout in seconds.",
    )
    parser.add_argument(
        "--wait-interval",
        type=int,
        default=DEFAULT_WAIT_INTERVAL,
        help="Polling interval for validation waits.",
    )
    parser.add_argument(
        "--log-dir",
        type=pathlib.Path,
        default=None,
        help="Directory for command logs. Defaults to a temp directory.",
    )
    parser.add_argument(
        "--result-json",
        type=pathlib.Path,
        default=None,
        help="Write structured matrix progress and final results to this JSON file.",
    )
    return parser.parse_args()


def require_tools(names: Iterable[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing required command(s): {joined}")


def discover_stacks(repo_root: pathlib.Path) -> list[Stack]:
    stack_dir = repo_root / "stacks"
    stacks = []
    for path in sorted(stack_dir.glob("*.yml")):
        data = parse_simple_yaml(path)
        version = data.get("cns_stack_version", path.stem)
        gpu_version = require_key(data, "gpu_operator_version", path)
        cuda_driver_version = require_key(data, CUDA_DRIVER_CONTAINER_VERSION_KEY, path)
        parse_stack_bool(
            require_key(data, INSTALL_GPU_OPERATOR_KEY, path),
            INSTALL_GPU_OPERATOR_KEY,
            path,
        )
        parse_stack_bool(
            require_key(data, INSTALL_NFS_PROVISIONER_KEY, path),
            INSTALL_NFS_PROVISIONER_KEY,
            path,
        )
        parse_stack_bool(
            require_key(data, INSTALL_METALLB_KEY, path),
            INSTALL_METALLB_KEY,
            path,
        )
        nfs_version = require_key(
            data,
            "nfs_subdir_external_provisioner_version",
            path,
        )
        metallb_version = require_key(data, "metallb_version", path)
        metallb_ip_range = require_key(data, "metallb_load_balancer_ip_range", path)
        stacks.append(
            Stack(
                version=version,
                path=path.resolve(),
                parameters=data,
                gpu_operator_version=gpu_version,
                cuda_driver_container_version=cuda_driver_version,
                nfs_provisioner_version=nfs_version,
                metallb_version=metallb_version,
                metallb_load_balancer_ip_range=metallb_ip_range,
            )
        )
    if not stacks:
        raise SystemExit(f"No stack files found under {stack_dir}.")
    return stacks


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
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]
        values[key] = value
    return values


def require_key(data: dict[str, str], key: str, path: pathlib.Path) -> str:
    value = data.get(key)
    if not value:
        raise SystemExit(f"{path} is missing required key: {key}")
    return value


def parse_stack_bool(value: str, key: str, path: pathlib.Path) -> bool:
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise SystemExit(f"{path} has invalid {key}: {value!r}; expected true or false.")


def parse_set_overrides(values: list[str]) -> dict[str, list[str]]:
    overrides: dict[str, list[str]] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"Invalid --set value: {item}. Expected key=value.")
        key, value = item.split("=", 1)
        if not key or not value:
            raise SystemExit(
                f"Invalid --set value: {item}. Expected non-empty key and value."
            )
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise SystemExit(f"Invalid --set key: {key}.")
        if key in STACK_BOOL_KEYS and value.lower() not in ("true", "false"):
            raise SystemExit(
                f"Invalid value for {key}: {value!r}; expected true or false."
            )
        overrides.setdefault(key, [])
        if value not in overrides[key]:
            overrides[key].append(value)
    return overrides


def stack_override_args(stack: Stack, overrides: dict[str, str]) -> list[str]:
    validate_stack_overrides(stack, overrides)

    args: list[str] = []
    for key, value in overrides.items():
        args.extend(["-e", f"{key}={value}"])
    return args


def validate_stack_overrides(stack: Stack, overrides: dict[str, str]) -> None:
    missing = [key for key in overrides if key not in stack.parameters]
    if missing:
        raise SystemExit(
            f"{stack.path} does not define stack parameter(s): "
            f"{', '.join(sorted(missing))}"
        )

    config = effective_stack_config(stack, overrides)
    if CUDA_DRIVER_CONTAINER_VERSION_KEY in overrides and not config.install_gpu_operator:
        raise SystemExit(
            f"{CUDA_DRIVER_CONTAINER_VERSION_KEY} requires "
            f"{INSTALL_GPU_OPERATOR_KEY}=true for {stack.path}."
        )


def effective_stack_config(stack: Stack, overrides: dict[str, str]) -> StackConfig:
    values = dict(stack.parameters)
    values.update(overrides)
    return StackConfig(
        install_gpu_operator=parse_stack_bool(
            require_key(values, INSTALL_GPU_OPERATOR_KEY, stack.path),
            INSTALL_GPU_OPERATOR_KEY,
            stack.path,
        ),
        install_nfs_provisioner=parse_stack_bool(
            require_key(values, INSTALL_NFS_PROVISIONER_KEY, stack.path),
            INSTALL_NFS_PROVISIONER_KEY,
            stack.path,
        ),
        install_metallb=parse_stack_bool(
            require_key(values, INSTALL_METALLB_KEY, stack.path),
            INSTALL_METALLB_KEY,
            stack.path,
        ),
        containerd_version=require_key(values, "containerd_version", stack.path),
        gpu_operator_version=require_key(values, "gpu_operator_version", stack.path),
        cuda_driver_container_version=require_key(
            values,
            CUDA_DRIVER_CONTAINER_VERSION_KEY,
            stack.path,
        ),
        nfs_provisioner_version=require_key(
            values,
            "nfs_subdir_external_provisioner_version",
            stack.path,
        ),
        metallb_version=require_key(values, "metallb_version", stack.path),
        metallb_load_balancer_ip_range=require_key(
            values,
            "metallb_load_balancer_ip_range",
            stack.path,
        ),
    )


def select_stacks(stacks: list[Stack], requested: list[str]) -> list[Stack]:
    if not requested:
        return stacks
    requested_set = set(requested)
    selected = [stack for stack in stacks if stack.version in requested_set]
    missing = requested_set - {stack.version for stack in selected}
    if missing:
        available = ", ".join(stack.version for stack in stacks)
        raise SystemExit(
            f"Unknown stack(s): {', '.join(sorted(missing))}. "
            f"Available: {available}"
        )
    return selected


def build_cases(
    stacks: list[Stack],
    override_sets: dict[str, list[str]],
) -> list[tuple[Stack, dict[str, str]]]:
    cases = []
    keys = list(override_sets)
    values = [override_sets[key] for key in keys]
    for stack in stacks:
        if not keys:
            validate_stack_overrides(stack, {})
            cases.append((stack, {}))
            continue
        for selected_values in itertools.product(*values):
            overrides = dict(zip(keys, selected_values, strict=True))
            validate_stack_overrides(stack, overrides)
            cases.append((stack, overrides))
    return cases


def format_stack_overrides(override_sets: dict[str, list[str]]) -> str:
    if not override_sets:
        return "none"
    return ", ".join(
        f"{key}={','.join(values)}" for key, values in override_sets.items()
    )


def make_log_dir(requested: pathlib.Path | None) -> pathlib.Path:
    if requested:
        requested.mkdir(parents=True, exist_ok=True)
        return requested.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return pathlib.Path(tempfile.mkdtemp(prefix=f"cns-matrix-{stamp}-"))


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def emit_matrix_result(
    path: pathlib.Path | None,
    *,
    status: str,
    repo_root: pathlib.Path,
    args: argparse.Namespace,
    stacks: list[Stack],
    override_sets: dict[str, list[str]],
    cases_total: int,
    log_dir: pathlib.Path,
    started_at: str,
    finished_at: str | None,
    exit_code: int | None,
    results: list[CaseResult],
    current_case: dict[str, object] | None,
) -> None:
    if path is None:
        return

    failed_cases = sum(result.result != "pass" for result in results)
    payload = {
        "schema_version": 1,
        "status": status,
        "started_at": started_at,
        "updated_at": utc_timestamp(),
        "finished_at": finished_at,
        "exit_code": exit_code,
        "repo_root": str(repo_root),
        "target": {
            "host": args.host,
            "user": args.user,
        },
        "stacks": [stack.version for stack in stacks],
        "stack_overrides": override_sets,
        "stack_overrides_label": format_stack_overrides(override_sets),
        "fail_fast": args.fail_fast,
        "pre_clean": args.pre_clean,
        "log_dir": str(log_dir),
        "cases_total": cases_total,
        "cases_completed": len(results),
        "failed_cases": failed_cases,
        "passed_cases": len(results) - failed_cases,
        "current_case": current_case,
        "results": [asdict(result) for result in results],
    }
    write_json_atomic(path, payload)


def write_json_atomic(path: pathlib.Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def write_inventory(
    path: pathlib.Path,
    host: str,
    user: str,
    password: str,
) -> None:
    content = f"""# Temporary CNS validation inventory.
[cns_nodes]
gpu-node ansible_host={host}

[cns_nodes:vars]
ansible_user={user}
ansible_password={password}
ansible_become=true
ansible_become_password={password}
ansible_python_interpreter=/usr/bin/python3
"""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def run_case(
    runner: Runner,
    case_name: str,
    stack: Stack,
    overrides: dict[str, str],
    progress: Callable[[CaseResult], None] | None = None,
) -> CaseResult:
    started = time.monotonic()
    config = effective_stack_config(stack, overrides)
    result = CaseResult(
        stack=stack.version,
        gpu_operator_version=case_gpu_operator_label(config),
        nfs_provisioner_version=case_nfs_provisioner_label(config),
        metallb_version=case_metallb_label(config),
        metallb_ip_range=case_metallb_ip_range_label(config, overrides),
        containerd_version=config.containerd_version,
        cuda_driver_version=case_cuda_driver_label(
            config,
            overrides,
        ),
        case_name=case_name,
    )

    def notify() -> None:
        if progress is not None:
            progress(result)

    result.result = "running"
    notify()
    case_log_dir = runner.log_dir / case_name
    case_log_dir.mkdir(parents=True, exist_ok=True)
    nfs_dir_preexisted = remote_path_exists(runner, NFS_EXPORT_PATH)

    try:
        result.install = "running"
        notify()
        install = runner.run_install(
            stack,
            overrides,
            case_log_dir / "01-install.log",
        )
        install_recap = parse_recap(install.stdout)
        result.install = phase_status(install, install_recap)
        notify()
        if result.install != "pass":
            raise RuntimeError(f"install failed; see {install.log_path}")

        result.rerun = "running"
        notify()
        rerun = runner.run_install(
            stack,
            overrides,
            case_log_dir / "02-install-rerun.log",
        )
        rerun_recap = parse_recap(rerun.stdout)
        result.rerun = phase_status(rerun, rerun_recap, require_changed_zero=True)
        notify()
        if result.rerun != "pass":
            changed = rerun_recap.get("changed", "?")
            raise RuntimeError(
                f"install rerun was not idempotent; changed={changed}; "
                f"see {rerun.log_path}"
            )

        result.validate = "running"
        notify()
        validate_install_state(
            runner,
            config,
            case_log_dir,
        )
        result.validate = "pass"
        notify()

        result.uninstall = "running"
        notify()
        uninstall = runner.run_uninstall(case_log_dir / "03-uninstall.log")
        uninstall_recap = parse_recap(uninstall.stdout)
        result.uninstall = phase_status(uninstall, uninstall_recap)
        notify()
        if result.uninstall != "pass":
            raise RuntimeError(f"uninstall failed; see {uninstall.log_path}")

        result.cleanup = "running"
        notify()
        uninstall_rerun = runner.run_uninstall(
            case_log_dir / "04-uninstall-rerun.log"
        )
        cleanup_recap = parse_recap(uninstall_rerun.stdout)
        result.cleanup = phase_status(
            uninstall_rerun,
            cleanup_recap,
            require_changed_zero=True,
        )
        notify()
        if result.cleanup != "pass":
            changed = cleanup_recap.get("changed", "?")
            raise RuntimeError(
                f"uninstall rerun was not idempotent; changed={changed}; "
                f"see {uninstall_rerun.log_path}"
            )

        validate_cleanup_state(
            runner,
            nfs_dir_should_exist=config.install_nfs_provisioner or nfs_dir_preexisted,
            log_dir=case_log_dir,
        )
        result.cleanup = "pass"
        result.result = "pass"
    except Exception as exc:
        result.reason = str(exc)
        result.result = "fail"
    finally:
        result.seconds = time.monotonic() - started
        notify()
    return result


def validate_install_state(
    runner: Runner,
    config: StackConfig,
    log_dir: pathlib.Path,
) -> None:
    wait_for_node_ready(runner, log_dir / "validate-node-ready.log")
    wait_for_calico(runner, log_dir / "validate-calico.log")
    validate_admin_kubectl(runner, log_dir / "validate-admin-kubectl.log")

    if config.install_nfs_provisioner:
        validate_nfs_enabled(runner, config, log_dir)
    else:
        validate_nfs_disabled(runner, log_dir)

    if config.install_metallb:
        validate_metallb_enabled(runner, config, log_dir)
    else:
        validate_metallb_disabled(runner, log_dir)

    if config.install_gpu_operator:
        validate_gpu_enabled(runner, config, log_dir)
    else:
        validate_gpu_disabled(runner, log_dir)


def wait_for_node_ready(runner: Runner, log_path: pathlib.Path) -> None:
    command = f"kubectl --kubeconfig {KUBECONFIG} get nodes --no-headers"
    runner.wait_for(
        "node Ready",
        command,
        lambda result: result.rc == 0 and nodes_are_ready(result.stdout),
        sudo=True,
        timeout=600,
        log_path=log_path,
    )


def wait_for_calico(runner: Runner, log_path: pathlib.Path) -> None:
    command = (
        f"kubectl --kubeconfig {KUBECONFIG} -n kube-system "
        "rollout status daemonset/calico-node --timeout=10s && "
        f"kubectl --kubeconfig {KUBECONFIG} -n kube-system "
        "rollout status deployment/calico-kube-controllers --timeout=10s"
    )
    runner.wait_for(
        "Calico rollouts",
        command,
        lambda result: result.rc == 0,
        sudo=True,
        timeout=600,
        log_path=log_path,
    )


def validate_admin_kubectl(runner: Runner, log_path: pathlib.Path) -> None:
    command = "kubectl get nodes --no-headers"
    runner.wait_for(
        "admin user kubectl",
        command,
        lambda result: result.rc == 0 and nodes_are_ready(result.stdout),
        sudo=False,
        timeout=180,
        log_path=log_path,
    )


def validate_nfs_enabled(
    runner: Runner,
    config: StackConfig,
    log_dir: pathlib.Path,
) -> None:
    releases = helm_releases(runner, NFS_NAMESPACE, log_dir / "validate-nfs-helm.log")
    chart = find_release_chart(releases, NFS_RELEASE)
    expected_chart = NFS_CHART_PREFIX + config.nfs_provisioner_version
    if chart != expected_chart:
        raise RuntimeError(f"NFS chart mismatch: got {chart!r}, want {expected_chart!r}")

    storage_class = kubectl_json(
        runner,
        f"get storageclass {NFS_STORAGE_CLASS} -o json",
        log_dir / "validate-nfs-storageclass.log",
    )
    annotations = storage_class.get("metadata", {}).get("annotations", {})
    default_value = annotations.get("storageclass.kubernetes.io/is-default-class")
    beta_default_value = annotations.get(
        "storageclass.beta.kubernetes.io/is-default-class"
    )
    if default_value != "true" and beta_default_value != "true":
        raise RuntimeError(f"{NFS_STORAGE_CLASS} is not the default StorageClass")

    validate_nfs_pvc_binding(runner, log_dir)


def validate_nfs_pvc_binding(runner: Runner, log_dir: pathlib.Path) -> None:
    namespace = "cns-test-validation"
    manifest = f"""
apiVersion: v1
kind: Namespace
metadata:
  name: {namespace}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cns-test-pvc
  namespace: {namespace}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Mi
"""
    apply_command = (
        f"cat <<'EOF' | kubectl --kubeconfig {KUBECONFIG} apply -f -\n"
        f"{manifest.strip()}\n"
        "EOF"
    )
    cleanup_command = (
        f"kubectl --kubeconfig {KUBECONFIG} delete namespace {namespace} "
        "--ignore-not-found=true"
    )
    try:
        applied = runner.ssh(
            apply_command,
            sudo=True,
            log_path=log_dir / "validate-nfs-pvc-apply.log",
        )
        if applied.rc != 0:
            raise RuntimeError(f"test PVC apply failed; see {applied.log_path}")

        wait_command = (
            f"kubectl --kubeconfig {KUBECONFIG} -n {namespace} "
            "get pvc cns-test-pvc -o json"
        )
        runner.wait_for(
            "test PVC Bound",
            wait_command,
            lambda result: result.rc == 0
            and json_status_phase(result.stdout) == "Bound",
            sudo=True,
            timeout=240,
            log_path=log_dir / "validate-nfs-pvc-bound.log",
        )
    finally:
        runner.ssh(
            cleanup_command,
            sudo=True,
            log_path=log_dir / "validate-nfs-pvc-cleanup.log",
            timeout=300,
        )


def validate_nfs_disabled(runner: Runner, log_dir: pathlib.Path) -> None:
    namespace = runner.ssh(
        f"kubectl --kubeconfig {KUBECONFIG} get namespace {NFS_NAMESPACE}",
        sudo=True,
        log_path=log_dir / "validate-nfs-disabled-namespace.log",
    )
    if namespace.rc == 0:
        raise RuntimeError(f"{NFS_NAMESPACE} namespace exists while NFS is disabled")

    storage_class = runner.ssh(
        f"kubectl --kubeconfig {KUBECONFIG} get storageclass {NFS_STORAGE_CLASS}",
        sudo=True,
        log_path=log_dir / "validate-nfs-disabled-storageclass.log",
    )
    if storage_class.rc == 0:
        raise RuntimeError(
            f"{NFS_STORAGE_CLASS} StorageClass exists while NFS is disabled"
        )


def validate_metallb_enabled(
    runner: Runner,
    config: StackConfig,
    log_dir: pathlib.Path,
) -> None:
    releases = helm_releases(
        runner,
        METALLB_NAMESPACE,
        log_dir / "validate-metallb-helm.log",
    )
    chart = find_release_chart(releases, METALLB_RELEASE)
    expected_chart = METALLB_CHART_PREFIX + config.metallb_version
    if chart != expected_chart:
        raise RuntimeError(
            f"MetalLB chart mismatch: got {chart!r}, want {expected_chart!r}"
        )

    values = helm_release_values(
        runner,
        METALLB_RELEASE,
        METALLB_NAMESPACE,
        log_dir / "validate-metallb-helm-values.log",
    )
    speaker = values.get("speaker", {})
    ignore_exclude_lb = (
        speaker.get("ignoreExcludeLB") if isinstance(speaker, dict) else None
    )
    if ignore_exclude_lb is not True:
        raise RuntimeError(
            "MetalLB speaker.ignoreExcludeLB mismatch: "
            f"got {ignore_exclude_lb!r}, want True"
        )

    pool = kubectl_json(
        runner,
        f"-n {METALLB_NAMESPACE} get ipaddresspools.metallb.io "
        f"{METALLB_IP_ADDRESS_POOL} -o json",
        log_dir / "validate-metallb-ipaddresspool.log",
    )
    addresses = pool.get("spec", {}).get("addresses", [])
    if not isinstance(addresses, list):
        raise RuntimeError("MetalLB IPAddressPool addresses were not a list")
    if config.metallb_load_balancer_ip_range not in addresses:
        raise RuntimeError(
            "MetalLB IPAddressPool range mismatch: "
            f"got {addresses!r}, want {config.metallb_load_balancer_ip_range!r}"
        )

    advertisement = kubectl_json(
        runner,
        f"-n {METALLB_NAMESPACE} get l2advertisements.metallb.io "
        f"{METALLB_L2_ADVERTISEMENT} -o json",
        log_dir / "validate-metallb-l2advertisement.log",
    )
    advertised_pools = advertisement.get("spec", {}).get("ipAddressPools", [])
    if (
        not isinstance(advertised_pools, list)
        or METALLB_IP_ADDRESS_POOL not in advertised_pools
    ):
        raise RuntimeError(
            "MetalLB L2Advertisement does not reference "
            f"{METALLB_IP_ADDRESS_POOL}"
        )

    validate_metallb_service_ip(runner, config, log_dir)


def validate_metallb_service_ip(
    runner: Runner,
    config: StackConfig,
    log_dir: pathlib.Path,
) -> None:
    manifest = f"""
apiVersion: v1
kind: Namespace
metadata:
  name: {METALLB_TEST_NAMESPACE}
---
apiVersion: v1
kind: Service
metadata:
  name: {METALLB_TEST_SERVICE}
  namespace: {METALLB_TEST_NAMESPACE}
spec:
  type: LoadBalancer
  ports:
    - name: http
      port: 80
      targetPort: 80
"""
    apply_command = (
        f"cat <<'EOF' | kubectl --kubeconfig {KUBECONFIG} apply -f -\n"
        f"{manifest.strip()}\n"
        "EOF"
    )
    cleanup_command = (
        f"kubectl --kubeconfig {KUBECONFIG} delete namespace "
        f"{METALLB_TEST_NAMESPACE} --ignore-not-found=true"
    )
    try:
        applied = runner.ssh(
            apply_command,
            sudo=True,
            log_path=log_dir / "validate-metallb-service-apply.log",
        )
        if applied.rc != 0:
            raise RuntimeError(
                f"test LoadBalancer Service apply failed; see {applied.log_path}"
            )

        wait_command = (
            f"kubectl --kubeconfig {KUBECONFIG} -n {METALLB_TEST_NAMESPACE} "
            f"get service {METALLB_TEST_SERVICE} -o json"
        )
        assigned = runner.wait_for(
            "test LoadBalancer external IP",
            wait_command,
            lambda result: result.rc == 0
            and bool(service_external_ips(result.stdout)),
            sudo=True,
            timeout=240,
            log_path=log_dir / "validate-metallb-service-ip.log",
        )
        external_ips = service_external_ips(assigned.stdout)
        if not external_ips:
            raise RuntimeError("test LoadBalancer Service did not receive an IP")
        if not any(
            ip_in_configured_range(
                ip,
                config.metallb_load_balancer_ip_range,
            )
            for ip in external_ips
        ):
            raise RuntimeError(
                "test LoadBalancer external IP is outside the MetalLB range: "
                f"got {external_ips!r}, want {config.metallb_load_balancer_ip_range!r}"
            )
    finally:
        runner.ssh(
            cleanup_command,
            sudo=True,
            log_path=log_dir / "validate-metallb-service-cleanup.log",
            timeout=300,
        )


def validate_metallb_disabled(runner: Runner, log_dir: pathlib.Path) -> None:
    namespace = runner.ssh(
        f"kubectl --kubeconfig {KUBECONFIG} get namespace {METALLB_NAMESPACE}",
        sudo=True,
        log_path=log_dir / "validate-metallb-disabled-namespace.log",
    )
    if namespace.rc == 0:
        raise RuntimeError(
            f"{METALLB_NAMESPACE} namespace exists while MetalLB is disabled"
        )


def validate_gpu_enabled(
    runner: Runner,
    config: StackConfig,
    log_dir: pathlib.Path,
) -> None:
    releases = helm_releases(runner, GPU_NAMESPACE, log_dir / "validate-gpu-helm.log")
    chart = find_release_chart(releases, GPU_RELEASE)
    expected_chart = GPU_CHART_PREFIX + config.gpu_operator_version
    if chart != expected_chart:
        raise RuntimeError(f"GPU chart mismatch: got {chart!r}, want {expected_chart!r}")

    values = helm_release_values(
        runner,
        GPU_RELEASE,
        GPU_NAMESPACE,
        log_dir / "validate-gpu-helm-values.log",
    )
    driver = values.get("driver", {})
    driver_version = driver.get("version") if isinstance(driver, dict) else None
    expected_driver_version = config.cuda_driver_container_version
    if driver_version != expected_driver_version:
        raise RuntimeError(
            "GPU driver container version mismatch: "
            f"got {driver_version!r}, want {expected_driver_version!r}"
        )
    kernel_module_type = driver.get("kernelModuleType") if isinstance(driver, dict) else None
    if kernel_module_type != GPU_DRIVER_KERNEL_MODULE_TYPE:
        raise RuntimeError(
            "GPU driver kernel module type mismatch: "
            f"got {kernel_module_type!r}, want {GPU_DRIVER_KERNEL_MODULE_TYPE!r}"
        )
    kernel_module_config = (
        driver.get("kernelModuleConfig", {}) if isinstance(driver, dict) else {}
    )
    kernel_module_config_name = (
        kernel_module_config.get("name")
        if isinstance(kernel_module_config, dict)
        else None
    )
    if kernel_module_config_name != GPU_DRIVER_KERNEL_MODULE_CONFIG_NAME:
        raise RuntimeError(
            "GPU driver kernel module config mismatch: "
            f"got {kernel_module_config_name!r}, "
            f"want {GPU_DRIVER_KERNEL_MODULE_CONFIG_NAME!r}"
        )

    runner.wait_for(
        "ClusterPolicy ready",
        f"kubectl --kubeconfig {KUBECONFIG} get clusterpolicy -o json",
        lambda result: result.rc == 0 and cluster_policy_ready(result.stdout),
        sudo=True,
        timeout=1800,
        log_path=log_dir / "validate-gpu-clusterpolicy.log",
    )

    runner.wait_for(
        "allocatable nvidia.com/gpu",
        f"kubectl --kubeconfig {KUBECONFIG} get nodes -o json",
        lambda result: result.rc == 0 and node_has_allocatable_gpu(result.stdout),
        sudo=True,
        timeout=600,
        log_path=log_dir / "validate-gpu-allocatable.log",
    )


def validate_gpu_disabled(runner: Runner, log_dir: pathlib.Path) -> None:
    namespace = runner.ssh(
        f"kubectl --kubeconfig {KUBECONFIG} get namespace {GPU_NAMESPACE}",
        sudo=True,
        log_path=log_dir / "validate-gpu-disabled-namespace.log",
    )
    if namespace.rc == 0:
        raise RuntimeError(f"{GPU_NAMESPACE} namespace exists while GPU is disabled")


def validate_cleanup_state(
    runner: Runner,
    *,
    nfs_dir_should_exist: bool,
    log_dir: pathlib.Path,
) -> None:
    checks = [
        (
            "admin kubeconfig removed",
            f"test ! -e {KUBECONFIG}",
            "cleanup-admin-conf.log",
        ),
        (
            "containerd inactive",
            "systemctl is-active --quiet containerd; test $? -ne 0",
            "cleanup-containerd.log",
        ),
        (
            "kubelet inactive",
            "systemctl is-active --quiet kubelet; test $? -ne 0",
            "cleanup-kubelet.log",
        ),
        (
            "NFS export config removed",
            f"test ! -e {NFS_EXPORT_FILE}",
            "cleanup-nfs-export.log",
        ),
    ]

    for description, command, filename in checks:
        check = runner.ssh(command, sudo=True, log_path=log_dir / filename)
        if check.rc != 0:
            raise RuntimeError(f"cleanup failed: {description}")

    if nfs_dir_should_exist:
        nfs_dir = runner.ssh(
            f"test -d {NFS_EXPORT_PATH}",
            sudo=True,
            log_path=log_dir / "cleanup-nfs-dir.log",
        )
        if nfs_dir.rc != 0:
            raise RuntimeError(f"cleanup failed: {NFS_EXPORT_PATH} was not preserved")


def remote_path_exists(runner: Runner, path: str) -> bool:
    result = runner.ssh(f"test -e {shlex.quote(path)}", sudo=True)
    return result.rc == 0


def helm_releases(
    runner: Runner,
    namespace: str,
    log_path: pathlib.Path,
) -> list[dict[str, object]]:
    result = runner.ssh(
        f"KUBECONFIG={KUBECONFIG} /usr/local/bin/helm list "
        f"--namespace {namespace} -o json",
        sudo=True,
        log_path=log_path,
    )
    if result.rc != 0:
        raise RuntimeError(f"helm list failed for namespace {namespace}; see {log_path}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"helm list returned invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError("helm list JSON was not a list")
    return data


def find_release_chart(releases: list[dict[str, object]], release_name: str) -> str:
    for release in releases:
        if release.get("name") == release_name:
            chart = release.get("chart")
            if isinstance(chart, str):
                return chart
            raise RuntimeError(f"release {release_name} does not include chart")
    raise RuntimeError(f"release {release_name} was not found")


def helm_release_values(
    runner: Runner,
    release_name: str,
    namespace: str,
    log_path: pathlib.Path,
) -> dict[str, object]:
    result = runner.ssh(
        f"KUBECONFIG={KUBECONFIG} /usr/local/bin/helm get values "
        f"{release_name} --namespace {namespace} --all -o json",
        sudo=True,
        log_path=log_path,
    )
    if result.rc != 0:
        raise RuntimeError(
            f"helm get values failed for release {release_name}; see {log_path}"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"helm get values returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("helm get values JSON was not an object")
    return data


def kubectl_json(
    runner: Runner,
    kubectl_args: str,
    log_path: pathlib.Path,
) -> dict[str, object]:
    result = runner.ssh(
        f"kubectl --kubeconfig {KUBECONFIG} {kubectl_args}",
        sudo=True,
        log_path=log_path,
    )
    if result.rc != 0:
        raise RuntimeError(f"kubectl {kubectl_args} failed; see {log_path}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"kubectl returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("kubectl JSON was not an object")
    return data


def nodes_are_ready(stdout: str) -> bool:
    lines = [line for line in stdout.splitlines() if line.strip()]
    return bool(lines) and all(" Ready " in f" {line} " for line in lines)


def json_status_phase(stdout: str) -> str:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return ""
    status = data.get("status", {}) if isinstance(data, dict) else {}
    phase = status.get("phase") if isinstance(status, dict) else ""
    return phase if isinstance(phase, str) else ""


def service_external_ips(stdout: str) -> list[str]:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    status = data.get("status", {}) if isinstance(data, dict) else {}
    load_balancer = status.get("loadBalancer", {}) if isinstance(status, dict) else {}
    ingress = load_balancer.get("ingress", []) if isinstance(load_balancer, dict) else []
    if not isinstance(ingress, list):
        return []
    ips = []
    for item in ingress:
        if not isinstance(item, dict):
            continue
        value = item.get("ip")
        if isinstance(value, str) and value:
            ips.append(value)
    return ips


def ip_in_configured_range(ip_value: str, configured_range: str) -> bool:
    ip = ipaddress.ip_address(ip_value)
    if "-" in configured_range:
        start_value, end_value = configured_range.split("-", 1)
        start = ipaddress.ip_address(start_value.strip())
        end = ipaddress.ip_address(end_value.strip())
        return start.version == ip.version and start <= ip <= end
    if "/" in configured_range:
        network = ipaddress.ip_network(configured_range, strict=False)
        return ip in network
    return ip == ipaddress.ip_address(configured_range)


def cluster_policy_ready(stdout: str) -> bool:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    items = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(items, list) or not items:
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        status = item.get("status", {})
        if not isinstance(status, dict):
            continue
        state = status.get("state")
        if isinstance(state, str) and state.lower() == "ready":
            return True
        conditions = status.get("conditions", [])
        if isinstance(conditions, list):
            for condition in conditions:
                if not isinstance(condition, dict):
                    continue
                condition_type = str(condition.get("type", "")).lower()
                condition_status = str(condition.get("status", "")).lower()
                if condition_type == "ready" and condition_status == "true":
                    return True
    return False


def node_has_allocatable_gpu(stdout: str) -> bool:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    items = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        status = item.get("status", {})
        allocatable = status.get("allocatable", {}) if isinstance(status, dict) else {}
        gpu_count = allocatable.get("nvidia.com/gpu")
        if gpu_count and str(gpu_count) != "0":
            return True
    return False


def run_command(
    *,
    label: str,
    command: list[str],
    cwd: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int,
    log_path: pathlib.Path | None,
) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        result = CommandResult(
            rc=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            seconds=time.monotonic() - started,
            log_path=log_path,
        )
    except subprocess.TimeoutExpired as exc:
        result = CommandResult(
            rc=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\nTimed out after {timeout} seconds.",
            seconds=time.monotonic() - started,
            log_path=log_path,
        )

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(command_log(label, command, result), encoding="utf-8")
    return result


def command_log(label: str, command: list[str], result: CommandResult) -> str:
    rendered_command = " ".join(shlex.quote(part) for part in command)
    return (
        f"# {label}\n"
        f"$ {rendered_command}\n"
        f"# rc={result.rc} seconds={result.seconds:.1f}\n\n"
        "## stdout\n"
        f"{result.stdout}\n\n"
        "## stderr\n"
        f"{result.stderr}\n"
    )


def parse_recap(stdout: str) -> dict[str, int]:
    recap: dict[str, int] = {}
    for line in reversed(stdout.splitlines()):
        if " changed=" not in line or " ok=" not in line:
            continue
        for key in ("ok", "changed", "unreachable", "failed", "rescued", "ignored"):
            match = re.search(rf"\b{key}=(\d+)\b", line)
            if match:
                recap[key] = int(match.group(1))
        if recap:
            return recap
    return recap


def phase_status(
    command: CommandResult,
    recap: dict[str, int],
    *,
    require_changed_zero: bool = False,
) -> str:
    if command.rc != 0:
        return "fail"
    if not recap:
        return "fail"
    if recap.get("unreachable", 0) != 0 or recap.get("failed", 0) != 0:
        return "fail"
    if require_changed_zero and recap.get("changed", -1) != 0:
        return "fail"
    return "pass"


def case_cuda_driver_label(
    config: StackConfig,
    overrides: dict[str, str],
) -> str:
    if not config.install_gpu_operator:
        return "-"
    if CUDA_DRIVER_CONTAINER_VERSION_KEY in overrides:
        return config.cuda_driver_container_version
    return f"stack:{config.cuda_driver_container_version}"


def case_gpu_operator_label(config: StackConfig) -> str:
    if not config.install_gpu_operator:
        return "-"
    return config.gpu_operator_version


def case_nfs_provisioner_label(config: StackConfig) -> str:
    if not config.install_nfs_provisioner:
        return "-"
    return config.nfs_provisioner_version


def case_metallb_label(config: StackConfig) -> str:
    if not config.install_metallb:
        return "-"
    return config.metallb_version


def case_metallb_ip_range_label(
    config: StackConfig,
    overrides: dict[str, str],
) -> str:
    if not config.install_metallb:
        return "-"
    if "metallb_load_balancer_ip_range" in overrides:
        return config.metallb_load_balancer_ip_range
    return f"stack:{config.metallb_load_balancer_ip_range}"


def case_id(
    index: int,
    stack: str,
    config: StackConfig,
    overrides: dict[str, str],
) -> str:
    gpu = "gpu" if config.install_gpu_operator else "no-gpu"
    nfs = "nfs" if config.install_nfs_provisioner else "no-nfs"
    metallb = "metallb" if config.install_metallb else "no-metallb"
    parts = [f"{index:02d}", "stack", stack, gpu, nfs, metallb]
    if config.install_gpu_operator:
        driver = (
            config.cuda_driver_container_version
            if CUDA_DRIVER_CONTAINER_VERSION_KEY in overrides
            else "stack"
        )
        parts.extend(["driver", slug(driver)])
    if overrides:
        label = ",".join(f"{key}={value}" for key, value in overrides.items())
        parts.extend(["set", slug(label)])
    return "-".join(parts)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()


def print_table(results: list[CaseResult]) -> None:
    headers = [
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
    ]
    rows = [
        [
            result.stack,
            result.gpu_operator_version,
            result.cuda_driver_version,
            result.nfs_provisioner_version,
            result.metallb_version,
            result.metallb_ip_range,
            result.containerd_version,
            result.install,
            result.rerun,
            result.validate,
            result.uninstall,
            result.cleanup,
            f"{result.seconds:.0f}",
            result.result,
            truncate(result.reason, 72),
        ]
        for result in results
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        if rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    separator = "-+-".join("-" * width for width in widths)
    header = " | ".join(
        headers[index].ljust(widths[index]) for index in range(len(headers))
    )
    print(header)
    print(separator)
    for row in rows:
        print(
            " | ".join(row[index].ljust(widths[index]) for index in range(len(row)))
        )


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


if __name__ == "__main__":
    raise SystemExit(main())
