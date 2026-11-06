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
# Regenerate hashed PyPI lock + Python notice inputs (after dependency changes):
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

`scripts/mac/python-bundle-local.manifest.json` lists the local `-e` trees (`apps/daemon`, `packages/*`) by path only. Change it only when you add or remove an `-e` line in `python-bundle-requirements.in`; `verify-python-local-manifest.py` checks that the two lists are equal. A source edit in a tree does not need a commit to these files. `build-python-runtime.sh` hashes the trees into `.mac-bundle-cache/python-bundle-local.digests.json` (gitignored) before it installs them, and `generate-notices-sbom.sh` adds these digests to `dist/legal/provenance.json` and `THIRD_PARTY_NOTICES.md`. Without that file (no build), the notices list the trees by name only. Set `VINCI_MAC_LOCAL_DIGESTS` to read or write another digests file.

Git does not hold the npm graph, the npm notices, the third-party notices, or the provenance. Each Mac build makes them for the build host (darwin arm64):

- `prepare-studio-bundle.sh` writes `studio-bundle-npm-graph.json` and `studio-bundle-npm-notices.json` to `dist/notices/` (gitignored).
- `generate-notices-sbom.sh` reads them and writes `THIRD_PARTY_NOTICES.md` and `provenance.json` to `dist/legal/`.
- `build-app.sh` copies these two files into `Vinci Studio.app/Contents/Resources/legal/`.

Before `prepare-studio-bundle.sh` runs, `verify-notices-inputs.py` checks only the Python inputs and logs that it skipped the npm checks. `generate-notices-sbom.sh` fails when the npm notices are missing. Set `VINCI_MAC_NPM_NOTICE_DIR` to read and write the npm files in another directory; the tests do this. `legal/README.md` lists the committed inputs.

Linux CI runs `make test` including `tests/test_desktop_daemon.py`; full `.app` build/smoke requires a Mac runner (`workflow_dispatch` only — no paid CI enablement by default).

## Signed / notarized release blockers

- Apple Developer ID + `notarytool` credentials (not purchased in this effort).
- Hardened runtime + entitlements for embedded Python/FFmpeg.
- macOS arm64 builder with codesign + staple.
