"""OLF movie engine routes for the Studio Shows page (``vinci_olf``, Apache-2.0).

``create_app`` mounts this router only when ``vinci_olf`` imports, so a build without it
(the Mac bundle today) has no ``/olf`` paths and the Studio shows that the page is off.
A project is a folder on this computer; every file the routes read or write stays inside it.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from vinci_olf import OlfError, Project, load
from vinci_olf.api import library, sample_path, shot_detail, summary
from vinci_olf.author import (
    _slug,
    add_character,
    add_episode,
    add_form,
    add_scene,
    add_sheet,
    add_shot,
    apply_template,
    clone_voice,
    new_show,
    replace_sheet,
    set_shot,
    set_voice,
)
from vinci_olf.batch import render_batch
from vinci_olf.cues import MAX_SECONDS, add_cue, place_cue, render_cue
from vinci_olf.cut import cut_view, use_approved
from vinci_olf.edit import set_clip, set_select, set_take
from vinci_olf.explain import explain, keep_take
from vinci_olf.export import export
from vinci_olf.provenance import available as c2pa_available
from vinci_olf.render import render, run_one
from vinci_olf.script import bible_names, draft, import_script, preview, split_with_model

log = logging.getLogger("vinci.olf")
router = APIRouter(prefix="/olf", tags=["olf"])
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".wav", ".mp3", ".m4a"}
MEDIA |= {".pdf"}  # the e-conte sheet (previs)
DERIVED = ("exports", "previs")  # made again on request: not in the Share zip
T = TypeVar("T")


class RenderBody(BaseModel):
    path: str
    shot: str
    kind: str = "video"
    model: str | None = None
    keyframe_model: str | None = None
    count: int = 1
    yes: bool = False
    max_total: float | None = None  # the price the Studio confirmed; a higher plan stops
    dry_run: bool = False


class BatchBody(BaseModel):
    """Re-render stale takes (``stale``) or animate approved keyframes (``animate``)."""

    path: str
    episode: str
    mode: str
    yes: bool = False
    max_total: float | None = None  # the total the Studio confirmed; a higher plan stops
    dry_run: bool = False


class KeepBody(BaseModel):
    path: str
    take: str


class TakeBody(BaseModel):
    path: str
    take: str
    status: str | None = None
    notes: str | None = None


class SelectBody(BaseModel):
    path: str
    shot: str
    choices: dict[str, str | None]


class CutBody(BaseModel):
    """Write the cut from approved takes, or change one clip (in, out, transition, audio)."""

    path: str
    episode: str
    use_approved: bool = False
    clip: int | None = None
    fields: dict[str, str | float | None] = {}


class ExportBody(BaseModel):
    path: str
    episode: str
    aspects: list[str] = ["16:9", "9:16"]
    subtitles: bool = True
    c2pa: bool = False  # sign each MP4 with a C2PA manifest of its takes
    otio: bool = False  # also write <episode>.otio and WAV stems
    sound: bool = True  # False: no audio stream, the lines are only subtitles


class PrevisBody(BaseModel):
    """Draw the e-conte sheet, the animatic and/or the mock render of an episode (each $0)."""

    path: str
    episode: str
    sheet: bool = True
    animatic: bool = True
    mock: bool = False  # every shot from its pills, no sound, lines as subtitles


class ShotFields(BaseModel):
    """Change a shot's description, duration or camera fields (``None`` removes a camera field)."""

    path: str
    shot: str
    fields: dict[str, str | float | None]


class CameraworkBody(BaseModel):
    """Put a camerawork template on a shot: a library ID (``anime/tu-slow``, copied into the
    show first) or a template of the show (``cam/tu-slow``). ``None`` takes the template off."""

    path: str
    shot: str
    template: str | None = None


class NewShot(BaseModel):
    path: str
    scene: str
    description: str
    duration: str = "3s"
    framing: str = "medium"


class NewScene(BaseModel):
    path: str
    episode: str
    heading: str
    location: str | None = None


class NewEpisode(BaseModel):
    path: str
    title: str
    season: str | None = None


