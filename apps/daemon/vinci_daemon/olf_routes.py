"""OLF movie engine routes for the Studio Shows page (``vinci_olf``, Apache-2.0).

``create_app`` mounts this router only when ``vinci_olf`` imports, so a build without it
(the Mac bundle today) has no ``/olf`` paths and the Studio shows that the page is off.
A project is a folder on this computer; every file the routes read or write stays inside it.
"""

from __future__ import annotations

import logging
import math
import shutil
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
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
    add_storyboard,
    apply_template,
    clone_voice,
    new_show,
    read_source,
    replace_sheet,
    set_entry,
    set_reference,
    set_scene_cast,
    set_shot,
    set_variant,
    set_voice,
    write_source,
)
from vinci_olf.batch import render_batch
from vinci_olf.cues import MAX_SECONDS, add_cue, place_cue, render_cue
from vinci_olf.cut import cut_view, use_approved
from vinci_olf.edit import set_clip, set_select, set_take
from vinci_olf.explain import explain, keep_take
from vinci_olf.export import export
from vinci_olf.package import pack, unpack
from vinci_olf.project import EXTS, read
from vinci_olf.provenance import available as c2pa_available
from vinci_olf.render import render, run_one
from vinci_olf.scene_lab import build, check, keep_room, overview, save_answer, use
from vinci_olf.script import bible_names, draft, import_script, preview, split_with_model

from vinci_daemon import projects

log = logging.getLogger("vinci.olf")
router = APIRouter(prefix="/olf", tags=["olf"])
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".wav", ".mp3", ".m4a"}
MEDIA |= {".pdf"}  # the e-conte sheet (previs)
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


class SceneCast(BaseModel):
    path: str
    scene: str
    characters: list[str]


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


class StoryboardBody(BaseModel):
    """A shot's 3D pill frame, base64 PNG (a ``data:`` URL is fine), rendered by the Studio."""

    path: str
    shot: str
    data: str


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
    project_id: str | None = None  # the Studio project the show belongs to (COREPRODUC-702)
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
    copy: bool = False  # answer with the prompt for the person's own agent; no model runs


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


class EntryBody(BaseModel):
    """A bible entry's new name and/or description (COREPRODUC-682)."""

    path: str
    entry: str
    name: str | None = None
    description: str | None = None


class ReferenceBody(BaseModel):
    """A reference image of a bible entry: ``data`` adds one (named by ``label``), ``data`` and
    ``ref`` replace that file, ``ref`` and ``remove`` take it out."""

    path: str
    entry: str
    data: str | None = None  # base64 image (a ``data:`` URL is fine; 20 MB at most)
    ref: str | None = None
    label: str | None = None
    remove: bool = False


class SourceBody(BaseModel):
    """A bible entry's YAML file as a person wrote it (Edit YAML, COREPRODUC-683)."""

    path: str
    entry: str
    text: str


class VariantBody(BaseModel):
    path: str
    entry: str
    name: str
    remove: bool = False


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


@router.get("/shows")
def list_shows(request: Request, project: str = "") -> dict[str, list[dict[str, str]]]:
    """The shows in ``$VINCI_HOME/shows``, last changed first, for the open screen's list.

    A folder counts when it has a manifest (``project.yaml``, ``.yml`` or ``.json``); its
    ``title`` names it. A show in another folder still opens by its path. With ``project``:
    only that Studio project's shows.
    """
    engine = request.app.state.engine
    if project:
        projects.store(engine).get(project)  # 404 for an unknown project
    inside = projects.member(engine, "show", project) if project else (lambda _key: True)
    rows = []
    home = Path(request.app.state.engine.config.home) / "shows"
    found = (m for ext in reversed(EXTS) for m in home.glob(f"*/project{ext}") if m.is_file())
    manifests = {m.parent: m for m in found}
    for manifest in manifests.values():  # project.yaml wins over .yml and .json, as in load()
        try:
            title = (read(manifest) or {}).get("title")
        except Exception:  # noqa: BLE001 - a broken manifest still lists, by its folder name
            title = None
        if not inside(projects.show_key(manifest.parent)):
            continue
        changed = max(manifest.stat().st_mtime, manifest.parent.stat().st_mtime)
        rows.append(
            {
                # Resolved, as /project reports it: a URL slug's key hashes it (COREPRODUC-698).
                "path": str(manifest.parent.resolve()),
                "title": str(title or manifest.parent.name),
                "updated_at": datetime.fromtimestamp(changed, UTC).isoformat(),
            }
        )
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    log.info("olf: %d shows in %s", len(rows), Path(request.app.state.engine.config.home))
    return {"shows": rows}


