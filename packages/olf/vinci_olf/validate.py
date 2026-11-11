"""Validate an OLF project: the JSON Schema of each object, then references and rules."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from vinci_olf.layout import staging
from vinci_olf.project import ASSET_REF, OlfError, Project, frames, seconds
from vinci_olf.resolve import cue_view, resolve

SCHEMA: dict[str, Any] = json.loads(
    (files("vinci_olf") / "schema.json").read_text(encoding="utf-8")
)
BIBLE_REF = re.compile(r"^([a-z0-9-]+:)?(char|loc|prop|voice|cam)/[a-z0-9-]+$")
TAKE_KIND = {"kf": "keyframe", "v": "video", "a": "audio"}
Report = Callable[[str, str], None]  # (where, message)


@dataclass(frozen=True)
class Issue:
    """One validation finding."""

    level: str  # "error" or "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.where}: {self.message}"


def schema_errors(kind: str, data: Any) -> list[str]:
    """Return JSON Schema errors for ``data`` against ``#/$defs/<kind>``."""
    validator = Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": SCHEMA["$defs"]})
    return [
        f"{'.'.join(str(x) for x in err.absolute_path) or '(top)'}: {err.message}"
        for err in sorted(
            validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path))
        )
    ]


def _strings(value: Any) -> Iterator[str]:
    """Yield every string in ``value``, map keys included."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def validate(p: Project) -> list[Issue]:
    """Check a loaded project. An empty list of errors means the project is valid for v0.1.

    Args:
        p: The loaded project.

    Returns:
        Errors and warnings, in file order.
    """
    issues = [Issue("error", "project", problem) for problem in p.problems]

    def err(where: str, message: str) -> None:
        issues.append(Issue("error", where, message))

    def warn(where: str, message: str) -> None:
        issues.append(Issue("warning", where, message))

    for key, doc in p.docs.items():
        kind, where = p.kind(key), f"{p.rel(doc.path)} ({key})"
        if kind == "unknown":
            err(where, "the id matches no OLF id format")
            continue
        data = {k: v for k, v in doc.data.items() if not (kind == "scene" and k == "shots")}
        problems = schema_errors(kind, data)
        for message in problems:
            err(where, message)
        for text in _strings(data) if kind != "take" else ():
            if BIBLE_REF.match(text) and text not in p.docs:
                fork = " (forked bibles are not supported yet)" if ":" in text else ""
                err(where, f"unknown reference {text}{fork}")
            if ASSET_REF.match(text):
                _check_asset(p, text, doc.path.parent, where, err)
        # The extra rules assume the shapes the schema checks, so a file that failed it skips them
        # (a string `forms` or `cut` row crashed the whole check, and /olf/project with it).
        if not problems:
            _check_object(p, key, kind, doc.data, where, err, warn)
    for asset, entry in p.lock.items():
        _check_lock(p, asset, entry, err, warn)
    for message in schema_errors("lock", p.lock):
        err("assets/lock.yaml", message)
    if not any(i.level == "error" for i in issues):  # resolving needs every reference to exist
        used: dict[str, str] = {}  # shot -> its camerawork template
        views: dict[str, dict[str, Any]] = {}
        at = {k: f"{p.rel(d.path)} ({k})" for k, d in p.of_kind("shot").items()}
        for shot_id, where in at.items():
            if (view := _check_resolved(p, shot_id, where, err)) is not None:
                views[shot_id] = view
                if template := _check_camerawork(p, view, where, warn):
                    used[shot_id] = template
        ordered = sorted(p.of_kind("shot")) if used else []  # one scan: validate runs often
        for shot_id, template in used.items():  # rules that look at the other shots of the scene
            rules = p.docs[template].data.get("rules") or {}
            if not (rules.get("not_twice_in_a_row") or rules.get("max_per_scene")):
                continue
            scene = shot_id.rsplit("/", 1)[0] + "/"  # `e02/s03/`, so `e02/s030` is another scene
            before = [s for s in ordered if s < shot_id and s.startswith(scene)]
            if rules.get("not_twice_in_a_row") and before and used.get(before[-1]) == template:
                warn(at[shot_id], f"{template} follows itself: {before[-1]} uses it too")
            most = rules.get("max_per_scene")
            if most and sum(used.get(s) == template for s in before) >= most:
                warn(at[shot_id], f"{template} suits {most} shot(s) of a scene at most")
        for shot_id, plan in staging(p, views).items():  # pills: the 180° line of each scene
            if plan["crosses"]:
                warn(at[shot_id], f"Crosses the 180° line: {plan['crosses']}")
    if "license" not in p.manifest:
        warn("project.yaml", "add license (owner, terms): render copies it into the lock file")
    return issues


def _check_asset(p: Project, text: str, base: Any, where: str, err: Report) -> None:
    try:
        asset = p.asset_id(text, base)
    except OlfError as exc:
        err(where, str(exc))
        return
    digest = str(asset).removeprefix("asset/")
    if text.startswith("asset/"):
        if len(digest) != 64:
            err(where, f"{text}: an asset ID needs the full 64-character SHA-256 hash")
        elif f"asset/{digest}" not in p.lock:
            err(where, f"{text}: not in assets/lock.yaml")


def _check_object(
    p: Project, key: str, kind: str, data: dict[str, Any], where: str, err: Report, warn: Report
) -> None:
    """Rules that the schema cannot express."""
    parent = key.rsplit("/", 1)[0]
    if kind in ("scene", "shot", "take") and not (_is_cue(p, parent) or parent in p.docs):
        (warn if kind == "take" else err)(where, f"its parent {parent} is missing")
    for field in ("sfx", "music") if kind in ("scene", "shot") else ():
        refs = (data.get("audio") or {}).get(field)
        for cue in [refs] if isinstance(refs, str) else refs or []:
            if not _is_cue(p, cue):
                err(where, f"audio.{field}: {cue} is not in its episode's cues")
    # Only levels that choose looks: a character's own `forms` defines them (a form named
    # `style` once matched the style document).
    for field in ("forms", "outfits") if kind in ("season", "episode", "scene", "shot") else ():
        for cid, name in (data.get(field) or {}).items():
            char = p.docs.get(cid)
            if char is not None and name not in (char.data.get(field) or {}):
                err(where, f"{cid} has no {field[:-1]} named {name!r}")
    if kind == "character":
        refs = [data.get(k) for k in ("sheet", "sheets", "references", "forms", "details")]
        if not any(ASSET_REF.match(text) for text in _strings(refs)):
            err(where, "a character needs a sheet or another reference image")
        likeness = data.get("likeness") or {}
        if likeness.get("real_person") and not likeness.get("consent"):
            warn(where, "a real person SHOULD point likeness.consent to a consent record")
    if kind == "scene" and (loc := p.docs.get(str(data.get("location")))) and "variant" in data:
        if data["variant"] not in (loc.data.get("variants") or [data["variant"]]):
            err(where, f"{data['location']} has no variant {data['variant']!r}")
    if kind == "season":
        for episode in data.get("episodes") or []:
            owner = p.season_of(episode)
            if episode not in p.docs:
                err(where, f"episode {episode} is missing")
            elif owner is not None and owner.data.get("id") != key:
                err(
                    where,
                    f"{episode} is also in {owner.data.get('id')}: one season per episode",
                )
    if kind == "episode":
        for scene in data.get("scenes") or []:
            if scene not in p.docs:
                err(where, f"scene {scene} is missing")
        for row in [*(data.get("cut") or []), *(data.get("audio") or [])]:
            if row.get("take") not in p.docs:
                err(where, f"take {row.get('take')} is missing")
    if kind == "take":
        segment = re.sub(r"\d+$", "", key.rsplit("/", 1)[-1])
        if data.get("kind") != TAKE_KIND.get(segment):
            err(
                where,
                f"kind {data.get('kind')!r} does not match the id (want {TAKE_KIND.get(segment)})",
            )
        if data.get("output") not in p.lock:
            warn(where, f"output {data.get('output')} is not in assets/lock.yaml")


def _is_cue(p: Project, cue_id: str) -> bool:
    """True for a cue that its episode lists under ``cues`` (``e02/cue/theme``)."""
    try:
        return "/cue/" in cue_id and bool(cue_view(p, cue_id))
    except OlfError:
        return False


def _check_lock(p: Project, asset: str, entry: Any, err: Report, warn: Report) -> None:
    if not isinstance(entry, dict):
        return
    where, uri = f"assets/lock.yaml ({asset})", str(entry.get("uri") or "")
    if entry.get("hash") != "sha256:" + asset.removeprefix("asset/"):
        err(where, "hash does not match the asset ID")
    if "://" in uri:
        warn(where, f"{uri}: remote URIs are not verified yet")
        return
    try:
        p.local_file(asset)
    except OlfError as exc:
        err(where, str(exc))


def _check_camerawork(p: Project, view: dict[str, Any], where: str, warn: Report) -> str | None:
    """Warn when a shot does not suit its camerawork template, and return the template's ID.

    The template states what it suits (``framing``, ``timing``, ``slots``, ``rules``). A shot
    can still go against it on purpose, so each finding is a warning.
    """
    camera = view.get("camera") or {}
    if not isinstance(camera.get("template"), dict):
        return None
    name: str = camera["template"]["id"]
    entry = p.docs[name].data
    rules, timing = entry.get("rules") or {}, entry.get("timing") or {}
    suits = entry.get("framing") or []
    if suits and camera.get("framing") not in suits:
        warn(where, f"{name} suits the framings {', '.join(suits)}, not {camera.get('framing')}")
    length = float(view.get("duration") or 0)
    low, high = timing.get("min"), timing.get("max")
    if low is not None and length < seconds(low):
        warn(where, f"{name} suits at least {low}: the shot is {frames(length)}")
    if high is not None and length > seconds(high):
        warn(where, f"{name} suits at most {high}: the shot is {frames(length)}")
    slots, cast = entry.get("slots"), view.get("characters") or []
    if slots == [] and cast:
        warn(where, f"{name} is a BG-only move: set `characters: []` on the shot")
    elif slots and len(cast) < len(slots):
        warn(where, f"{name} needs {len(slots)} characters in the shot: it has {len(cast)}")
    if "needs_dialogue" in rules and rules["needs_dialogue"] != bool(view.get("dialogue")):
        need = "with a dialogue line" if rules["needs_dialogue"] else "with no dialogue"
        warn(where, f"{name} is for a shot {need}")
    if rules.get("needs_prop") and not view.get("props"):
        warn(where, f"{name} is for a shot of a prop: name it in the shot's props")
    if "max_amount" in rules and float(camera.get("amount") or 0) > rules["max_amount"]:
        warn(
            where,
            f"{name} is a small move: amount {camera['amount']:g} is over {rules['max_amount']:g}",
        )
    if "max_move" in rules:
        move = length - float(camera.get("hold_start") or 0) - float(camera.get("hold_end") or 0)
        if move > seconds(rules["max_move"]) + 1e-9:
            warn(
                where,
                f"{name} is a quick move of {rules['max_move']} at most: this move takes "
                f"{frames(move)} (make a hold longer)",
            )
    return name


def _check_resolved(p: Project, shot_id: str, where: str, err: Report) -> dict[str, Any] | None:
    """Check a shot's resolved view, and return it (None when the shot does not resolve)."""
    try:
        view = resolve(p, shot_id)
    except OlfError as exc:
        err(where, str(exc))
        return None
    lens, lenses = (
        (view.get("camera") or {}).get("lens"),
        (view.get("style") or {}).get("lenses") or [],
    )
    if lens and lens not in lenses:  # the resolved style includes episode overrides
        err(where, f"lens {lens} is not in style.lenses {lenses}")
    cast = {c["id"] for c in view.get("characters") or []}
    for line in view.get("dialogue") or []:
        if line.get("speaker") not in cast:
            err(where, f"speaker {line.get('speaker')} is not in the shot's characters")
    for cid in view.get("blocking") or {}:
        if cid not in cast:
            err(where, f"blocking names {cid}, who is not in the shot's characters")
    for name in (view.get("select") or {}).values():
        if f"{shot_id}/{name}" not in p.docs:
            err(where, f"select names {name}, but take {shot_id}/{name} is missing")
    return view