class SheetBody(BaseModel):
    """A sheet image for a character, base64 (a ``data:`` URL is fine; 20 MB at most): it
    replaces ``sheet`` (the primary when empty), or with ``add`` it is a new sheet."""

    path: str
    entry: str
    data: str
    sheet: str | None = None
    add: bool = False


class CharacterBody(BaseModel):
    name: str
    description: str = ""
    sheet: str | None = None  # base64 or a data: URL; the whole sheet is the reference
    voice_id: str | None = None  # an ElevenLabs voice (GET /olf/voices)
    voice_name: str = ""


class CloneBody(BaseModel):
    """Design: Clone from sample. ``consent``: the person has the right to this voice and the
    speaker agreed to the clone (ElevenLabs asks the same)."""

    path: str
    character: str
    name: str = ""
    sample: str  # base64 or a data: URL: MP3, WAV, OGG or FLAC
    consent: bool = False


class VoiceBody(BaseModel):
    """Design: the character's Voice field. ``voice_id`` comes from ``GET /olf/voices``."""

    path: str
    character: str
    voice_id: str
    name: str = ""


class NewShowBody(BaseModel):
    """Design: New show. Without ``character`` and ``script``: "Skip to an empty project"."""

    title: str = "Untitled show"
    medium: str = "2D anime"
    aspect: str = "16:9"
    character: CharacterBody | None = None
    script: str | None = None


class ScriptBody(BaseModel):
    """A script (Fountain or plain text), or an idea for "Draft from idea". ``path`` is the show
    whose bible names are used; without it, ``characters`` (ID -> name) stand in (New show)."""

    script: str = ""
    idea: str = ""
    path: str | None = None
    episode: str | None = None
    characters: dict[str, str] = {}
    refs: bool = False  # price a keyframe from reference images (i2i), else from text (t2i)
    model: str | None = None  # the text model a person picked (GET /olf/models); else routing
    yes: bool = False
    max_total: float | None = None  # the price the Studio confirmed; a higher plan stops
    dry_run: bool = False


class CueBody(BaseModel):
    """Design: Add music cue. A new cue, rendered (price first) and placed in the audio list at
    ``start`` with ``volume`` and ducking under dialogue."""

    path: str
    episode: str
    kind: str = "music"
    description: str
    duration: float = 10.0
    start: float = 0.0
    volume: float = 0.6
    duck: bool = True
    model: str | None = None
    yes: bool = False
    max_total: float | None = None  # the price the Studio confirmed; a higher plan stops
    dry_run: bool = False


class FormBody(BaseModel):
    path: str
    entry: str
    name: str
    description: str
    palette: list[str] = []
    front: str | None = None  # base64 image of the front view


def _project(path: str) -> Project:
    try:
        return load(Path(path).expanduser())
    except OlfError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _no_journal(engine: Any, dry_run: bool) -> None:
    """OLF renders run inline workflows, which the durable journal does not record yet."""
    if getattr(engine, "_journal", None) is not None and not dry_run:
        raise HTTPException(
            status_code=409,
            detail="OLF renders skip the durable journal: run with VINCI_DURABLE_JOURNAL=off",
        )


def _olf(fn: Callable[[], T]) -> T:
    """Run an engine call; a project problem becomes HTTP 400 with the engine's message."""
    try:
        return fn()
    except OlfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sample")
def open_sample(request: Request) -> dict[str, str]:
    """Copy the tidewatch sample show into ``$VINCI_HOME/shows`` (once) and return its folder."""
    source = sample_path()
    if source is None:
        raise HTTPException(
            status_code=404, detail="the sample show ships only in a source checkout"
        )
    dest = Path(request.app.state.engine.config.home) / "shows" / "tidewatch"
    if not (dest / "project.yaml").is_file():
        shutil.copytree(source, dest, dirs_exist_ok=True)
        log.info("olf: copied the sample show to %s", dest)
    return {"path": str(dest)}


def _names(body: ScriptBody) -> dict[str, Any]:
    """Bible names for a script: the show's, or the wizard's characters and the default lenses."""
    if body.path:
        return bible_names(_project(body.path))
    return {"characters": body.characters, "lenses": ["24mm", "35mm", "50mm", "85mm"]}


