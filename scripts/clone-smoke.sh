#!/usr/bin/env bash
# Prove a stranger clone of this tree can init --demo and get a $0 asset + receipt.
# Uses git archive so we do not copy .venv, dist, or secrets. Do not enable live spend.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${VINCI_CLONE_SMOKE_DIR:-$(mktemp -d /tmp/vinci-clone-smoke.XXXX)}"
export VINCI_HOME="${DEST}/.vinci-home"
unset VINCI_ALLOW_LIVE_SPEND || true
# Dummy env ref so `vinci providers add mcp` can resolve MCP_API_KEY. Not a live key.
export MCP_API_KEY=mcp-secret-value
mkdir -p "$DEST"
GIT_ROOT="$(git -C "$ROOT" rev-parse --show-toplevel)"
PREFIX="$(git -C "$ROOT" rev-parse --show-prefix)"
if [[ -n "$PREFIX" ]]; then
  git -C "$GIT_ROOT" archive "HEAD:${PREFIX%/}" | tar -x -C "$DEST"
else
  git -C "$ROOT" archive HEAD | tar -x -C "$DEST"
fi
if [[ -e "$DEST/apps/vinci-backend" || -e "$DEST/apps/vinci-frontend" || -e "$DEST/apps/leonardo" ]]; then
  echo "clone-smoke leaked Platform apps into the archive; expected the OSS subtree only" >&2
  exit 1
fi
cd "$DEST"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
make install
python -m vinci_harness demo
python -c '
import json, os, sys
from pathlib import Path
from struct import unpack
from vinci_runtime.engine import Engine
home = Path(os.environ["VINCI_HOME"])
engine = Engine(home)
run = engine.start_run("@tryvinci/image-generate", {"prompt": "clone smoke cube"})
need = ("asset_uris", "job_uris", "receipt_uris")
missing = [k for k in need if not run.get(k)]
if run.get("state") != "completed" or (run.get("estimate") or {}).get("total") != 0 or missing:
    print(json.dumps(run, default=str)[:2000], file=sys.stderr)
    raise SystemExit("clone smoke failed: expected completed $0 run with vinci:// URIs")
digest = run["outputs"][0]
blob = engine.cas.get(digest)
width, height = unpack(">II", blob[16:24])
if width != 960 or height != 540:
    raise SystemExit(f"clone smoke failed: expected 960x540 PNG, got {width}x{height}")
print(json.dumps({
    "state": run["state"],
    "total": run["estimate"]["total"],
    "asset_uris": run["asset_uris"],
    "job_uris": run["job_uris"],
    "receipt_uris": run["receipt_uris"],
    "png_ihdr": [width, height],
    "live_usd": 0,
}, indent=2))
'
PORT="${VINCI_CLONE_SMOKE_PORT:-14310}"
MCP_PORT="${VINCI_CLONE_SMOKE_MCP_PORT:-$((PORT + 1))}"
export VINCI_DAEMON_URL="http://127.0.0.1:${PORT}"
export VINCI_DAEMON_PORT="$PORT"
python -m vinci_mcp.mock_server --host 127.0.0.1 --port "$MCP_PORT" >"$DEST/mcp-mock.log" 2>&1 &
MCP_PID=$!
python -m vinci_daemon --host 127.0.0.1 --port "$PORT" >"$DEST/daemon.log" 2>&1 &
DAEMON_PID=$!
cleanup() { kill "$DAEMON_PID" "$MCP_PID" 2>/dev/null || true; }
trap cleanup EXIT
ok=0
for _ in $(seq 1 50); do
  if curl -sf "$VINCI_DAEMON_URL/healthz" >/dev/null; then ok=1; break; fi
  sleep 0.1
done
if [[ "$ok" != 1 ]]; then
  echo "clone-smoke daemon failed to start" >&2
  cat "$DEST/daemon.log" >&2
  exit 1
fi
ok_mcp=0
for _ in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:${MCP_PORT}/healthz" >/dev/null; then ok_mcp=1; break; fi
  sleep 0.1
