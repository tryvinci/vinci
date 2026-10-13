#!/usr/bin/env bash
# Regenerate hashed PyPI lock, local tree manifest, and notice inputs (Python 3.12+).
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
python3 "$ROOT/scripts/mac/hash-python-local-trees.py"
python3 "$ROOT/scripts/mac/verify-python-local-manifest.py"
make install
python3 "$ROOT/scripts/mac/collect-python-notices.py"
python3 "$ROOT/scripts/mac/collect-npm-notices.py"
echo "lock + notices regenerated"
