#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: install-apt-transport.sh [methods-dir]

Installs the DAPT APT acquire method as:
  - dapt+http
  - dapt+https

Default destination:
  /usr/lib/apt/methods

Example:
  sudo ./scripts/install-apt-transport.sh
  ./scripts/install-apt-transport.sh /tmp/apt-methods
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

methods_dir="${1:-/usr/lib/apt/methods}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_file="${script_dir}/dapt-apt-method.py"

if [[ ! -f "$source_file" ]]; then
  echo "error: missing source file: $source_file" >&2
  exit 1
fi

mkdir -p "$methods_dir"
install -m 0755 "$source_file" "${methods_dir}/dapt+http"
ln -sfn "dapt+http" "${methods_dir}/dapt+https"

printf 'Installed DAPT transport into %s\n' "$methods_dir"
printf 'Methods:\n'
printf '  %s\n' "${methods_dir}/dapt+http"
printf '  %s\n' "${methods_dir}/dapt+https"
