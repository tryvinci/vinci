"""Resolve a shot through the OLF levels, and hash what a take used.

Levels (SPEC.md, Layering and overrides): project defaults, show bible, season (when a
season lists the episode), episode, scene, shot. Takes are outputs and never override
anything. The hash rules are in SPEC.md, Hash input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from vinci_olf.project import Doc, OlfError, Project, seconds

EPISODE_OVERRIDES = ("defaults", "forms", "outfits", "style", "extensions")  # also a season's
NOT_RENDERED = ("credits", "license", "likeness")  # an edit here never makes a take stale
DURATION_KEYS = {"duration", "in", "out", "start", "hold_start", "hold_end"}
TEMPLATE_WORDS = ("keyframe", "prompt", "avoid")  # the template fields that change a render
# Camera fields that only a video uses: a keyframe take leaves them out of its hash. A keyframe
# keeps `canvas`: a drawing of another shape is a new drawing.
MOTION = ("move", "direction", "amount", "ease", "hold_start", "hold_end", "center", "render")


def merge(base: Any, over: Any) -> Any:
    """Merge ``over`` (the lower level) onto ``base`` with the OLF merge rules.

    Scalars and lists replace. Maps merge key by key. ``{$append: [...], $remove: [...]}``
    edits the list from the level above.
    """
    if isinstance(over, dict) and ("$append" in over or "$remove" in over):
        drop = over.get("$remove") or []
        kept = [x for x in (base if isinstance(base, list) else []) if x not in drop]
        return kept + [x for x in over.get("$append") or [] if x not in kept]
    if isinstance(over, dict):
        base = base if isinstance(base, dict) else {}
        return {**base, **{k: merge(base.get(k), v) for k, v in over.items()}}
    return copy.deepcopy(over)


def _levels(p: Project, shot_id: str) -> list[tuple[str, dict[str, Any]]]:
    """The levels of a shot, top to bottom, as (name, fields) with asset references hashed."""
    shot, scene, episode = (
        p.docs.get(i) for i in (shot_id, shot_id.rsplit("/", 1)[0], shot_id.split("/")[0])
    )
    if shot is None or p.kind(shot_id) != "shot":
        raise OlfError(f"{shot_id}: no such shot")
    if scene is None or episode is None:
        raise OlfError(f"{shot_id}: its scene or episode file is missing")
    manifest, style, season = (
        p.docs["project"],
        p.docs.get("style"),
        p.season_of(episode.data["id"]),
    )
    return [
        ("project", _pick(p, manifest, ("defaults", "extensions"))),
        ("bible", {"style": _entry(p, "style")} if style else {}),
        ("season", _pick(p, season, EPISODE_OVERRIDES) if season else {}),
        ("episode", _pick(p, episode, EPISODE_OVERRIDES)),
        ("scene", _pick(p, scene, tuple(k for k in scene.data if k != "shots"))),
        ("shot", p.hashed(shot.data, shot.path.parent)),
    ]


def resolve(p: Project, shot_id: str) -> dict[str, Any]:
    """Return the resolved view of a shot: all levels merged, bible entries embedded.

    Args:
        p: The loaded project.
        shot_id: A shot ID such as ``e02/s03/sh014``.

    Raises:
        OlfError: The shot, its scene or episode, or a bible entry it names is missing.
    """
    view: dict[str, Any] = {}
    for _, level in _levels(p, shot_id):
        view = merge(view, level)
    looks = {"forms": view.pop("forms", None) or {}, "outfits": view.pop("outfits", None) or {}}
    if "location" in view:
        view["location"] = _entry(p, view["location"])
        view["location"].pop("variants", None)
        if "variant" in view:
            view["location"]["variant"] = view.pop("variant")
    if "characters" in view:
        view["characters"] = [_character(p, cid, looks) for cid in view["characters"]]
    if "props" in view:
        view["props"] = [_entry(p, pid) for pid in view["props"]]
    if isinstance(view.get("camera"), dict) and "template" in view["camera"]:
        view["camera"] = _camerawork(p, view["camera"])
    resolved: dict[str, Any] = _seconds({"id": view.pop("id"), **view})  # id first, for people
    return resolved


def origins(p: Project, shot_id: str) -> dict[str, Any]:
    """Return which level last set each field of a shot, and each character's form and outfit.

    Levels are ``project``, ``bible``, ``season``, ``episode``, ``scene`` and ``shot``. A look
    that no level chooses has no entry: the character's ``default`` applies (SPEC.md).
    ``camera_fields`` has the origin of each camera field: a level, or the ID of the camerawork
    template that fills it (``cam/tu-slow``).
    """
    found: dict[str, Any] = {"forms": {}, "outfits": {}, "camera_fields": {}}
    template = None
    for name, level in _levels(p, shot_id):
        for key, value in level.items():
            if key in ("forms", "outfits"):
                found[key].update({cid: name for cid in value or {}})
            else:
                found[key] = name
            if key == "camera" and isinstance(value, dict):
                found["camera_fields"].update({field: name for field in value})
                template = value.get("template", template)
    # The camera fields that no level states come from the template: its ID is their origin.
    if (doc := p.docs.get(str(template))) is not None:
        for field in doc.data.get("camera") or {}:
            found["camera_fields"].setdefault(field, template)
    return found


def _pick(p: Project, doc: Doc, keys: tuple[str, ...]) -> dict[str, Any]:
    hashed: dict[str, Any] = p.hashed(
        {k: doc.data[k] for k in keys if k in doc.data}, doc.path.parent
    )
    return hashed


def _entry(p: Project, ref: Any) -> dict[str, Any]:
    """Return a bible entry for embedding: asset references hashed, unrendered fields dropped."""
    doc = p.docs.get(str(ref))
    if doc is None:
        raise OlfError(f"unknown reference {ref}")
    return _pick(p, doc, tuple(k for k in doc.data if k not in NOT_RENDERED))


def _character(p: Project, cid: str, looks: dict[str, dict[str, str]]) -> dict[str, Any]:
    """Embed a character with only its chosen form and outfit (``default`` when none is chosen)."""
    char = _entry(p, cid)
    for field, key in (("forms", "form"), ("outfits", "outfit")):
        options = char.pop(field, None) or {}
        name = looks[field].get(cid) or ("default" if "default" in options else None)
        if name is not None:
            if name not in options:
                raise OlfError(f"{cid}: no {key} named {name!r}")
            char[key] = {"name": name, **options[name]}
    if "voice" in char:
        char["voice"] = _entry(p, char["voice"])
    return char


def _camerawork(p: Project, camera: dict[str, Any]) -> dict[str, Any]:
    """Fill a camera from its camerawork template (``camera.template``).

    The template fills only the fields that no level states. Of the template itself, the view
    keeps its ID and its words for the prompts. Its other fields (name, intent, timing, rules)
    change no render, so they stay out, as ``credits`` does.

    Raises:
        OlfError: The bible has no such entry, or it is not a camerawork template.
    """
    ref = str(camera["template"])
    entry = _entry(p, ref)
    if p.kind(ref) != "camerawork":
        raise OlfError(f"camera.template {ref} is not a camerawork template (cam/<slug>)")
    words = {k: entry[k] for k in ("id", *TEMPLATE_WORDS) if k in entry}
    return {**(entry.get("camera") or {}), **camera, "template": words}


def _seconds(value: Any, key: str | None = None) -> Any:
    """Turn durations such as ``4s``, ``4.0s`` or ``3+12`` into numbers of seconds (``4``)."""
    if isinstance(value, dict):
        return {k: _seconds(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_seconds(v) for v in value]
    if key in DURATION_KEYS and isinstance(value, str) and (found := seconds(value, -1.0)) >= 0:
        return int(found) if found.is_integer() else found
    return value


def hash_view(
    view: dict[str, Any], kind: str, frames: dict[str, str] | None = None
) -> dict[str, Any]:
    """Keep only what a take of ``kind`` uses (SPEC.md, Hash input, steps 2 and 3).

    Args:
        view: A resolved shot.
        kind: ``keyframe``, ``video`` or ``audio``.
        frames: For video takes: the output asset of the keyframe take each ``keyframe``
            control used (``first_frame`` / ``last_frame``).
    """
    v = copy.deepcopy(view)
    v.pop("select", None)
    v.pop("layout", None)  # pills are a plan: no take uses them (SPEC.md, Layout)
    if kind == "audio":
        speakers = {line.get("speaker") for line in v.get("dialogue") or []}
        out: dict[str, Any] = {k: v[k] for k in ("id", "dialogue") if k in v}
        cast = [{k: c[k] for k in ("id", "voice") if k in c} for c in v.get("characters") or []]
        if cast := [c for c in cast if c.get("id") in speakers]:
            out["characters"] = cast
        return out
    if kind == "keyframe":
        for key in ("duration", "dialogue", "audio"):
            v.pop(key, None)
        if isinstance(v.get("camera"), dict):  # of a template, a keyframe uses its keyframe words
            _drop(v["camera"], "template", "id", "prompt", "avoid")
        _drop(v, "camera", *MOTION)
        _drop(v, "control", "first_frame", "last_frame")
        for char in v.get("characters") or []:
            char.pop("voice", None)
    else:
        if (v.get("camera") or {}).get("render") == "engine":
            # An engine move animates the chosen keyframe, so the video hashes that keyframe's
            # output as a `keyframe` first frame does.
            v.setdefault("control", {}).setdefault("first_frame", "keyframe")
        control = v.get("control") or {}
        for key in ("first_frame", "last_frame"):
            if control.get(key) == "keyframe" and frames and key in frames:
                control[key] = frames[key]
    return v


def from_keyframe(view: dict[str, Any]) -> bool:
    """True when a video of this shot animates its chosen keyframe: a ``keyframe`` first frame,
    or an engine move (``camera.render: engine``) with no other first frame to move."""
    first = (view.get("control") or {}).get("first_frame")
    engine_move = (view.get("camera") or {}).get("render") == "engine"
    return first == "keyframe" or (first is None and engine_move)


def awaits_keyframe(view: dict[str, Any], frames: dict[str, str]) -> bool:
    """True when a video of this shot has no hash yet: it animates a keyframe (a ``keyframe``
    control, or an engine move) and no keyframe take is chosen (``frames`` is empty)."""
    control = (view.get("control") or {}).values()
    return ("keyframe" in control or from_keyframe(view)) and not frames


def _drop(view: dict[str, Any], field: str, *keys: str) -> None:
    sub = view.get(field)
    if isinstance(sub, dict):
        for key in keys:
            sub.pop(key, None)
        if not sub:
            view.pop(field)


def inputs_hash(view: dict[str, Any], kind: str, frames: dict[str, str] | None = None) -> str:
    """Return ``sha256:<64 hex>`` of the canonical JSON of the take's hash view."""
    text = canonical(hash_view(view, kind, frames))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def take_frames(p: Project, take: dict[str, Any]) -> dict[str, str]:
    """Map ``first_frame`` / ``last_frame`` inputs that name keyframe takes to their outputs."""
    inputs = take.get("inputs") or {}
    found = {k: p.docs.get(str(inputs.get(k))) for k in ("first_frame", "last_frame")}
    return {
        k: str(d.data["output"]) for k, d in found.items() if d is not None and "output" in d.data
    }


