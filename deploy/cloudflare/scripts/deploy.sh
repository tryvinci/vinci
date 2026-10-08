#!/usr/bin/env bash
# Deploy Vinci OSS self-host to the developer's Cloudflare account.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OSS_ROOT="$(cd "$ROOT/../.." && pwd)"
# shellcheck source=lib.sh
source "$ROOT/scripts/lib.sh"

DRY_RUN="${DRY_RUN:-0}"
FIXTURE_MODE="${FIXTURE_MODE:-0}"

die() { printf 'deploy: %s\n' "$*" >&2; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || die "missing prerequisite: $1"
}

if printf '%s' "${*:-}" | grep -Eqi 'wrangler deploy|wrangler versions deploy'; then
  die "refusing inline wrangler deploy in arguments; run this script instead"
fi

require python3
require openssl

bootstrap_tools

WORKER_NAME="$(resolve_worker_name)"
BUCKET_NAME="$(resolve_bucket_name)"

run_fixture_validation() {
  printf '%s\n' "FIXTURE_MODE=1 — validating deploy CLI wiring (no remote mutation)."
  test -f "$ROOT/wrangler.jsonc"
  test -x "$WRANGLER"
  "$WRANGLER" --version
  WORKER_NAME="$WORKER_NAME" BUCKET_NAME="$BUCKET_NAME" python3 - <<'PY'
import json, os, subprocess, tempfile, textwrap
from pathlib import Path
root = Path(os.environ["ROOT"])
worker = os.environ["WORKER_NAME"]
bucket = os.environ["BUCKET_NAME"]
state = {"worker_name": worker, "bucket_name": bucket, "account_id": "acctfixture"}
path = root / ".deploy-state.json.fixture"
path.write_text(json.dumps(state), encoding="utf-8")
assert "vinci-oss-selfhost" in worker or worker
assert bucket.startswith("vinci-oss-data")
print("fixture ok", worker, bucket)
PY
}

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%s\n' "DRY_RUN=1 — validation only (no Cloudflare resources created)."
  test -f "$ROOT/wrangler.jsonc"
  test -f "$ROOT/container/Dockerfile"
  test -f "$OSS_ROOT/Makefile"
  python3 -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" || die "Python 3.12+ required"
  bootstrap_tools
  (cd "$ROOT" && npm run typecheck)
  (cd "$ROOT" && npm test)
  if command -v docker >/dev/null 2>&1; then
    docker version >/dev/null
  else
    printf '%s\n' "note: docker not installed (required for real deploy image build)"
  fi
  if [[ "$FIXTURE_MODE" == "1" ]]; then
    ROOT="$ROOT" WORKER_NAME="$WORKER_NAME" BUCKET_NAME="$BUCKET_NAME" run_fixture_validation
  fi
  printf '%s\n' "dry-run ok: worker=$WORKER_NAME bucket=$BUCKET_NAME"
  printf '%s\n' "To deploy: VINCI_INSTANCE_SECRET=\$(openssl rand -hex 24) $0"
  exit 0
fi

require npm
if ! command -v docker >/dev/null 2>&1; then
  die "docker is required for container image build"
fi

if ! verify_account; then
  die "wrangler not authenticated or CLOUDFLARE_ACCOUNT_ID mismatch — run wrangler login"
fi

if [[ -z "${VINCI_INSTANCE_SECRET:-}" ]]; then
  die "set VINCI_INSTANCE_SECRET (>=16 chars) for the owner access gate"
fi
if ((${#VINCI_INSTANCE_SECRET} < 16)); then
  die "VINCI_INSTANCE_SECRET must be at least 16 characters"
fi

if [[ -z "${VINCI_R2_ACCESS_KEY_ID:-}" || -z "${VINCI_R2_SECRET_ACCESS_KEY:-}" || -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  die "set CLOUDFLARE_ACCOUNT_ID, VINCI_R2_ACCESS_KEY_ID, VINCI_R2_SECRET_ACCESS_KEY before deploy"
fi

export PYTHONPATH="$OSS_ROOT/packages/storage:$OSS_ROOT/packages/protocol:$OSS_ROOT/packages/core:${PYTHONPATH:-}"
ensure_bucket "$BUCKET_NAME"
verify_r2_credentials "$BUCKET_NAME"

VINCI_BRIDGE_TOKEN="${VINCI_BRIDGE_TOKEN:-$(openssl rand -hex 32)}"

cd "$ROOT"
DEPLOY_LOG="$(mktemp)"
trap 'rm -f "$DEPLOY_LOG"' EXIT

"$WRANGLER" secret put VINCI_INSTANCE_SECRET --name "$WORKER_NAME" <<<"$VINCI_INSTANCE_SECRET"
"$WRANGLER" secret put VINCI_BRIDGE_TOKEN --name "$WORKER_NAME" <<<"$VINCI_BRIDGE_TOKEN"
"$WRANGLER" secret put VINCI_R2_BUCKET --name "$WORKER_NAME" <<<"$BUCKET_NAME"
"$WRANGLER" secret put VINCI_R2_ACCOUNT_ID --name "$WORKER_NAME" <<<"$CLOUDFLARE_ACCOUNT_ID"
"$WRANGLER" secret put VINCI_R2_ACCESS_KEY_ID --name "$WORKER_NAME" <<<"$VINCI_R2_ACCESS_KEY_ID"
"$WRANGLER" secret put VINCI_R2_SECRET_ACCESS_KEY --name "$WORKER_NAME" <<<"$VINCI_R2_SECRET_ACCESS_KEY"
"$WRANGLER" secret put VINCI_ALLOW_LIVE_SPEND --name "$WORKER_NAME" <<<"${VINCI_ALLOW_LIVE_SPEND:-0}"

"$WRANGLER" deploy --name "$WORKER_NAME" 2>&1 | tee "$DEPLOY_LOG"
URL="$(parse_deploy_url "$DEPLOY_LOG" || true)"
save_state "$WORKER_NAME" "$BUCKET_NAME" "$CLOUDFLARE_ACCOUNT_ID"

if [[ -n "$URL" ]]; then
  JOURNAL_BASE="${URL%/}/__vinci/journal"
  printf '%s\n' "setting VINCI_DO_JOURNAL_BASE to worker journal API prefix"
  printf '%s' "$JOURNAL_BASE" | "$WRANGLER" secret put VINCI_DO_JOURNAL_BASE --name "$WORKER_NAME"
fi

printf '\n%s\n' "Deployed worker: $WORKER_NAME"
if [[ -n "$URL" ]]; then
  printf '%s\n' "Health: ${URL}/healthz"
  printf '%s\n' "Ready (auth required): ${URL}/readyz"
  printf '%s\n' "Studio: ${URL}/studio"
else
  printf '%s\n' "Could not parse workers.dev URL from deploy log — check Cloudflare dashboard."
fi
printf '%s\n' "Live provider spend stays OFF until secret VINCI_ALLOW_LIVE_SPEND=1 on worker $WORKER_NAME."
