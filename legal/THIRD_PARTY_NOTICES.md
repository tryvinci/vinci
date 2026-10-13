# Third-party notices (Vinci Studio Mac bundle)

Pinned inputs: `scripts/mac/deps.lock.json` (schema v2).

## Bundled runtimes

| Component | Version | License | SHA256 |
|-----------|---------|---------|--------|
| CPython | 3.12.8 | PSF-2.0 | `abe1de2494bb8b243fd507944f4d50292848fa00685d5288c858a72623a16635` |
| Node.js | 22.12.0 | MIT | `293dcc6c2408da21562d135b0412525e381bb6fe150d688edb58fe850d0f3e13` |
| FFmpeg | 7.1 | LGPL-2.1+ | `40973d44970dbc83ef302b0609f2e74982be2d85916dd2ee7472d30678a7abe6` |

FFmpeg built with `--disable-gpl --disable-nonfree --disable-autodetect`. Source offer: https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz

## PyPI (bundled Python prefix)

_Regenerate PyPI list on Mac builder after build-python-runtime (bundled prefix pip-licenses)._

## npm (Studio bundle)

_Run on builder: npx license-checker --production --json (LGPL sharp-libvips called out below)._
- **sharp-libvips** LGPL-3.0 — see bundled `node_modules/@img/sharp-libvips-*` and upstream source.

## Application code

MIT unless noted in package metadata. See `legal/AGPL_CLEAN_ROOM.md`.
