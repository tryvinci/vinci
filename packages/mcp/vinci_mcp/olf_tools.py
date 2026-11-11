"""MCP tools for the OLF movie engine (``vinci-olf``, Apache-2.0).

The tools are listed only when ``vinci_olf`` imports, as the daemon mounts ``/olf`` only then.
A show is a folder on this computer (``path``); the tools write only inside it. They write show
files, not daemon state, so the durable journal does not record them, and ``vinci.olf_render``
refuses to spend while the journal is on (as ``POST /olf/render`` does; COREPRODUC-545).
"""

from __future__ import annotations

import logging
from importlib.util import find_spec
from pathlib import Path
from typing import Any

log = logging.getLogger("vinci.mcp.olf")
AVAILABLE = find_spec("vinci_olf") is not None

DESCRIPTIONS = {
    "vinci.olf_validate": "Check an OLF show folder: schemas, references, assets, lock file.",
    "vinci.olf_resolve": "An OLF shot after its levels merge, with hashes, prompts and references.",
    "vinci.olf_status": "List an OLF show's takes: kind, status, and stale (calculated).",
    "vinci.olf_render": (
        "Render an OLF shot: keyframe (count 1-4), video or audio (dialogue). Plans first; a paid "
        "render runs only within max_cost. dry_run returns the plan and price only."
    ),
}
NAMES = tuple(DESCRIPTIONS) if AVAILABLE else ()

_PATH = {"type": "string", "description": "The show folder (it holds project.yaml)"}
_SHOT = {"type": "string", "description": "Shot ID, for example e02/s03/sh014"}
SCHEMAS: dict[str, dict[str, Any]] = {
    "vinci.olf_validate": {"path": _PATH},
    "vinci.olf_resolve": {"path": _PATH, "shot": _SHOT},
    "vinci.olf_status": {
        "path": _PATH,
        "prefix": {"type": "string", "description": "Only takes whose ID starts with this"},
    },
    "vinci.olf_render": {
        "path": _PATH,
        "shot": _SHOT,
        "kind": {"type": "string", "enum": ["keyframe", "video", "audio"]},
        "model_id": {"type": "string"},
        "count": {"type": "integer", "minimum": 1, "maximum": 4},
        "max_cost": {"type": "number", "description": "USD this call may spend"},
        "dry_run": {"type": "boolean"},
    },
}
REQUIRED = {"vinci.olf_validate": ["path"], "vinci.olf_status": ["path"]}


def schema(name: str) -> dict[str, Any]:
    """The JSON Schema of a tool's arguments."""
    required = REQUIRED.get(name, ["path", "shot"])
    return {"type": "object", "properties": SCHEMAS[name], "required": required}


def call(engine: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run an OLF tool.

    Raises:
        vinci_olf.OlfError: The show, the shot or the price stops the call. The MCP error
            envelope carries the engine's message, which is written for people.
    """
    from vinci_olf import OlfError, load, stale, validate

    p = load(Path(str(args.get("path") or "")).expanduser())
    if name == "vinci.olf_validate":
        issues = [{"level": i.level, "where": i.where, "message": i.message} for i in validate(p)]
        errors = sum(i["level"] == "error" for i in issues)
        return {
            "ok": not errors,
            "errors": errors,
            "warnings": len(issues) - errors,
            "issues": issues,
        }
    if name == "vinci.olf_resolve":
        from vinci_olf.api import shot_detail

        return shot_detail(p, str(args.get("shot") or ""))
    if name == "vinci.olf_status":
        cache: dict[str, Any] = {}
        prefix = str(args.get("prefix") or "")
        takes = [
            {
                "id": take_id,
                "kind": doc.data.get("kind"),
                "status": doc.data.get("status"),
                "stale": stale(p, take_id, cache),
            }
            for take_id, doc in sorted(p.of_kind("take").items())
            if take_id.startswith(prefix)
        ]
        return {"takes": takes, "count": len(takes)}
    if name != "vinci.olf_render":
        raise KeyError(name)
    from vinci_olf.render import render

    shot = str(args.get("shot") or "")
    opts = {
        "kind": str(args.get("kind") or "video"),
        "model": args.get("model_id"),
        "count": int(args.get("count") or 1),
        "engine": engine,
    }
    plan = render(p, shot, dry_run=True, **opts)
    if args.get("dry_run"):
        return plan
    if getattr(engine, "_journal", None) is not None:
        raise OlfError("OLF renders skip the durable journal: run with VINCI_DURABLE_JOURNAL=off")
    if plan["unpriced"]:  # no flat price: max_cost cannot bound it
        raise OlfError(
            f"{', '.join(plan['unpriced'])} has no flat price, so max_cost cannot bound it. "
            "Pick a priced model with model_id"
        )
    limit = args.get("max_cost")
    if plan["total"] > 0 and (limit is None or plan["total"] > float(limit)):
        raise OlfError(
            f"this render costs ${plan['total']:.2f}: pass max_cost of at least that to spend it"
        )
    log.info("olf render %s %s via MCP: plan $%.2f", shot, opts["kind"], plan["total"])
    # The price check above is this call's consent, so the render runs as with --yes, bounded by
    # max_cost in case the show changed after the plan.
    bound = float(limit) if limit is not None else 0.0
    return render(load(p.root), shot, yes=True, max_total=bound, **opts)
