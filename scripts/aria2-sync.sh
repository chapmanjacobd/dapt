#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: aria2-sync.sh <base-url> <dest-dir> [codename] [component] [architecture]

This mirrors the APT repository into <dest-dir> using aria2c while preferring:
  1. .meta4 sidecars
  2. .metalink sidecars
  3. .torrent sidecars
  4. direct downloads

Example:
  ./scripts/aria2-sync.sh http://mirror.example.internal:8000 /srv/dapt-mirror stable main amd64
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 || $# -gt 5 ]]; then
  usage >&2
  exit 1
fi

base_url="${1%/}"
dest_dir="${2%/}"
codename="${3:-stable}"
component="${4:-main}"
architecture="${5:-amd64}"

if ! command -v aria2c >/dev/null 2>&1; then
  echo "error: aria2c is required" >&2
  exit 1
fi

fetch_path() {
  local rel_path="$1"
  local target_dir target_name local_root
  target_dir="$dest_dir/$(dirname "$rel_path")"
  target_name="$(basename "$rel_path")"
  mkdir -p "$target_dir"

  if [[ "$base_url" == file://* ]]; then
    local_root="${base_url#file://}"
    cp "${local_root}/${rel_path}" "${target_dir}/${target_name}"
    return 0
  fi

  if [[ "$base_url" == /* ]]; then
    cp "${base_url}/${rel_path}" "${target_dir}/${target_name}"
    return 0
  fi

  for metalink_suffix in .meta4 .metalink; do
    if aria2c \
        --allow-overwrite=true \
        --auto-file-renaming=false \
        --check-integrity=true \
        --connect-timeout=5 \
        --dir "$target_dir" \
        --follow-metalink=mem \
        --max-tries=1 \
        --out "$target_name" \
        --timeout=20 \
        "${base_url}/${rel_path}${metalink_suffix}" >/dev/null 2>&1; then
      return 0
    fi
  done

  if aria2c \
      --allow-overwrite=true \
      --auto-file-renaming=false \
      --bt-stop-timeout=10 \
      --bt-enable-lpd=true \
      --check-integrity=true \
      --connect-timeout=5 \
      --dir "$target_dir" \
      --follow-torrent=mem \
      --max-tries=1 \
      --out "$target_name" \
      --seed-time=0 \
      --timeout=20 \
      "${base_url}/${rel_path}.torrent" >/dev/null 2>&1; then
    return 0
  fi

  aria2c \
    --allow-overwrite=true \
    --auto-file-renaming=false \
    --check-integrity=true \
    --connect-timeout=5 \
    --dir "$target_dir" \
    --max-tries=1 \
    --out "$target_name" \
    --timeout=20 \
    "${base_url}/${rel_path}" >/dev/null
}

release_rel="dists/${codename}/Release"
packages_gz_rel="dists/${codename}/${component}/binary-${architecture}/Packages.gz"
packages_rel="dists/${codename}/${component}/binary-${architecture}/Packages"

fetch_path "$release_rel"
fetch_path "$packages_gz_rel"

mkdir -p "$dest_dir/$(dirname "$packages_rel")"
gzip -dc "$dest_dir/$packages_gz_rel" > "$dest_dir/$packages_rel"

python3 - "$dest_dir/$packages_rel" <<'PY' | while IFS= read -r rel_path; do
import sys
from pathlib import Path

packages = Path(sys.argv[1]).read_text(encoding="utf-8")
for stanza in packages.split("\n\n"):
    for line in stanza.splitlines():
        if line.startswith("Filename: "):
            print(line.split(": ", 1)[1])
            break
PY
  fetch_path "$rel_path"
done

printf 'APT mirror ready at %s\n' "$dest_dir"
printf 'Example source: deb [trusted=yes] file:%s %s %s\n' "$dest_dir" "$codename" "$component"