def _unit_price(engine: Any, capability: str) -> dict[str, Any] | None:
    """The routed model for one ``capability`` node and its price; None when none is connected."""
    from vinci_core.catalog import price_key
    from vinci_core.cost import plan_workflow
    from vinci_protocol.models import WorkflowSpec

    node = {"id": "n", "type": "generate", "capability": capability, "params": {}}
    shape = {"id": "olf:price", "version": "0.1.0", "edges": [], "nodes": [node]}
    try:
        rows = plan_workflow(
            engine.catalog(),
            WorkflowSpec.model_validate(
                shape | {"preference": engine.config.preference or "cheapest"}
            ),
            available_providers=engine.routing_providers(),
        )
    except (KeyError, ValueError):
        return None
    model = rows[0]["model"]
    amount = float(rows[0]["estimate"].amount)
    return {"model": model.id, "amount": amount, "unpriced": bool(price_key(model)[0])}


@router.post("/new")
def new(body: NewShowBody, request: Request) -> dict[str, Any]:
    """Create a show in ``$VINCI_HOME/shows/<title>`` (design: New show): project and style, the
    first character, and episode 1 from the script. A failed create leaves no folder behind."""
    base = Path(request.app.state.engine.config.home) / "shows"
    slug = _slug(body.title) or "show"
    root = next(
        base / name
        for name in (slug, *(f"{slug}-{n}" for n in range(2, 1000)))
        if not (base / name).exists()
    )

    def create() -> dict[str, Any]:
        p = new_show(root, body.title, medium=body.medium, aspect=body.aspect)
        out: dict[str, Any] = {"path": str(root)}
        if body.character:
            c = body.character
            out["character"] = add_character(
                p,
                c.name,
                c.description,
                sheet=c.sheet,
                voice_id=c.voice_id,
                voice_name=c.voice_name,
            )
        if (body.script or "").strip():
            episode = add_episode(load(root), "Episode 1")
            out |= {"episode": episode} | import_script(load(root), episode, str(body.script))
        return out

    log.info("olf: new show %r in %s (script: %s)", body.title, root, bool(body.script))
    try:
        return _olf(create)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


@router.post("/script/preview")
def script_preview(body: ScriptBody, request: Request) -> dict[str, Any]:
    """The scenes and shots a script makes, without AI and without writing, and the price of one
    keyframe (design: "2 keyframe options per shot · est.")."""
    view = _olf(lambda: preview(body.script, **_names(body)))
    view["keyframe"] = _unit_price(request.app.state.engine, "i2i" if body.refs else "t2i")
    return view


@router.post("/script")
def script_import(body: ScriptBody) -> dict[str, Any]:
    """Add a script's scenes and shots to an episode (Storyboard: Shot list from script)."""
    if not body.path or not body.episode:
        raise HTTPException(status_code=400, detail="path and episode are required")
    p = _project(body.path)
    log.info("olf: import a script into %s in %s", body.episode, p.root)
    return _olf(lambda: import_script(p, str(body.episode), body.script))


@router.get("/models")
def models(capability: str, request: Request) -> dict[str, Any]:
    """The models a person may pick for one step (the text model menu): ``choices``, and
    ``auto``, the model routing picks with no choice (None when none is connected). An agent CLI
    (currency ``PLAN``) is only ever a choice: it bills the person's own sign-in."""
    eng = request.app.state.engine
    return {"choices": _choices(eng, capability), "auto": _unit_price(eng, capability)}


@router.post("/script/model")
def script_model(body: ScriptBody, request: Request) -> dict[str, Any]:
    """Split a script into shots with a text model, price first; the reply comes back parsed."""
    eng = request.app.state.engine
    _no_journal(eng, body.dry_run)
    names = _names(body)
    opts = {"yes": body.yes, "max_total": body.max_total, "dry_run": body.dry_run, "engine": eng}
    opts["model"] = body.model
    out = _olf(lambda: split_with_model(body.script, lenses=names.get("lenses"), **opts))
    if out["text"] is not None:
        out["preview"] = _olf(lambda: preview(out["text"], **names))
    return out


