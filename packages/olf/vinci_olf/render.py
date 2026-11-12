"""Render a shot through the Vinci runtime: a keyframe still, a video, or the dialogue audio.

The spec says what to make, not how (SPEC.md, Overview). This module is Vinci's "how":
it turns a resolved shot into a prompt plus reference images (or one speech request per
dialogue line), runs an inline workflow on the local runtime (demo mode costs $0), and
writes take files with provenance.
"""

from __future__ import annotations

import hashlib
import logging
import math
import mimetypes
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vinci_olf.explain import save_inputs
from vinci_olf.project import OlfError, Project, sheets_of, write
from vinci_olf.qa import palette_check, palettes
from vinci_olf.resolve import from_keyframe, hash_view, inputs_hash, resolve

log = logging.getLogger(__name__)
REF_LIMIT = 8  # same cap as Studio Library refs
EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
}
PREFERENCES = ("cheapest", "fastest", "quality")
KINDS = ("keyframe", "video", "audio")
LINE_GAP = 0.3  # seconds of silence between dialogue lines in an audio take
MAX_VARIATIONS = 4  # keyframes one render can draw
# The camera fields an engine move reads; `canvas` lets a pan use the room of a larger drawing.
MOVE_KEYS = ("move", "direction", "amount", "ease", "hold_start", "hold_end", "center", "canvas")
SOFT = 1.25  # an engine move that enlarges the keyframe more than this gets a note
LOCAL = "local:ffmpeg:v1"  # the runtime's model ID for a local media job
# Extension keys that would change a core field (SPEC.md, Extensions, rule 4): the clip length
# and the number of outputs. The engine sets these, and the price check could not see them.
RESERVED = frozenset(
    {
        "duration",
        "seconds",
        "num_frames",
        "n",
        "num_images",
        "num_outputs",
        "num_videos",
        "batch_size",
    }
)


def references(view: dict[str, Any]) -> list[str]:
    """Pick reference images in priority order: characters, props, location, style.

    Each node sends the first as ``image`` and all of them as ``image_urls``. Models that take
    several (fal, Higgsfield, Wavespeed's Seedream and Nano Banana Pro edit routes) read all.
    """
    refs: list[str] = []
    for char in view.get("characters") or []:
        # A form's front view shows the chosen look; else every whole sheet of the character.
        front = ((char.get("form") or {}).get("views") or {}).get("front")
        refs += [front] if front else sheets_of(char) or _leaves(char.get("references"))[:1]
    for prop in view.get("props") or []:
        refs += _leaves(prop.get("references"))[:1]
    refs += _leaves((view.get("location") or {}).get("references"))[:1]
    refs += _leaves((view.get("style") or {}).get("references"))
    return list(dict.fromkeys(refs))[:REF_LIMIT]


def _leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith("asset/") else []
    items = (
        list(value.values())
        if isinstance(value, dict)
        else value
        if isinstance(value, list)
        else []
    )
    return [leaf for item in items for leaf in _leaves(item)]


def prompt(view: dict[str, Any], kind: str) -> str:
    """Write a model-agnostic prompt from a resolved shot (video adds motion and dialogue)."""
    cam = view.get("camera") or {}
    words = [f"{cam.get('framing', 'medium')} shot"]
    words += [f"{cam['angle']} angle"] if cam.get("angle") else []
    words += [f"{cam['lens']} lens"] if cam.get("lens") else []
    if kind == "video" and cam.get("move"):
        words.append(" ".join(filter(None, [cam["move"], cam.get("direction")])))
    parts = [", ".join(words).replace("_", " ").capitalize(), view.get("description")]
    parts.append(_template_words(view, "prompt" if kind == "video" else "keyframe"))
    blocking = view.get("blocking") or {}
    for char in view.get("characters") or []:
        outfit = (char.get("outfit") or {}).get("description")
        looks = [char.get("description"), (char.get("form") or {}).get("description")]
        looks += [f"Wearing: {outfit}" if outfit else None, blocking.get(char["id"])]
        parts.append(
            f"{char.get('name', char['id'])}: " + " ".join(_sentence(x) for x in looks if x)
        )
    if loc := view.get("location"):
        parts.append(
            f"Location: {loc.get('name')}" + (f", {loc['variant']}" if loc.get("variant") else "")
        )
        parts.append(loc.get("description"))
    parts += [f"Prop: {prop.get('description')}" for prop in view.get("props") or []]
    if look := (view.get("style") or {}).get("look"):
        parts.append(
            "Style: "
            + "; ".join(
                f"{k} {', '.join(v) if isinstance(v, list) else v}" for k, v in look.items()
            )
        )
    parts.append(f"Mood: {view['mood']}" if view.get("mood") else None)
    if kind == "video":
        names = {c["id"]: c.get("name", c["id"]) for c in view.get("characters") or []}
        for line in view.get("dialogue") or []:
            delivery = f" ({line['delivery']})" if line.get("delivery") else ""
            parts.append(
                f'{names.get(line["speaker"], line["speaker"])}{delivery} says: "{line["line"]}"'
            )
    return " ".join(_sentence(str(x)) for x in parts if x)