done
if [[ "$ok_mcp" != 1 ]]; then
  echo "clone-smoke mock MCP failed to start" >&2
  cat "$DEST/mcp-mock.log" >&2
  exit 1
fi
./scripts/vinci init --demo
CLI_OUT="$(./scripts/vinci run @tryvinci/image-generate --input '{"prompt":"clone smoke cli"}')"
printf '%s\n' "$CLI_OUT"
ASSET_ID="$(printf '%s\n' "$CLI_OUT" | sed -n 's|^vinci://assets/||p' | head -1)"
if [[ -z "$ASSET_ID" ]]; then
  echo "clone-smoke CLI missing vinci://assets URI" >&2
  exit 1
fi
curl -sf "$VINCI_DAEMON_URL/assets/${ASSET_ID}/file" -o "$DEST/swatch.png"
python -c '
import struct, sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
if not data.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("clone smoke CLI asset is not a PNG")
width, height = struct.unpack(">II", data[16:24])
if (width, height) != (960, 540):
    raise SystemExit(f"clone smoke CLI expected 960x540 PNG, got {width}x{height}")
print("cli_png_ihdr", width, height)
' "$DEST/swatch.png"
CLI_VIDEO="$(./scripts/vinci run @tryvinci/video-generate --input '{"prompt":"clone smoke video"}')"
printf '%s\n' "$CLI_VIDEO"
VIDEO_ID="$(printf '%s\n' "$CLI_VIDEO" | sed -n 's|^vinci://assets/||p' | head -1)"
if [[ -z "$VIDEO_ID" ]]; then
  echo "clone-smoke CLI missing video vinci://assets URI" >&2
  exit 1
fi
curl -sf "$VINCI_DAEMON_URL/assets/${VIDEO_ID}/file" -o "$DEST/swatch.mp4"
python -c '
import sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
if data[4:8] != b"ftyp":
    raise SystemExit("clone smoke CLI expected an MP4 ftyp box")
from vinci_provider_sdk.mock import mp4_dimensions, mp4_duration_seconds
wh = mp4_dimensions(data)
if wh != (960, 540):
    raise SystemExit(f"clone smoke CLI expected 960x540 MP4, got {wh}")
seconds = mp4_duration_seconds(data)
if seconds is None or seconds < 4.5 or seconds > 5.5:
    raise SystemExit(f"clone smoke CLI expected ~5s MP4, got {seconds}")
print("cli_mp4_ftyp", data[4:8].decode("ascii"), "size", wh, "bytes", len(data), "seconds", round(seconds, 3))
' "$DEST/swatch.mp4"
RECEIPT_ID="$(printf '%s\n' "$CLI_OUT" | sed -n 's|^vinci://receipts/||p' | head -1)"
if [[ -z "$RECEIPT_ID" ]]; then
  echo "clone-smoke CLI missing vinci://receipts URI" >&2
  exit 1
fi
curl -sf "$VINCI_DAEMON_URL/receipts/${RECEIPT_ID}" -o "$DEST/receipt.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
if body.get("computed_cost") != 0:
    raise SystemExit("clone smoke receipt cost %s" % body.get("computed_cost"))
if not str(body.get("uri", "")).startswith("vinci://receipts/"):
    raise SystemExit("clone smoke receipt missing vinci://receipts URI")
print("cli_receipt_cost", body["computed_cost"], body["uri"])
' "$DEST/receipt.json"
# Cost engine: estimate → awaiting_approval → approve → $0 receipt (mock total is 0, so max_cost -0.01 parks).
PARK_OUT="$(./scripts/vinci run @tryvinci/image-generate --input '{"prompt":"clone smoke park"}' --max-cost -0.01)"
printf '%s\n' "$PARK_OUT" | tee "$DEST/park-run.txt"
PARK_ID="$(printf '%s\n' "$PARK_OUT" | sed -n 's|^vinci jobs approve ||p' | head -1)"
if [[ -z "$PARK_ID" ]]; then
  echo "clone-smoke park missing vinci jobs approve run id" >&2
  exit 1