class SampleBody(BaseModel):
    project_id: str | None = None


@router.post("/sample")
def open_sample(request: Request, body: SampleBody | None = None) -> dict[str, str]:
    """Copy the tidewatch sample show into ``$VINCI_HOME/shows`` (once) and return its folder.

    My work keeps ``shows/tidewatch``; a named project gets its own copy, ``tidewatch-<id8>``, so
    the sample opened in one project never shows up as another project's (CodeRabbit on #682).
    """
    engine = request.app.state.engine
    project_id = projects.stamp(engine, body.project_id if body else None)
    source = sample_path()
    if source is None:
        raise HTTPException(
            status_code=404, detail="the sample show ships only in a source checkout"
        )
    named = project_id and project_id != projects.DEFAULT_ID
    folder = f"tidewatch-{project_id[:8]}" if named else "tidewatch"
    dest = Path(engine.config.home) / "shows" / folder
    if not (dest / "project.yaml").is_file():
        shutil.copytree(source, dest, dirs_exist_ok=True)
        log.info("olf: copied the sample show to %s", dest)
    projects.store(engine).link("show", projects.show_key(dest), project_id)
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
    engine = request.app.state.engine
    project_id = projects.stamp(engine, body.project_id)  # checked before any file is written
    base = Path(request.app.state.engine.config.home) / "shows"
    slug = _slug(body.title) or "show"
    base.mkdir(parents=True, exist_ok=True)
    # Claim the folder, as Import does: with an exists() check, two New shows with one title at
    # once wrote one folder, and the second took the show's project link (CodeRabbit on #691).
    for name in (slug, *(f"{slug}-{n}" for n in range(2, 1000))):
        root = base / name
        try:
            root.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise HTTPException(status_code=409, detail=f"too many shows named {slug}")

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

    log.info(
        "olf: new show %r in %s (script: %s, project: %s)",
        body.title,
        root,
        bool(body.script),
        project_id,
    )
    try:
        out = _olf(create)
        projects.store(engine).link("show", projects.show_key(root), project_id, fresh=True)
        return out
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
    _no_journal(eng, body.dry_run or body.copy)
    names = _names(body)
    opts = {"yes": body.yes, "max_total": body.max_total, "dry_run": body.dry_run, "engine": eng}
    opts |= {"model": body.model, "copy": body.copy}
    out = _olf(lambda: split_with_model(body.script, lenses=names.get("lenses"), **opts))
    if out["text"] is not None:
        out["preview"] = _olf(lambda: preview(out["text"], **names))
    return out


@router.post("/draft")
def draft_script(body: ScriptBody, request: Request) -> dict[str, Any]:
    """Draft a first episode script from an idea with a text model (design: Draft from idea)."""
    eng = request.app.state.engine
    _no_journal(eng, body.dry_run or body.copy)
    cast = list(_names(body)["characters"].values())
    opts = {"yes": body.yes, "max_total": body.max_total, "dry_run": body.dry_run, "engine": eng}
    opts |= {"model": body.model, "copy": body.copy}
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
    from vinci_core.cost import asked_chars

    p = _project(path)
    detail = _olf(lambda: shot_detail(p, shot))
    eng = request.app.state.engine
    plans: dict[str, Any] = {}
    # A video row is priced for the clip the engine asks: the shot's length, rounded up.
    length = math.ceil(float((detail.get("resolved") or {}).get("duration") or 0)) or None
    for kind in ("video", "keyframe", "audio"):
        try:
            plans[kind] = render(p, shot, kind=kind, dry_run=True, engine=eng)
            seconds = length if kind == "video" else None
            lines = (detail.get("resolved") or {}).get("dialogue") or [] if kind == "audio" else []
            # A speech row costs these lines, as the plan does, not 1,000 chars (COREPRODUC-789).
            # Counted as the planner counts a line (asked_chars), so the row matches the plan.
            said = [str(x["line"]) for x in lines if isinstance(x, dict) and x.get("line")]
            chars = [asked_chars({"prompt": line}) for line in said]
            cap = plans[kind]["plan"][-1]["capability"]
            plans[kind]["choices"] = _choices(eng, cap, seconds, chars or None)
        except OlfError as exc:
            plans[kind] = {"error": str(exc)} | ({"notes": list(exc.notes)} if exc.notes else {})
            if exc.pick:  # a model pick, not a failure: the shot page shows a hint (COREPRODUC-793)
                plans[kind]["pick"] = True
            if kind == "video" and _by_reference(detail):  # the person picks a reference model
                plans[kind]["choices"] = _choices(eng, "r2v", length)
                # An empty menu: say what to connect, as the host does.
                if exc.pick and not plans[kind]["choices"]:
                    plans[kind]["error"] = REFERENCE_CONNECT
    return detail | {"plans": plans}