def cue_view(p: Project, cue_id: str) -> dict[str, Any]:
    """The hash view of a music or SFX cue (``e02/cue/theme``, listed in the episode's ``cues``):
    ``{"id", "kind", "description", "duration"}``, the duration in seconds.

    Raises:
        OlfError: The episode lists no cue with that slug.
    """
    episode_id, _, slug = cue_id.partition("/cue/")
    doc = p.docs.get(episode_id) if p.kind(episode_id) == "episode" else None
    cues = (doc.data.get("cues") if doc else None) or {}
    cue = cues.get(slug) if isinstance(cues, dict) else None
    if not isinstance(cue, dict):
        raise OlfError(f"{cue_id}: no such cue (an episode lists its cues under `cues`)")
    view = {"id": cue_id, "kind": cue.get("kind"), "description": str(cue.get("description") or "")}
    return view | {"duration": _seconds(cue.get("duration"), "duration")}


def cue_hash(view: dict[str, Any]) -> str:
    """A cue take's ``inputs_hash``: RFC 8785 JSON of the cue's view, then SHA-256."""
    return "sha256:" + hashlib.sha256(canonical(view).encode("utf-8")).hexdigest()


def stale(p: Project, take_id: str, cache: dict[str, dict[str, Any]] | None = None) -> bool | None:
    """Return True when a take's stored inputs_hash no longer matches its current inputs.

    Staleness is calculated on every read and never stored (SPEC.md, Status values). A music or
    SFX cue take is stale when its cue changed. Returns None when the shot or cue is missing.
    """
    take = p.docs[take_id].data
    shot_id = take_id.rsplit("/", 1)[0]
    if "/cue/" in shot_id:
        try:
            return cue_hash(cue_view(p, shot_id)) != take.get("inputs_hash")
        except OlfError:
            return None
    if p.kind(shot_id) != "shot":
        return None
    cache = {} if cache is None else cache
    if shot_id not in cache:
        cache[shot_id] = resolve(p, shot_id)
    current = inputs_hash(cache[shot_id], str(take.get("kind")), take_frames(p, take))
    return current != take.get("inputs_hash")


