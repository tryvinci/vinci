"""Explicit MCP tool mappings for providers that sign in with OAuth.

Higgsfield tool names are provisional until a live ``tools/list`` capture.
Magnific names match the published MCP tool list.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from vinci_protocol.enums import Capability, ErrorCode, JobState
from vinci_protocol.models import JobStatus, ModelSpec, Pricing, VinciError

# Confirmed against Magnific MCP docs. Higgsfield names are not yet captured live.
HIGGSFIELD_TOOLS_PROVISIONAL = True


@dataclass(frozen=True)
class Connector:
    id: str
    label: str
    url: str
    docs: str
    currency: str
    tools: dict[str, str]
    status_tool: str
    provisional: bool = False

    def tool_for(self, capability: Capability) -> str:
        name = self.tools.get(capability.value)
        if not name:
            raise ValueError(f"{self.id} has no {capability.value} tool")
        return name

    def arguments(self, capability: Capability, inputs: dict[str, Any]) -> dict[str, Any]:
        args: dict[str, Any] = {"prompt": str(inputs.get("prompt") or inputs.get("text") or "")}
        image = inputs.get("image_url") or inputs.get("image") or inputs.get("image_urls")
        if isinstance(image, list) and image:
            image = image[0]
        if isinstance(image, str) and image and capability in {
            Capability.I2I,
            Capability.I2V,
            Capability.EDIT_MULTI,
        }:
            args["image_url"] = image
        return args


CONNECTORS: dict[str, Connector] = {
    "mcp_higgsfield": Connector(
        id="mcp_higgsfield",
        label="Higgsfield",
        url="https://mcp.higgsfield.ai/mcp",
        docs="https://higgsfield.ai/creator-hub/help-center/integrations/what-is-higgsfield-mcp",
        currency="credits",
        tools={
            "t2i": "generate_image",
            "i2i": "generate_image",
            "t2v": "generate_video",
            "i2v": "generate_video",
        },
        status_tool="get_generation",
        provisional=HIGGSFIELD_TOOLS_PROVISIONAL,
    ),
    "mcp_magnific": Connector(
        id="mcp_magnific",
        label="Magnific",
        url="https://mcp.magnific.com",
        docs="https://docs.magnific.com/modelcontextprotocol",
        currency="credits",
        tools={
            "t2i": "images_generate",
            "i2i": "images_generate",
            "t2v": "video_generate",
            "i2v": "video_generate",
        },
        status_tool="creation_status",
    ),
}


def connector_for(provider_id: str) -> Connector | None:
    return CONNECTORS.get(provider_id)


def models_for(connector: Connector, tool_names: set[str] | None) -> list[ModelSpec]:
    now = datetime.now(tz=UTC)
    specs: list[ModelSpec] = []
    seen: set[str] = set()
    for capability, tool in connector.tools.items():
        if tool in seen:
            continue
        if tool_names is not None and tool not in tool_names:
            continue
        seen.add(tool)
        caps = [Capability(item) for item, name in connector.tools.items() if name == tool]
        if not caps:
            caps = [Capability(capability)]
        specs.append(
            ModelSpec(
                id=f"{connector.id}:{tool}",
                display_name=f"{connector.label} {tool}",
                provider=connector.id,
                capabilities=caps,
                pricing=Pricing(
                    unit="generation",
                    amount=1.0,
                    currency=connector.currency,
                    snapshot_at=now,
                ),
                quality_tier="fast",
                secret_names=[],
            )
        )
    return specs


def parse_generate(result: Any) -> tuple[str, JobStatus, str | None]:
    payload = payload_from_tool(result)
    if not isinstance(payload, dict):
        raise ValueError("mcp generate returned no object")
    ref = _first_str(payload, ("id", "creation_id", "task_id", "generation_id"))
    if not ref:
        raise ValueError("mcp generate returned no job id")
    b64 = _first_str(payload, ("b64", "base64"))
    url = _first_str(payload, ("url", "output_url", "image_url", "video_url"))
    state = _job_state(payload.get("status") or payload.get("state"))
    outputs: list[str] = []
    if url:
        outputs.append(url)
    status = JobStatus(
        state=state,
        outputs=outputs,
        progress=1.0 if state == JobState.COMPLETED else 0.0,
    )
    if state == JobState.FAILED:
        status = JobStatus(
            state=JobState.FAILED,
            error=VinciError(code=ErrorCode.UNKNOWN, message="mcp generation failed"),
        )
    return ref, status, b64


def parse_status(result: Any) -> tuple[JobStatus, str | None]:
    payload = payload_from_tool(result)
    if not isinstance(payload, dict):
        raise ValueError("mcp status returned no object")
    b64 = _first_str(payload, ("b64", "base64"))
    url = _first_str(payload, ("url", "output_url", "image_url", "video_url"))
    state = _job_state(payload.get("status") or payload.get("state"))
    outputs = [url] if url else []
    if state == JobState.FAILED:
        return (
            JobStatus(
                state=JobState.FAILED,
                error=VinciError(code=ErrorCode.UNKNOWN, message="mcp generation failed"),
            ),
            b64,
        )
    return (
        JobStatus(
            state=state,
            outputs=outputs,
            progress=1.0 if state == JobState.COMPLETED else 0.2,
        ),
        b64,
    )


def decode_b64(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:  # noqa: BLE001 — invalid media is invalid input
        raise ValueError("mcp generate returned invalid b64") from exc


def payload_from_tool(result: Any) -> Any:
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
    if isinstance(result, dict) and isinstance(result.get("content"), list):
        for block in result["content"]:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if not isinstance(text, str):
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    return result


def _job_state(raw: object) -> JobState:
    text = str(raw or "").lower()
    if text in {"completed", "complete", "succeeded", "success", "done"}:
        return JobState.COMPLETED
    if text in {"cancelled", "canceled"}:
        return JobState.CANCELLED
    if text in {"failed", "error"}:
        return JobState.FAILED
    if text in {"queued", "pending", "created"}:
        return JobState.QUEUED
    return JobState.RUNNING


def _first_str(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    urls = payload.get("urls") or payload.get("outputs")
    if isinstance(urls, list) and urls and isinstance(urls[0], str):
        return urls[0]
    return None
