#!/usr/bin/env bash
# Scan a built .app for banned markers (AGPL clips, secrets, proprietary strings).
set -euo pipefail
APP="${1:-}"
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "usage: $0 'Vinci Studio.app'" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export SCAN_ROOT="$APP"
python3 "$ROOT/scripts/mac/scan_bundle.py" "$APP"
