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
# python-build-standalone ships its dylibs with the install name /install/lib/<name>.
# verify-macho.py rejects absolute non-system paths. bin/python3 already loads libpython via
# @executable_path, so only the dylib ID changes. install_name_tool voids the linker
# signature, so re-sign ad hoc (COREPRODUC-520).
for lib in "$PREFIX"/lib/*.dylib; do
  [[ -e "$lib" ]] || continue
  id="$(otool -D "$lib" | tail -1)"
  [[ "$id" == /install/* ]] || continue
  install_name_tool -id "@rpath/$(basename "$lib")" "$lib"
  codesign --force -s - "$lib"
  echo "install name: $(basename "$lib") $id -> @rpath/$(basename "$lib")"
done
PY="$PREFIX/bin/python3"
export PYTHONDONTWRITEBYTECODE=1
python3 "$ROOT/scripts/mac/verify-python-bundle-lock.py" "$ROOT/scripts/mac/python-bundle-runtime.lock.txt"
# Checks the committed tree list, then writes build-time digests for provenance (COREPRODUC-508).
python3 "$ROOT/scripts/mac/hash-python-local-trees.py"
"$PY" -m pip install --no-compile --require-hashes -r "$ROOT/scripts/mac/python-bundle-runtime.lock.txt"
while IFS= read -r rel; do
  [[ -z "$rel" ]] && continue
  # Regular install (not -e): an editable finder points at this checkout, so the app would
  # only run on the build machine. --no-build-isolation builds with the locked setuptools.
  # The build runs in place: drop the last build/ so deleted modules do not ship again.
  rm -rf "$ROOT/$rel/build"
  "$PY" -m pip install --no-compile --no-deps --no-build-isolation "$ROOT/$rel"
done < <(grep -E '^-e ' "$ROOT/scripts/mac/python-bundle-requirements.in" | sed 's/^-e //')
"$PY" -c "import vinci_daemon.app, vinci_media.ops"
echo "python runtime staged at $PREFIX"