def _template_words(view: dict[str, Any], key: str) -> str | None:
    """The words of the shot's camerawork template for a prompt (``keyframe`` or ``prompt``).

    A slot token (``{a}``, ``{b}``, ``{c}``) becomes the name of the shot's character in that
    place, so one template serves each cast.
    """
    template = (view.get("camera") or {}).get("template")
    text = template.get(key) if isinstance(template, dict) else None
    if not text:
        return None
    names = [str(c.get("name", c["id"])) for c in view.get("characters") or []]
    for place, slot in enumerate("abc"):
        name = names[place] if place < len(names) else "the character"
        text = text.replace("{" + slot + "}", name)
    return str(text).strip()


def _sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return f"{text[:1].upper()}{text[1:]}."


def _next_take(p: Project, shot_id: str, prefix: str) -> str:
    """Return the next free take ID, for example ``e02/s03/sh014/kf2``."""
    files = (p.root / "takes" / shot_id).glob(f"{prefix}*")
    used = [int(m[1]) for f in files if (m := re.fullmatch(rf"{prefix}(\d+)", f.stem))]
    used += [
        int(k.rsplit(prefix, 1)[1])
        for k in p.docs
        if re.fullmatch(rf"{re.escape(shot_id)}/{prefix}\d+", k)
    ]
    return f"{shot_id}/{prefix}{max(used, default=0) + 1}"


def render(
    p: Project,
    shot_id: str,
    *,
    kind: str = "video",
    model: str | None = None,
    keyframe_model: str | None = None,
    count: int = 1,
    yes: bool = False,
    max_total: float | None = None,
    dry_run: bool = False,
    engine: Any = None,
) -> dict[str, Any]:
    """Plan a shot render, show its price, and (unless ``dry_run``) run it and write the takes.

    A video render animates from the selected keyframe (``select.keyframe``) when
    ``control.first_frame`` is ``keyframe``. With no selection it renders a new keyframe
    first. With ``camera.render: engine`` no video model runs: the runtime moves the frame
    over that keyframe (an engine move, $0), and it needs no connected provider. An audio
    render speaks each dialogue line in its speaker's voice and joins the lines into one take.
    The engine never writes ``select``: picking a take is a human choice.
    Each node also gets ``extensions.<provider>`` of the planned model as parameters: the
    speaker's voice entry first, then the shot's levels (``_extensions``).
    This is ``plan_render``, the price check, a run on ``engine``, then ``record_render``.

    Args:
        p: The loaded project.
        shot_id: The shot to render.
        kind: ``keyframe`` (a still only), ``video``, or ``audio`` (the shot's dialogue).
        model: Model ID for the last step. Default: routing by preference.
        keyframe_model: Model ID for a new keyframe inside a video render.
        count: Keyframe variations to draw at once (1 to 4); each is its own take.
        yes: Allow a render that costs money. Without it, a paid render stops before it runs.
        max_total: The price a person confirmed (Studio, MCP). A plan above it stops, so a show
            that changed after the confirm cannot spend more than was approved.
        dry_run: Return the plan and price only. Nothing is staged, run or written.
        engine: A ``vinci_runtime.engine.Engine``. Default: the one for ``$VINCI_HOME``.

    Returns:
        ``{"plan": [{"node", "model", "amount", "extensions"}], "total": USD, "unpriced",
        "takes": [new take IDs]}``. ``extensions`` lists the keys a node gets from the show.
        An engine move that enlarges its keyframe adds ``"notes"``.

    Raises:
        OlfError: The project, the price, or the run stops the render.
    """
    from vinci_protocol.models import WorkflowSpec

    if engine is None:
        from vinci_runtime.engine import Engine

        engine = Engine()
    result, job = plan_render(
        p,
        shot_id,
        kind=kind,
        model=model,
        keyframe_model=keyframe_model,
        count=count,
        engine=engine,
    )
    if dry_run:
        return result
    text = ", ".join(f"{r['node']}: {r['model']} ${r['amount']:.2f}" for r in result["plan"])
    if max_total is not None and result["total"] > max_total + 1e-9:
        raise OlfError(
            f"the price changed: this render costs ${result['total']:.2f}, more than the "
            f"${max_total:.2f} you confirmed. Check the price again"
        )
    if (result["total"] > 0 or result["unpriced"]) and not yes:
        more = (
            f", plus {', '.join(result['unpriced'])} with no flat price"
            if result["unpriced"]
            else ""
        )
        raise OlfError(
            f"this render costs ${result['total']:.2f}{more} ({text}). "
            "Run again with --yes to spend it"
        )
    job["license"] = take_license(p)
    staged: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    for node in job["nodes"]:  # the run gets runtime CAS IDs; the job keeps the asset IDs
        for key in ("image", "image_urls", "last_frame_url", "media"):
            value = node["params"].get(key)
            for ref in value if isinstance(value, list) else [value]:
                if isinstance(ref, str) and ref.startswith("asset/") and ref not in staged:
                    staged[ref] = _stage(engine, p, ref)
        params = {
            k: [staged.get(x, x) for x in v] if isinstance(v, list) else staged.get(v, v)
            for k, v in node["params"].items()
        }
        nodes.append(node | {"params": params})
    shape = {"id": f"olf:{shot_id}", "version": "0.1.0", "edges": job["edges"]}
    run = engine.start_run(
        None,
        {},
        workflow=WorkflowSpec.model_validate(
            shape | {"preference": job["preference"], "nodes": nodes}
        ),
        preference=job["preference"],
        max_cost=job["max_cost"],
    )
    if run.get("state") != "completed":
        reason = run.get("awaiting_reason") or run.get("error") or "unknown"
        raise OlfError(f"run {run.get('id')} is {run.get('state')}: {reason}")
    log.info("render %s: run %s completed", shot_id, run.get("id"))
    outputs: dict[str, bytes] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for node in nodes:
        info = run["nodes"][node["id"]]
        outputs[node["id"]] = engine.cas.get(str(info["output"]))
        found = engine.store.get_job(info["job_id"])
        receipt = found.receipt if found is not None else None
        receipts[node["id"]] = {"model": found.model_id if found is not None else None} | (
            {
                "provider": receipt.provider,
                "cost": receipt.computed_cost,
                "currency": receipt.currency,
            }
            if receipt is not None
            else {}
        )
    result["takes"] = record_render(p, job, outputs, receipts)
    return result


