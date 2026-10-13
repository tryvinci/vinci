#!/usr/bin/env bash
# Download pinned inputs; verify SHA256 from deps.lock (upstream manifest values).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE="$ROOT/.mac-bundle-cache"
LOCK="$ROOT/scripts/mac/deps.lock.json"
mkdir -p "$CACHE"
python3 "$ROOT/scripts/mac/verify-inputs.py"

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

download() {
  local url="$1" dest="$2" expected="$3"
  if [[ -f "$dest" ]] && [[ "$(sha256_file "$dest")" == "$expected" ]]; then
    echo "ok (cached) $dest"
    return 0
  fi
  echo "fetch $url"
  curl -fsSL "$url" -o "$dest.part"
  actual="$(sha256_file "$dest.part")"
  if [[ "$actual" != "$expected" ]]; then
    echo "digest mismatch for $dest (got $actual want $expected)" >&2
    rm -f "$dest.part"
    exit 1
  fi
  mv "$dest.part" "$dest"
  echo "verified $dest"
}

PY_URL="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["python_build_standalone"]["url"])')"
PY_SHA="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["python_build_standalone"]["sha256"])')"
PY_FILE="$CACHE/$(basename "$PY_URL")"
NODE_URL="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["node"]["url"])')"
NODE_SHA="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["node"]["sha256"])')"
NODE_FILE="$CACHE/$(basename "$NODE_URL")"
FF_URL="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["ffmpeg_source"]["url"])')"
FF_SHA="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["ffmpeg_source"]["sha256"])')"
FF_FILE="$CACHE/$(basename "$FF_URL")"

download "$PY_URL" "$PY_FILE" "$PY_SHA"
download "$NODE_URL" "$NODE_FILE" "$NODE_SHA"
download "$FF_URL" "$FF_FILE" "$FF_SHA"

python3 "$ROOT/scripts/mac/verify-inputs.py" --require-cache
echo "fetch-deps complete: $CACHE"
