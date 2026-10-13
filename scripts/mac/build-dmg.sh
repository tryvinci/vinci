#!/usr/bin/env bash
# Create arm64 DMG from dist/Vinci Studio.app (run after build-app.sh on macOS).
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "build-dmg.sh requires macOS arm64 (host: $(uname -s)/$(uname -m))" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$ROOT/dist"
APP="$DIST/Vinci Studio.app"
if [[ ! -d "$APP" ]]; then
  echo "missing app bundle; run scripts/mac/build-app.sh first" >&2
  exit 1
fi
STAGING="$DIST/dmg-staging"
DMG="$DIST/Vinci-Studio-0.1.0-alpha-arm64.dmg"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -sf /Applications "$STAGING/Applications"
rm -f "$DMG"
hdiutil create \
  -volname "Vinci Studio" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG"
(
  cd "$DIST"
  shasum -a 256 "$(basename "$DMG")" > SHA256SUMS.dmg
  cat SHA256SUMS.dmg >> SHA256SUMS
)
echo "Built $DMG"
