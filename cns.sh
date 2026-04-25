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
  ./cns.sh install <stack-version>
  ./cns.sh uninstall
  ./cns.sh help

Commands:
  install <stack-version>  Deploy the requested CNS stack version.
  uninstall                Remove the deployed CNS stack from the target node.
  help                     Show this help text.

Available stack versions:
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
  local stack_file="${STACKS_DIR}/${stack_version}.yml"

  if [[ -z "${stack_version}" ]]; then
    printf 'Missing stack version.\n\n' >&2
    print_help
    exit 1
  fi

  require_file "${stack_file}"
  require_file "${INVENTORY_FILE}"
  require_file "${PLAYBOOK_FILE}"

  ansible-playbook \
    -i "${INVENTORY_FILE}" \
    "${PLAYBOOK_FILE}" \
    -e "cns_action=install" \
    -e "cns_stack_version=${stack_version}" \
    -e "@${stack_file}"
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
      run_install "${1:-}"
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
