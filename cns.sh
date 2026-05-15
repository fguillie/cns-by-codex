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
  ./cns.sh install <stack-version> [--set <stack-key>=<value> ...]
  ./cns.sh uninstall
  ./cns.sh help

Commands:
  install <stack-version>  Deploy the requested CNS stack version.
  uninstall                Remove the deployed CNS stack from the target node.
  help                     Show this help text.

Install options:
  --set <key>=<value>      Override a top-level key defined in the selected stack file.

Examples:
  ./cns.sh install 1.36 --set install_gpu_operator=false
  ./cns.sh install 1.36 --set install_nfs_provisioner=false
  ./cns.sh install 1.36 --set cuda_driver_container_version=580.126.20

Available stack versions:
  1.36
  1.35
  1.34
  1.33

Notes:
  - Override keys must exist as top-level keys in the selected stack file.
  - install_gpu_operator and install_nfs_provisioner values must be true or false.
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

stack_has_key() {
  local stack_file="$1"
  local key="$2"

  awk -F ':' -v key="${key}" '$1 == key { found = 1; exit } END { exit found ? 0 : 1 }' "${stack_file}"
}

stack_value() {
  local stack_file="$1"
  local key="$2"

  awk -F ':' -v key="${key}" '
    $1 == key {
      value = substr($0, index($0, ":") + 1)
      sub(/[[:space:]]+#.*$/, "", value)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if ((value ~ /^".*"$/) || (value ~ /^'\''.*'\''$/)) {
        value = substr(value, 2, length(value) - 2)
      }
      print value
      exit
    }
  ' "${stack_file}"
}

is_truthy() {
  local value="${1,,}"

  case "${value}" in
    true|yes|on|1)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

run_install() {
  local stack_version="${1:-}"
  local stack_file
  local set_arg
  local set_key
  local set_value
  local effective_gpu_operator
  local cuda_driver_version_overridden="false"
  local -a ansible_args
  local -a set_overrides=()

  if [[ -z "${stack_version}" || "${stack_version}" == --* ]]; then
    printf 'Missing stack version.\n\n' >&2
    print_help
    exit 1
  fi

  stack_file="${STACKS_DIR}/${stack_version}.yml"

  require_file "${stack_file}"
  require_file "${INVENTORY_FILE}"
  require_file "${PLAYBOOK_FILE}"

  shift || true
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --set)
        if [[ "$#" -lt 2 || -z "${2:-}" || "${2}" == --* ]]; then
          printf 'Missing stack override for --set.\n\n' >&2
          print_help
          exit 1
        fi
        set_arg="$2"
        if [[ "${set_arg}" != *=* ]]; then
          printf 'Invalid --set value: %s\nExpected key=value.\n\n' "${set_arg}" >&2
          print_help
          exit 1
        fi
        set_key="${set_arg%%=*}"
        set_value="${set_arg#*=}"
        if [[ -z "${set_key}" || -z "${set_value}" ]]; then
          printf 'Invalid --set value: %s\nExpected non-empty key and value.\n\n' "${set_arg}" >&2
          print_help
          exit 1
        fi
        if [[ ! "${set_key}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
          printf 'Invalid --set key: %s\n\n' "${set_key}" >&2
          print_help
          exit 1
        fi
        if ! stack_has_key "${stack_file}" "${set_key}"; then
          printf 'Unknown stack parameter for %s: %s\n\n' "${stack_version}" "${set_key}" >&2
          print_help
          exit 1
        fi
        if [[ "${set_key}" =~ ^install_(gpu_operator|nfs_provisioner)$ && ! "${set_value,,}" =~ ^(true|false)$ ]]; then
          printf 'Invalid value for %s: %s\nExpected true or false.\n\n' "${set_key}" "${set_value}" >&2
          print_help
          exit 1
        fi
        set_overrides+=("${set_arg}")
        shift
        ;;
      *)
        printf 'Unknown install option: %s\n\n' "$1" >&2
        print_help
        exit 1
        ;;
    esac
    shift
  done

  effective_gpu_operator="$(stack_value "${stack_file}" "install_gpu_operator")"
  for set_arg in "${set_overrides[@]}"; do
    set_key="${set_arg%%=*}"
    set_value="${set_arg#*=}"
    if [[ "${set_key}" == "install_gpu_operator" ]]; then
      effective_gpu_operator="${set_value}"
    elif [[ "${set_key}" == "cuda_driver_container_version" ]]; then
      cuda_driver_version_overridden="true"
    fi
  done

  if ! is_truthy "${effective_gpu_operator}" && [[ "${cuda_driver_version_overridden}" == "true" ]]; then
    printf '%s\n\n' 'cuda_driver_container_version requires GPU Operator installation. Set install_gpu_operator=true or omit the driver version override.' >&2
    print_help
    exit 1
  fi

  ansible_args=(
    ansible-playbook
    -i "${INVENTORY_FILE}"
    "${PLAYBOOK_FILE}"
    -e "cns_action=install"
    -e "cns_stack_version=${stack_version}"
    -e "@${stack_file}"
  )

  for set_arg in "${set_overrides[@]}"; do
    ansible_args+=(-e "${set_arg}")
  done

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
