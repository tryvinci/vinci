#!/usr/bin/env bash
# Build Next standalone + static + public into dist/studio-bundle (any OS with Node).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STUDIO="$ROOT/apps/studio"
OUT="$ROOT/dist/studio-bundle"
rm -rf "$OUT"
mkdir -p "$OUT"
export NODE_ENV=production
STANDALONE="$STUDIO/.next/standalone"
if [[ ! -f "$STANDALONE/server.js" || "${FORCE_STUDIO_REBUILD:-0}" == "1" ]]; then
  npm run build --workspace @tryvinci/studio
fi
STATIC="$STUDIO/.next/static"
PUBLIC="$STUDIO/public"
test -f "$STANDALONE/server.js" || { echo "missing $STANDALONE/server.js" >&2; exit 1; }
test -d "$STATIC" || { echo "missing $STATIC" >&2; exit 1; }
cp -R "$STANDALONE/." "$OUT/"
if [[ -f "$ROOT/package-lock.json" ]]; then
  cp "$ROOT/package-lock.json" "$OUT/package-lock.json"
fi
if [[ ! -d "$OUT/node_modules/next" ]]; then
  mkdir -p "$OUT/node_modules"
  cp -R "$ROOT/node_modules/." "$OUT/node_modules/"
fi
mkdir -p "$OUT/.next/static"
cp -R "$STATIC/." "$OUT/.next/static/"
if [[ -d "$PUBLIC" ]]; then
  cp -R "$PUBLIC/." "$OUT/public/"
fi
cp "$ROOT/scripts/mac/studio-launcher.cjs" "$OUT/studio-launcher.cjs"
python3 "$ROOT/scripts/mac/prune-studio-bundle.py" "$OUT"
python3 "$ROOT/scripts/mac/write-studio-bundle-lock.py" "$OUT"
python3 "$ROOT/scripts/mac/write-studio-bundle-npm-graph.py" "$OUT"
bash "$ROOT/scripts/mac/sync-bundle-notices.sh"
python3 "$ROOT/scripts/mac/verify-studio-bundle-npm-graph.py"
python3 "$ROOT/scripts/mac/verify-studio-bundle.py" "$OUT"
echo "studio bundle ready: $OUT"