fi
python -c '
import json, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
if "awaiting approval" not in text:
    raise SystemExit("clone smoke park missing awaiting approval")
start = text.find("\n{")
body = json.loads(text[start + 1 :] if start >= 0 else text[text.find("{") :])
if body.get("state") != "awaiting_approval" or body.get("id") != sys.argv[2]:
    raise SystemExit("clone smoke park failed: %s" % body)
print("parked", body["id"], body.get("awaiting_reason"))
' "$DEST/park-run.txt" "$PARK_ID"
./scripts/vinci jobs approve "$PARK_ID" | tee "$DEST/approve-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
uris = body.get("receipt_uris") or []
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0:
    raise SystemExit("clone smoke approve failed: %s" % body)
if not uris or not str(uris[0]).startswith("vinci://receipts/"):
    raise SystemExit("clone smoke approve missing receipt URI")
print("approved", body["state"], body["estimate"]["total"], uris[0])
' "$DEST/approve-run.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/image-generate","inputs":{"prompt":"clone smoke http"}}' \
  -o "$DEST/http-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0:
    raise SystemExit("clone smoke POST /runs failed: %s" % body)
uris = body.get("receipt_uris") or []
if not uris or not str(uris[0]).startswith("vinci://receipts/"):
    raise SystemExit("clone smoke POST /runs missing receipt URI")
print("http_run", body["state"], body["estimate"]["total"], uris[0])
' "$DEST/http-run.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/image-generate","inputs":{"prompt":"clone smoke portrait","aspect_ratio":"9:16"}}' \
  -o "$DEST/portrait-run.json"
python -c '
import json, struct, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0:
    raise SystemExit("clone smoke 9:16 run failed: %s" % body)
digest = (body.get("outputs") or [None])[0]
print("portrait_run", body["state"], digest)
' "$DEST/portrait-run.json"
PORTRAIT_ID="$(python -c 'import json,sys; from pathlib import Path; print((json.loads(Path(sys.argv[1]).read_text()).get("outputs") or [""])[0])' "$DEST/portrait-run.json")"
curl -sf "$VINCI_DAEMON_URL/assets/${PORTRAIT_ID}/file" -o "$DEST/portrait.png"
python -c '
import struct, sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
if not data.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("clone smoke 9:16 asset is not a PNG")
width, height = struct.unpack(">II", data[16:24])
if (width, height) != (540, 960):
    raise SystemExit(f"clone smoke 9:16 expected 540x960 PNG, got {width}x{height}")
print("portrait_png_ihdr", width, height)
' "$DEST/portrait.png"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/image-generate","inputs":{"prompt":"clone smoke portrait","aspect_ratio":"9:16","camera":"handheld","lens":"50mm","look":"noir"}}' \
  -o "$DEST/optical-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0:
    raise SystemExit("clone smoke optical run failed: %s" % body)
print("optical_run", body["state"], (body.get("outputs") or [None])[0])
' "$DEST/optical-run.json"
OPTICAL_ID="$(python -c 'import json,sys; from pathlib import Path; print((json.loads(Path(sys.argv[1]).read_text()).get("outputs") or [""])[0])' "$DEST/optical-run.json")"
curl -sf "$VINCI_DAEMON_URL/assets/${OPTICAL_ID}/file" -o "$DEST/optical.png"
python -c '
import sys
from pathlib import Path
plain = Path(sys.argv[1]).read_bytes()
optic = Path(sys.argv[2]).read_bytes()
if plain == optic:
    raise SystemExit("clone smoke optical PNG matched the plain 9:16 still")
print("optical_png_diff", len(optic))
' "$DEST/portrait.png" "$DEST/optical.png"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/product-reveal-5s","inputs":{"prompt":"clone smoke reveal"}}' \
  -o "$DEST/reveal-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 2:
    raise SystemExit("clone smoke product-reveal-5s failed: %s" % body)