@router.post("/draft")
def draft_script(body: ScriptBody, request: Request) -> dict[str, Any]:
    """Draft a first episode script from an idea with a text model (design: Draft from idea)."""
    eng = request.app.state.engine
    _no_journal(eng, body.dry_run)
    cast = list(_names(body)["characters"].values())
    opts = {"yes": body.yes, "max_total": body.max_total, "dry_run": body.dry_run, "engine": eng}
    opts["model"] = body.model
    log.info(
        "olf: draft from an idea (%d characters), model=%s, dry_run=%s",
        len(cast),
        body.model or "auto",
        body.dry_run,
    )
    return _olf(lambda: draft(body.idea, cast=cast, **opts))


@router.post("/cue")
def new_cue(body: CueBody, request: Request) -> dict[str, Any]:
    """Add a music or SFX cue to an episode, render it and place it (Cut: Add music cue).

    The price comes first: a dry run writes nothing, and a cue is written only after its price
    is accepted (``yes``, ``max_total``). 409 while the durable journal is on.
    """
    eng = request.app.state.engine
    _no_journal(eng, body.dry_run)
    p = _project(body.path)
    if body.kind not in MAX_SECONDS or not 0.5 <= body.duration <= MAX_SECONDS[body.kind]:
        top = MAX_SECONDS.get(body.kind, 0)
        raise HTTPException(status_code=400, detail=f"a {body.kind} cue lasts 0.5 to {top:g} s")
    params = {"prompt": body.description, "duration": body.duration}
    plan = _olf(lambda: run_one(body.kind, params, model=body.model, dry_run=True, engine=eng))
    plan = {k: v for k, v in plan.items() if k not in ("output", "provenance")} | {"takes": []}
    log.info(
        "olf: cue %s %r (%s s) dry_run=%s in %s",
        body.kind,
        body.description,
        body.duration,
        body.dry_run,
        p.root,
    )
    if body.dry_run:
        return plan
    if body.max_total is not None and plan["total"] > body.max_total + 1e-9:
        raise HTTPException(status_code=400, detail="the price changed: check the price again")
    if (plan["total"] or plan["unpriced"]) and not body.yes:
        raise HTTPException(status_code=400, detail="this cue costs money: confirm the price first")

    def make() -> dict[str, Any]:
        doc = p.docs.get(body.episode)
        before = doc.path.read_text(encoding="utf-8") if doc else None
        cue = add_cue(p, body.episode, body.kind, body.description, body.duration)
        try:
            done = render_cue(
                load(p.root), cue, model=body.model, yes=True, max_total=plan["total"], engine=eng
            )
        except Exception:
            # Nothing was rendered: take the cue back out, or each retry adds another one.
            if doc is not None and before is not None:
                doc.path.write_text(before, encoding="utf-8")
            log.warning("olf: cue %s did not render; removed it from %s", cue, body.episode)
            raise
        audio = place_cue(
            load(p.root),
            body.episode,
            done["takes"][0],
            start=body.start,
            volume=body.volume,
            duck=body.duck,
        )
        return done | {"cue": cue, "audio": audio}

    return _olf(make)


@router.get("/project")
def project(path: str) -> dict[str, Any]:
    p = _project(path)
    return _olf(lambda: summary(p))


@router.get("/shot")
def shot(path: str, shot: str, request: Request) -> dict[str, Any]:
    """Resolved view, hashes, prompts, references, and the price of each render kind.

    A shot without dialogue gets an ``audio`` plan with an ``error`` (nothing to speak).
    """
    p = _project(path)
    detail = _olf(lambda: shot_detail(p, shot))
    eng = request.app.state.engine
    plans: dict[str, Any] = {}
    for kind in ("video", "keyframe", "audio"):
        try:
            plans[kind] = render(p, shot, kind=kind, dry_run=True, engine=eng)
            plans[kind]["choices"] = _choices(eng, plans[kind]["plan"][-1]["capability"])
        except OlfError as exc:
            plans[kind] = {"error": str(exc)}
    return detail | {"plans": plans}


