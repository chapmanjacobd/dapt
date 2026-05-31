#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: rsync-sync.sh <source> <dest-dir>

Mirror a DAPT repo into <dest-dir> using rsync. <source> may be:
  - rsync://host/module/path
  - host::module/path
  - /local/path

The helper syncs payloads first and repository metadata last so the mirror
does not publish a new Release/Packages index before its referenced files exist.

Example:
  ./scripts/rsync-sync.sh rsync://mirror.example.internal/dapt/repo /srv/dapt-mirror
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 1
fi

source_root="${1%/}/"
dest_dir="${2%/}"
dest_root="${dest_dir}/"

if ! command -v rsync >/dev/null 2>&1; then
  echo "error: rsync is required" >&2
  exit 1
fi

mkdir -p "$dest_dir"

# Sync payloads and sidecars before indices. --fuzzy lets rsync reuse similar
# old package versions as basis files when filenames change across releases.
rsync \
  --archive \
  --compress \
  --delay-updates \
  --delete-delay \
  --fuzzy \
  --partial-dir=.rsync-partial \
  --safe-links \
  --exclude '/dists/***' \
  "$source_root" \
  "$dest_root"

# Refresh APT metadata last, using checksums because these files are small and
# correctness matters more than mtime-based shortcuts.
rsync \
  --archive \
  --compress \
  --checksum \
  --delete \
  --prune-empty-dirs \
  --safe-links \
  --include '/dists/***' \
  --exclude '*' \
  "$source_root" \
  "$dest_root"

printf 'APT mirror ready at %s\n' "$dest_dir"
printf 'Example source: deb [trusted=yes] file:%s stable main\n' "$dest_dir"
