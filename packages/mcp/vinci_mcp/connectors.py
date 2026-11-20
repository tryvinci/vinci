"""Tool mappings for the MCP servers that sign in with OAuth: Higgsfield and Magnific.

Each connector lists the models it runs. A row's price is in the provider's own credits, from the
provider's free price preview (Higgsfield ``get_cost``, Magnific ``simulate_cost``) on 2026-11-12.
The tool names and argument shapes come from a live, signed-in ``tools/list`` on that date
(COREPRODUC-610 and 614). Before, the Higgsfield names were guesses, both servers got only
``prompt`` and ``image_url``, and every row cost "1 credit".

Every other model of each provider comes from ``catalogs/<provider>.json``: a snapshot of the
provider's free model list, priced with its free preview (COREPRODUC-669, made by
``vinci_mcp.catalog_live``). Before, each provider listed only the 3 rows below, and none took a
reference image.
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vinci_protocol.enums import Capability, ErrorCode, JobState
from vinci_protocol.models import JobStatus, ModelConstraints, ModelSpec, Pricing, VinciError

# The pricing snapshot of every connector row. Fixed, not the time of the call: the job cache
# reuses a result only under the row's current snapshot, so a new time at each catalog call made
# each cached result stale and paid again. Change it when a connector's tools or request mapping
# change (COREPRODUC-596; changed 2026-11-12 for the live tool mapping, 2026-11-16 for every model
# with references, end frames and lengths, COREPRODUC-669).
SNAPSHOT = datetime(2026, 11, 16, tzinfo=UTC)


@dataclass(frozen=True)
class Row:
    """One model a connector runs.

    Attributes:
        model: The provider's model id (Higgsfield ``model``, Magnific ``mode`` or ``slug``).
        label: The name in the Studio's model lists.
        capability: ``t2i`` or ``i2v``: the run's tool (image or video).
        credits: The provider's price of one run with ``settings``, in its own credits; None when
            its free preview gave none (the Studio shows "price varies").
        ratios: The shapes the model takes. Another shape is not sent.
        settings: Fixed model settings sent with every run (length, resolution, variant).
        caps: Every capability (``t2i``, ``i2i``, ``t2v``, ``i2v``); empty: only ``capability``.
        durations: The lengths a video row offers, each priced in ``clip_credits``.
        clip_credits: The price of each length, ``((5, 40.0), (10, 80.0))``.
        end_frame: The model takes an end frame.
        refs: The reference images it takes (image edit, or a video's References mode).
        ref_role: Higgsfield's media role of a reference image (``image_references``, ``image``).
        reference: A reference video render (``r2v``, COREPRODUC-732): the model follows a pin
            video and takes pictures as the look, with no start frame. Its own Studio id
            (``<model>:reference``) and its own price: the reference seconds are billed too.
        video_refs: The reference videos it takes.
    """

    model: str
    label: str
    capability: str
    credits: float | None
    ratios: tuple[str, ...]
    settings: tuple[tuple[str, Any], ...] = ()
    caps: tuple[str, ...] = ()
    durations: tuple[int, ...] = ()
    clip_credits: tuple[tuple[int, float], ...] = ()
    end_frame: bool = False
    refs: int = 0
    ref_role: str = ""
    reference: bool = False
    video_refs: int = 0

    @property
    def capabilities(self) -> tuple[str, ...]:
        return self.caps or (self.capability,)

    @property
    def video(self) -> bool:
        return self.capability in ("i2v", "t2v", "r2v")

    @property
    def key(self) -> str:
        """The row's part of its Studio id: the model, and ``:reference`` for a reference row."""
        return self.model + (":reference" if self.reference else "")

    def length(self, asked: Any) -> int | None:
        """The clip length a run sends: the asked one fitted to ``durations``, else the fixed."""
        fixed = dict(self.settings).get("duration")
        if not self.durations:
            return int(fixed) if isinstance(fixed, int | float) else None
        try:
            want = float(asked)
        except (TypeError, ValueError):
            want = 5.0
        return min(self.durations, key=lambda n: (abs(n - want), n))

    def price(self, length: int | None) -> float | None:
        """What a run of ``length`` costs: its clip price, else the row's price."""
        return dict(self.clip_credits).get(length or -1, self.credits)


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
    balance_tool: str = ""  # free call: the account's credits now (Connect shows it)
    # A tool error that means the provider ended the account session behind a valid token:
    # the user must sign in again (COREPRODUC-677). A regex; empty for none.
    session_ended: str = ""
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
            if row.key == model:
                return row
        raise KeyError(model_id)

    def arguments(
        self,
        row: Row,
        inputs: dict[str, Any],
        start: str | None = None,
        end: str | None = None,
        refs: tuple[str, ...] = (),
        videos: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Tool arguments of one run.

        Args:
            row: The model row.
            inputs: The run inputs (``prompt``, ``aspect_ratio``, ``duration``).
            start: The start frame as the provider's own id (Higgsfield media id, Magnific
                creation identifier), for a video row.
            end: The end frame, the same way, for a row that takes one.
            refs: Reference images the same way: an image edit, or a video's References mode.
            videos: Reference videos the same way, for a reference row (the pin video).

        Returns:
            The ``arguments`` of the generate tool.
        """
        prompt = str(inputs.get("prompt") or inputs.get("text") or "")
        ratio = inputs.get("aspect_ratio")
        ratio = ratio if isinstance(ratio, str) and ratio in row.ratios else None
        settings = dict(row.settings)
        length = row.length(inputs.get("duration")) if row.durations else None
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
            if length:
                params["duration"] = length
            medias = [{"value": start, "role": "start_image"}] if start else []
            medias += [{"value": end, "role": "end_image"}] if end else []
            medias += [{"value": ref, "role": row.ref_role or "image_references"} for ref in refs]
            if row.reference:  # Seedance 2.5's omni_reference mode; a show adds its own sound
                params |= {"mode": "omni_reference", "generate_audio": False}
                medias += [{"value": video, "role": "video_references"} for video in videos]
            if medias:
                params["medias"] = medias
            return {"params": params}
        args: dict[str, Any] = {"prompt": prompt, **settings}
        if length:
            args["duration"] = length
        if row.video:
            args["slug"] = row.model
            if ratio or row.ratios:
                args["aspectRatio"] = ratio or row.ratios[0]
            frames = {"start": start} if start else {}
            frames |= {"end": end} if end else {}
            if frames:
                args["keyframes"] = frames
            if refs or videos:  # a reference row: the pin video, then the pictures
                args["references"] = [{"type": "video", "url": v} for v in videos]
                args["references"] += [{"type": "image", "url": ref} for ref in refs]
            return args
        args |= {"mode": row.model, "count": 1}
        if ratio:
            args["aspectRatio"] = ratio
        if refs:
            args["references"] = [{"type": "image", "identifier": ref} for ref in refs]
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
        tools={
            "t2i": "generate_image",
            "i2i": "generate_image",
            "t2v": "generate_video",
            "i2v": "generate_video",
            "r2v": "generate_video",
        },
        status_tool="job_status",
        status_arg="jobId",
        balance_tool="balance",
        # Seen 48 h and 67 h after a sign-in: "FNF API GET /mcp/workspaces failed (403)".
        session_ended=r"FNF API \S+ \S+ failed \(403\)",
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
        tools={
            "t2i": "images_generate",
            "i2i": "images_generate",
            "t2v": "video_generate",
            "i2v": "video_generate",
            "r2v": "video_generate",
        },
        status_tool="creation_status",
        status_arg="creationIdentifier",
        balance_tool="account_balance",
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


CATALOGS = Path(__file__).with_name("catalogs")


def snapshot_rows(provider_id: str, skip: set[str] = frozenset()) -> tuple[Row, ...]:  # type: ignore[assignment]
    """The rows of ``catalogs/<provider_id>.json`` (COREPRODUC-669), minus the ``skip`` models."""
    path = CATALOGS / f"{provider_id}.json"
    if not path.is_file():
        return ()
    rows = []
    for item in json.loads(path.read_text(encoding="utf-8")).get("rows", []):
        if item["model"] in skip:
            continue
        rows.append(
            Row(
                model=item["model"],
                label=item["label"],
                capability=item["capability"],
                credits=item.get("credits"),
                ratios=tuple(item.get("ratios") or ()),
                settings=tuple((k, v) for k, v in (item.get("settings") or {}).items()),
                caps=tuple(item.get("caps") or ()),
                durations=tuple(item.get("durations") or ()),
                clip_credits=tuple(
                    (int(k), float(v)) for k, v in (item.get("clip_credits") or {}).items()
                ),
                end_frame=bool(item.get("end_frame")),
                refs=int(item.get("refs") or 0),
                ref_role=str(item.get("ref_role") or ""),
            )
        )
    return tuple(rows)


# The models proven with the pin video method run as reference rows too (COREPRODUC-732; user
# decision 2026-11-19: list only models that work with it). The blockout editor tested Seedance
# 2.5 alone. Checked signed in, 2026-11-19: Higgsfield `seedance_2_5` takes `video_references`
# in mode `omni_reference`; Magnific's `video_generate` takes `references` of type `video`.
REFERENCE = {"mcp_higgsfield": "seedance_2_5", "mcp_magnific": "bytedance-seedance-pro-2.5"}
LENGTHS = tuple(range(4, 16))  # Seedance 2.5 makes 4 to 30 s; a shot stays under 15 s
# A reference render is a 480p draft, as in the blockout editor (user, 2026-11-19: "lets do a
# 480p"). The published plain Seedance 2.5 rates at 480p, in the provider's credits per second:
# Magnific 200 (its Seedance 2.5 page: 200/s Draft 480p, 440/s 720p, 1,100/s 1080p) and
# Higgsfield 3 (15 credits for 5 s at 480p, a public quote of Higgsfield's price).
DRAFT = {"mcp_higgsfield": 3.0, "mcp_magnific": 200.0}
# Both providers bill the output seconds plus the reference video's seconds, at a lower rate
# (Magnific's API docs). ByteDance's own meter puts that rate at 0.6 of the plain one (Volcano
# Engine ¥42 vs ¥70 per million tokens; Tein lists $0.1323 vs $0.2205 per second).
REFERENCE_RATE = 0.6


def reference_row(row: Row, per_second: float) -> Row:
    """A model's reference row: ``r2v`` at 480p with no start frame, priced for the pin video too.

    The pin video is as long as the shot, so a length ``n`` bills ``2n`` seconds at the
    reference rate. Before, each length cost twice the row's own clip price (at its 720p
    setting): Magnific 5,280 credits for 6 s, where the rule above gives 1,440. The provider's
    free preview still runs before each job, and a job that costs more than this does not run.

    Args:
        row: The model's own row (``REFERENCE``).
        per_second: The provider's plain 480p price per second (``DRAFT``).
    """
    clips = tuple((n, float(math.ceil(2 * n * per_second * REFERENCE_RATE))) for n in LENGTHS)
    return replace(
        row,
        label=f"{row.label} reference",
        capability="r2v",
        caps=("r2v",),
        credits=dict(clips)[5],
        settings=tuple({**dict(row.settings), "resolution": "480p"}.items()),
        durations=LENGTHS,
        clip_credits=clips,
        end_frame=False,
        refs=9,
        reference=True,
        video_refs=3,
    )


# The 3 hand-tuned rows of each provider stay first; its snapshot adds every other model.
for _id, _connector in list(CONNECTORS.items()):
    _rows = _connector.rows + snapshot_rows(_id, {r.model for r in _connector.rows})
    _rows += tuple(reference_row(r, DRAFT[_id]) for r in _rows if r.model == REFERENCE.get(_id))
    CONNECTORS[_id] = replace(_connector, rows=_rows)


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
        lengths = [float(n) for n in row.durations] or (
            [float(settings["duration"])] if "duration" in settings else []
        )
        specs.append(
            ModelSpec(
                id=f"{connector.id}:{row.key}",
                display_name=f"{connector.label} {row.label}",
                provider=connector.id,
                capabilities=[Capability(cap) for cap in row.capabilities],
                constraints=ModelConstraints(
                    aspect_ratios=list(row.ratios),
                    durations=lengths,
                    max_duration=max(lengths) if lengths else None,
                    resolutions=[str(resolution)] if resolution else [],
                    max_input_images=row.refs or None,
                    end_frame=row.end_frame,
                    max_references=row.refs if row.video else 0,
                ),
                pricing=Pricing(
                    unit="generation",
                    amount=row.credits or 0,
                    currency=connector.currency,
                    snapshot_at=SNAPSHOT,
                    clip_prices={str(n): c for n, c in row.clip_credits},
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


def parse_balance(result: Any) -> float | None:
    """Credits of a balance call.

    Higgsfield ``balance`` answers ``credits``; Magnific ``account_balance`` answers
    ``credits.available``.

    Args:
        result: The ``tools/call`` result of the connector's ``balance_tool``.

    Returns:
        The credits the account can spend now, or None when the answer has no number.
    """
    payload = payload_from_tool(result)
    value = payload.get("credits") if isinstance(payload, dict) else None
    if isinstance(value, dict):
        value = value.get("available")
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