def _choices(engine: Any, capability: str | None) -> list[dict[str, Any]]:
    """Models a person may pick for the last step (design: the video model menu): active, from a
    connected provider, cheapest first. ``unpriced`` marks a model with no flat price. An agent
    CLI row has ``tools``: True when the CLI keeps some of its own tools (the Studio warns)."""
    from vinci_core.catalog import price_key
    from vinci_provider_sdk.agent_cli import AGENT_CLIS

    if not capability:
        return []
    connected = engine.routing_providers()
    models = [
        m
        for m in engine.catalog().by_capability(capability)
        if m.provider in connected and m.status.value == "active"
    ]
    return [
        {
            "id": m.id,
            "name": m.display_name,
            "provider": m.provider,
            "amount": float(m.pricing.amount),
            "currency": m.pricing.currency,
            "unpriced": price_key(m)[0],
        }
        | ({"tools": not AGENT_CLIS[m.provider].tools_off} if m.provider in AGENT_CLIS else {})
        for m in sorted(models, key=price_key)
    ]


@router.post("/render")
def render_shot(body: RenderBody, request: Request) -> dict[str, Any]:
    eng = request.app.state.engine
    _no_journal(eng, body.dry_run)
    p = _project(body.path)
    log.info("olf: render %s kind=%s dry_run=%s in %s", body.shot, body.kind, body.dry_run, p.root)
    opts = body.model_dump(exclude={"path", "shot"})
    return _olf(lambda: render(p, body.shot, engine=eng, **opts))


@router.post("/batch")
def batch_render(body: BatchBody, request: Request) -> dict[str, Any]:
    """Plan an episode batch with one price, then run it shot after shot (``render_batch``)."""
    eng = request.app.state.engine
    _no_journal(eng, body.dry_run)
    p = _project(body.path)
    log.info(
        "olf: batch %s mode=%s dry_run=%s in %s", body.episode, body.mode, body.dry_run, p.root
    )
    return _olf(
        lambda: render_batch(
            p,
            body.episode,
            mode=body.mode,
            yes=body.yes,
            max_total=body.max_total,
            dry_run=body.dry_run,
            engine=eng,
        )
    )


@router.get("/stale")
def stale_cause(path: str, take: str) -> dict[str, Any]:
    """What changed since a take was rendered (``vinci_olf.explain``)."""
    p = _project(path)
    return _olf(lambda: explain(p, take))


@router.post("/keep")
def keep(body: KeepBody) -> dict[str, Any]:
    """Keep a stale take on purpose: its inputs_hash becomes current (kept_from records the old)."""
    p = _project(body.path)
    log.info("olf: keep %s in %s", body.take, p.root)
    return _olf(lambda: keep_take(p, body.take))


@router.patch("/take")
def review_take(body: TakeBody) -> dict[str, Any]:
    p = _project(body.path)
    return _olf(lambda: set_take(p, body.take, status=body.status, notes=body.notes))


@router.patch("/select")
def select_takes(body: SelectBody) -> dict[str, Any]:
    p = _project(body.path)
    return {"select": _olf(lambda: set_select(p, body.shot, **body.choices))}


@router.patch("/shot")
def edit_shot(body: ShotFields) -> dict[str, Any]:
    """Change shot fields in the file that holds the shot (one line each)."""
    p = _project(body.path)
    log.info("olf: shot %s fields %s in %s", body.shot, body.fields, p.root)
    return _olf(lambda: set_shot(p, body.shot, **body.fields))


@router.get("/camerawork")
def camerawork_library() -> dict[str, Any]:
    """The camerawork library that ships with the engine (the Studio's Camerawork menu). The
    templates a show has are in its bible (``GET /olf/project``)."""
    return {"library": library()}


@router.post("/camerawork")
def set_camerawork(body: CameraworkBody) -> dict[str, Any]:
    """Put a template on a shot: its camera, its default length and, for a BG-only template,
    an empty cast. A library template is copied into the show's bible first."""
    p = _project(body.path)
    log.info("olf: shot %s camerawork %s in %s", body.shot, body.template, p.root)
    return _olf(lambda: apply_template(p, body.shot, body.template))