# A reference shot whose menu is empty (PR-Agent on #800): a hint to pick from nothing helps no one.
REFERENCE_CONNECT = (
    "A reference render needs a reference-to-video model: paste a Wavespeed key on Connect, "
    "then pick Seedance 2.5 reference in the video model menu."
)


def _by_reference(detail: dict[str, Any]) -> bool:
    """Whether a shot renders its video from its pin video (``camera.render: reference``)."""
    return ((detail.get("resolved") or {}).get("camera") or {}).get("render") == "reference"


def _choices(
    engine: Any,
    capability: str | None,
    seconds: float | None = None,
    chars: list[int | None] | None = None,
) -> list[dict[str, Any]]:
    """Models a person may pick for the last step (design: the video model menu): active, from a
    connected provider, cheapest first. ``unpriced`` marks a model with no flat price. An agent
    CLI row has ``tools``: True when the CLI keeps some of its own tools (the Studio warns).

    ``amount`` is one job of ``seconds`` (``vinci_core.cost.clip_price``), as the engine bills it.
    Bug fixed (first occurrence, 2026-11-20, a live run): a picked video model showed its 5 s
    price ($1.10 for a 6 s shot that bills $1.32), so the confirm was below the plan and
    ``max_total`` would stop the run (seen at the confirm, before the click).
    ``chars``: the characters of each dialogue line, so a speech row costs the shot's lines.
    """
    from vinci_core.catalog import price_key
    from vinci_core.cost import clip_price
    from vinci_provider_sdk.agent_cli import AGENT_CLIS

    if not capability:
        return []
    connected = engine.routing_providers()
    models = [
        m
        for m in engine.catalog().by_capability(capability)
        if m.provider in connected and m.status.value == "active"
    ]
    rows = [
        {
            "id": m.id,
            "name": m.display_name,
            "provider": m.provider,
            "amount": float(
                sum(clip_price(m, seconds, n) for n in chars) if chars else clip_price(m, seconds)
            ),
            "currency": m.pricing.currency,
            "unpriced": price_key(m)[0],
        }
        | ({"tools": not AGENT_CLIS[m.provider].tools_off} if m.provider in AGENT_CLIS else {})
        for m in models
    ]
    # Cheapest first at this length: a row with a per-length table can pass another (CodeRabbit).
    return sorted(rows, key=lambda row: (row["unpriced"], row["amount"]))


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


@router.patch("/scene")
def edit_scene(body: SceneCast) -> dict[str, list[str]]:
    """Set who is in a scene: its shots take this cast (COREPRODUC-770)."""
    p = _project(body.path)
    log.info("olf: scene %s cast %s in %s", body.scene, body.characters, p.root)
    return {"characters": _olf(lambda: set_scene_cast(p, body.scene, body.characters))}


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


class SceneBody(BaseModel):
    """A scene lab request (COREPRODUC-720): ``target`` is a scene (build its room) or a shot
    (stage it in the scene's room). ``text`` is an answer pasted from the person's own agent."""

    path: str
    target: str
    request: str = ""
    room: int | None = None  # the room version to stage in; the newest when left out
    base: int | None = None  # a try to start from (the compare screen)
    text: str = ""
    model: str | None = None
    yes: bool = False
    max_total: float | None = None
    dry_run: bool = False
    copy_prompt: bool = Field(False, alias="copy")  # `copy` would shadow BaseModel.copy


class RoomBody(BaseModel):
    """A new room version: from a room try (``room_try``) or from hand-edited ``pieces``."""

    path: str
    scene: str
    room_try: int | None = None
    pieces: list[dict[str, Any]] | None = None
    source: str | None = None


class SceneCheckBody(BaseModel):
    """An unsaved try (a hand edit) to check."""

    path: str
    shot: str
    data: dict[str, Any]