print("product_reveal_5s", body["state"], body["estimate"]["total"], "jobs", len(jobs))
' "$DEST/reveal-run.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/cinema-still","inputs":{"prompt":"clone smoke cinema"}}' \
  -o "$DEST/cinema-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
nodes = body.get("nodes") or {}
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 3:
    raise SystemExit("clone smoke cinema-still failed: %s" % body)
if not (nodes.get("still") or {}).get("output") or not (nodes.get("motion") or {}).get("output"):
    raise SystemExit("clone smoke cinema-still missing per-node outputs: %s" % nodes)
print("cinema_still", body["state"], body["estimate"]["total"], "jobs", len(jobs), "nodes", sorted(nodes))
' "$DEST/cinema-run.json"
MOTION_ID="$(python -c 'import json,sys; from pathlib import Path; print((((json.loads(Path(sys.argv[1]).read_text()).get("nodes") or {}).get("motion") or {}).get("output") or ""))' "$DEST/cinema-run.json")"
curl -sf "$VINCI_DAEMON_URL/assets/${MOTION_ID}/file" -o "$DEST/cinema-motion.mp4"
python -c '
import sys
from pathlib import Path
from vinci_provider_sdk.mock import mp4_dimensions
data = Path(sys.argv[1]).read_bytes()
if data[4:8] != b"ftyp":
    raise SystemExit("clone smoke cinema motion expected an MP4 ftyp box")
wh = mp4_dimensions(data)
if wh != (960, 540):
    raise SystemExit(f"clone smoke cinema motion expected 960x540 MP4, got {wh}")
print("cinema_motion", *wh, "bytes", len(data))
' "$DEST/cinema-motion.mp4"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/still-to-talk","inputs":{"prompt":"clone smoke speak"}}' \
  -o "$DEST/talk-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
nodes = body.get("nodes") or {}
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 2:
    raise SystemExit("clone smoke still-to-talk failed: %s" % body)
if not (nodes.get("still") or {}).get("output") or not (nodes.get("talk") or {}).get("output"):
    raise SystemExit("clone smoke still-to-talk missing per-node outputs: %s" % nodes)
print("still_to_talk", body["state"], body["estimate"]["total"], "jobs", len(jobs), "nodes", sorted(nodes))
' "$DEST/talk-run.json"
curl -sf "$VINCI_DAEMON_URL/templates" -o "$DEST/templates.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
ids = {row.get("id") for row in body.get("templates") or []}
need = {"cinema-sequence", "first-last-frame", "speak-selfie", "speak-podcast", "speak-car", "soul-character"}
if not need <= ids:
    raise SystemExit("clone smoke templates missing %s" % (need - ids))
selfie = next(row for row in body["templates"] if row["id"] == "speak-selfie")
if selfie.get("page") != "speak" or (selfie.get("defaults") or {}).get("scene") != "selfie":
    raise SystemExit("clone smoke speak-selfie defaults: %s" % selfie)
print("templates", len(ids), "includes", sorted(need))
' "$DEST/templates.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/cinema-sequence","inputs":{"prompt":"clone smoke popcorn sequence"}}' \
  -o "$DEST/sequence-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
nodes = body.get("nodes") or {}
need = ("establish", "coverage", "close", "reverse")
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 4:
    raise SystemExit("clone smoke cinema-sequence failed: %s" % body)
if any(not (nodes.get(nid) or {}).get("output") for nid in need):
    raise SystemExit("clone smoke cinema-sequence missing per-node outputs: %s" % nodes)
print("cinema_sequence", body["state"], body["estimate"]["total"], "jobs", len(jobs), "nodes", sorted(nodes))
' "$DEST/sequence-run.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/first-last-frame","inputs":{"prompt":"clone smoke first last frame","duration":5}}' \
  -o "$DEST/flf-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
nodes = body.get("nodes") or {}
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 3:
    raise SystemExit("clone smoke first-last-frame failed: %s" % body)
if not (nodes.get("first") or {}).get("output") or not (nodes.get("motion") or {}).get("output"):
    raise SystemExit("clone smoke first-last-frame missing per-node outputs: %s" % nodes)
