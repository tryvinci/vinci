from __future__ import annotations

import json
from typing import Any

from vinci_core.redact import redact_mapping
from vinci_protocol.models import WorkflowSpec
from vinci_runtime.engine import Engine

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
)

_TOOL_DESCRIPTIONS = {
    "vinci.models_list": "List catalog models and whether a key makes them available.",
    "vinci.skills_search": "Search first-party skills by task, tag, or id.",
    "vinci.image_generate": "Run @tryvinci/image-generate. Honors max_cost.",
    "vinci.video_generate": "Run @tryvinci/video-generate. Honors max_cost.",
    "vinci.media_inspect": "Inspect a vinci://assets/{id} object (metadata only).",
    "vinci.workflow_run": "Run a skill id or WorkflowSpec. Honors max_cost.",
    "vinci.jobs_get": "Get a job by id.",
    "vinci.jobs_cancel": "Cancel a run (run_id) or no-op cancel of a provider job.",
    "vinci.cost_estimate": "Estimate a skill without submitting work.",
}

_SPEND_TOOLS = {"vinci.image_generate", "vinci.video_generate", "vinci.workflow_run"}


def tool_schemas() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for name in TOOL_NAMES:
        schema: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": True}
        if name in _SPEND_TOOLS:
            schema["properties"]["max_cost"] = {"type": "number"}
            schema["properties"]["prompt"] = {"type": "string"}
            schema["properties"]["model_id"] = {"type": "string"}
            schema["properties"]["inputs"] = {"type": "object"}
        if name == "vinci.skills_search":
            schema["properties"]["query"] = {"type": "string"}
        if name == "vinci.jobs_get":
            schema["properties"]["job_id"] = {"type": "string"}
        if name == "vinci.jobs_cancel":
            schema["properties"]["run_id"] = {"type": "string"}
        if name == "vinci.media_inspect":
            schema["properties"]["uri"] = {"type": "string"}
        if name == "vinci.cost_estimate":
            schema["properties"]["skill"] = {"type": "string"}
            schema["properties"]["inputs"] = {"type": "object"}
            schema["properties"]["max_cost"] = {"type": "number"}
            schema["properties"]["model_id"] = {"type": "string"}
        if name == "vinci.workflow_run":
            schema["properties"]["skill"] = {"type": "string"}
            schema["properties"]["workflow"] = {"type": "object"}
        tools.append(
            {
                "name": name,
                "description": _TOOL_DESCRIPTIONS[name],
                "inputSchema": schema,
            }
        )
    return tools


def call_tool(engine: Engine, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
    if name == "vinci.models_list":
        return {"models": engine.models()}
    if name == "vinci.skills_search":
        hits = engine.skills.search(str(args.get("query") or ""))
        return {"skills": [engine.skills.inspect(s.id) for s in hits]}
    if name == "vinci.cost_estimate":
        return engine.estimate_skill(
            str(args.get("skill") or "@tryvinci/image-generate"),
            dict(args.get("inputs") or {"prompt": args.get("prompt")}),
            max_cost=_max_cost(args),
            model_id=args.get("model_id"),
        )
    if name == "vinci.image_generate":
        return engine.start_run(
            "@tryvinci/image-generate",
            _inputs(args),
            max_cost=_max_cost(args),
            model_id=args.get("model_id"),
        )
    if name == "vinci.video_generate":
        return engine.start_run(
            "@tryvinci/video-generate",
            _inputs(args),
            max_cost=_max_cost(args),
        )
    if name == "vinci.workflow_run":
        workflow = args.get("workflow")
        spec = WorkflowSpec.model_validate(workflow) if workflow else None
        return engine.start_run(
            args.get("skill"),
            _inputs(args),
            max_cost=_max_cost(args),
            preference=args.get("preference"),
            workflow=spec,
        )
    if name == "vinci.jobs_get":
        job = engine.store.get_job(str(args["job_id"]))
        if job is None:
            raise KeyError(args["job_id"])
        dumped = job.model_dump(mode="json")
        redacted = redact_mapping(dumped, extra_values=secrets)
        return redacted if isinstance(redacted, dict) else dumped
    if name == "vinci.jobs_cancel":
        return engine.cancel_run(str(args["run_id"]))
    if name == "vinci.media_inspect":
        uri = str(args.get("uri") or args.get("id") or "")
        asset_id = uri.removeprefix("vinci://assets/")
        asset = engine.store.get_asset(asset_id)
        if asset is None:
            raise KeyError(uri)
        dumped = asset.model_dump(mode="json")
        redacted = redact_mapping(dumped, extra_values=secrets)
        return redacted if isinstance(redacted, dict) else dumped
    raise KeyError(name)


def _inputs(args: dict[str, Any]) -> dict[str, Any]:
    if isinstance(args.get("inputs"), dict):
        return dict(args["inputs"])
    prompt = args.get("prompt")
    return {"prompt": prompt} if prompt is not None else {}


def _max_cost(args: dict[str, Any]) -> float | None:
    value = args.get("max_cost")
    return float(value) if value is not None else None


def handle_rpc(engine: Engine, message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    rpc_id = message.get("id")
    if method is None or str(method).startswith("notifications/"):
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "vinci", "version": "0.1.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tool_schemas()}}
    if method == "tools/call":
        params = message.get("params") or {}
        name = params["name"]
        arguments = params.get("arguments") or {}
        try:
            result = call_tool(engine, name, arguments)
            text = json.dumps(result, default=str)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"content": [{"type": "text", "text": text}]},
            }
        except Exception as exc:  # noqa: BLE001 — MCP error envelope
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"},
            }
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
