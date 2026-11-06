#!/usr/bin/env bash
# Regenerate hashed PyPI lock and Python notice inputs; check the local tree list (Python 3.12+).
# prepare-studio-bundle.sh writes the npm notices (build output in dist/notices).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
IN="$ROOT/scripts/mac/python-bundle-requirements.in"
FULL="$ROOT/scripts/mac/python-bundle-runtime.full.lock.txt"
OUT="$ROOT/scripts/mac/python-bundle-runtime.lock.txt"
python3 -m pip install -q pip-tools
pip-compile \
  --generate-hashes \
  --allow-unsafe \
  --resolver=backtracking \
  --strip-extras \
  --output-file "$FULL" \
  "$IN"
python3 "$ROOT/scripts/mac/split-python-bundle-lock.py" "$FULL" "$OUT"
python3 "$ROOT/scripts/mac/verify-python-bundle-lock.py" "$OUT"
python3 "$ROOT/scripts/mac/verify-python-local-manifest.py"
make install
python3 "$ROOT/scripts/mac/collect-python-notices.py"
echo "lock + notices regenerated"