class SceneUseBody(BaseModel):
    """Use a shot try as the shot's keyframe layout; ``frame`` is its start frame (base64 PNG)."""

    path: str
    shot: str
    n: int
    frame: str
    pin: str = "pin"  # the pin shape in the frame (the comparison, COREPRODUC-718)
    video: str | None = None  # the try's pin video, base64 (COREPRODUC-732)
    video_raw: bool = False  # `video` is a raw H.264 stream (WebCodecs frames at 24 fps)


@router.get("/scene")
def scene_overview(path: str, target: str) -> dict[str, Any]:
    """The scene lab of a scene or a shot: room versions, the newest room, the shot's tries."""
    return _olf(lambda: overview(_project(path), target))


@router.post("/scene/build")
def scene_build(body: SceneBody, request: Request) -> dict[str, Any]:
    """Build a room or stage a shot with a text model, price first, or copy the prompt."""
    eng = request.app.state.engine
    _no_journal(eng, body.dry_run or body.copy_prompt)
    run = {"yes": body.yes, "max_total": body.max_total, "dry_run": body.dry_run, "engine": eng}
    run |= {"model": body.model, "copy": body.copy_prompt}
    log.info(
        "olf: scene lab build %s, model=%s, copy=%s",
        body.target,
        body.model or "auto",
        body.copy_prompt,
    )
    return _olf(
        lambda: build(
            _project(body.path), body.target, body.request, room=body.room, base=body.base, **run
        )
    )


@router.post("/scene/paste")
def scene_paste(body: SceneBody) -> dict[str, Any]:
    """Save an answer pasted from the person's own agent, read like a model's."""
    log.info("olf: scene lab paste for %s (%d characters)", body.target, len(body.text))
    p = _project(body.path)
    return _olf(
        lambda: save_answer(p, body.target, body.text, request=body.request, room=body.room)
    )


@router.post("/scene/room")
def scene_room(body: RoomBody) -> dict[str, int]:
    """Save a new room version of a scene; older versions and their frames stay as they are."""
    p = _project(body.path)
    opts = {"room_try": body.room_try, "pieces": body.pieces, "source": body.source}
    return {"version": _olf(lambda: keep_room(p, body.scene, **opts))}


@router.post("/scene/check")
def scene_check(body: SceneCheckBody) -> dict[str, Any]:
    """Check a hand-edited try as saving would, and save nothing."""
    return {"issues": _olf(lambda: check(_project(body.path), body.shot, body.data))}


@router.post("/scene/use")
def scene_use(body: SceneUseBody) -> dict[str, Any]:
    """Use a shot try: its start frame as the keyframe layout, its places as the pills."""
    p = _project(body.path)
    log.info("olf: scene lab use %s try %d", body.shot, body.n)
    args = (body.shot, body.n, body.frame, body.pin, body.video, body.video_raw)
    return _olf(lambda: use(p, *args))


@router.post("/storyboard")
def new_storyboard(body: StoryboardBody) -> dict[str, str]:
    """Save a shot's 3D pill frame as its ``control.storyboard`` (the keyframe's layout)."""
    p = _project(body.path)
    log.info("olf: storyboard for %s in %s", body.shot, p.root)
    return {"storyboard": _olf(lambda: add_storyboard(p, body.shot, body.data))}


@router.post("/form")
def new_form(body: FormBody) -> dict[str, str]:
    p = _project(body.path)
    form = _olf(
        lambda: add_form(
            p, body.entry, body.name, body.description, palette=body.palette, front=body.front
        )
    )
    return {"form": form}


@router.patch("/entry")
def edit_entry(body: EntryBody) -> dict[str, str]:
    """Change a bible entry's name and/or description."""
    p = _project(body.path)
    log.info("olf: entry %s in %s", body.entry, p.root)
    name, text = body.name, body.description
    return {"entry": _olf(lambda: set_entry(p, body.entry, name=name, description=text))}


@router.post("/reference")
def edit_reference(body: ReferenceBody) -> dict[str, str]:
    """Add, replace or remove a reference image of a bible entry."""
    p = _project(body.path)
    log.info("olf: reference %s (remove=%s) of %s in %s", body.ref, body.remove, body.entry, p.root)
    ref = _olf(
        lambda: set_reference(
            p, body.entry, data=body.data, ref=body.ref, label=body.label, remove=body.remove
        )
    )
    return {"reference": ref}


