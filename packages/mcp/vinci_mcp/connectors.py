"""Tool mappings for the MCP servers that sign in with OAuth: Higgsfield and Magnific.

Each connector lists the models it runs. A row's price is in the provider's own credits, from the
provider's free price preview (Higgsfield ``get_cost``, Magnific ``simulate_cost``) on 2026-11-12.
The tool names and argument shapes come from a live, signed-in ``tools/list`` on that date
(COREPRODUC-610 and 614). Before, the Higgsfield names were guesses, both servers got only
``prompt`` and ``image_url``, and every row cost "1 credit".
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from vinci_protocol.enums import Capability, ErrorCode, JobState
from vinci_protocol.models import JobStatus, ModelConstraints, ModelSpec, Pricing, VinciError

# The pricing snapshot of every connector row. Fixed, not the time of the call: the job cache
# reuses a result only under the row's current snapshot, so a new time at each catalog call made
# each cached result stale and paid again. Change it when a connector's tools or request mapping
# change (COREPRODUC-596; changed 2026-11-12 for the live tool mapping).
SNAPSHOT = datetime(2026, 11, 12, tzinfo=UTC)


@dataclass(frozen=True)
class Row:
    """One model a connector runs.

    Attributes:
        model: The provider's model id (Higgsfield ``model``, Magnific ``mode`` or ``slug``).
        label: The name in the Studio's model lists.
        capability: ``t2i`` or ``i2v``.
        credits: The provider's price of one run with ``settings``, in its own credits.
        ratios: The shapes the model takes. Another shape is not sent.
        settings: Fixed model settings sent with every run (length, resolution, variant).
    """

    model: str
    label: str
    capability: str
    credits: float
    ratios: tuple[str, ...]
    settings: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class Connector:
    id: str
    label: str
    url: str
    docs: str
    currency: str
    tools: dict[str, str]
    status_tool: str
    status_arg: str
    rows: tuple[Row, ...] = field(default=())

    def tool_for(self, capability: Capability) -> str:
        name = self.tools.get(capability.value)
        if not name:
            raise ValueError(f"{self.id} has no {capability.value} tool")
        return name

    def row(self, model_id: str) -> Row:
        """The row of a Studio model id such as ``mcp_higgsfield:soul_2``."""
        model = model_id.split(":", 1)[-1]
        for row in self.rows:
            if row.model == model:
                return row
        raise KeyError(model_id)

    def arguments(
        self, row: Row, inputs: dict[str, Any], start: str | None = None
    ) -> dict[str, Any]:
        """Tool arguments of one run.

        Args:
            row: The model row.
            inputs: The run inputs (``prompt``, ``aspect_ratio``).
            start: The start frame as the provider's own id (Higgsfield media id, Magnific
                creation identifier), for an image-to-video row.

        Returns:
            The ``arguments`` of the generate tool.
        """
        prompt = str(inputs.get("prompt") or inputs.get("text") or "")
        ratio = inputs.get("aspect_ratio")
        ratio = ratio if isinstance(ratio, str) and ratio in row.ratios else None
        settings = dict(row.settings)
        if self.id == "mcp_higgsfield":
            # use_unlim false: without it, a free-trial allowance makes the tool ask instead of run.
            params: dict[str, Any] = {
                "model": row.model,
                "prompt": prompt,
                "count": 1,
                "use_unlim": False,
            }
            params |= settings
            if ratio:
                params["aspect_ratio"] = ratio
            if start:
                params["medias"] = [{"value": start, "role": "start_image"}]
            return {"params": params}
        args: dict[str, Any] = {"prompt": prompt, **settings}
        if row.capability == "i2v":
            args["slug"] = row.model
            args["aspectRatio"] = ratio or row.ratios[0]
            if start:
                args["keyframes"] = {"start": start}
            return args
        args |= {"mode": row.model, "count": 1}
        if ratio:
            args["aspectRatio"] = ratio
        return args

    def cost_call(self, tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """The provider's free price preview of a generate call: no job, no spend."""
        if self.id == "mcp_higgsfield":
            return tool, {"params": {**args["params"], "get_cost": True}}
        return "simulate_cost", {"tool": tool, "arguments": args}


CONNECTORS: dict[str, Connector] = {
    "mcp_higgsfield": Connector(
        id="mcp_higgsfield",
        label="Higgsfield",
        url="https://mcp.higgsfield.ai/mcp",
        docs="https://higgsfield.ai/creator-hub/help-center/integrations/what-is-higgsfield-mcp",
        currency="Higgsfield credits",
        tools={"t2i": "generate_image", "i2v": "generate_video"},
        status_tool="job_status",
        status_arg="jobId",
        rows=(
            Row(
                "seedream_v4_5",
                "Seedream 4.5",
                "t2i",
                1,
                ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"),
            ),
            Row(
                "soul_2", "Soul 2.0", "t2i", 1, ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3")
            ),
            # The clip takes the shape of its start frame.
            Row(
                "minimax_hailuo",
                "Hailuo 2.3 Fast",
                "i2v",
                4,
                ("16:9", "9:16"),
                (("variant", "minimax-2.3-fast"), ("duration", 6), ("resolution", "768")),
            ),
        ),
    ),
    "mcp_magnific": Connector(
        id="mcp_magnific",
        label="Magnific",
        url="https://mcp.magnific.com",
        docs="https://docs.magnific.com/modelcontextprotocol",
        currency="Magnific credits",
        tools={"t2i": "images_generate", "i2v": "video_generate"},
        status_tool="creation_status",
        status_arg="creationIdentifier",
        rows=(
            Row(
                "seedream-4-5",
                "Seedream 4.5",
                "t2i",
                50,
                ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"),
                (("resolution", "2k"),),
            ),
            Row(
                "mystic-2-5",
                "Mystic 2.5",
                "t2i",
                50,
                ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"),
            ),
            Row(
                "minimax-video-2_3-fast",
                "Hailuo 2.3 Fast",
                "i2v",
                150,
                ("16:9",),
                (("duration", 6), ("resolution", "768p")),
            ),
        ),
    ),
}


