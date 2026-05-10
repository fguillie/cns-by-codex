#!/usr/bin/env python3
# Runs the live CNS Ansible validation matrix against a single target host.

from __future__ import annotations

import argparse
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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable


DEFAULT_HOST = "10.86.6.94"
DEFAULT_USER = "nvidia"
DEFAULT_COMMAND_TIMEOUT = 7200
DEFAULT_WAIT_INTERVAL = 10
KUBECONFIG = "/etc/kubernetes/admin.conf"
NFS_NAMESPACE = "nfs-provisioner"
NFS_RELEASE = "nfs-subdir-external-provisioner"
NFS_STORAGE_CLASS = "nfs-client"
NFS_CHART_PREFIX = "nfs-subdir-external-provisioner-"
GPU_NAMESPACE = "gpu-operator"
GPU_RELEASE = "gpu-operator"
GPU_CHART_PREFIX = "gpu-operator-"
NFS_EXPORT_FILE = "/etc/exports.d/cns-nfs-provisioner.exports"
NFS_EXPORT_PATH = "/srv/cns/nfs"


@dataclass(frozen=True)
class Stack:
    version: str
    path: pathlib.Path
    gpu_operator_version: str
    nfs_provisioner_version: str


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
    gpu_enabled: bool
    nfs_enabled: bool
    install: str = "skip"
    rerun: str = "skip"
    validate: str = "skip"
    uninstall: str = "skip"
    cleanup: str = "skip"
    seconds: float = 0.0
    result: str = "fail"
    reason: str = ""


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
        gpu_enabled: bool,
        nfs_enabled: bool,
        log_path: pathlib.Path,
    ) -> CommandResult:
        return self.run_ansible(
            "install",
            [
                "-e",
                "cns_action=install",
                "-e",
                f"cns_stack_version={stack.version}",
                "-e",
                f"cns_gpu_operator_enabled={bool_string(gpu_enabled)}",
                "-e",
                f"cns_nfs_provisioner_enabled={bool_string(nfs_enabled)}",
                "-e",
                f"@{stack.path}",
            ],
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
    gpu_values = select_bool_values(args.gpu)
    nfs_values = select_bool_values(args.nfs)
    cases = list(itertools.product(stacks, gpu_values, nfs_values))
    log_dir = make_log_dir(args.log_dir)

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
        print(f"Logs: {log_dir}")
        print()

        if args.pre_clean:
            print("Pre-clean: running CNS uninstall before the matrix.")
            pre_clean = runner.run_uninstall(log_dir / "pre-clean-uninstall.log")
            if pre_clean.rc != 0:
                print("Pre-clean uninstall failed; see log for details.")
                print_table(
                    [
                        CaseResult(
                            stack="-",
                            gpu_enabled=False,
                            nfs_enabled=False,
                            cleanup="fail",
                            reason="pre-clean uninstall failed",
                        )
                    ]
                )
                return 1

        results: list[CaseResult] = []
        for index, (stack, gpu_enabled, nfs_enabled) in enumerate(cases, start=1):
            case_name = case_id(index, stack.version, gpu_enabled, nfs_enabled)
            print(f"[{index}/{len(cases)}] {case_name}")
            result = run_case(runner, case_name, stack, gpu_enabled, nfs_enabled)
            results.append(result)
            print_table(results)
            print()
            if args.fail_fast and result.result != "pass":
                break

    print_table(results)
    failed = [result for result in results if result.result != "pass"]
    if failed:
        print(f"\nFailed cases: {len(failed)} of {len(results)}")
        return 1

    print(f"\nAll cases passed: {len(results)}")
    return 0


def parse_args(repo_root: pathlib.Path) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the live CNS release and option validation matrix.",
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
        "--gpu",
        choices=("enabled", "disabled", "both"),
        default="both",
        help="GPU Operator option set to test.",
    )
    parser.add_argument(
        "--nfs",
        choices=("enabled", "disabled", "both"),
        default="both",
        help="NFS provisioner option set to test.",
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
        nfs_version = require_key(
            data,
            "nfs_subdir_external_provisioner_version",
            path,
        )
        stacks.append(
            Stack(
                version=version,
                path=path.resolve(),
                gpu_operator_version=gpu_version,
                nfs_provisioner_version=nfs_version,
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


def select_bool_values(value: str) -> list[bool]:
    if value == "enabled":
        return [True]
    if value == "disabled":
        return [False]
    return [True, False]


def make_log_dir(requested: pathlib.Path | None) -> pathlib.Path:
    if requested:
        requested.mkdir(parents=True, exist_ok=True)
        return requested.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return pathlib.Path(tempfile.mkdtemp(prefix=f"cns-matrix-{stamp}-"))


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
    gpu_enabled: bool,
    nfs_enabled: bool,
) -> CaseResult:
    started = time.monotonic()
    result = CaseResult(
        stack=stack.version,
        gpu_enabled=gpu_enabled,
        nfs_enabled=nfs_enabled,
    )
    case_log_dir = runner.log_dir / case_name
    case_log_dir.mkdir(parents=True, exist_ok=True)
    nfs_dir_preexisted = remote_path_exists(runner, NFS_EXPORT_PATH)

    try:
        install = runner.run_install(
            stack,
            gpu_enabled,
            nfs_enabled,
            case_log_dir / "01-install.log",
        )
        install_recap = parse_recap(install.stdout)
        result.install = phase_status(install, install_recap)
        if result.install != "pass":
            raise RuntimeError(f"install failed; see {install.log_path}")

        rerun = runner.run_install(
            stack,
            gpu_enabled,
            nfs_enabled,
            case_log_dir / "02-install-rerun.log",
        )
        rerun_recap = parse_recap(rerun.stdout)
        result.rerun = phase_status(rerun, rerun_recap, require_changed_zero=True)
        if result.rerun != "pass":
            changed = rerun_recap.get("changed", "?")
            raise RuntimeError(
                f"install rerun was not idempotent; changed={changed}; "
                f"see {rerun.log_path}"
            )

        validate_install_state(
            runner,
            stack,
            gpu_enabled,
            nfs_enabled,
            case_log_dir,
        )
        result.validate = "pass"

        uninstall = runner.run_uninstall(case_log_dir / "03-uninstall.log")
        uninstall_recap = parse_recap(uninstall.stdout)
        result.uninstall = phase_status(uninstall, uninstall_recap)
        if result.uninstall != "pass":
            raise RuntimeError(f"uninstall failed; see {uninstall.log_path}")

        uninstall_rerun = runner.run_uninstall(
            case_log_dir / "04-uninstall-rerun.log"
        )
        cleanup_recap = parse_recap(uninstall_rerun.stdout)
        result.cleanup = phase_status(
            uninstall_rerun,
            cleanup_recap,
            require_changed_zero=True,
        )
        if result.cleanup != "pass":
            changed = cleanup_recap.get("changed", "?")
            raise RuntimeError(
                f"uninstall rerun was not idempotent; changed={changed}; "
                f"see {uninstall_rerun.log_path}"
            )

        validate_cleanup_state(
            runner,
            nfs_dir_should_exist=nfs_enabled or nfs_dir_preexisted,
            log_dir=case_log_dir,
        )
        result.cleanup = "pass"
        result.result = "pass"
    except Exception as exc:
        result.reason = str(exc)
        result.result = "fail"
    finally:
        result.seconds = time.monotonic() - started
    return result


def validate_install_state(
    runner: Runner,
    stack: Stack,
    gpu_enabled: bool,
    nfs_enabled: bool,
    log_dir: pathlib.Path,
) -> None:
    wait_for_node_ready(runner, log_dir / "validate-node-ready.log")
    wait_for_calico(runner, log_dir / "validate-calico.log")
    validate_admin_kubectl(runner, log_dir / "validate-admin-kubectl.log")

    if nfs_enabled:
        validate_nfs_enabled(runner, stack, log_dir)
    else:
        validate_nfs_disabled(runner, log_dir)

    if gpu_enabled:
        validate_gpu_enabled(runner, stack, log_dir)
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
    stack: Stack,
    log_dir: pathlib.Path,
) -> None:
    releases = helm_releases(runner, NFS_NAMESPACE, log_dir / "validate-nfs-helm.log")
    chart = find_release_chart(releases, NFS_RELEASE)
    expected_chart = NFS_CHART_PREFIX + stack.nfs_provisioner_version
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


def validate_gpu_enabled(
    runner: Runner,
    stack: Stack,
    log_dir: pathlib.Path,
) -> None:
    releases = helm_releases(runner, GPU_NAMESPACE, log_dir / "validate-gpu-helm.log")
    chart = find_release_chart(releases, GPU_RELEASE)
    expected_chart = GPU_CHART_PREFIX + stack.gpu_operator_version
    if chart != expected_chart:
        raise RuntimeError(f"GPU chart mismatch: got {chart!r}, want {expected_chart!r}")

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


def bool_string(value: bool) -> str:
    return "true" if value else "false"


def case_id(index: int, stack: str, gpu_enabled: bool, nfs_enabled: bool) -> str:
    gpu = "gpu" if gpu_enabled else "no-gpu"
    nfs = "nfs" if nfs_enabled else "no-nfs"
    return f"{index:02d}-stack-{stack}-{gpu}-{nfs}"


def print_table(results: list[CaseResult]) -> None:
    headers = [
        "STACK",
        "GPU",
        "NFS",
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
            "on" if result.gpu_enabled else "off",
            "on" if result.nfs_enabled else "off",
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