def canonical(value: Any) -> str:
    """Serialize JSON values with RFC 8785, the JSON Canonicalization Scheme (JCS)."""
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0].encode("utf-16-be"))  # UTF-16 code units
        return (
            "{"
            + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{canonical(v)}" for k, v in items)
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(canonical(v) for v in value) + "]"
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, int) and abs(value) < 2**53:
        return str(value)
    if isinstance(value, int | float):
        return _number(float(value))
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # escapes match JCS (lowercase \u00xx)
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def _number(x: float) -> str:
    """Format a double like ECMAScript Number.prototype.toString (RFC 8785, section 3.2.2.3)."""
    if not math.isfinite(x):
        raise ValueError("NaN and Infinity are not JSON")
    if x == 0:
        return "0"
    mantissa, _, exp = repr(abs(x)).partition("e")  # repr gives the shortest round-trip digits
    whole, _, frac = mantissa.partition(".")
    digits, e = (whole + frac).lstrip("0"), int(exp or 0) - len(frac)
    stripped = digits.rstrip("0")
    e += len(digits) - len(stripped)
    digits, n = stripped, len(stripped) + e  # x = 0.digits * 10**n
    k = len(digits)
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        text = digits[0] + ("." + digits[1:] if k > 1 else "") + f"e{n - 1:+d}"
    return ("-" if x < 0 else "") + text
