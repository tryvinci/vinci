#!/usr/bin/env bash
# Write the npm notices from the host npm graph in dist/notices, then verify (prepare-studio-bundle.sh runs this).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/scripts/mac/collect-npm-notices.py"
python3 "$ROOT/scripts/mac/verify-notices-inputs.py"
