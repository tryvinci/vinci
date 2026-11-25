"""Vinci's authored MCP tools, served by the local daemon at ``POST /mcp``.

The tool names and argument names match the hosted Studio server
(``apps/vinci-backend/services/studio_mcp.py``), so one agent setup works local and hosted.
One difference: ``max_cost`` here is USD; the hosted server takes ``max_credits``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from vinci_core.redact import redact_mapping
from vinci_protocol.models import WorkflowSpec
from vinci_runtime.engine import Engine

from vinci_mcp import olf_tools

log = logging.getLogger("vinci.mcp")

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")  # newest first
INSTRUCTIONS = (
    "Vinci makes images and videos on this computer with the person's provider keys. "
    "Price a run first with vinci.cost_estimate (USD). Start it with vinci.image_generate, "
    "vinci.video_generate or vinci.workflow_run. Then poll vinci.jobs_get with the run_id "
    "until the state is completed or failed. A run over max_cost or the person's budget "
    "waits for their approval: the tool result gives the price and the approve command to "
    "show them. You cannot approve spend yourself."
)

TOOL_NAMES = (
    "vinci.models_list",
    "vinci.skills_search",
    "vinci.image_generate",
    "vinci.video_generate",
    "vinci.media_inspect",
    "vinci.workflow_run",
    "vinci.jobs_get",
    "vinci.jobs_cancel",
    "vinci.cost_estimate",
    "vinci.presets_list",
    "vinci.adapts_run",
    "vinci.batch_status",
    *olf_tools.NAMES,  # the OLF movie engine, when vinci-olf is installed
)

_TOOL_DESCRIPTIONS = {
    "vinci.models_list": "List catalog models and whether a key makes them available.",
    "vinci.skills_search": "Search first-party skills by task, tag, or id.",
    "vinci.image_generate": (
        "Start an image run (@tryvinci/image-generate). Returns the run: poll vinci.jobs_get with "
        "its id until the state is completed or failed."
    ),
    "vinci.video_generate": (
        "Start a video run (@tryvinci/video-generate). Returns the run: poll vinci.jobs_get with "
        "its id every 10-20 s until the state is completed or failed."
    ),
    "vinci.media_inspect": "Inspect a vinci://assets/{id} object (metadata only).",
    "vinci.workflow_run": "Run a skill id or an inline WorkflowSpec. Returns the run.",
    "vinci.jobs_get": "Read a run (state, outputs, asset_uris) by run_id, or a job by job_id.",
    "vinci.jobs_cancel": "Cancel a run.",
    "vinci.cost_estimate": "Price a skill in USD without starting it. Free.",
    "vinci.presets_list": "List generic, partner, and custom adapt presets.",
    "vinci.adapts_run": "Adapt one asset or source URL through preset ids. Returns a batch_id.",
    "vinci.batch_status": "Status, outputs, and per-preset checks for an adapt batch.",
    **olf_tools.DESCRIPTIONS,
}

MUTATING_TOOLS = frozenset(
    {
        "vinci.image_generate",
        "vinci.video_generate",
        "vinci.workflow_run",
        "vinci.adapts_run",
        "vinci.jobs_cancel",
    }
)

_DEFERRED_EXEC_TOOLS = frozenset(
    {
        "vinci.image_generate",
        "vinci.video_generate",
        "vinci.workflow_run",
        "vinci.adapts_run",
    }
)


_ARG_SPECS: dict[str, dict[str, Any]] = {
    "prompt": {"type": "string", "description": "What to make. It fills inputs.prompt."},
    "model_id": {
        "type": "string",
        "description": "A model id from vinci.models_list. Empty: the route picks the model.",
    },
    "inputs": {
        "type": "object",
        "description": "Skill inputs, for example aspect_ratio, resolution, duration (seconds).",
    },
    "max_cost": {
        "type": "number",
        "description": "USD this run may spend (the hosted server takes max_credits). Over it, "
        "the run waits for the person's approval.",
    },
    "skill": {"type": "string", "description": "A skill id from vinci.skills_search."},
    "workflow": {"type": "object", "description": "An inline WorkflowSpec, in place of skill."},
    "preference": {
        "type": "string",
        "enum": ["cheapest", "fastest", "quality"],
        "description": "How the route picks a model. Empty: the skill's preference.",
    },
    "query": {"type": "string", "description": "Words to match: a task, a tag or an id."},
    "run_id": {"type": "string", "description": "The id a run tool returned."},
    "job_id": {"type": "string", "description": "A provider job id from a run's job_ids."},
    "uri": {"type": "string", "description": "vinci://assets/{id}, or the asset id."},
    "asset_id": {"type": "string", "description": "The asset to adapt (or give source_url)."},
    "source_url": {"type": "string", "description": "A link to the media to adapt."},
    "preset_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Preset ids from vinci.presets_list.",
    },
    "batch_id": {"type": "string", "description": "The id vinci.adapts_run returned."},
}
_RUN = ("prompt", "model_id", "inputs", "max_cost")
# Per tool: (its arguments, the required ones).
_ARGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "vinci.skills_search": (("query",), ()),
    "vinci.image_generate": (_RUN, ("prompt",)),
    "vinci.video_generate": (_RUN, ("prompt",)),
    "vinci.workflow_run": (("skill", "workflow", *_RUN, "preference"), ()),
    "vinci.jobs_get": (("run_id", "job_id"), ()),
    "vinci.jobs_cancel": (("run_id",), ("run_id",)),
    "vinci.media_inspect": (("uri",), ("uri",)),
    "vinci.cost_estimate": (("skill", *_RUN), ()),
    "vinci.adapts_run": (("asset_id", "source_url", "preset_ids"), ("preset_ids",)),
    "vinci.batch_status": (("batch_id",), ("batch_id",)),
}


def tool_schemas() -> list[dict[str, Any]]:
    """The ``tools/list`` rows: each tool with a described JSON Schema of its arguments."""
    tools: list[dict[str, Any]] = []
    for name in TOOL_NAMES:
        if name in olf_tools.NAMES:
            schema = olf_tools.schema(name)
        else:
            props, required = _ARGS.get(name, ((), ()))
            schema = {"type": "object", "properties": {k: _ARG_SPECS[k] for k in props}}
            if required:
                schema["required"] = list(required)
        tools.append({"name": name, "description": _TOOL_DESCRIPTIONS[name], "inputSchema": schema})
    return tools


def call_tool(
    engine: Engine,
    name: str,
    arguments: dict[str, Any],
    *,
    operation_id: str | None = None,
) -> dict[str, Any]:
    secrets = engine.resolver.known_values(
        [
            "MOCK_API_KEY",
            "WAVESPEED_API_KEY",
            "GEMINI_API_KEY",
            "FAL_KEY",
            "ELEVENLABS_API_KEY",
            "CLOUDFLARE_API_TOKEN",
        ]
    )
    args = redact_mapping(arguments, extra_values=secrets)
    if name not in TOOL_NAMES:
        raise KeyError(name)
    if name in olf_tools.NAMES:
        return olf_tools.call(engine, name, args)
    if name == "vinci.models_list":
        return {"models": engine.models()}
    if name == "vinci.skills_search":
        hits = engine.skills.search(str(args.get("query") or ""))
        return {"skills": [engine.skills.inspect(s.id) for s in hits]}
    if name == "vinci.cost_estimate":  # the hosted call names only model_id and inputs
        return engine.estimate_skill(
            str(args.get("skill") or _default_skill(engine, args.get("model_id"))),
            _inputs(args),
            max_cost=_max_cost(args),
            model_id=args.get("model_id"),
        )
    journal_deferred = getattr(engine, "_journal", None) is not None and bool(operation_id)
    if name == "vinci.image_generate":
        if journal_deferred:
            return engine.accept_run(
                "@tryvinci/image-generate",
                _inputs(args),
                max_cost=_max_cost(args),
                model_id=args.get("model_id"),
                operation_id=operation_id,
            )
        return engine.start_run(
            "@tryvinci/image-generate",
            _inputs(args),
            max_cost=_max_cost(args),
            model_id=args.get("model_id"),
        )
    if name == "vinci.video_generate":
        if journal_deferred:
            return engine.accept_run(
                "@tryvinci/video-generate",
                _inputs(args),
                max_cost=_max_cost(args),
                model_id=args.get("model_id"),
                operation_id=operation_id,
            )
        return engine.start_run(
            "@tryvinci/video-generate",
            _inputs(args),
            max_cost=_max_cost(args),
            model_id=args.get("model_id"),
        )
    if name == "vinci.workflow_run":
        workflow = args.get("workflow")
        spec = WorkflowSpec.model_validate(workflow) if workflow else None
        if journal_deferred:
            return engine.accept_run(
                args.get("skill"),
                _inputs(args),
                max_cost=_max_cost(args),
                preference=args.get("preference"),
                workflow=spec,
                model_id=args.get("model_id"),
                operation_id=operation_id,
            )
        return engine.start_run(
            args.get("skill"),
            _inputs(args),
            max_cost=_max_cost(args),
            preference=args.get("preference"),
            workflow=spec,
            model_id=args.get("model_id"),
        )
    if name == "vinci.jobs_get":  # the run tools return a run id, so read runs first
        ref = _need(args, name, "run_id", "job_id")
        job = None if args.get("run_id") else engine.store.get_job(ref)
        found = job.model_dump(mode="json") if job is not None else engine.store.get_run(ref)
        if found is None:
            raise ValueError(f"No run or job has the id {ref}. Use the id a run tool returned.")
        redacted = redact_mapping(found, extra_values=secrets)
        return redacted if isinstance(redacted, dict) else dict(found)
    if name == "vinci.jobs_cancel":
        return engine.cancel_run(_need(args, name, "run_id"))
    if name == "vinci.media_inspect":
        uri = str(args.get("uri") or args.get("id") or "")
        asset_id = uri.removeprefix("vinci://assets/")
        asset = engine.store.get_asset(asset_id)
        if asset is None:
            raise KeyError(uri)
        dumped = asset.model_dump(mode="json")
        redacted = redact_mapping(dumped, extra_values=secrets)
        return redacted if isinstance(redacted, dict) else dumped
    if name == "vinci.presets_list":
        return {"presets": engine.adapt_presets()}
    if name == "vinci.adapts_run":
        item: dict[str, Any] = {"preset_ids": list(args.get("preset_ids") or [])}
        if args.get("asset_id"):
            item["asset_id"] = str(args["asset_id"])
        if args.get("source_url"):
            item["source_url"] = str(args["source_url"])
        return engine.start_adapt_batch([item], operation_id=operation_id)
    if name == "vinci.batch_status":
        return engine.adapt_batch_status(_need(args, name, "batch_id"))
    raise KeyError(name)


def _need(args: dict[str, Any], tool: str, *keys: str) -> str:
    """The first of ``keys`` the agent gave, or a ValueError that names them."""
    value = next((str(args[k]) for k in keys if args.get(k)), "")
    if not value:
        raise ValueError(f"Check the arguments: {tool} needs {' or '.join(keys)}.")
    return value


def _inputs(args: dict[str, Any]) -> dict[str, Any]:
    """The run inputs: ``inputs``, and a top-level ``prompt`` over ``inputs.prompt`` (as hosted).

    Bug fixed (first occurrence, 2026-11-24 code read, 0 user reports, COREPRODUC-775): with both
    ``prompt`` and ``inputs``, the prompt was dropped and the run had no prompt.
    """
    inputs = dict(args["inputs"]) if isinstance(args.get("inputs"), dict) else {}
    if args.get("prompt") is not None:
        inputs["prompt"] = args["prompt"]
    return inputs


def _default_skill(engine: Engine, model_id: Any) -> str:
    """The generate skill for a model: video-generate for a video model, else image-generate."""
    row = next((r for r in engine.models() if r["id"] == model_id), None) if model_id else None
    video = row is not None and {"t2v", "i2v"} & set(row["capabilities"])
    return "@tryvinci/video-generate" if video else "@tryvinci/image-generate"


def _next_step(result: dict[str, Any]) -> str | None:
    """What the agent does next with a run that waits for approval; None for other results.

    The agent cannot approve its own spend: only the person can, with the CLI (the Studio has no
    approve button yet, COREPRODUC-786).
    """
    if result.get("state") != "awaiting_approval":
        return None
    run_id, reason = result.get("id"), result.get("awaiting_reason") or "over the approval limit"
    return (
        f"Nothing ran and nothing was spent: run {run_id} waits for the person's approval "
        f"({reason}). Show them the price (estimate.total, USD). They approve it in a terminal "
        f"with: vinci jobs approve {run_id}. Or, when the reason is max_cost and they agree to the "
        "price, start the run again with a higher max_cost. Then poll vinci.jobs_get with run_id."
    )


def tool_failed(envelope: dict[str, Any]) -> bool:
    """True for a JSON-RPC error or a tool result with ``isError``: neither has run data."""
    return bool(envelope.get("error") or (envelope.get("result") or {}).get("isError"))


def _max_cost(args: dict[str, Any]) -> float | None:
    value = args.get("max_cost")
    return float(value) if value is not None else None


def handle_rpc(
    engine: Engine,
    message: dict[str, Any],
    *,
    operation_id: str | None = None,
) -> dict[str, Any] | None:
    method = message.get("method")
    rpc_id = message.get("id")
    if method is None or str(method).startswith("notifications/"):
        return None
    params = message.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "vinci", "version": "0.1.0"},
                "instructions": INSTRUCTIONS,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tool_schemas()}}
    if method == "tools/call":
        return _tools_call(engine, rpc_id, params, operation_id)
    if method == "resources/list":
        resources = []
        for job in engine.store.list_jobs():
            resources.append({"uri": f"vinci://jobs/{job.id}", "name": f"job {job.id}"})
        for asset in engine.store.list_assets():
            resources.append({"uri": f"vinci://assets/{asset.id}", "name": f"asset {asset.id}"})
        for receipt in engine.store.list_receipts():
            job_id = receipt.get("job_id")
            resources.append({"uri": f"vinci://receipts/{job_id}", "name": f"receipt {job_id}"})
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"resources": resources}}
    if method == "resources/read":
        uri = str((message.get("params") or {}).get("uri") or "")
        payload = _read_resource(engine, uri)
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(payload, default=str),
                    }
                ]
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32601, "message": "method not found"},
    }


def _tools_call(
    engine: Engine, rpc_id: Any, params: dict[str, Any], operation_id: str | None
) -> dict[str, Any]:
    """Run one tool. An unknown tool is a JSON-RPC error; a failed tool is an ``isError`` result.

    Bug fixed (first occurrence, 2026-11-24 code read, 0 user reports, COREPRODUC-775): every tool
    failure was JSON-RPC error -32000 ("KeyError: 'job_id'"), which MCP clients show as a protocol
    fault, not as a tool result the agent reads and acts on.
    """
    name, arguments = params.get("name"), params.get("arguments") or {}
    if name not in TOOL_NAMES:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32602, "message": f"Unknown tool: {name}. Call tools/list."},
        }
    try:
        if not isinstance(arguments, dict):
            raise ValueError("Check the arguments: arguments must be an object.")
        result = call_tool(engine, name, arguments, operation_id=operation_id)
    except ValueError as exc:  # a refused request: the sentence says what to change
        log.info("mcp_tool_refused tool=%s detail=%s", name, exc)
        return _tool_text(rpc_id, [str(exc)], error=True)
    except KeyError as exc:  # an id the store does not have
        log.info("mcp_tool_not_found tool=%s key=%s", name, exc)
        key = exc.args[0] if exc.args else exc
        text = f"Not found: {key}. Check the id (vinci.models_list lists the model ids)."
        return _tool_text(rpc_id, [text], error=True)
    except Exception as exc:  # noqa: BLE001 — a bug or a provider fault: log it, tell the agent
        log.exception("mcp_tool_failed tool=%s", name)
        text = f"Vinci could not run {name}: {type(exc).__name__}: {exc}. See the daemon log."
        return _tool_text(rpc_id, [text], error=True)
    texts = [json.dumps(result, default=str)]
    if hint := _next_step(result):
        log.info("mcp_run_awaiting_approval tool=%s run_id=%s", name, result.get("id"))
        texts.append(hint)  # content[0] stays the JSON: the journal rewrites only that block
    return _tool_text(rpc_id, texts)


def _tool_text(rpc_id: Any, texts: list[str], *, error: bool = False) -> dict[str, Any]:
    """A ``tools/call`` result envelope with one text block per entry."""
    result: dict[str, Any] = {"content": [{"type": "text", "text": t} for t in texts]}
    if error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _read_resource(engine: Engine, uri: str) -> dict[str, Any]:
    if uri.startswith("vinci://jobs/"):
        job = engine.store.get_job(uri.removeprefix("vinci://jobs/"))
        if job is None:
            raise KeyError(uri)
        return job.model_dump(mode="json")
    if uri.startswith("vinci://assets/"):
        asset = engine.store.get_asset(uri.removeprefix("vinci://assets/"))
        if asset is None:
            raise KeyError(uri)
        return asset.model_dump(mode="json")
    if uri.startswith("vinci://receipts/"):
        receipt = engine.store.get_receipt(uri.removeprefix("vinci://receipts/"))
        if receipt is None:
            raise KeyError(uri)
        return receipt.model_dump(mode="json")
    raise KeyError(uri)
