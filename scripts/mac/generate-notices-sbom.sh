#!/usr/bin/env bash
# Write THIRD_PARTY_NOTICES.md and provenance.json to dist/legal (build output, not in git).
# Fails closed: needs the npm notices that prepare-studio-bundle.sh writes to dist/notices.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_LEGAL="${1:-$ROOT/dist/legal}"
LOCK="$ROOT/scripts/mac/deps.lock.json"
PY_NOTICES="$ROOT/scripts/mac/python-bundle-notices.json"
NPM_NOTICES="${VINCI_MAC_NPM_NOTICE_DIR:-$ROOT/dist/notices}/studio-bundle-npm-notices.json"
mkdir -p "$OUT_LEGAL"
# Read-only on inputs: prepare-studio-bundle.sh (run first by build-app.sh) already wrote the
# npm graph, synced the notices, and checked the graph against dist/studio-bundle.
# Explicit paths: the verify fails (does not skip npm) when the npm notices are missing.
python3 "$ROOT/scripts/mac/verify-notices-inputs.py" "$PY_NOTICES" "$NPM_NOTICES"
python3 - "$LOCK" "$OUT_LEGAL/provenance.json" "$OUT_LEGAL/THIRD_PARTY_NOTICES.md" "$PY_NOTICES" "$NPM_NOTICES" "$ROOT/scripts/mac" <<'PY'
import json
import sys
from pathlib import Path

lock_path = Path(sys.argv[1])
out_json = Path(sys.argv[2])
out_md = Path(sys.argv[3])
py_path = Path(sys.argv[4])
npm_path = Path(sys.argv[5])
sys.path.insert(0, sys.argv[6])
from notice_graph import LOCAL_DIGESTS, local_digests

lock = json.loads(lock_path.read_text(encoding="utf-8"))
py_data = json.loads(py_path.read_text(encoding="utf-8"))
npm_data = json.loads(npm_path.read_text(encoding="utf-8"))
if not py_data.get("pypi") or not py_data.get("local"):
    raise SystemExit("python-bundle-notices.json incomplete")
if not npm_data.get("packages"):
    raise SystemExit("studio-bundle-npm-notices.json incomplete")
# build-python-runtime.sh hashes the trees it installs; without that file, list names only.
digests = local_digests()
local = [{**p, **({"sha256": digests[p["name"]]} if digests else {})} for p in py_data["local"]]
print(f"local trees: {len(local)}; sha256 " + (f"from {LOCAL_DIGESTS}" if digests else "skipped (no build-time digests)"))

provenance = {
    "schema": 3,
    "bundled_runtimes": {
        "cpython": {
            "version": lock["python_build_standalone"]["version"],
            "target": lock["python_build_standalone"]["target"],
            "url": lock["python_build_standalone"]["url"],
            "sha256": lock["python_build_standalone"]["sha256"],
            "license": "PSF-2.0",
        },
        "node": {
            "version": lock["node"]["version"],
            "target": lock["node"]["target"],
            "url": lock["node"]["url"],
            "sha256": lock["node"]["sha256"],
            "license": "MIT",
        },
        "ffmpeg": {
            "version": lock["ffmpeg_source"]["version"],
            "url": lock["ffmpeg_source"]["url"],
            "sha256": lock["ffmpeg_source"]["sha256"],
            "license": "LGPL-2.1+",
            "build_flags": "--disable-gpl --disable-nonfree --disable-autodetect",
            "source_offer": lock["ffmpeg_source"]["url"],
        },
    },
    "pypi": py_data["pypi"],
    "pypi_local": local,
    "npm": npm_data["packages"],
}

pypi_lines = "\n".join(
    f"- **{p.get('name')}** {p.get('version', '')} — {p.get('license', 'UNKNOWN')}" for p in py_data["pypi"][:80]
)
local_lines = "\n".join(
    f"- **{p['name']}**{' `' + p['sha256'][:12] + '…`' if 'sha256' in p else ''} — {p.get('license', 'MIT')}" for p in local
)
npm_lines = "\n".join(
    f"- **{p.get('name')}** {p.get('version', '')} — {p.get('licenses', 'UNKNOWN')}" for p in npm_data["packages"][:80]
)

out_json.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
md = f"""# Third-party notices (Vinci Studio Mac bundle)

Pinned inputs: `scripts/mac/deps.lock.json` (schema v2). PyPI lock: `scripts/mac/python-bundle-runtime.lock.txt`.

## Bundled runtimes

| Component | Version | License | SHA256 |
|-----------|---------|---------|--------|
| CPython | {lock['python_build_standalone']['version']} | PSF-2.0 | `{lock['python_build_standalone']['sha256']}` |
| Node.js | {lock['node']['version']} | MIT | `{lock['node']['sha256']}` |
| FFmpeg | {lock['ffmpeg_source']['version']} | LGPL-2.1+ | `{lock['ffmpeg_source']['sha256']}` |

FFmpeg built with `{provenance['bundled_runtimes']['ffmpeg']['build_flags']}`. Source offer: {provenance['bundled_runtimes']['ffmpeg']['source_offer']}

## PyPI (hashed lock)

{pypi_lines}

## Vinci packages (local tree manifest)

{local_lines}

## npm (Studio production)

{npm_lines}

## Application code

MIT unless noted in package metadata. See `legal/AGPL_CLEAN_ROOM.md`.
"""
out_md.write_text(md, encoding="utf-8")
print(f"notices ok: {out_md} + {out_json.name} (pypi {len(py_data['pypi'])}, npm {len(npm_data['packages'])})")
PY
