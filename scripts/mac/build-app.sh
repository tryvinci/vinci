#!/usr/bin/env bash
# Build Vinci Studio.app (macOS arm64). Fails closed if inputs or bundle paths are missing.
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "build-app.sh requires macOS arm64 (host: $(uname -s)/$(uname -m))" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST="$ROOT/dist"
APP="$DIST/Vinci Studio.app"
CACHE="$ROOT/.mac-bundle-cache"
MAC="$ROOT/apps/mac"
PY_PREFIX="$CACHE/python-prefix"
STUDIO_BUNDLE="$ROOT/dist/studio-bundle"
NODE_TAR="$(python3 -c 'import json;print(json.load(open("'"$ROOT/scripts/mac/deps.lock.json"'"))["node"]["url"].split("/")[-1])')"

python3 "$ROOT/scripts/mac/verify-inputs.py" --require-cache --require-ffmpeg-bin
bash "$ROOT/scripts/mac/prepare-studio-bundle.sh"
bash "$ROOT/scripts/mac/build-python-runtime.sh"
bash "$ROOT/scripts/mac/generate-notices-sbom.sh"
python3 "$ROOT/scripts/mac/verify-packaging-paths.py" --prebuild

for req in \
  "$PY_PREFIX/bin/python3" \
  "$CACHE/ffmpeg-arm64/bin/ffmpeg" \
  "$CACHE/ffmpeg-arm64/bin/ffprobe" \
  "$STUDIO_BUNDLE/server.js" \
  "$STUDIO_BUNDLE/node_modules/next/package.json" \
  "$MAC/Info.plist" \
  "$MAC/VinciStudio.swift" \
  "$MAC/SmokeRunner.swift"; do
  if [[ ! -e "$req" ]]; then
    echo "missing required build input: $req" >&2
    exit 1
  fi
done

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/runtime" "$APP/Contents/Resources/studio" "$APP/Contents/Resources/bin" "$APP/Contents/Resources/legal"

cp "$MAC/Info.plist" "$APP/Contents/Info.plist"
swiftc -parse-as-library -O -target arm64-apple-macos13.0 \
  -framework Cocoa -framework WebKit -framework AVFoundation \
  "$MAC/VinciStudio.swift" "$MAC/SmokeRunner.swift" -o "$APP/Contents/MacOS/VinciStudio"

cp -R "$PY_PREFIX/." "$APP/Contents/Resources/runtime/"
cp -R "$STUDIO_BUNDLE/." "$APP/Contents/Resources/studio/"
NODE_EXTRACT="$CACHE/node-extract"
rm -rf "$NODE_EXTRACT"
mkdir -p "$NODE_EXTRACT"
tar -xzf "$CACHE/$NODE_TAR" -C "$NODE_EXTRACT" --strip-components=1
cp "$NODE_EXTRACT/bin/node" "$APP/Contents/Resources/studio/node"
cp "$CACHE/ffmpeg-arm64/bin/ffmpeg" "$APP/Contents/Resources/bin/ffmpeg"
cp "$CACHE/ffmpeg-arm64/bin/ffprobe" "$APP/Contents/Resources/bin/ffprobe"
cp "$ROOT/legal/THIRD_PARTY_NOTICES.md" "$APP/Contents/Resources/legal/THIRD_PARTY_NOTICES.md"
cp "$ROOT/legal/provenance.json" "$APP/Contents/Resources/legal/provenance.json"

python3 "$ROOT/scripts/mac/verify-packaging-paths.py" --app "$APP"
python3 "$ROOT/scripts/mac/verify-macho.py" "$APP"

while IFS= read -r bin; do
  [[ -z "$bin" ]] && continue
  codesign --force -s - --timestamp=none "$bin"
done < <(python3 "$ROOT/scripts/mac/list-macho-signables.py" "$APP")

codesign --force -s - --timestamp=none "$APP/Contents/MacOS/VinciStudio"
codesign --force -s - --timestamp=none "$APP"
codesign --verify --strict --deep "$APP"

mkdir -p "$DIST"
ZIP="$DIST/Vinci-Studio-0.1.0-alpha-arm64.zip"
rm -f "$ZIP"
( cd "$DIST" && ditto -c -k --keepParent "Vinci Studio.app" "$(basename "$ZIP")" )
(
  cd "$DIST"
  shasum -a 256 "$(basename "$ZIP")" > SHA256SUMS
)
bash "$ROOT/scripts/mac/scan-bundle.sh" "$APP"
echo "Built $APP and $ZIP"
echo "Optional DMG: bash scripts/mac/build-dmg.sh"
