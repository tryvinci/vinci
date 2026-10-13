# Vinci Studio Mac alpha (private)

Unsigned **arm64 Apple Silicon** build. **Not** notarized or production-ready.

## What ships

- `Vinci Studio.app` with bundled relocatable CPython 3.12, FFmpeg/ffprobe (LGPL build), Node + **Next.js standalone** TypeScript Studio, and the Vinci daemon on loopback.
- `Vinci-Studio-0.1.0-alpha-arm64.dmg` (primary handoff) plus `Vinci-Studio-0.1.0-alpha-arm64.zip`; checksums in `dist/SHA256SUMS` (DMG line also in `SHA256SUMS.dmg`).

## CPU / OS

- **arm64 only** for this alpha (no Universal or Intel claim until tested).
- Target minimum macOS **13.0** (`LSMinimumSystemVersion`); raise if smoke only passes on newer macOS.

## First launch (ad-hoc signed)

Gatekeeper blocks unsigned apps. **Right-click → Open** the first time, or:

```bash
xattr -dr com.apple.quarantine "/path/to/Vinci Studio.app"
```

## Data

- If `~/.vinci` exists, the app **keeps using it** (keys/jobs preserved).
- Otherwise: `~/Library/Application Support/Vinci`.
- Logs: `~/Library/Logs/Vinci/`.

## Spend

- `VINCI_ALLOW_LIVE_SPEND=0` is forced. Live provider HTTP stays off; mock image/video/receipts work offline.

## Build (macOS maintainer)

```bash
cd apps/vinci-oss
python3 scripts/mac/verify-inputs.py          # fails on placeholder digests
bash scripts/mac/fetch-deps.sh                # downloads + verifies upstream SHA256
# Regenerate hashed PyPI lock + notice inputs (after dependency changes):
# bash scripts/mac/generate-python-bundle-lock.sh
bash scripts/mac/build-ffmpeg.sh              # macOS arm64 LGPL build
NODE_ENV=production bash scripts/mac/prepare-studio-bundle.sh
bash scripts/mac/build-app.sh                 # fails closed if runtime/studio paths missing
bash scripts/mac/smoke-app.sh "dist/Vinci Studio.app"   # writes main + smoke-relaunch-report.json
bash scripts/mac/scan-bundle.sh "dist/Vinci Studio.app"
bash scripts/mac/build-dmg.sh
```

Produces `dist/Vinci-Studio-0.1.0-alpha-arm64.dmg` (unsigned; ad-hoc signed `.app` inside). Not notarized.

The harness runs `VinciStudio --smoke-report` (WKWebView + bundled daemon/Studio). **Linux agents exit 2** (`GUI pending`); do not treat Mac GUI smoke as green from Linux CI.

Linux CI runs `make test` including `tests/test_desktop_daemon.py`; full `.app` build/smoke requires a Mac runner (`workflow_dispatch` only — no paid CI enablement by default).

## Signed / notarized release blockers

- Apple Developer ID + `notarytool` credentials (not purchased in this effort).
- Hardened runtime + entitlements for embedded Python/FFmpeg.
- macOS arm64 builder with codesign + staple.
