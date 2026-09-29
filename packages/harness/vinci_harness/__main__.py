from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from struct import unpack
from typing import Any

from vinci_harness import __version__

USAGE = """vinci-harness {version}

Meta-package for Vinci OSS (unpublished). Do not npx @tryvinci/cli from the registry yet.

  python3 -m venv .venv && source .venv/bin/activate
  make install
  python3 -m vinci_harness demo
  python3 -m vinci_daemon --host 127.0.0.1 --port 4310
  ./scripts/vinci init --demo
  ./scripts/vinci run @tryvinci/image-generate --input '{{"prompt":"a red cube"}}'
"""


def run_demo(home: Path | None = None) -> dict[str, Any]:
    from vinci_runtime.engine import Engine

    target = home or Path(os.environ.get("VINCI_HOME") or (Path.home() / ".vinci"))
    engine = Engine(target)
    engine.init_home(demo=True)
    prompt = {"prompt": "a red cube"}
    result = engine.start_run("@tryvinci/image-generate", prompt)
    job_ids = result.get("job_ids") or []
    job = engine.store.get_job(job_ids[0]) if job_ids else None
    receipt = job.receipt if job is not None else None
    nodes = (result.get("estimate") or {}).get("nodes") or []
    outputs = result.get("outputs") or []
    width, height = (0, 0)
    if outputs:
        blob = engine.cas.get(outputs[0])
        width, height = unpack(">II", blob[16:24])
    replay = engine.start_run("@tryvinci/image-generate", prompt)
    replay_ids = replay.get("job_ids") or []
    replay_job = engine.store.get_job(replay_ids[0]) if replay_ids else None
    replay_receipt = replay_job.receipt if replay_job is not None else None
    payload = {
        "home": str(engine.config.home),
        "state": result.get("state"),
        "skill": result.get("skill"),
        "total": (result.get("estimate") or {}).get("total"),
        "model_id": nodes[0]["model_id"] if nodes else None,
        "outputs": outputs,
        "asset_uris": result.get("asset_uris") or [],
        "job_uris": result.get("job_uris") or [],
        "asset_uri": f"vinci://assets/{outputs[0]}" if outputs else None,
        "job_uri": f"vinci://jobs/{job.id}" if job is not None else None,
        "receipt_uri": f"vinci://receipts/{job.id}" if job is not None else None,
        "computed_cost": receipt.computed_cost if receipt is not None else None,
        "cached": receipt.cached if receipt is not None else None,
        "replay_cached": replay_receipt.cached if replay_receipt is not None else None,
        "replay_cost": replay_receipt.computed_cost if replay_receipt is not None else None,
        "replay_outputs": list(replay_job.outputs) if replay_job is not None else [],
        "png_ihdr": [width, height],
        "live_usd": 0,
    }
    print(json.dumps(payload, indent=2, default=str))
    if payload["state"] != "completed" or receipt is None or receipt.computed_cost != 0:
        raise SystemExit("demo failed: expected completed run with $0 receipt")
    if not outputs:
        raise SystemExit("demo failed: missing generated asset")
    if not payload["asset_uri"] or not payload["job_uri"] or not payload["receipt_uri"]:
        raise SystemExit("demo failed: missing vinci:// asset/job/receipt URIs")
    if width != 960 or height != 540:
        raise SystemExit(f"demo failed: expected 960x540 PNG, got {width}x{height}")
    if replay.get("state") != "completed" or replay_job is None or replay_receipt is None:
        raise SystemExit("demo failed: CAS replay did not complete")
    if replay_receipt.cached is not True or replay_receipt.computed_cost != 0:
        raise SystemExit("demo failed: CAS replay must be cached at $0")
    if list(replay_job.outputs) != list(outputs):
        raise SystemExit("demo failed: CAS replay returned different outputs")
    return payload


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"demo", "--demo"}:
        run_demo()
        return
    print(USAGE.format(version=__version__).rstrip())


if __name__ == "__main__":
    main()
