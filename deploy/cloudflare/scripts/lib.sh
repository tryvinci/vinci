#!/usr/bin/env bash
# Shared helpers for Vinci OSS Cloudflare deploy (sourced, not executed).
set -euo pipefail

deploy_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

oss_root() {
  local root
  root="$(deploy_root)"
  cd "$root/../.." && pwd
}

state_file() {
  printf '%s/.deploy-state.json' "$(deploy_root)"
}

bootstrap_tools() {
  local root
  root="$(deploy_root)"
  if [[ ! -x "$root/node_modules/.bin/wrangler" ]]; then
    (cd "$root" && npm ci)
  fi
  export WRANGLER="$root/node_modules/.bin/wrangler"
  export PATH="$root/node_modules/.bin:$PATH"
}

load_state() {
  local path
  path="$(state_file)"
  if [[ -f "$path" ]]; then
    python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))' "$path"
  else
    printf '{}'
  fi
}

save_state() {
  local worker="$1" bucket="$2" account="$3"
  python3 - <<PY
import json
from pathlib import Path
path = Path("$(state_file)")
path.write_text(json.dumps({
  "worker_name": "$worker",
  "bucket_name": "$bucket",
  "account_id": "$account",
}, indent=2) + "\n", encoding="utf-8")
PY
}

resolve_worker_name() {
  local state worker
  worker="${VINCI_CF_WORKER_NAME:-}"
  if [[ -z "$worker" ]]; then
    state="$(load_state)"
    worker="$(STATE_JSON="$state" python3 -c 'import json,os; d=json.loads(os.environ["STATE_JSON"]); print(d.get("worker_name") or "vinci-oss-selfhost")')"
  fi
  printf '%s' "$worker"
}

resolve_bucket_name() {
  local state bucket account
  bucket="${VINCI_R2_BUCKET_NAME:-}"
  if [[ -n "$bucket" ]]; then
    printf '%s' "$bucket"
    return
  fi
  state="$(load_state)"
  bucket="$(STATE_JSON="$state" python3 -c 'import json,os; d=json.loads(os.environ["STATE_JSON"]); print(d.get("bucket_name") or "")')"
  if [[ -n "$bucket" ]]; then
    printf '%s' "$bucket"
    return
  fi
  account="${CLOUDFLARE_ACCOUNT_ID:-}"
  if [[ -z "$account" ]]; then
    account="$(STATE_JSON="$state" python3 -c 'import json,os; d=json.loads(os.environ["STATE_JSON"]); print(d.get("account_id") or "")')"
  fi
  if [[ -z "$account" ]]; then
    printf 'vinci-oss-data' 
  else
    printf 'vinci-oss-data-%s' "${account:0:8}"
  fi
}

verify_account() {
  bootstrap_tools
  local who account
  who="$("$WRANGLER" whoami 2>/dev/null || true)"
  if [[ -z "$who" ]]; then
    return 1
  fi
  if [[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
    return 0
  fi
  printf '%s' "$who" | grep -q "$CLOUDFLARE_ACCOUNT_ID"
}

verify_r2_credentials() {
  local bucket="$1"
  python3 - <<PY
import os, sys
from vinci_storage.r2_client import R2Client
bucket = "$bucket"
client = R2Client(
    bucket=bucket,
    account_id=os.environ["CLOUDFLARE_ACCOUNT_ID"],
    access_key_id=os.environ["VINCI_R2_ACCESS_KEY_ID"],
    secret_access_key=os.environ["VINCI_R2_SECRET_ACCESS_KEY"],
)
probe = b"vinci-deploy-probe"
key = "home/.deploy-probe"
client.put_bytes(key, probe)
got = client.get_bytes(key)
if got != probe:
    sys.exit("R2 probe read/write failed")
client.delete(key)
print("r2 ok", bucket)
PY
}

ensure_bucket() {
  local bucket="$1"
  bootstrap_tools
  if "$WRANGLER" r2 bucket list 2>/dev/null | grep -q " ${bucket}$"; then
    printf '%s\n' "using existing R2 bucket: $bucket"
    return 0
  fi
  printf '%s\n' "creating R2 bucket: $bucket"
  "$WRANGLER" r2 bucket create "$bucket"
}

parse_deploy_url() {
  local log="$1"
  python3 - "$log" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
for pat in (
    r"https://[a-z0-9-]+\.[a-z0-9-]+\.workers\.dev",
    r"https://[a-z0-9-]+\.workers\.dev",
):
    m = re.search(pat, text)
    if m:
        print(m.group(0))
        raise SystemExit(0)
raise SystemExit("deploy url not found in log")
PY
}
