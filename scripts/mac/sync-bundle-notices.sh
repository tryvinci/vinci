#!/usr/bin/env bash
# Regenerate notice inputs from committed graphs (run after studio npm graph refresh).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/scripts/mac/collect-npm-notices.py"
python3 "$ROOT/scripts/mac/verify-notices-inputs.py"