@router.get("/source")
def get_source(path: str, entry: str) -> dict[str, str]:
    """A bible entry's YAML file as written: ``{file, text}``."""
    p = _project(path)
    return _olf(lambda: read_source(p, entry))


@router.put("/source")
def put_source(body: SourceBody) -> dict[str, str]:
    """Save a bible entry's YAML file if the show stays as valid as before (else a 400)."""
    p = _project(body.path)
    log.info("olf: YAML of %s by hand (%d chars) in %s", body.entry, len(body.text), p.root)
    return {"file": _olf(lambda: write_source(p, body.entry, body.text))}


@router.post("/variant")
def edit_variant(body: VariantBody) -> dict[str, list[str]]:
    """Add a variant to a location, or remove one that no scene picks."""
    p = _project(body.path)
    log.info("olf: variant %s (remove=%s) of %s in %s", body.name, body.remove, body.entry, p.root)
    return {"variants": _olf(lambda: set_variant(p, body.entry, body.name, remove=body.remove))}


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
    """The show folder as one ``<show>.volf`` package (design: Share; SPEC.md, Package).

    ``vinci_olf.package.pack`` leaves out ``exports/``, ``previs/`` and links that leave the show.
    """
    p = _project(path)
    handle = tempfile.NamedTemporaryFile(prefix="olf-share-", suffix=".volf", delete=False)
    handle.close()
    try:
        count = _olf(lambda: pack(p, handle.name))  # too large for one package: HTTP 400
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)  # a failed zip leaves no temp file behind
        raise
    name = f"{p.manifest.get('show') or p.root.name}.volf"  # was .olf.zip until 2026-11-18
    log.info("olf: share %s as %s (%d files)", p.root, name, count)
    return FileResponse(
        handle.name,
        media_type="application/zip",
        filename=name,
        background=BackgroundTask(Path(handle.name).unlink, missing_ok=True),
    )


@router.post("/import")
def import_show(
    request: Request, file: UploadFile, project_id: str = Form("")
) -> dict[str, Any]:
    """Unpack a ``.volf`` package as a new show in ``$VINCI_HOME/shows`` (design: Import show).

    The folder is named after the show ID (``tidewatch``, then ``tidewatch-2``...), so an import
    never writes over a show. A show with OLF issues still imports: the Studio lists them, as for
    any folder. A file that is not a package, or breaks a package rule, is refused (HTTP 400).
    The show joins ``project_id`` (COREPRODUC-702; empty: My work), as on the host.
    """
    engine = request.app.state.engine
    project = projects.stamp(engine, project_id)  # checked before any file is written
    shows = Path(engine.config.home) / "shows"
    shows.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".import-", dir=shows))  # same disk: a rename moves it
    try:
        root = _olf(lambda: unpack(file.file, staging / "show"))
        p = _olf(lambda: load(root))  # a manifest that does not load is the package's fault: 400
        name = str(p.manifest.get("show") or Path(file.filename or "show").stem)
        slug = _slug(name)[:64].strip("-") or "show"  # a folder name has a length limit
        for n in range(1, 1000):
            dest = shows / (slug if n == 1 else f"{slug}-{n}")
            try:
                dest.mkdir()  # claims the name: a parallel import of one show gets the next
            except FileExistsError:
                continue
            try:
                root.replace(dest)  # onto the empty folder just claimed (POSIX rename)
            except OSError:
                dest.rmdir()  # give the name back: a failed import leaves no empty show
                raise
            break
        else:
            raise HTTPException(status_code=409, detail=f"too many shows named {slug}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    try:
        projects.store(engine).link("show", projects.show_key(dest), project, fresh=True)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)  # as New show: a failed import leaves no show
        raise
    log.info("olf: imported %s as %s (project %s)", file.filename, dest, project or "default")
    # Resolved, as /shows and /project report it (a URL slug's key hashes it, COREPRODUC-698).
    return {"path": str(dest.resolve()), "title": str(p.manifest.get("title") or dest.name)}


@router.get("/file")
def project_file(path: str, rel: str) -> FileResponse:
    """Serve a media file from inside the project folder (images, video, audio only)."""
    p = _project(path)
    target = _olf(lambda: p.inside(p.root / rel))
    if target.suffix.lower() not in MEDIA or not target.is_file():
        raise HTTPException(status_code=404, detail="no such media file in this project")
    return FileResponse(target)