print("first_last_frame", body["state"], body["estimate"]["total"], "jobs", len(jobs), "nodes", sorted(nodes))
' "$DEST/flf-run.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/still-to-talk","inputs":{"prompt":"clone smoke selfie","scene":"selfie","aspect_ratio":"9:16"}}' \
  -o "$DEST/selfie-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
nodes = body.get("nodes") or {}
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 2:
    raise SystemExit("clone smoke speak selfie failed: %s" % body)
if not (nodes.get("still") or {}).get("output") or not (nodes.get("talk") or {}).get("output"):
    raise SystemExit("clone smoke speak selfie missing per-node outputs: %s" % nodes)
print("speak_selfie", body["state"], body["estimate"]["total"], "jobs", len(jobs))
' "$DEST/selfie-run.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@tryvinci/soul-character","inputs":{"prompt":"clone smoke soul character","lighting":"studio"}}' \
  -o "$DEST/soul-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
nodes = body.get("nodes") or {}
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 2:
    raise SystemExit("clone smoke soul-character failed: %s" % body)
sheet = (nodes.get("sheet") or {}).get("output")
lock = (nodes.get("lock") or {}).get("output")
if not sheet or not lock or sheet == lock:
    raise SystemExit("clone smoke soul-character missing distinct sheet/lock: %s" % nodes)
print("soul_character", body["state"], body["estimate"]["total"], "jobs", len(jobs))
' "$DEST/soul-run.json"
curl -sf -X POST "$VINCI_DAEMON_URL/mcp" \
  -H "content-type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"vinci.image_generate","arguments":{"prompt":"clone smoke mcp","max_cost":1}}}' \
  -o "$DEST/mcp-call.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
text = (((body.get("result") or {}).get("content") or [{}])[0]).get("text") or ""
if "completed" not in text or "vinci://assets/" not in text or "vinci://receipts/" not in text:
    raise SystemExit("clone smoke MCP failed: %s" % text[:2000])
print("mcp_image_generate ok")
' "$DEST/mcp-call.json"
curl -sf -X POST "$VINCI_DAEMON_URL/mcp" \
  -H "content-type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"vinci.video_generate","arguments":{"prompt":"clone smoke mcp video","max_cost":1}}}' \
  -o "$DEST/mcp-video-call.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
text = (((body.get("result") or {}).get("content") or [{}])[0]).get("text") or ""
if "completed" not in text or "vinci://assets/" not in text or "vinci://receipts/" not in text:
    raise SystemExit("clone smoke MCP video failed: %s" % text[:2000])
print("mcp_video_generate ok")
' "$DEST/mcp-video-call.json"
python -c '
import json
from pathlib import Path
from vinci_media.ops import make_fixture_video
media = make_fixture_video(Path("podcast.mp4"), duration=3.0)
Path("podcast-run-req.json").write_text(json.dumps({
    "skill": "@tryvinci/podcast-to-shorts",
    "inputs": {"media": str(media.resolve()), "query": "pricing"},
}))
print("fixture_podcast", media)
'
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d @"$DEST/podcast-run-req.json" \
  -o "$DEST/podcast-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
jobs = body.get("job_ids") or []
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0 or len(jobs) != 5:
    raise SystemExit("clone smoke podcast-to-shorts failed: %s" % body)
print("podcast_to_shorts", body["state"], body["estimate"]["total"], "jobs", len(jobs))
' "$DEST/podcast-run.json"
./scripts/vinci skills add "$DEST/tests/fixtures/skills/stamp-text"
./scripts/vinci skills add "$DEST/tests/fixtures/skills/stamp-video"
curl -sf "$VINCI_DAEMON_URL/skills" -o "$DEST/skills.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
ids = {s.get("id") for s in body.get("skills") or []}
need = {"@example/stamp-text", "@example/stamp-video"}
if not need <= ids:
    raise SystemExit("clone smoke skill installs missing %s in %s" % (need - ids, sorted(ids)))
