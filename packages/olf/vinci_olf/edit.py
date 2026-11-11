"""Edit OLF files the way a person does: a take's status and notes, a shot's ``select``, the cut.

SPEC.md: people SHOULD edit only ``status`` and ``notes`` in take files, and ``select``
records the chosen takes of a shot. Edits change only their own line, so the rest of a
hand-written file (comments, spacing, ``{ key: value }`` style) stays byte for byte
(SPEC.md rule 7, diff-friendly). Each edit is parsed again before it is saved.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from vinci_olf.project import OlfError, Project, read

log = logging.getLogger(__name__)
STATUSES = ("draft", "candidate", "approved", "rejected")
SELECT_PREFIX = {"keyframe": "kf", "video": "v", "audio": "a"}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _put(
    lines: list[str], start: int, end: int, indent: str, key: str, value: str | list[str] | None
) -> None:
    """Set ``key: value`` among ``lines[start:end]`` at ``indent``; ``None`` removes the key.

    A list value is a block: ``key:`` and then those lines. A key that holds a block (deeper
    lines, or ``-`` items at its own indent) is replaced with its block.
    """
    new = (
        []
        if value is None
        else [f"{indent}{key}:\n", *value]
        if isinstance(value, list)
        else [f"{indent}{key}: {value}\n"]
    )
    head = re.compile(rf"^{re.escape(indent)}{re.escape(key)}:(\s|$)")

    def inside(line: str) -> bool:
        deeper = _indent(line) > len(indent)
        return deeper or (_indent(line) == len(indent) and line.lstrip().startswith("- "))

    for i in range(start, end):
        if head.match(lines[i]):
            j = i + 1
            while j < end and lines[j].strip() and inside(lines[j]):
                j += 1
            lines[i:j] = new
            return
    if value is not None:
        k = end
        while k > start and not lines[k - 1].strip():
            k -= 1
        if k and not lines[k - 1].endswith("\n"):
            lines[k - 1] += "\n"
        lines[k:k] = new


def shot_block(lines: list[str], shot_id: str) -> tuple[int, int, str]:
    """Return ``(first, end, indent)``: the lines that hold a shot's keys, and their indent.

    A shot in its own file is the whole file at the top level. An inline shot in its scene
    file runs from the line after ``- id: <shot>`` to the next item or a smaller indent.
    """
    item = re.compile(rf"^(\s*)-(\s+)id:\s*[\"']?{re.escape(shot_id)}[\"']?\s*(#.*)?$")
    for i, line in enumerate(lines):
        if match := item.match(line.rstrip("\n")):
            dash = len(match[1])
            end = next(
                (
                    j
                    for j in range(i + 1, len(lines))
                    if lines[j].strip() and _indent(lines[j]) <= dash
                ),
                len(lines),
            )
            return i + 1, end, " " * (dash + 1 + len(match[2]))  # keys after the "- id:" line
    return 0, len(lines), ""


def _save(path: Path, lines: list[str], ok: Callable[[Any], bool]) -> None:
    """Write ``lines`` only when they parse and ``ok`` accepts the parsed data."""
    text = "".join(lines)
    try:
        data = YAML(typ="safe", pure=True).load(text)
    except Exception as exc:  # noqa: BLE001 - never save a file that no longer parses
        raise OlfError(
            f"{path.name}: the edit would break the YAML ({exc}); nothing was saved"
        ) from exc
    if not ok(data):
        raise OlfError(f"{path.name}: could not edit this file safely; nothing was saved")
    path.write_text(text, encoding="utf-8")


def set_take(
    p: Project, take_id: str, *, status: str | None = None, notes: str | None = None
) -> dict[str, Any]:
    """Change a take's ``status`` and/or ``notes`` (an empty note removes it).

    Raises:
        OlfError: The take is missing or the status is not an OLF status.
    """
    doc = p.docs.get(take_id)
    if doc is None or p.kind(take_id) != "take":
        raise OlfError(f"{take_id}: no such take")
    if status is not None and status not in STATUSES:
        raise OlfError(f"status must be one of {', '.join(STATUSES)}, not {status!r}")
    lines = doc.path.read_text(encoding="utf-8").splitlines(keepends=True)
    note = None if notes is None else notes.strip()
    if status is not None:
        _put(lines, 0, len(lines), "", "status", status)
    if note is not None:
        _put(lines, 0, len(lines), "", "notes", json.dumps(note) if note else None)

    def ok(data: Any) -> bool:
        good = status is None or data.get("status") == status
        return good and (note is None or data.get("notes", "") == note)

    _save(doc.path, lines, ok)
    log.info("take %s: status=%s notes=%s", take_id, status, note)
    doc.data = read(doc.path)
    return doc.data


def set_select(p: Project, shot_id: str, **choices: str | None) -> dict[str, Any]:
    """Set or clear ``select.keyframe`` / ``select.video`` / ``select.audio`` of a shot.

    The change goes into the file that holds the shot (inline in its scene, or its own
    file), as one line in the spec's style: ``select: { keyframe: kf3, video: v2 }``.
    ``None`` clears a choice.

    Raises:
        OlfError: The shot or the named take is missing, or the take is of another kind.
    """
    doc = p.docs.get(shot_id)
    if doc is None or p.kind(shot_id) != "shot":
        raise OlfError(f"{shot_id}: no such shot")
    for key, name in choices.items():
        if key not in SELECT_PREFIX:
            raise OlfError(f"select has no field {key!r}")
        if name is not None and not re.fullmatch(rf"{SELECT_PREFIX[key]}\d+", name):
            raise OlfError(f"select.{key} must look like {SELECT_PREFIX[key]}1, not {name!r}")
        if name is not None and f"{shot_id}/{name}" not in p.docs:
            raise OlfError(f"select.{key}: take {shot_id}/{name} is missing")
    merged = {**(doc.data.get("select") or {}), **choices}
    select = {k: merged[k] for k in SELECT_PREFIX if merged.get(k)}
    value = "{ " + ", ".join(f"{k}: {v}" for k, v in select.items()) + " }" if select else None
    lines = doc.path.read_text(encoding="utf-8").splitlines(keepends=True)
    first, end, indent = shot_block(lines, shot_id)
    _put(lines, first, end, indent, "select", value)

    def ok(data: Any) -> bool:
        shots = data.get("shots") or []
        node = (
            data
            if data.get("id") == shot_id
            else next((s for s in shots if s.get("id") == shot_id), {})
        )
        return (node.get("select") or {}) == select

    _save(doc.path, lines, ok)
    log.info("shot %s: select=%s", shot_id, select)
    doc.data = (
        {**doc.data, "select": select}
        if select
        else {k: v for k, v in doc.data.items() if k != "select"}
    )
    return select


CUT_FIELDS = ("take", "in", "out", "transition", "audio")
CUT_DEFAULTS = {"transition": "cut", "audio": "own"}


def set_cut(p: Project, episode_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Write an episode's ``cut`` list, one clip per line in the spec's style.

    For example ``- { take: e02/s03/sh014/v2, in: 0.2s, out: 3.8s }``. Only the ``cut:`` block
    changes; the rest of ``episode.yaml`` stays byte for byte. Default values (``transition:
    cut``, ``audio: own``) are left out. An empty list removes the block.

    Raises:
        OlfError: The episode or a take is missing, or a field or value is not allowed.
    """
    doc = p.docs.get(episode_id)
    if doc is None or p.kind(episode_id) != "episode":
        raise OlfError(f"{episode_id}: no such episode")
    clean: list[dict[str, Any]] = []
    for row in rows:
        if unknown := sorted(set(row) - set(CUT_FIELDS)):
            raise OlfError(f"a cut clip has no field {unknown[0]!r}")
        take = str(row.get("take") or "")
        if p.kind(take) != "take" or take not in p.docs:
            raise OlfError(f"cut: take {take or '(none)'} is missing")
        if row.get("transition", "cut") not in ("cut", "fade"):
            raise OlfError(f"transition must be cut or fade, not {row['transition']!r}")
        if row.get("audio", "own") not in ("own", "separate"):
            raise OlfError(f"audio must be own or separate, not {row['audio']!r}")
        clip = {}
        for key in CUT_FIELDS:
            value = row.get(key)
            if value in (None, "") or CUT_DEFAULTS.get(key) == value:
                continue
            clip[key] = (
                f"{float(str(value).rstrip('s')):g}s" if key in ("in", "out") else str(value)
            )
        clean.append(clip)
    block = ["  - { " + ", ".join(f"{k}: {v}" for k, v in clip.items()) + " }\n" for clip in clean]
    lines = doc.path.read_text(encoding="utf-8").splitlines(keepends=True)
    _put(lines, 0, len(lines), "", "cut", block or None)
    _save(doc.path, lines, lambda data: [dict(r) for r in data.get("cut") or []] == clean)
    log.info("episode %s: cut of %d clips", episode_id, len(clean))
    doc.data = read(doc.path)
    return clean


def set_clip(p: Project, episode_id: str, index: int, **fields: Any) -> list[dict[str, Any]]:
    """Change one clip of the cut: ``in``, ``out``, ``transition`` or ``audio``.

    ``None`` removes a field (so the default applies).

    Raises:
        OlfError: The episode, the clip or a field is missing.
    """
    doc = p.docs.get(episode_id)
    if doc is None or p.kind(episode_id) != "episode":
        raise OlfError(f"{episode_id}: no such episode")
    rows = [dict(row) for row in doc.data.get("cut") or []]
    if not 0 <= index < len(rows):
        raise OlfError(f"{episode_id}: the cut has no clip {index + 1}")
    for key, value in fields.items():
        if key not in CUT_FIELDS[1:]:
            raise OlfError(f"a cut clip has no field {key!r} to change")
        if value is None:
            rows[index].pop(key, None)
        else:
            rows[index][key] = value
    return set_cut(p, episode_id, rows)
