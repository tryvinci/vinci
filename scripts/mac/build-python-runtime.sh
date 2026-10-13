#!/usr/bin/env bash
# Install OSS Python packages into extracted python-build-standalone prefix (macOS arm64).
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "build-python-runtime.sh requires macOS arm64" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE="$ROOT/.mac-bundle-cache"
PREFIX="$CACHE/python-prefix"
LOCK="$ROOT/scripts/mac/deps.lock.json"
python3 "$ROOT/scripts/mac/verify-inputs.py" --require-cache
PY_TAR="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["python_build_standalone"]["url"].split("/")[-1])')"
rm -rf "$PREFIX"
mkdir -p "$PREFIX"
tar -xzf "$CACHE/$PY_TAR" -C "$PREFIX" --strip-components=1
PY="$PREFIX/bin/python3"
export PYTHONDONTWRITEBYTECODE=1
python3 "$ROOT/scripts/mac/verify-python-bundle-lock.py" "$ROOT/scripts/mac/python-bundle-runtime.lock.txt"
python3 "$ROOT/scripts/mac/verify-python-local-manifest.py"
"$PY" -m pip install --no-compile --require-hashes -r "$ROOT/scripts/mac/python-bundle-runtime.lock.txt"
while IFS= read -r rel; do
  [[ -z "$rel" ]] && continue
  "$PY" -m pip install --no-compile --no-deps -e "$ROOT/$rel"
done < <(grep -E '^-e ' "$ROOT/scripts/mac/python-bundle-requirements.in" | sed 's/^-e //')
"$PY" -c "import vinci_daemon.app, vinci_media.ops"
echo "python runtime staged at $PREFIX"
