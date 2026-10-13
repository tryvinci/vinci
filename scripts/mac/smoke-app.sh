#!/usr/bin/env bash
# Invoke VinciStudio --smoke-report harness (macOS arm64 GUI). No hand-written JSON.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "smoke-app.sh: macOS arm64 GUI harness pending (host: $(uname -s)/$(uname -m))" >&2
  exit 2
fi

APP="${1:-}"
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "usage: $0 'dist/Vinci Studio.app'" >&2
  exit 1
fi

BIN="$APP/Contents/MacOS/VinciStudio"
if [[ ! -x "$BIN" ]]; then
  echo "smoke-app.sh: missing executable: $BIN" >&2
  exit 1
fi

GIT_SHA="${VINCI_GIT_SHA:-$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)}"
ART_DIR="$ROOT/ci-artifacts/mac-smoke/$GIT_SHA"
mkdir -p "$ART_DIR"
REPORT="$ART_DIR/smoke-report.json"
RELAUNCH_REPORT="$ART_DIR/smoke-relaunch-report.json"
SHOT="$ART_DIR/smoke-screenshot.png"
DOWNLOAD="$ART_DIR/smoke-export.bin"
SMOKE_HOME="$(mktemp -d "${TMPDIR:-/tmp}/vinci-smoke-home.XXXX")"
STATE="$SMOKE_HOME/smoke-relaunch-state.json"
cleanup() { rm -rf "$SMOKE_HOME"; }
trap cleanup EXIT

export VINCI_GIT_SHA="$GIT_SHA"

echo "smoke-app: launching harness report=$REPORT sha=$GIT_SHA" >&2
set +e
perl -e 'alarm shift; exec @ARGV' 240 "$BIN" \
  --smoke-report "$REPORT" \
  --smoke-relaunch-report "$RELAUNCH_REPORT" \
  --smoke-screenshot "$SHOT" \
  --smoke-home "$SMOKE_HOME" \
  --smoke-download "$DOWNLOAD" \
  --smoke-state "$STATE"
HARNESS_EC=$?
set -e

if [[ ! -f "$REPORT" ]]; then
  echo "smoke-app.sh: harness exited $HARNESS_EC without report" >&2
  exit 1
fi

python3 "$ROOT/scripts/mac/verify-smoke-report.py" "$REPORT" "$SHOT" "$GIT_SHA" "$BIN" || exit 1
if [[ -f "$RELAUNCH_REPORT" ]]; then
  python3 "$ROOT/scripts/mac/verify-smoke-report.py" --relaunch "$RELAUNCH_REPORT" "$GIT_SHA" "$BIN" || exit 1
fi
if [[ "$HARNESS_EC" -ne 0 ]]; then
  echo "smoke-app.sh: harness failed ec=$HARNESS_EC (see $REPORT)" >&2
  exit "$HARNESS_EC"
fi

bash "$ROOT/scripts/mac/scan-bundle.sh" "$APP"
echo "smoke-app ok: $REPORT"
