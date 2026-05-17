#!/usr/bin/env bash
# Installs CNS matrix systemd services and prepares dashboard runtime paths.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SYSTEMD_DIR="${REPO_ROOT}/packaging/systemd"
RUNTIME_DIR="/var/lib/cns-matrix"
ENV_FILE="/etc/cns-matrix.env"
START_MATRIX="false"

usage() {
  cat <<'EOF'
Usage:
  ./tools/install_cns_matrix_services.sh [--start-matrix]

Options:
  --start-matrix  Start cns-matrix.service after installing the units.

The installer starts and enables cns-matrix-web.service on port 8888.
The matrix runner reads target settings from /etc/cns-matrix.env.
EOF
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --start-matrix)
      START_MATRIX="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
  SERVICE_USER="${SUDO_USER:-root}"
  if [[ "${SERVICE_USER}" == "root" ]]; then
    AS_SERVICE_USER=()
  else
    AS_SERVICE_USER=(runuser -u "${SERVICE_USER}" --)
  fi
else
  SUDO=(sudo)
  SERVICE_USER="$(id -un)"
  AS_SERVICE_USER=()
fi
SERVICE_GROUP="$(id -gn "${SERVICE_USER}")"

quote_env() {
  local value="$1"
  printf "'%s'" "${value//\'/\'\\\'\'}"
}

inventory_value() {
  local key="$1"
  awk -F '=' -v key="${key}" '
    $1 == key {
      print substr($0, index($0, "=") + 1)
      exit
    }
  ' "${REPO_ROOT}/ansible/inventory/hosts.ini"
}

inventory_host() {
  awk '
    $1 !~ /^#/ && $0 ~ /ansible_host=/ {
      for (i = 1; i <= NF; i++) {
        if ($i ~ /^ansible_host=/) {
          sub(/^ansible_host=/, "", $i)
          print $i
          exit
        }
      }
    }
  ' "${REPO_ROOT}/ansible/inventory/hosts.ini"
}

render_unit() {
  local template="$1"
  local destination="$2"
  local rendered
  rendered="$(mktemp)"
  sed \
    -e "s#__REPO_ROOT__#${REPO_ROOT}#g" \
    -e "s#__SERVICE_USER__#${SERVICE_USER}#g" \
    -e "s#__SERVICE_GROUP__#${SERVICE_GROUP}#g" \
    "${template}" > "${rendered}"
  "${SUDO[@]}" install -m 0644 "${rendered}" "${destination}"
  rm -f "${rendered}"
}

create_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    return
  fi

  local host
  local user
  local password
  host="$(inventory_host)"
  user="$(inventory_value ansible_user)"
  password="$(inventory_value ansible_password)"

  local rendered
  rendered="$(mktemp)"
  {
    printf '# Stores CNS matrix service environment and target secret.\n'
    printf 'CNS_TEST_PASSWORD=%s\n' "$(quote_env "${password}")"
    printf 'CNS_MATRIX_HOST=%s\n' "$(quote_env "${host:-10.86.6.94}")"
    printf 'CNS_MATRIX_USER=%s\n' "$(quote_env "${user:-nvidia}")"
    printf 'CNS_MATRIX_ARGS=%s\n' "$(quote_env "")"
  } > "${rendered}"
  "${SUDO[@]}" install -o root -g root -m 0600 "${rendered}" "${ENV_FILE}"
  rm -f "${rendered}"
}

for path in "${RUNTIME_DIR}" "${RUNTIME_DIR}/runs" "${RUNTIME_DIR}/state" "${RUNTIME_DIR}/www"; do
  "${SUDO[@]}" install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0755 "${path}"
done

create_env_file
render_unit "${SYSTEMD_DIR}/cns-matrix.service.in" /etc/systemd/system/cns-matrix.service
render_unit "${SYSTEMD_DIR}/cns-matrix-web.service.in" /etc/systemd/system/cns-matrix-web.service

"${AS_SERVICE_USER[@]}" /usr/bin/python3 \
  "${REPO_ROOT}/tools/cns_matrix_dashboard.py" \
  --base-dir "${RUNTIME_DIR}"

"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable --now cns-matrix-web.service

if [[ "${START_MATRIX}" == "true" ]]; then
  "${SUDO[@]}" systemctl start --no-block cns-matrix.service
fi

cat <<EOF
CNS matrix services installed.

Dashboard:
  http://$(hostname -I | awk '{print $1}'):8888/

Run status:
  systemctl status cns-matrix.service
  systemctl status cns-matrix-web.service

Start a matrix run:
  sudo systemctl start --no-block cns-matrix.service

Runtime data:
  ${RUNTIME_DIR}
EOF
