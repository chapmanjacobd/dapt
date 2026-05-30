#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: generate-sidecars.sh <repo-root> <base-url> [tracker-url]

Creates:
  - .metalink files for repo artifacts
  - .torrent files when mktorrent or transmission-create is available

Example:
  ./scripts/generate-sidecars.sh repo http://mirror.example.internal:8000 udp://tracker.lan:6969/announce
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage >&2
  exit 1
fi

repo_root="${1%/}"
base_url="${2%/}"
tracker_url="${3:-}"

if [[ ! -d "$repo_root" ]]; then
  echo "error: repo root does not exist: $repo_root" >&2
  exit 1
fi

torrent_tool=""
if [[ -n "$tracker_url" ]]; then
  if command -v mktorrent >/dev/null 2>&1; then
    torrent_tool="mktorrent"
  elif command -v transmission-create >/dev/null 2>&1; then
    torrent_tool="transmission-create"
  else
    echo "warning: tracker was provided but no torrent creation tool was found; only .metalink files will be generated" >&2
  fi
fi

find "$repo_root" -type f \
  \( -name '*.deb' -o -name 'Packages' -o -name 'Packages.gz' -o -name 'Release' -o -name 'InRelease' \) |
while IFS= read -r file; do
  rel_path="${file#$repo_root/}"
  file_name="$(basename "$file")"
  sha256="$(sha256sum "$file" | awk '{print $1}')"
  size="$(stat -c '%s' "$file")"

  cat > "${file}.metalink" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<metalink version="3.0" xmlns="http://www.metalinker.org/">
  <files>
    <file name="${file_name}">
      <size>${size}</size>
      <verification>
        <hash type="sha-256">${sha256}</hash>
      </verification>
      <resources>
        <url type="http" preference="100">${base_url}/${rel_path}</url>
      </resources>
    </file>
  </files>
</metalink>
EOF

  if [[ -n "$torrent_tool" ]]; then
    case "$torrent_tool" in
      mktorrent)
        mktorrent -q -a "$tracker_url" -w "${base_url}/${rel_path}" -o "${file}.torrent" "$file"
        ;;
      transmission-create)
        transmission-create -o "${file}.torrent" -t "$tracker_url" -w "${base_url}/${rel_path}" "$file" >/dev/null
        ;;
    esac
  fi
done