print("skills_installed", len(ids), "includes", sorted(need))
' "$DEST/skills.json"
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d '{"skill":"@example/stamp-text","inputs":{"prompt":"installed cube"}}' \
  -o "$DEST/stamp-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0:
    raise SystemExit("clone smoke installed skill failed: %s" % body)
print("stamp_text", body["state"], body["estimate"]["total"])
' "$DEST/stamp-run.json"
STUDIO_CLI="$(./scripts/vinci studio --html --no-open)"
printf '%s\n' "$STUDIO_CLI"
printf '%s\n' "$STUDIO_CLI" | grep -q "/studio"
curl -sf "$VINCI_DAEMON_URL/studio" -o "$DEST/studio.html"
python -c '
import sys
from pathlib import Path
body = Path(sys.argv[1]).read_text()
need = ("Vinci Studio", "Explore", "Canvas", "Templates", "Timeline", "Skills", "Cost report", "Find", "Speak", "Bring your own keys", "New connector", "connector-mark", "connect-select", "Named MCP", "Supercomputer", "Collab", "Upscale still", "Higgsfield", "Magnific", "Magnific / Freepik", "Custom MCP", "compose-gallery", "model-card", "aspect-pills", "duration-pills", "first-frame", "camera-pills", "lens-pills", "look-pills", "lighting-pills", "palette-pills", "motion-pills", "aperture-pills", "add-shot", "creativity", "resemblance", "optimized-pills", "cast-pills", "element-kind-pills", "image_urls", "Generate this node", "Generate graph", "Play timeline", "node-model", "Cinema stack", "/assets/${a.id}/file", "vinci://assets/", "run.nodes", "fillDrawer", "t.defaults", "t.page || \"canvas\"", "Speak scenes open Speak", "Skip for now", "vinci-onboard-v1", "Inter Tight", "Instrument Serif", "Your Brand\u0027s Superagency")
missing = [item for item in need if item not in body]
if missing:
    raise SystemExit("clone smoke Studio missing %s" % missing)
print("studio_html ok")
' "$DEST/studio.html"
python -c '
from pathlib import Path
page = Path("apps/studio/app/page.tsx").read_text()
if "iframe" in page:
    raise SystemExit("clone smoke TS Studio still iframes daemon HTML")
client = Path("apps/studio/app/studio-client.tsx").read_text()
need = ("vinci-api", "Play timeline", "Generate this node", "Cinema stack", "motion", "cast-pills", "first-frame", "Bring your own keys", "New connector", "connector-mark", "connect-select", "Named MCP", "Supercomputer", "Collab", "Custom MCP", "data-port", "vinci://assets/", "Start generating", "aperture-pills", "lighting-pills", "palette-pills", "image_urls", "add-shot", "creativity", "optimized-pills", "element-kind-pills", "t.defaults", "t.page || \"canvas\"", "Speak scenes open Speak", "Skip for now", "vinci-onboard-v1", "Your Brand\u0027s Superagency")
missing = [item for item in need if item not in client]
if missing:
    raise SystemExit("clone smoke TS Studio missing %s" % missing)
print("studio_ts ok")
'
curl -sf "$VINCI_DAEMON_URL/find?q=pricing" -o "$DEST/find.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
hits = body.get("hits") or []
if not hits:
    raise SystemExit("clone smoke vinci find returned no hits: %s" % body)
print("find_pricing hits", len(hits))
' "$DEST/find.json"
./scripts/vinci providers add mcp --from-env MCP_API_KEY --url "http://127.0.0.1:${MCP_PORT}/mcp"
python -c '
import json
from pathlib import Path
Path("mcp-run-req.json").write_text(json.dumps({
    "workflow": {
        "id": "mcp-png",
        "version": "0.1.0",
        "nodes": [{
            "id": "generate",
            "type": "generate",
            "capability": "t2i",
            "model_id": "mcp:png:v1",
            "params": {"prompt": "clone smoke external mcp"},
        }],
        "edges": [],
    },
    "inputs": {"prompt": "clone smoke external mcp"},
}))
'
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d @"$DEST/mcp-run-req.json" \
  -o "$DEST/mcp-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0:
    raise SystemExit("clone smoke external MCP failed: %s" % body)