@router.post("/shot")
def new_shot(body: NewShot) -> dict[str, str]:
    p = _project(body.path)
    shot = _olf(
        lambda: add_shot(
            p, body.scene, body.description, duration=body.duration, framing=body.framing
        )
    )
    log.info("olf: added shot %s in %s", shot, p.root)
    return {"shot": shot}


@router.post("/scene")
def new_scene(body: NewScene) -> dict[str, str]:
    p = _project(body.path)
    scene = _olf(lambda: add_scene(p, body.episode, body.heading, location=body.location))
    log.info("olf: added scene %s in %s", scene, p.root)
    return {"scene": scene}


@router.post("/episode")
def new_episode(body: NewEpisode) -> dict[str, str]:
    p = _project(body.path)
    episode = _olf(lambda: add_episode(p, body.title, season=body.season))
    log.info("olf: added episode %s in %s", episode, p.root)
    return {"episode": episode}


@router.post("/sheet")
def new_sheet(body: SheetBody) -> dict[str, str]:
    """Add a character sheet (``add``), or replace one in place under its file name."""
    p = _project(body.path)
    log.info("olf: sheet %s (add=%s) for %s in %s", body.sheet, body.add, body.entry, p.root)
    if body.add:
        return {"sheet": _olf(lambda: add_sheet(p, body.entry, body.data))}
    return {"file": _olf(lambda: replace_sheet(p, body.entry, body.data, sheet=body.sheet))}


@router.post("/form")
def new_form(body: FormBody) -> dict[str, str]:
    p = _project(body.path)
    form = _olf(
        lambda: add_form(
            p, body.entry, body.name, body.description, palette=body.palette, front=body.front
        )
    )
    return {"form": form}


@router.get("/voices")
def voices(request: Request) -> dict[str, Any]:
    """Voices a character can speak in (the Voice field): the ElevenLabs account's voices (a free
    call). Without ElevenLabs the list is empty: demo speech has one voice and needs no pick."""
    eng = request.app.state.engine
    if not eng.provider_available("elevenlabs"):
        return {"provider": None, "voices": []}
    try:
        rows = eng.providers["elevenlabs"].voices()
    except Exception as exc:  # noqa: BLE001 - a person sees why the list is empty
        log.warning("olf: ElevenLabs voices failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail=f"ElevenLabs gave no voice list: {exc}"
        ) from exc
    log.info("olf: %d ElevenLabs voices", len(rows))
    return {"provider": "elevenlabs", "voices": rows}


@router.post("/voice/clone")
def clone_voice_route(body: CloneBody, request: Request) -> dict[str, str]:
    """Clone a voice from a recording (ElevenLabs Instant Voice Cloning) and give it to the
    character. It needs consent and a connected ElevenLabs; the clone takes a voice slot."""
    import urllib.error

    from vinci_runtime.engine import provider_error_detail

    if not body.consent:
        raise HTTPException(
            status_code=400, detail="confirm that you have the right to this voice and its consent"
        )
    eng = request.app.state.engine
    if not eng.provider_available("elevenlabs"):
        raise HTTPException(status_code=400, detail="connect ElevenLabs to clone a voice")
    provider = eng.providers["elevenlabs"]
    p = _project(body.path)

    def clone(name: str, data: bytes, file: str) -> str:
        try:
            return str(provider.clone_voice(name, [(file, data)]))
        except urllib.error.HTTPError as exc:  # 422: too short or no speech; 401, 403: key, plan
            why = provider_error_detail(exc, [])
            raise OlfError(
                f"ElevenLabs refused the clone (HTTP {exc.code})" + (f": {why}" if why else "")
            ) from exc
        except (OSError, RuntimeError, ValueError) as exc:  # no network, a timeout, no voice_id
            log.warning("olf: voice clone for %s failed: %r", body.character, exc)
            reason = getattr(exc, "reason", None) or exc  # URLError keeps the cause in .reason
            raise OlfError(f"ElevenLabs could not clone the voice: {reason}") from exc

    log.info("olf: clone a voice for %s in %s", body.character, p.root)
    return {"voice": _olf(lambda: clone_voice(p, body.character, body.name, body.sample, clone))}


