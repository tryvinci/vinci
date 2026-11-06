#!/usr/bin/env bash
# Start daemon + TypeScript Studio for Playwright (demo mode, mock models).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export PATH="${HOME}/.local/bin:$ROOT/.venv/bin:$PATH"
export VINCI_HOME="${VINCI_HOME:-$(mktemp -d /tmp/vinci-e2e-home.XXXX)}"
export VINCI_DAEMON_URL="${VINCI_DAEMON_URL:-http://127.0.0.1:4310}"
export VINCI_STUDIO_USE_REWRITE=1
if ! curl -sf "$VINCI_DAEMON_URL/healthz" >/dev/null 2>&1; then
  python3 -m vinci_daemon --host 127.0.0.1 --port 4310 &
  for _ in $(seq 1 40); do
    curl -sf "$VINCI_DAEMON_URL/healthz" >/dev/null 2>&1 && break
    sleep 0.2
  done
fi
curl -sf -X POST "$VINCI_DAEMON_URL/init" -H 'content-type: application/json' -d '{"demo":true}' >/dev/null
cd "$ROOT/apps/studio"
exec npx next dev -p 4311