nodes = ((body.get("estimate") or {}).get("nodes") or [{}])
if (nodes[0] or {}).get("model_id") != "mcp:png:v1":
    raise SystemExit("clone smoke external MCP routed %s" % nodes)
print("mcp_provider", body["state"], body["estimate"]["total"], nodes[0]["model_id"])
' "$DEST/mcp-run.json"
MCP_ASSET="$(python -c 'import json,sys; print(((json.load(open(sys.argv[1])).get("asset_uris") or [""])[0]).removeprefix("vinci://assets/"))' "$DEST/mcp-run.json")"
if [[ -z "$MCP_ASSET" ]]; then
  echo "clone-smoke external MCP missing asset URI" >&2
  exit 1
fi
curl -sf "$VINCI_DAEMON_URL/assets/${MCP_ASSET}/file" -o "$DEST/mcp-swatch.png"
python -c '
import struct, sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
if not data.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("clone smoke external MCP asset is not a PNG")
width, height = struct.unpack(">II", data[16:24])
if (width, height) != (960, 540):
    raise SystemExit(f"clone smoke external MCP expected 960x540 PNG, got {width}x{height}")
print("mcp_png_ihdr", width, height)
' "$DEST/mcp-swatch.png"
python -c '
import json
from pathlib import Path
Path("mcp-video-run-req.json").write_text(json.dumps({
    "workflow": {
        "id": "mcp-mp4",
        "version": "0.1.0",
        "nodes": [{
            "id": "generate",
            "type": "generate",
            "capability": "t2v",
            "model_id": "mcp:mp4:v1",
            "params": {"prompt": "clone smoke external mcp video"},
        }],
        "edges": [],
    },
    "inputs": {"prompt": "clone smoke external mcp video"},
}))
'
curl -sf -X POST "$VINCI_DAEMON_URL/runs" \
  -H "content-type: application/json" \
  -d @"$DEST/mcp-video-run-req.json" \
  -o "$DEST/mcp-video-run.json"
python -c '
import json, sys
from pathlib import Path
body = json.loads(Path(sys.argv[1]).read_text())
if body.get("state") != "completed" or (body.get("estimate") or {}).get("total") != 0:
    raise SystemExit("clone smoke external MCP video failed: %s" % body)
nodes = ((body.get("estimate") or {}).get("nodes") or [{}])
if (nodes[0] or {}).get("model_id") != "mcp:mp4:v1":
    raise SystemExit("clone smoke external MCP video routed %s" % nodes)
print("mcp_provider_video", body["state"], body["estimate"]["total"], nodes[0]["model_id"])
' "$DEST/mcp-video-run.json"
MCP_VIDEO="$(python -c 'import json,sys; print(((json.load(open(sys.argv[1])).get("asset_uris") or [""])[0]).removeprefix("vinci://assets/"))' "$DEST/mcp-video-run.json")"
if [[ -z "$MCP_VIDEO" ]]; then
  echo "clone-smoke external MCP video missing asset URI" >&2
  exit 1
fi
curl -sf "$VINCI_DAEMON_URL/assets/${MCP_VIDEO}/file" -o "$DEST/mcp-swatch.mp4"
python -c '
import sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
if data[4:8] != b"ftyp":
    raise SystemExit("clone smoke external MCP expected an MP4 ftyp box")
from vinci_provider_sdk.mock import mp4_dimensions
wh = mp4_dimensions(data)
if wh != (960, 540):
    raise SystemExit(f"clone smoke external MCP expected 960x540 MP4, got {wh}")
print("mcp_mp4_ftyp", data[4:8].decode("ascii"), "size", wh, "bytes", len(data))
' "$DEST/mcp-swatch.mp4"
echo "clone-smoke ok dest=$DEST live_usd=0"
