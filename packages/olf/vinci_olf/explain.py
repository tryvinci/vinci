"""Say why a take is stale, and keep a stale take on purpose (Claude Design: "See change",
"Keep v2 anyway").

A stale take has a stored ``inputs_hash`` that no longer matches its inputs, and a hash cannot
say what changed. So the engine keeps each take's hash view next to the take file
(``takes/<take>.inputs.json``) and compares it with the current one. A take rendered before
this file existed can be kept, but its cause is unknown.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from vinci_olf.edit import _put, _save
from vinci_olf.project import OlfError, Project, read
from vinci_olf.resolve import hash_view, inputs_hash, origins, resolve, take_frames
from vinci_olf.resolve import stale as is_stale

log = logging.getLogger(__name__)


def inputs_path(p: Project, take_id: str) -> Path:
    """The file that keeps a take's hash view: ``takes/<take>.inputs.json``."""
    return p.inside(p.root / "takes" / f"{take_id}.inputs.json")


def save_inputs(p: Project, take_id: str, view: dict[str, Any]) -> None:
    """Keep the hash view a take was rendered (or kept) with."""
    path = inputs_path(p, take_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(view, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _flat(value: Any, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Leaf values by path. A list of objects is keyed by each ``id`` (characters), else by
    position (``dialogue.0.line``), so a change names one field, not a whole list."""
    if isinstance(value, dict):
        out: dict[tuple[str, ...], Any] = {}
        for key, item in value.items():
            out |= _flat(item, (*path, str(key)))
        return out or {path: {}}
    if isinstance(value, list) and value and all(isinstance(i, dict) for i in value):
        out = {}
        ids = all("id" in i for i in value)
        for n, item in enumerate(value):
            key = str(item["id"]) if ids else str(n)
            out |= _flat({k: v for k, v in item.items() if not (ids and k == "id")}, (*path, key))
        return out
    return {path: value}


def _label(path: tuple[str, ...], view: dict[str, Any], camera: dict[str, str]) -> str:
    """Words for a changed field: the bible entry or look it belongs to, then the field.

    ``camera`` has the origin of each camera field (``origins``): a field that the shot's
    camerawork template fills is named after the template.
    """
    head, rest = path[0], list(path[1:])
    if head == "camera" and rest:
        template = (view.get("camera") or {}).get("template")
        if rest[0] == "template" and isinstance(template, dict):
            return f"{template.get('id')} ({'.'.join(rest[1:]) or 'entry'})"
        if str(camera.get(rest[0], "")).startswith("cam/"):
            return f"{camera[rest[0]]} (camera.{'.'.join(rest)})"
    if head == "characters" and rest:
        cid, field = rest[0], rest[1:]
        char: dict[str, Any] = next(
            (c for c in view.get("characters") or [] if c.get("id") == cid), {}
        )
        if field and field[0] in ("form", "outfit"):
            name = (char.get(field[0]) or {}).get("name")
            detail = ".".join(field[1:])
            return f'the {field[0]} "{name}" of {cid}' + (f" ({detail})" if detail else "")
        return f"{cid} ({'.'.join(field) or 'entry'})"
    if head in ("location", "style") and isinstance(view.get(head), dict):
        return f"{view[head].get('id', head)} ({'.'.join(rest) or 'entry'})"
    if head == "props" and rest:
        return f"{rest[0]} ({'.'.join(rest[1:]) or 'entry'})"
    return f"the shot's {'.'.join(path)}"


def explain(p: Project, take_id: str) -> dict[str, Any]:
    """Return what changed since a take was rendered (or kept).

    Returns:
        ``{"take", "stale", "known", "changes": [{"field", "label", "before", "after"}],
        "summary"}``. ``known`` is False for a take with no ``.inputs.json``.

    Raises:
        OlfError: The take is missing, or it is not a shot take.
    """
    doc = p.docs.get(take_id)
    if doc is None or p.kind(take_id) != "take":
        raise OlfError(f"{take_id}: no such take")
    shot_id = take_id.rsplit("/", 1)[0]
    if p.kind(shot_id) != "shot":
        raise OlfError(f"{take_id}: only shot takes have inputs to compare")
    kind = str(doc.data.get("kind"))
    now = hash_view(resolve(p, shot_id), kind, take_frames(p, doc.data))
    stale = bool(is_stale(p, take_id))
    path = inputs_path(p, take_id)
    if not path.is_file():
        return {"take": take_id, "stale": stale, "known": False, "changes": [], "summary": ""}
    then = json.loads(path.read_text(encoding="utf-8"))
    old, new = _flat(then), _flat(now)
    camera = origins(p, shot_id)["camera_fields"]
    changes = [
        {
            "field": ".".join(key),
            "label": _label(key, now if key in new else then, camera),
            "before": old.get(key),
            "after": new.get(key),
        }
        for key in sorted(set(old) | set(new))
        if old.get(key) != new.get(key)
    ]
    first = changes[0]["label"] if changes else ""
    more = f" and {len(changes) - 1} more" if len(changes) > 1 else ""
    summary = f"{first}{more} changed" if changes else ""
    return {"take": take_id, "stale": stale, "known": True, "changes": changes, "summary": summary}


def keep_take(p: Project, take_id: str) -> dict[str, Any]:
    """Keep a stale take on purpose: ``inputs_hash`` becomes the current hash, and the old one is
    recorded in ``kept_from`` (SPEC.md, Takes). The take is fresh until an input changes again.

    Raises:
        OlfError: The take is missing or not a shot take.
    """
    doc = p.docs.get(take_id)
    if doc is None or p.kind(take_id) != "take" or p.kind(take_id.rsplit("/", 1)[0]) != "shot":
        raise OlfError(f"{take_id}: no such shot take")
    kind, frames = str(doc.data.get("kind")), take_frames(p, doc.data)
    view = resolve(p, take_id.rsplit("/", 1)[0])
    current, old = inputs_hash(view, kind, frames), doc.data.get("inputs_hash")
    if current == old:
        return {"take": take_id, "kept": False, "inputs_hash": current}
    lines = doc.path.read_text(encoding="utf-8").splitlines(keepends=True)
    _put(lines, 0, len(lines), "", "inputs_hash", current)
    if old:
        _put(lines, 0, len(lines), "", "kept_from", str(old))
    _save(doc.path, lines, lambda data: data.get("inputs_hash") == current)
    save_inputs(p, take_id, hash_view(view, kind, frames))
    doc.data = read(doc.path)
    log.info("take %s kept: inputs_hash %s (was %s)", take_id, current, old)
    return {"take": take_id, "kept": True, "inputs_hash": current, "kept_from": old}