@router.post("/voice")
def pick_voice(body: VoiceBody) -> dict[str, str]:
    """Set the voice a character speaks in (design: Voice). Its dialogue takes go stale."""
    p = _project(body.path)
    return {"voice": _olf(lambda: set_voice(p, body.character, body.voice_id, body.name))}


@router.get("/cut")
def get_cut(path: str, episode: str) -> dict[str, Any]:
    """The episode's cut as clips on a timeline (``vinci_olf.cut.cut_view``), and whether the
    export can sign C2PA (``c2pa-python`` installed)."""
    p = _project(path)
    return _olf(lambda: cut_view(p, episode)) | {"c2pa": c2pa_available()}


@router.patch("/cut")
def patch_cut(body: CutBody) -> dict[str, Any]:
    p = _project(body.path)
    if body.use_approved:
        _olf(lambda: use_approved(p, body.episode))
    elif body.clip is not None:
        _olf(lambda: set_clip(p, body.episode, body.clip, **body.fields))
    log.info(
        "olf: cut %s use_approved=%s clip=%s %s",
        body.episode,
        body.use_approved,
        body.clip,
        body.fields,
    )
    return _olf(lambda: cut_view(_project(body.path), body.episode))


@router.post("/export")
def export_episode(body: ExportBody, request: Request) -> dict[str, Any]:
    """Export the cut with local ffmpeg (no model runs, no spend) into exports/<episode>/: the
    MP4s (signed with C2PA on request), and with ``otio`` an OpenTimelineIO file and stems."""
    p = _project(body.path)
    opts = body.model_dump(include={"subtitles", "c2pa", "otio", "sound"})
    log.info("olf: export %s aspects=%s %s in %s", body.episode, body.aspects, opts, p.root)
    home = Path(request.app.state.engine.config.home)  # keeps the local C2PA signer
    return _olf(lambda: export(p, body.episode, aspects=tuple(body.aspects), home=home, **opts))


@router.post("/previs")
def previs_episode(body: PrevisBody) -> dict[str, Any]:
    """The e-conte sheet (PDF and PNG pages), the animatic and the mock render (MP4s) in
    previs/<episode>/, with local Pillow and ffmpeg: no model runs, no spend."""
    from vinci_olf.previs import previs

    p = _project(body.path)
    picks = body.model_dump(include={"sheet", "animatic", "mock"})
    log.info("olf: previs %s %s in %s", body.episode, picks, p.root)
    return _olf(lambda: previs(p, body.episode, **picks))


@router.get("/share")
def share(path: str) -> FileResponse:
    """The show folder as one ``<show>.olf.zip`` (design: Share): plain OLF files to send.

    ``exports/`` and ``previs/`` are left out (derived files). A link that leaves the show is
    skipped, so a zip never carries a file from outside the folder.
    """
    p = _project(path)
    handle = tempfile.NamedTemporaryFile(prefix="olf-share-", suffix=".zip", delete=False)
    handle.close()
    count = 0
    try:
        with zipfile.ZipFile(handle.name, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(p.root.rglob("*")):
                rel = file.relative_to(p.root)
                if not file.is_file() or rel.parts[0] in DERIVED:
                    continue
                try:
                    p.inside(file)  # resolves links: one that leaves the show is skipped
                except OlfError:
                    log.warning("olf: share skips %s (outside the show)", rel)
                    continue
                archive.write(file, Path(p.root.name) / rel)
                count += 1
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)  # a failed zip leaves no temp file behind
        raise
    name = f"{p.manifest.get('show') or p.root.name}.olf.zip"
    log.info("olf: share %s as %s (%d files)", p.root, name, count)
    return FileResponse(
        handle.name,
        media_type="application/zip",
        filename=name,
        background=BackgroundTask(Path(handle.name).unlink, missing_ok=True),
    )


@router.get("/file")
def project_file(path: str, rel: str) -> FileResponse:
    """Serve a media file from inside the project folder (images, video, audio only)."""
    p = _project(path)
    target = _olf(lambda: p.inside(p.root / rel))
    if target.suffix.lower() not in MEDIA or not target.is_file():
        raise HTTPException(status_code=404, detail="no such media file in this project")
    return FileResponse(target)
