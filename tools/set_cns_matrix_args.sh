#!/usr/bin/env bash
# Updates the CNS matrix service argument line in /etc/cns-matrix.env.

set -euo pipefail

ENV_FILE="/etc/cns-matrix.env"

usage() {
  cat <<'EOF'
Usage:
  sudo ./tools/set_cns_matrix_args.sh '<test_cns_matrix.py args>'

Examples:
  sudo ./tools/set_cns_matrix_args.sh ''
  sudo ./tools/set_cns_matrix_args.sh '--stack 1.36 --set install_gpu_operator=false --fail-fast'
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$#" -ne 1 ]]; then
  usage >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run this command with sudo so %s can remain root-readable only.\n' "${ENV_FILE}" >&2
  exit 1
fi

quote_env() {
  local value="$1"
  printf "'%s'" "${value//\'/\'\\\'\'}"
}

args="$1"
tmp="$(mktemp)"
if [[ -f "${ENV_FILE}" ]]; then
  grep -v '^CNS_MATRIX_ARGS=' "${ENV_FILE}" > "${tmp}" || true
else
  printf '# Stores CNS matrix service environment and target secret.\n' > "${tmp}"
fi
printf 'CNS_MATRIX_ARGS=%s\n' "$(quote_env "${args}")" >> "${tmp}"
install -o root -g root -m 0600 "${tmp}" "${ENV_FILE}"
rm -f "${tmp}"
