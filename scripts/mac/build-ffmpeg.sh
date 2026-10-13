#!/usr/bin/env bash
# Build LGPL FFmpeg/ffprobe for arm64 (no GPL/nonfree codecs).
set -euo pipefail
if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "build-ffmpeg.sh requires macOS arm64" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CACHE="$ROOT/.mac-bundle-cache"
LOCK="$ROOT/scripts/mac/deps.lock.json"
OUT="$CACHE/ffmpeg-arm64"
SRC_TAR="$(python3 -c 'import json;print(json.load(open("'"$LOCK"'"))["ffmpeg_source"]["url"].split("/")[-1])')"
python3 "$ROOT/scripts/mac/verify-inputs.py" --require-cache
WORK="$CACHE/ffmpeg-build"
rm -rf "$WORK"
mkdir -p "$WORK"
tar -xJf "$CACHE/$SRC_TAR" -C "$WORK"
SRC_DIR="$(find "$WORK" -maxdepth 1 -type d -name 'ffmpeg-*' | head -1)"
cd "$SRC_DIR"
./configure \
  --prefix="$OUT" \
  --disable-shared \
  --enable-static \
  --disable-autodetect \
  --disable-gpl \
  --disable-nonfree \
  --disable-doc \
  --disable-debug \
  --enable-videotoolbox \
  --enable-audiotoolbox \
  --enable-zlib \
  --pkg-config=/usr/bin/false
make -j"$(sysctl -n hw.ncpu)"
make install
test -x "$OUT/bin/ffmpeg" && test -x "$OUT/bin/ffprobe"
"$OUT/bin/ffmpeg" -hide_banner -buildconf | grep -q -- '--disable-gpl'
"$OUT/bin/ffmpeg" -hide_banner -buildconf | grep -q -- '--disable-nonfree'
echo "ffmpeg installed to $OUT/bin"
