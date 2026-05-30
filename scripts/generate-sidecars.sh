#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: generate-sidecars.sh <repo-root> <mirror-url> [<mirror-url> ...] [--tracker <tracker-url>]

Creates:
  - .meta4 and .torrent files with mkmetalink when available
  - fallback .metalink files and optional .torrent files otherwise

Example:
  ./scripts/generate-sidecars.sh repo \
    http://mirror.example.internal:8000 \
    http://mirror2.example.internal:8000 \
    --tracker udp://tracker.lan:6969/announce
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 1
fi

repo_root="${1%/}"
shift

tracker_url=""
mirror_urls=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tracker)
      if [[ $# -lt 2 ]]; then
        echo "error: --tracker requires a value" >&2
        exit 1
      fi
      tracker_url="$2"
      shift 2
      ;;
    --tracker=*)
      tracker_url="${1#*=}"
      shift
      ;;
    *)
      mirror_urls+=("${1%/}")
      shift
      ;;
  esac
done

if [[ ! -d "$repo_root" ]]; then
  echo "error: repo root does not exist: $repo_root" >&2
  exit 1
fi

if [[ ${#mirror_urls[@]} -eq 0 ]]; then
  echo "error: at least one mirror URL is required" >&2
  exit 1
fi

mkmetalink_available=0
if command -v mkmetalink >/dev/null 2>&1; then
  mkmetalink_available=1
fi

torrent_tool=""
if [[ $mkmetalink_available -eq 0 && -n "$tracker_url" ]]; then
  if command -v mktorrent >/dev/null 2>&1; then
    torrent_tool="mktorrent"
  elif command -v transmission-create >/dev/null 2>&1; then
    torrent_tool="transmission-create"
  else
    echo "warning: tracker was provided but no torrent creation tool was found; only Metalink sidecars will be generated" >&2
  fi
fi

find "$repo_root" -type f \
  \( -name '*.deb' -o -name 'Packages' -o -name 'Packages.gz' -o -name 'Release' -o -name 'InRelease' \) |
while IFS= read -r file; do
  rel_path="${file#$repo_root/}"
  file_name="$(basename "$file")"
  if [[ $mkmetalink_available -eq 1 ]]; then
    mkmetalink_args=(--out-dir "$(dirname "$file")")
    if [[ -n "$tracker_url" ]]; then
      mkmetalink_args+=(--tracker "$tracker_url")
    fi
    for mirror_url in "${mirror_urls[@]}"; do
      mkmetalink_args+=(-m "$mirror_url")
    done
    mkmetalink "${mkmetalink_args[@]}" "$file"
    continue
  fi

  sha256="$(sha256sum "$file" | awk '{print $1}')"
  size="$(stat -c '%s' "$file")"
  metalink_path="${file}.metalink"

  {
    cat <<EOF
<?xml version="1.0" encoding="utf-8"?>
<metalink version="3.0" xmlns="http://www.metalinker.org/">
  <files>
    <file name="${file_name}">
      <size>${size}</size>
      <verification>
        <hash type="sha-256">${sha256}</hash>
      </verification>
      <resources>
EOF
    preference=100
    for mirror_url in "${mirror_urls[@]}"; do
      printf '        <url type="http" preference="%s">%s/%s</url>\n' "$preference" "$mirror_url" "$rel_path"
      preference=$((preference - 1))
    done
    cat <<'EOF'
      </resources>
    </file>
  </files>
</metalink>
EOF
  } > "$metalink_path"

  if [[ -n "$torrent_tool" ]]; then
    case "$torrent_tool" in
      mktorrent)
        mktorrent -q -a "$tracker_url" -w "${mirror_urls[0]}/${rel_path}" -o "${file}.torrent" "$file"
        ;;
      transmission-create)
        transmission-create -o "${file}.torrent" -t "$tracker_url" -w "${mirror_urls[0]}/${rel_path}" "$file" >/dev/null
        ;;
    esac
  fi
done