def take_license(p: Project) -> dict[str, Any]:
    """The license every generated take gets: ``license`` in project.yaml (owner and terms).

    Raises:
        OlfError: project.yaml has no license with an owner and terms.
    """
    license_ = p.manifest.get("license")
    if not isinstance(license_, dict) or not {"owner", "terms"} <= license_.keys():
        raise OlfError(
            "project.yaml needs license.owner and license.terms: every generated take gets them"
        )
    return dict(license_)


def plan_render(
    p: Project,
    shot_id: str,
    *,
    kind: str = "video",
    model: str | None = None,
    keyframe_model: str | None = None,
    count: int = 1,
    engine: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Plan a shot render: its price, and the job that a run executes and ``record_render`` writes.

    ``render`` joins the plan, the run and the record on the local runtime. A host that runs the
    nodes itself (the hosted Studio starts one paid node per poll) calls this, runs
    ``job["nodes"]`` (``asset/<sha256>`` params name show files), then calls ``record_render``.

    Args:
        p: The loaded project.
        shot_id: The shot to render.
        kind: ``keyframe``, ``video`` or ``audio``, as in ``render``.
        model: Model ID for the last step. Default: routing by preference.
        keyframe_model: Model ID for a new keyframe inside a video render.
        count: Keyframe variations to draw at once (1 to 4).
        engine: Anything with ``catalog()``, ``routing_providers()`` and ``config.preference``.
            Default: the ``vinci_runtime.engine.Engine`` for ``$VINCI_HOME``.

    Returns:
        ``(result, job)``. ``result`` is ``render``'s answer before the run (``takes`` empty).
        ``job`` holds ``shot``, ``kind``, ``nodes`` (models pinned), ``edges``, ``preference``,
        ``max_cost``, ``view`` (the resolved shot the takes are hashed from), ``refs``,
        ``ref_files`` (reference -> project file) and ``ids``.

    Raises:
        OlfError: The project or the connected models cannot make the render.
    """
    if kind not in KINDS:  # an empty workflow would run and write nothing
        raise OlfError(f"kind must be keyframe, video or audio, not {kind!r}")
    if not 1 <= count <= MAX_VARIATIONS or (count > 1 and kind != "keyframe"):
        raise OlfError(f"count must be 1 to {MAX_VARIATIONS}, and more than 1 only for keyframes")
    from vinci_core.catalog import price_key
    from vinci_core.cost import fit_duration, plan_workflow
    from vinci_protocol.models import WorkflowSpec

    if engine is None:
        from vinci_runtime.engine import Engine

        engine = Engine()
    view = resolve(p, shot_id)
    control, picked = view.get("control") or {}, (view.get("select") or {}).get("keyframe")
    # An engine move: a held drawing with camera work on top, made with no video model.
    engine_move = kind == "video" and (view.get("camera") or {}).get("render") == "engine"
    kf_used = f"{shot_id}/{picked}" if picked else None
    if kind == "video" and kf_used and kf_used not in p.docs:
        raise OlfError(f"select.keyframe {picked}: take {kf_used} is missing")
    new_kf = kind == "keyframe" or (kind == "video" and from_keyframe(view) and kf_used is None)
    if (new_kf or not engine_move) and not engine.routing_providers():
        raise OlfError("no providers are connected: run `vinci init --demo` or add a provider key")
    ids = {
        "keyframe": _next_take(p, shot_id, "kf") if new_kf else kf_used,
        "video": _next_take(p, shot_id, "v"),
        "audio": _next_take(p, shot_id, "a"),
    }
    router = (view.get("extensions") or {}).get("x-router") or {}
    pref = router.get("prefer") or engine.config.preference or "cheapest"
    if pref not in PREFERENCES:
        raise OlfError(
            f"extensions.x-router.prefer must be one of {', '.join(PREFERENCES)}, not {pref!r}"
        )
    base = {"aspect_ratio": (view.get("defaults") or {}).get("aspect")}
    base["negative_prompt"] = ", ".join((view.get("style") or {}).get("negative") or [])
    refs = references(view) if new_kf else []
    nodes: list[dict[str, Any]] = []
    # Params hold asset IDs while planning; they are staged into the runtime CAS only to run.
    # A drawing larger than the frame (camera.canvas, for a pan or a tilt) has the canvas shape.
    canvas = (view.get("camera") or {}).get("canvas")
    if new_kf:
        params = (
            base
            | {"prompt": prompt(view, "keyframe")}
            | ({"aspect_ratio": canvas} if canvas else {})
        )
        if refs:
            params |= {"image": refs[0], "image_urls": refs}
        kf_model = model if kind == "keyframe" else keyframe_model
        first = int(str(ids["keyframe"]).rsplit("kf", 1)[1])
        for n in range(count):  # variations: kf3, kf4, ... each a node of its own
            take_id = f"{shot_id}/kf{first + n}"
            cap = "i2i" if refs else "t2i"
            nodes.append(
                _node("keyframe" if n == 0 else f"keyframe{n + 1}", cap, kf_model, params, take_id)
            )
    notes: list[str] = []
    if kind == "video":
        source = control.get("first_frame")  # what the video starts from: a stated file, or
        if from_keyframe(view):  # the keyframe (the new one, else the chosen one)
            source = "{{nodes.keyframe.output}}" if new_kf else _output(p, kf_used)
        if engine_move:
            nodes.append(_move_node(view, source, str(ids["video"])))
            notes = _soft(p, view, source)
        else:
            params = base | {
                "prompt": prompt(view, "video"),
                "duration": math.ceil(float(view["duration"])),
            }
            template = (view.get("camera") or {}).get("template")
            if avoid := (template.get("avoid") if isinstance(template, dict) else None):
                # The template's avoid words join the style's negative words (video only).
                params["negative_prompt"] = ", ".join(
                    [*filter(None, [base["negative_prompt"]]), *avoid]
                )
            if source:
                params["image"] = source
            if control.get("last_frame") not in (None, "keyframe"):
                params["last_frame_url"] = control["last_frame"]
            cap = "i2v" if "image" in params else "t2v"
            nodes.append(_node("video", cap, model, params, ids["video"]))
    voices: dict[str, Any] = {}  # dialogue node -> the speaker's voice entry, for extensions
    speakers: dict[str, str] = {}  # dialogue node -> its speaker, to name one with no voice
    if kind == "audio":
        cast = {c["id"]: c for c in view.get("characters") or []}
        lines = [x for x in view.get("dialogue") or [] if isinstance(x, dict) and x.get("line")]
        if not lines:
            raise OlfError(f"{shot_id} has no dialogue to speak")
        for i, line in enumerate(lines, 1):  # one speech request per line, in the line's voice
            voices[f"line{i}"] = (cast.get(line.get("speaker")) or {}).get("voice")
            speakers[f"line{i}"] = str(line.get("speaker") or "the speaker")
            nodes.append(
                _node(f"line{i}", "tts", model, {"prompt": str(line["line"])}, ids["audio"])
            )
    edges = (
        [{"src": "keyframe", "dst": "video", "input_key": "media" if engine_move else "image"}]
        if new_kf and kind == "video"
        else []
    )
    shape = {"id": f"olf:{shot_id}", "version": "0.1.0", "edges": edges, "preference": pref}
    try:
        rows = plan_workflow(
            engine.catalog(),
            WorkflowSpec.model_validate(shape | {"nodes": nodes}),
            available_providers=engine.routing_providers(),
        )
    except (KeyError, ValueError) as exc:  # the connected providers cannot make a step
        detail = exc.args[0] if exc.args else exc
        raise OlfError(
            f"no connected model can render this {kind} ({detail}): run `vinci init --demo` or "
            "add a provider key"
        ) from exc
    caps = {node["id"]: node.get("capability") for node in nodes}  # a model menu lists these
    for row in rows if canvas else []:  # stop at the plan: the shape is a promise of the drawing
        shapes = list(getattr(row["model"].constraints, "aspect_ratios", None) or [])
        if caps.get(row["node_id"]) in ("t2i", "i2i") and shapes and canvas not in shapes:
            raise OlfError(
                f"{row['model'].id} cannot draw a {canvas} keyframe for camera.canvas (it draws "
                f"{', '.join(shapes)}): pick another keyframe model, or another canvas"
            )
    plan = [
        {
            "node": row["node_id"],
            "model": row["model"].id,
            "amount": float(row["estimate"].amount),
            "capability": caps.get(row["node_id"]),
        }
        for row in rows
    ]
    if engine_move:  # the runtime's local job: no model, so no price and no menu
        plan.append({"node": "video", "model": LOCAL, "amount": 0.0, "capability": None})
    chosen = {row["node_id"]: row["model"] for row in rows}
    added: dict[str, list[str]] = {}  # node -> keys from extensions, shown with the plan
    for node in nodes:  # pin the planned model, so the extensions of its provider apply
        if (spec_model := chosen.get(node["id"])) is not None:
            node["model_id"] = spec_model.id
            if node["id"] == "video":  # a model takes only some clip lengths
                fitted = fit_duration(
                    float(view["duration"]), getattr(spec_model, "constraints", None)
                )
                if fitted != node["params"]["duration"]:
                    log.info(
                        "render %s: %s takes %s s clips, so the %s s shot asks for %s s",
                        shot_id,
                        spec_model.id,
                        "/".join(f"{d:g}" for d in spec_model.constraints.durations)
                        or f"up to {spec_model.constraints.max_duration:g}",
                        view["duration"],
                        fitted,
                    )
                node["params"]["duration"] = fitted
            extra = _extensions(spec_model.provider, voices.get(node["id"]), view)
            if refused := sorted(set(extra) & RESERVED):
                log.warning(
                    "render %s %s: extensions.%s cannot set %s (the engine sets them)",
                    shot_id,
                    node["id"],
                    spec_model.provider,
                    ", ".join(refused),
                )
            # Core params win: an extension only adds detail (SPEC.md, Extensions, rule 4).
            extra = {
                k: v for k, v in extra.items() if k not in node["params"] and k not in RESERVED
            }
            node["params"] |= extra
            added[node["id"]] = sorted(extra)
            if (
                node["id"] in speakers
                and spec_model.provider == "elevenlabs"
                and "voice_id" not in node["params"]
                and not os.environ.get("ELEVENLABS_VOICE_ID")
            ):  # ElevenLabs has no default voice: say so before the price check, not after it
                raise OlfError(
                    f"{speakers[node['id']]} has no ElevenLabs voice: pick one on its bible page"
                )
            if extra:
                log.info(
                    "render %s %s: extensions.%s adds %s",
                    shot_id,
                    node["id"],
                    spec_model.provider,
                    ", ".join(sorted(extra)),
                )
    for row in plan:  # show what the show adds, so the price is checked with it in view
        if added.get(row["node"]):
            row["extensions"] = added[row["node"]]
    # Amount 0 on a live provider means "no flat price" (per-token billing), not free.
    unpriced = [row["model"].id for row in rows if price_key(row["model"])[0]]
    result: dict[str, Any] = {
        "plan": plan,
        "total": sum(r["amount"] for r in plan),
        "unpriced": unpriced,
        "takes": [],
    } | ({"notes": notes} if notes else {})
    text = ", ".join(f"{r['node']}: {r['model']} ${r['amount']:.2f}" for r in plan)
    log.info("render %s plan: %s (total $%.2f)", shot_id, text, result["total"])
    job = {
        "shot": shot_id,
        "kind": kind,
        "nodes": nodes,
        "edges": edges,
        "preference": pref,
        "max_cost": router.get("max_cost_usd"),
        "view": view,
        "refs": refs,
        # Reference files this plan hashed: the record locks them if they are still the same.
        "ref_files": {a: p.rel(p.files[a[6:]]) for a in refs if a[6:] in p.files},
        "ids": ids,
    }
    return result, job


def run_one(
    capability: str,
    params: dict[str, Any],
    *,
    model: str | None = None,
    yes: bool = False,
    max_total: float | None = None,
    dry_run: bool = False,
    engine: Any = None,
) -> dict[str, Any]:
    """Plan one model call, check its price, then (unless ``dry_run``) run it, as a render does.

    Text steps (``t2t``) and music and SFX cues use it; a shot render has its own workflow.

    Returns:
        ``{"plan": [{"node", "model", "amount", "capability"}], "total", "unpriced", "output",
        "provenance"}``. ``output`` is the result's bytes and ``provenance`` the take's
        provenance (provider, model, prompt, parameters, created, cost); both None for a dry run.

    Raises:
        OlfError: No connected model has the capability, the price stops it, or the run fails.
    """
    from vinci_core.catalog import price_key
    from vinci_core.cost import plan_workflow
    from vinci_protocol.models import WorkflowSpec

    if engine is None:
        from vinci_runtime.engine import Engine

        engine = Engine()
    if not engine.routing_providers():
        raise OlfError("no providers are connected: run `vinci init --demo` or add a provider key")
    node = _node(capability, capability, model, params, params.get("olf_take"))
    shape = {"id": f"olf:{capability}", "version": "0.1.0", "edges": []}
    shape["preference"] = engine.config.preference or "cheapest"
    try:
        rows = plan_workflow(
            engine.catalog(),
            WorkflowSpec.model_validate(shape | {"nodes": [node]}),
            available_providers=engine.routing_providers(),
        )
    except (KeyError, ValueError) as exc:
        raise OlfError(f"no connected model can make {capability} ({exc})") from exc
    spec, amount = rows[0]["model"], float(rows[0]["estimate"].amount)
    unpriced = [spec.id] if price_key(spec)[0] else []  # amount 0 on a live provider: per token
    plan = [{"node": capability, "model": spec.id, "amount": amount, "capability": capability}]
    result: dict[str, Any] = {"plan": plan, "total": amount, "unpriced": unpriced}
    result |= {"output": None, "provenance": None}
    log.info(
        "%s plan: %s $%.4f%s", capability, spec.id, amount, " (no flat price)" * bool(unpriced)
    )
    if dry_run:
        return result
    if max_total is not None and amount > max_total + 1e-9:
        raise OlfError(
            f"the price changed: this costs ${amount:.2f}, more than the ${max_total:.2f} you "
            "confirmed. Check the price again"
        )
    if (amount > 0 or unpriced) and not yes:
        extra = f" ({spec.id} has no flat price)" if unpriced else ""
        raise OlfError(f"this costs ${amount:.2f}{extra}. Run again with --yes to spend it")
    node["model_id"] = spec.id  # run the model that was priced
    run = engine.start_run(
        None,
        {},
        workflow=WorkflowSpec.model_validate(shape | {"nodes": [node]}),
        preference=shape["preference"],
    )
    if run.get("state") != "completed":
        reason = run.get("awaiting_reason") or run.get("error") or "unknown"
        raise OlfError(f"run {run.get('id')} is {run.get('state')}: {reason}")
    info = run["nodes"][capability]
    job = engine.store.get_job(info["job_id"])
    receipt = job.receipt if job is not None else None
    result["output"] = engine.cas.get(str(info["output"]))
    result["provenance"] = {
        "provider": receipt.provider if receipt else spec.provider,
        "model": spec.id,
        "prompt": str(params.get("prompt") or ""),
        "parameters": {k: params[k] for k in ("duration",) if k in params},
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **(
            {"cost": {"amount": round(receipt.computed_cost, 6), "currency": receipt.currency}}
            if receipt
            else {}
        ),
    }
    log.info("%s run %s: %s, %d bytes", capability, run.get("id"), spec.id, len(result["output"]))
    return result


def _node(
    node_id: str, cap: str, model: str | None, params: dict[str, Any], take_id: str | None
) -> dict[str, Any]:
    # olf_take is Vinci-only: providers send only the params they know. It makes each take a new
    # generation, not a $0 replay of the last identical request.
    params = {k: v for k, v in params.items() if v not in (None, "")} | {"olf_take": take_id}
    return {
        "id": node_id,
        "type": "generate",
        "capability": cap,
        "model_id": model,
        "params": params,
    }


def _move_node(view: dict[str, Any], still: Any, take_id: str) -> dict[str, Any]:
    """The media node of an engine move: the held still under the shot's camera move.

    Raises:
        OlfError: A still cannot do the move (a dolly, a crane, an orbit, handheld).
    """
    from vinci_media import MediaError
    from vinci_media.camera import MOVES, check

    from vinci_olf.validate import schema_errors

    camera, defaults = view.get("camera") or {}, view.get("defaults") or {}
    move = camera.get("move") or "static"
    if move not in MOVES:
        raise OlfError(
            f"the engine cannot make a {move} move from a held drawing: use one of "
            f"{', '.join(MOVES)}, or set camera.render to model"
        )
    # Render does not validate the show first, so check what the move reads: a wrong type or a
    # huge frame must stop here with a plain reason, not inside the runtime.
    fields = {k: v for k, v in camera.items() if k != "template"}
    if errors := schema_errors("camera", fields):
        raise OlfError(f"camera.{errors[0]}")
    size, fps = str(defaults.get("resolution") or "1920x1080"), defaults.get("fps") or 24
    try:
        wide, _, high = size.partition("x")
        check(int(wide), int(high), float(fps), float(view["duration"]))
    except (MediaError, ValueError) as exc:
        raise OlfError(f"an engine move cannot use defaults {size} at {fps} fps: {exc}") from exc
    params = {
        "op": "camera_move",
        "media": still,
        "size": size,
        "fps": fps,
        "seconds": float(view["duration"]),
        "move": move,
        **{k: camera[k] for k in MOVE_KEYS[1:] if k in camera},
        "seed": take_id,  # the same shake for the same take
        "olf_take": take_id,
    }
    return {"id": "video", "type": "media", "params": params}


def _soft(p: Project, view: dict[str, Any], still: Any) -> list[str]:
    """Say when an engine move enlarges its keyframe: a push shows the size of the drawing."""
    from vinci_media.camera import drawing_size, upscale

    if not str(still).startswith("asset/"):
        return []  # a keyframe that this render draws first has no size yet
    camera = view.get("camera") or {}
    size = str((view.get("defaults") or {}).get("resolution") or "1920x1080").partition("x")
    path = p.local_file(str(still))  # a missing file stops the render (OlfError)
    try:
        drawing = drawing_size(path)
    except (OSError, ValueError):  # no image that Pillow reads: the note is only advice
        log.info("render %s: no size for %s, so no note on the move", view.get("id"), path.name)
        return []
    factor = upscale(
        drawing,
        (int(size[0]), int(size[2])),
        camera.get("move") or "static",
        amount=camera.get("amount"),
        center=camera.get("center"),
        canvas=camera.get("canvas"),
    )
    if factor <= SOFT:
        return []
    return [
        f"the keyframe is {drawing[0]} px wide and this move enlarges it {factor:.1f}x, so "
        "the picture can look soft: use a larger keyframe or a smaller amount"
    ]


def _extensions(provider: str, *levels: Any) -> dict[str, Any]:
    """Return model parameters from ``extensions.<provider>`` of each level, lower levels last.

    The namespace is the Vinci provider ID of the planned model (``elevenlabs``, ``fal``,
    ``mock``), for example a voice's ``elevenlabs: { voice_id: ... }``. Other namespaces,
    such as ``x-router``, are not parameters (SPEC.md, Extensions). Empty values are left out.
    """
    found: dict[str, Any] = {}
    for level in levels:
        ext = level.get("extensions") if isinstance(level, dict) else None
        ext = ext.get(provider) if isinstance(ext, dict) else None
        if isinstance(ext, dict):
            found |= {k: v for k, v in ext.items() if v not in (None, "")}
    return found


def _output(p: Project, take_id: str | None) -> str:
    output = p.docs[str(take_id)].data.get("output")
    if not output:
        raise OlfError(f"take {take_id} has no output")
    return str(output)


def _stage(engine: Any, p: Project, ref: str) -> str:
    """Copy a whole reference file into the runtime CAS and return its ID."""
    from vinci_provider_sdk.local_image import sniff_media_mime

    path = p.local_file(ref)
    data = path.read_bytes()
    staged = str(
        engine.ingest_bytes(data, mime=sniff_media_mime(data) or "image/png", filename=path.name).id
    )
    log.info("staged %s as %s", ref, staged)
    return staged


def record_render(
    p: Project,
    job: dict[str, Any],
    outputs: dict[str, bytes],
    receipts: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Write a finished render job: each output into ``takes/`` with its take file, and the lock.

    A keyframe or video node is one take. The dialogue nodes (``line1``, ``line2``, ...) are
    one audio take together: their audio is joined in order (``_speech``).

    Args:
        p: The project, loaded again when time passed since the plan. The takes keep the plan's
            view, so a take made while the show changed shows as stale, not as fresh.
        job: ``plan_render``'s job. Its ``license`` (``take_license``) goes on every take; a job
            without one gets the show's license now.
        outputs: Node ID -> the node's output bytes.
        receipts: Node ID -> ``{"provider", "model", "cost", "currency"}``, for provenance.

    Returns:
        The new take IDs.
    """
    from vinci_provider_sdk.local_image import sniff_media_mime

    nodes, view, refs, ids = job["nodes"], job["view"], job["refs"], job["ids"]
    license_, receipts = job.get("license") or take_license(p), receipts or {}
    created, written, lock = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), [], {}
    # The input files this render used (SPEC.md: the engine adds them to the lock file).
    for asset, rel in (job.get("ref_files") or {}).items():
        digest, path = asset.removeprefix("asset/"), p.root / rel
        if asset in p.lock or not path.is_file() or p.sha256(path) != digest:
            continue  # locked already, or the file changed after the plan
        # A hosted show's stand-in file has no bytes to sniff, so its name gives the type.
        mime = sniff_media_mime(path.read_bytes()) or mimetypes.guess_type(rel)[0]
        lock[asset] = _lock_entry(
            rel, digest, mime or "application/octet-stream", "uploaded", license_
        )
    speech = nodes and nodes[0].get("capability") == "tts"
    kinds = [("video" if node["id"] == "video" else "keyframe", [node]) for node in nodes]
    groups = [("audio", nodes)] if speech else kinds
    for kind, group in groups:
        take_id = str(group[0]["params"]["olf_take"])  # each node names its take
        blob = _speech([outputs[n["id"]] for n in group]) if speech else outputs[group[0]["id"]]
        digest = hashlib.sha256(blob).hexdigest()  # the CAS digest too: CAS keys are SHA-256
        mime = sniff_media_mime(blob) or "application/octet-stream"
        rel = Path("takes", f"{take_id}.{EXT.get(mime, 'bin')}")
        (p.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (p.root / rel).write_bytes(blob)
        lock[f"asset/{digest}"] = _lock_entry(rel.as_posix(), digest, mime, "generated", license_)
        take: dict[str, Any] = {
            "id": take_id,
            "kind": kind,
            "status": "draft",
            "output": f"asset/{digest}",
        }
        inputs: dict[str, Any] = {"references": refs} if kind == "keyframe" and refs else {}
        frames: dict[str, str] = {}
        moved = group[0].get("type") == "media"  # an engine move, exact to the frame
        if kind != "keyframe" and (duration := _duration(p.root / rel, exact=moved)):
            take["duration"] = duration
        if kind == "video" and from_keyframe(view):
            new = outputs.get("keyframe")  # drawn in this render, else the chosen keyframe
            frames = {
                "first_frame": f"asset/{hashlib.sha256(new).hexdigest()}"
                if new is not None
                else _output(p, ids["keyframe"])
            }
            inputs = {"first_frame": ids["keyframe"]}
        take["inputs_hash"] = inputs_hash(view, kind, frames)
        save_inputs(p, take_id, hash_view(view, kind, frames))  # explains a later stale state
        if inputs:
            take["inputs"] = inputs
        got = [receipts.get(node["id"]) or {} for node in group]
        paid = [row for row in got if row.get("cost") is not None]
        params = group[0]["params"]
        prompts = [node["params"]["prompt"] for node in group if "prompt" in node["params"]]
        take["provenance"] = {
            "provider": (paid[0].get("provider") if paid else None) or "unknown",
            "model": got[0].get("model") or "unknown",
            **({"prompt": "\n".join(prompts)} if prompts else {}),  # one per line; none for a move
            **(
                {"negative_prompt": params["negative_prompt"]}
                if params.get("negative_prompt")
                else {}
            ),
            "parameters": {
                k: params[k] for k in ("aspect_ratio", "duration", *MOVE_KEYS) if k in params
            },
            "created": created,
            **(
                {
                    "cost": {
                        "amount": round(sum(row["cost"] for row in paid), 6),
                        "currency": paid[0].get("currency"),
                    }
                }
                if paid
                else {}
            ),
        }
        if kind != "audio" and (check := palette_check(p.root / rel, palettes(view))):
            take["qa"] = [check]  # the palette check: a cheap signal, not a likeness score
        write(take, p.root / "takes" / f"{take_id}.yaml")
        log.info("wrote take %s (%s, model %s)", take_id, rel, take["provenance"]["model"])
        written.append(take_id)
    p.add_to_lock(lock)
    return written


def _speech(blobs: list[bytes]) -> bytes:
    """Join the audio of each dialogue line, in order, into one WAV (``LINE_GAP`` s between)."""
    from vinci_media import join_audio

    with tempfile.TemporaryDirectory(prefix="olf-audio-") as raw:
        parts = [Path(raw, f"line{i}") for i in range(len(blobs))]
        for part, blob in zip(parts, blobs, strict=True):
            part.write_bytes(blob)
        return join_audio(parts, Path(raw, "dialogue.wav"), gap=LINE_GAP).read_bytes()


def _lock_entry(
    uri: str, digest: str, mime: str, source: str, license_: dict[str, Any]
) -> dict[str, Any]:
    return {
        "uri": uri,
        "hash": f"sha256:{digest}",
        "type": mime,
        "source": source,
        "license": dict(license_),
    }


def _duration(path: Path, exact: bool = False) -> str | None:
    """Probe the real clip length (a model can round the asked duration).

    ``exact`` keeps the millisecond (``0.542s``), for an engine move: it is exact to the frame,
    and a tenth of a second is more than two frames, so the cut would lose a frame.
    """
    try:
        from vinci_media import probe

        return f"{probe(path)['duration']:.{3 if exact else 1}f}s"
    except Exception as exc:  # noqa: BLE001 - a missing ffprobe must not lose the take
        log.warning("could not probe %s: %s", path, exc)
        return None