def connector_for(provider_id: str) -> Connector | None:
    return CONNECTORS.get(provider_id)


def models_for(connector: Connector, tool_names: set[str] | None) -> list[ModelSpec]:
    """Studio rows of a connector: the rows whose generate tool the server lists (all when None)."""
    specs: list[ModelSpec] = []
    for row in connector.rows:
        tool = connector.tools.get(row.capability)
        if tool_names is not None and tool not in tool_names:
            continue
        settings = dict(row.settings)
        resolution = settings.get("resolution")
        specs.append(
            ModelSpec(
                id=f"{connector.id}:{row.model}",
                display_name=f"{connector.label} {row.label}",
                provider=connector.id,
                capabilities=[Capability(row.capability)],
                constraints=ModelConstraints(
                    aspect_ratios=list(row.ratios),
                    durations=[float(settings["duration"])] if "duration" in settings else [],
                    max_duration=float(settings["duration"]) if "duration" in settings else None,
                    resolutions=[str(resolution)] if resolution else [],
                ),
                pricing=Pricing(
                    unit="generation",
                    amount=row.credits,
                    currency=connector.currency,
                    snapshot_at=SNAPSHOT,
                ),
                quality_tier="fast",
                secret_names=[],
            )
        )
    return specs


def parse_cost(result: Any) -> float | None:
    """Credits of a price preview (Higgsfield: cost.credits; Magnific: credits)."""
    payload = payload_from_tool(result)
    if not isinstance(payload, dict):
        return None
    nested = payload.get("cost")
    cost = nested if isinstance(nested, dict) else payload
    value = cost.get("credits")
    return float(value) if isinstance(value, int | float) else None


def parse_generate(result: Any) -> tuple[str, JobStatus, str | None]:
    payload = payload_from_tool(result)
    if not isinstance(payload, dict):
        raise ValueError("mcp generate returned no object")
    refusal = _refusal(payload)
    if refusal:
        raise RuntimeError(refusal)
    job = _job(payload)
    ref = _first_str(
        job, ("id", "identifier", "creationIdentifier", "creation_id", "task_id", "generation_id")
    )
    if not ref:
        raise ValueError("mcp generate returned no job id")
    status, b64 = _status_of(job)
    return ref, status, b64


def parse_status(result: Any) -> tuple[JobStatus, str | None]:
    payload = payload_from_tool(result)
    if not isinstance(payload, dict):
        raise ValueError("mcp status returned no object")
    refusal = _refusal(payload)
    if refusal:
        return JobStatus(
            state=JobState.FAILED, error=VinciError(code=ErrorCode.UNKNOWN, message=refusal)
        ), None
    return _status_of(_job(payload))


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


def _job(payload: dict[str, Any]) -> dict[str, Any]:
    """The job object in a provider envelope: Higgsfield ``results[0]`` or ``generation``, Magnific
    ``creation`` or ``creations[0]``. Other payloads are the job itself."""
    for key in ("generation", "creation"):
        found = payload.get(key)
        if isinstance(found, dict):
            return found
    for key in ("results", "creations"):
        items = payload.get(key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
    return payload


def _refusal(payload: dict[str, Any]) -> str | None:
    """A provider's refusal (no credits, a bad setting) as a short message, or None."""
    error = payload.get("error")
    if isinstance(error, str) and error:
        return error[:300]
    if (
        payload.get("recovery_tool") and _job(payload) is payload
    ):  # Higgsfield: a recovery step and no job
        reason = (
            payload.get("recovery_reason")
            or payload.get("assistant_response")
            or "the provider refused the run"
        )
        return str(reason)[:300]
    return None


def _status_of(job: dict[str, Any]) -> tuple[JobStatus, str | None]:
    b64 = _first_str(job, ("b64", "base64"))
    url = _first_str(job, ("url", "rawUrl", "downloadUrl", "output_url", "image_url", "video_url"))
    nested = job.get("results")
    if not url and isinstance(nested, dict):
        url = _first_str(nested, ("rawUrl", "url", "downloadUrl"))
    raw = str(job.get("status") or job.get("state") or "").lower()
    if raw == "ip_detect":
        message = (
            "Higgsfield holds this result for an IP check. Open it on Higgsfield to release it."
        )
        return JobStatus(
            state=JobState.FAILED, error=VinciError(code=ErrorCode.UNKNOWN, message=message)
        ), b64
    state = _job_state(raw)
    if state == JobState.FAILED:
        reason = job.get("failureReason") or job.get("error") or "mcp generation failed"
        return JobStatus(
            state=JobState.FAILED,
            error=VinciError(code=ErrorCode.UNKNOWN, message=str(reason)[:300]),
        ), b64
    if state == JobState.COMPLETED and not url and not b64:
        state = JobState.RUNNING  # a finished job whose file link is not there yet
    outputs = [url] if url and state == JobState.COMPLETED else []
    return JobStatus(
        state=state, outputs=outputs, progress=1.0 if state == JobState.COMPLETED else 0.2
    ), b64


def _job_state(raw: object) -> JobState:
    text = str(raw or "").lower()
    if text in {"completed", "complete", "succeeded", "success", "done"}:
        return JobState.COMPLETED
    if text in {"cancelled", "canceled"}:
        return JobState.CANCELLED
    if text in {"failed", "error", "nsfw", "rejected"}:
        return JobState.FAILED
    if text in {"queued", "pending", "created", "waiting"}:
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
