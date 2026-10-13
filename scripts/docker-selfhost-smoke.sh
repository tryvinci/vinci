#!/usr/bin/env bash
# Build and smoke-test the self-host container image (no provider spend, no deploy).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${VINCI_SELFHOST_IMAGE:-vinci-oss-selfhost:ci}"
RUN_ID="${GITHUB_RUN_ID:-local}"
DURABLE_VOL="${VINCI_DOCKER_DURABLE_VOL:-vinci-oss-durable-${RUN_ID}}"
HOME_VOL="${VINCI_DOCKER_HOME_VOL:-vinci-oss-home-${RUN_ID}}"
PORT="${VINCI_DOCKER_PORT:-18080}"
OP_ID="docker-smoke-op-1"

cleanup() {
  if [[ -n "${CID:-}" ]]; then
    docker rm -f "$CID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker build -f "$ROOT/deploy/cloudflare/container/Dockerfile" -t "$IMAGE" "$ROOT"
DIGEST="$(docker image inspect "$IMAGE" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
if [[ -z "$DIGEST" ]]; then
  DIGEST="$(docker image inspect "$IMAGE" --format '{{.Id}}')"
fi
echo "image_digest=$DIGEST"

docker run --rm --user vinci -e VINCI_DURABLE_JOURNAL=off -e VINCI_CAS_BACKEND=local \
  "$IMAGE" python -c "from vinci_daemon.app import create_app; create_app()" >/dev/null

docker volume create "$DURABLE_VOL" >/dev/null
docker volume create "$HOME_VOL" >/dev/null
docker run --rm --user root \
  -v "$DURABLE_VOL":/durable \
  -v "$HOME_VOL":/data/.vinci \
  "$IMAGE" sh -c 'mkdir -p /durable/cas /data/.vinci && chown -R vinci:vinci /durable /data/.vinci'

container_env=(
  -e VINCI_DURABLE_JOURNAL=local
  -e VINCI_DURABLE_JOURNAL_PATH=/durable/control-plane.sqlite
  -e VINCI_CAS_DIR=/durable/cas
  -e VINCI_HOME=/data/.vinci
  -e VINCI_CAS_BACKEND=local
  -e VINCI_HOME_LEASE_SECONDS=5
  -v "$DURABLE_VOL":/durable
  -v "$HOME_VOL":/data/.vinci
  -p "${PORT}:8080"
)

wait_health() {
  local tries="${1:-60}"
  for _ in $(seq 1 "$tries"); do
    if curl -sf "http://127.0.0.1:${PORT}/healthz" | grep -q '"status":"ok"'; then
      return 0
    fi
    sleep 1
  done
  docker logs "$CID" 2>&1 | tail -100 >&2 || true
  return 1
}

CID="$(docker run -d --user vinci "${container_env[@]}" "$IMAGE")"
wait_health

curl -sf -X POST "http://127.0.0.1:${PORT}/init" \
  -H 'content-type: application/json' \
  -d '{"demo":true}' | grep -q '"demo"'
curl -sf -X PATCH "http://127.0.0.1:${PORT}/settings" \
  -H 'content-type: application/json' \
  -H "X-Vinci-Operation-Id: ${OP_ID}-settings" \
  -d '{"preference":"cheapest"}' | grep -q 'cheapest'

printf 'ledger-cas-bytes' >/tmp/vinci-smoke-upload.bin
ASSET_JSON="$(curl -sf -X POST "http://127.0.0.1:${PORT}/assets" \
  -H "X-Vinci-Operation-Id: ${OP_ID}-asset" \
  -F "file=@/tmp/vinci-smoke-upload.bin;type=application/octet-stream")"
ASSET_ID="$(echo "$ASSET_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")"
curl -sf "http://127.0.0.1:${PORT}/assets/${ASSET_ID}/file" | grep -q ledger-cas-bytes

RUN_JSON="$(curl -sf -X POST "http://127.0.0.1:${PORT}/runs" \
  -H 'content-type: application/json' \
  -H "X-Vinci-Operation-Id: ${OP_ID}-run" \
  -d '{"skill":"@tryvinci/image-generate","inputs":{"prompt":"smoke"}}')"
RUN_ID="$(echo "$RUN_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))")"
for _ in $(seq 1 90); do
  STATE="$(curl -sf "http://127.0.0.1:${PORT}/runs/${RUN_ID}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('state',''))")"
  [[ "$STATE" == "completed" || "$STATE" == "failed" ]] && break
  sleep 1
done
curl -sf "http://127.0.0.1:${PORT}/runs/${RUN_ID}" | grep -q '"state":"completed"'

docker rm -f "$CID" >/dev/null
CID=""
sleep 6

docker run --rm -v "$HOME_VOL":/data/.vinci "$IMAGE" sh -c 'rm -rf /data/.vinci/* /data/.vinci/.[!.]* 2>/dev/null || true'

CID="$(docker run -d --user vinci "${container_env[@]}" "$IMAGE")"
wait_health

curl -sf "http://127.0.0.1:${PORT}/settings" | grep -q 'cheapest'
curl -sf "http://127.0.0.1:${PORT}/assets/${ASSET_ID}/file" | grep -q ledger-cas-bytes
curl -sf "http://127.0.0.1:${PORT}/runs/${RUN_ID}" | grep -q '"state":"completed"'

echo "docker-selfhost-smoke ok digest=$DIGEST recovery=ledger+cas"
