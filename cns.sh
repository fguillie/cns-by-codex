#!/usr/bin/env bash
# Runs the CNS Ansible playbook for install, uninstall, and help commands.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_DIR="${SCRIPT_DIR}/ansible"
INVENTORY_FILE="${ANSIBLE_DIR}/inventory/hosts.ini"
PLAYBOOK_FILE="${ANSIBLE_DIR}/site.yml"
STACKS_DIR="${SCRIPT_DIR}/stacks"

print_help() {
  cat <<'EOF'
Usage:
  ./cns.sh install <stack-version> [--gpu-operator|--no-gpu-operator] [--cuda-driver-version <version>] [--nfs-provisioner|--no-nfs-provisioner]
  ./cns.sh uninstall
  ./cns.sh help

Commands:
  install <stack-version>  Deploy the requested CNS stack version.
  uninstall                Remove the deployed CNS stack from the target node.
  help                     Show this help text.

Install options:
  --gpu-operator           Install the NVIDIA GPU Operator (default).
  --no-gpu-operator        Skip GPU Operator and host driver cleanup.
  --cuda-driver-version    Deploy the requested GPU Operator CUDA driver container version.
  --nfs-provisioner        Install the NFS dynamic storage provisioner (default).
  --no-nfs-provisioner     Skip NFS server and provisioner setup.

Available stack versions:
  1.36
  1.35
  1.34
  1.33

Notes:
  - Edit ansible/inventory/hosts.ini before running the playbook.
  - Password-based SSH requires sshpass on the control machine.
EOF
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    printf 'Required file not found: %s\n' "${path}" >&2
    exit 1
  fi
}

run_install() {
  local stack_version="${1:-}"
  local gpu_operator_enabled="true"
  local nfs_provisioner_enabled="true"
  local cuda_driver_version=""
  local stack_file
  local -a ansible_args

  if [[ -z "${stack_version}" || "${stack_version}" == --* ]]; then
    printf 'Missing stack version.\n\n' >&2
    print_help
    exit 1
  fi

  shift || true
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --gpu-operator)
        gpu_operator_enabled="true"
        ;;
      --no-gpu-operator)
        gpu_operator_enabled="false"
        ;;
      --cuda-driver-version)
        if [[ "$#" -lt 2 || -z "${2:-}" || "${2}" == --* ]]; then
          printf 'Missing CUDA driver container version for --cuda-driver-version.\n\n' >&2
          print_help
          exit 1
        fi
        cuda_driver_version="$2"
        shift
        ;;
      --nfs-provisioner)
        nfs_provisioner_enabled="true"
        ;;
      --no-nfs-provisioner)
        nfs_provisioner_enabled="false"
        ;;
      *)
        printf 'Unknown install option: %s\n\n' "$1" >&2
        print_help
        exit 1
        ;;
    esac
    shift
  done

  if [[ "${gpu_operator_enabled}" != "true" && -n "${cuda_driver_version}" ]]; then
    printf '%s\n\n' '--cuda-driver-version requires GPU Operator installation. Remove --no-gpu-operator or omit the driver version override.' >&2
    print_help
    exit 1
  fi

  stack_file="${STACKS_DIR}/${stack_version}.yml"

  require_file "${stack_file}"
  require_file "${INVENTORY_FILE}"
  require_file "${PLAYBOOK_FILE}"

  ansible_args=(
    ansible-playbook
    -i "${INVENTORY_FILE}"
    "${PLAYBOOK_FILE}"
    -e "cns_action=install"
    -e "cns_stack_version=${stack_version}"
    -e "cns_gpu_operator_enabled=${gpu_operator_enabled}"
    -e "cns_nfs_provisioner_enabled=${nfs_provisioner_enabled}"
    -e "@${stack_file}"
  )

  if [[ -n "${cuda_driver_version}" ]]; then
    ansible_args+=(-e "cns_cuda_driver_container_version=${cuda_driver_version}")
  fi

  "${ansible_args[@]}"
}

run_uninstall() {
  require_file "${INVENTORY_FILE}"
  require_file "${PLAYBOOK_FILE}"

  ansible-playbook \
    -i "${INVENTORY_FILE}" \
    "${PLAYBOOK_FILE}" \
    -e "cns_action=uninstall"
}

main() {
  local command="${1:-help}"

  case "${command}" in
    install)
      shift || true
      run_install "$@"
      ;;
    uninstall)
      run_uninstall
      ;;
    help|-h|--help)
      print_help
      ;;
    *)
      printf 'Unknown command: %s\n\n' "${command}" >&2
      print_help
      exit 1
      ;;
  esac
}

main "$@"
