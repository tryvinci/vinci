"""Music and SFX cues (COREPRODUC-551): an episode's ``cues``, their takes, and the audio list.

A cue is ``e02/cue/<slug>``: a kind (``music`` or ``sfx``), a description and a length, listed
in ``episode.yaml`` under ``cues``. A cue take (``e02/cue/<slug>/a1``) is one render of it, and
it is stale when the cue changed since the render. The episode ``audio`` list places takes over
the cut, each with a start, a volume and ducking under dialogue (SPEC.md, Episode).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from vinci_olf.edit import _put, _save
from vinci_olf.project import OlfError, Project, write
from vinci_olf.render import EXT, _duration, _lock_entry, _next_take, run_one
from vinci_olf.resolve import cue_hash, cue_view

log = logging.getLogger(__name__)
# sfx: the ElevenLabs limit; music: one priced minute (the runtime prices one unit, COREPRODUC-555)
MAX_SECONDS = {"sfx": 30.0, "music": 60.0}


def _episode(p: Project, episode_id: str) -> Any:
    if p.kind(episode_id) != "episode" or episode_id not in p.docs:
        raise OlfError(f"{episode_id}: no such episode")
    return p.docs[episode_id]


def add_cue(p: Project, episode_id: str, kind: str, description: str, duration: float) -> str:
    """List a new cue in ``episode.yaml`` (one line under ``cues``) and return its ID.

    The slug comes from the first words of the description (``door-creaks``, then ``-2``...).

    Raises:
        OlfError: The episode is missing, or the kind, description or length is not allowed.
    """
    episode = _episode(p, episode_id)
    text = " ".join(str(description or "").split())
    if kind not in MAX_SECONDS:
        raise OlfError(f"a cue is music or sfx, not {kind!r}")
    if not text:
        raise OlfError("a cue needs a description, for example: slow piano, distant waves")
    if not 0.5 <= float(duration) <= MAX_SECONDS[kind]:
        raise OlfError(f"a {kind} cue lasts 0.5 to {MAX_SECONDS[kind]:g} s, not {duration} s")
    cues = episode.data.get("cues") or {}
    if not isinstance(cues, dict):
        raise OlfError(f"{episode_id}: cues must be a map of cue names; fix the file first")
    base = re.sub(r"[^a-z0-9]+", "-", " ".join(text.lower().split()[:3])).strip("-") or kind
    slug = next(s for s in (base, *(f"{base}-{n}" for n in range(2, 999))) if s not in cues)
    rows = {**cues, slug: {"kind": kind, "description": text, "duration": f"{float(duration):g}s"}}
    lines = episode.path.read_text(encoding="utf-8").splitlines(keepends=True)
    # One flow line per cue, as the spec writes short maps: `  theme: { kind: music, ... }`.
    block = []
    for name, row in rows.items():
        text = json.dumps(str(row.get("description")))
        length = f", duration: {row['duration']}" if row.get("duration") else ""
        block.append(f"  {name}: {{ kind: {row.get('kind')}, description: {text}{length} }}\n")
    _put(lines, 0, len(lines), "", "cues", block)
    _save(episode.path, lines, lambda data: (data.get("cues") or {}).get(slug) == rows[slug])
    cue_id = f"{episode_id}/cue/{slug}"
    log.info("episode %s: added cue %s (%s, %s)", episode_id, cue_id, kind, rows[slug]["duration"])
    return cue_id


def render_cue(
    p: Project,
    cue_id: str,
    *,
    model: str | None = None,
    yes: bool = False,
    max_total: float | None = None,
    dry_run: bool = False,
    engine: Any = None,
) -> dict[str, Any]:
    """Render a cue take (``music`` or ``sfx`` capability), price first, as a shot render.

    Returns:
        ``{"plan", "total", "unpriced", "takes"}``; ``takes`` is empty for a dry run.

    Raises:
        OlfError: The cue is missing or too long, the price stops it, or the run fails.
    """
    view = cue_view(p, cue_id)
    kind, seconds = str(view["kind"]), float(view["duration"] or 0)
    if kind not in MAX_SECONDS or not 0.5 <= seconds <= MAX_SECONDS[kind]:
        raise OlfError(
            f"{cue_id}: a {kind} cue needs a duration of 0.5 to {MAX_SECONDS.get(kind, 0):g} s"
        )
    take_id = _next_take(p, cue_id, "a")
    params = {"prompt": view["description"], "duration": seconds, "olf_take": take_id}
    result = run_one(
        kind, params, model=model, yes=yes, max_total=max_total, dry_run=dry_run, engine=engine
    )
    blob, provenance = result.pop("output"), result.pop("provenance")
    result["takes"] = []
    if blob is None:
        return result
    license_ = p.manifest.get("license")
    if not isinstance(license_, dict) or not {"owner", "terms"} <= license_.keys():
        raise OlfError("project.yaml needs license.owner and license.terms: every take gets them")
    from vinci_provider_sdk.local_image import sniff_media_mime

    digest = hashlib.sha256(blob).hexdigest()
    mime = sniff_media_mime(blob) or "audio/mpeg"
    rel = Path("takes", f"{take_id}.{EXT.get(mime, 'bin')}")
    (p.root / rel).parent.mkdir(parents=True, exist_ok=True)
    (p.root / rel).write_bytes(blob)
    take: dict[str, Any] = {
        "id": take_id,
        "kind": "audio",
        "status": "draft",
        "output": f"asset/{digest}",
    }
    take["duration"] = _duration(p.root / rel) or f"{seconds:g}s"
    take |= {"inputs_hash": cue_hash(view), "provenance": provenance}
    write(take, p.root / "takes" / f"{take_id}.yaml")
    p.add_to_lock(
        {f"asset/{digest}": _lock_entry(rel.as_posix(), digest, mime, "generated", license_)}
    )
    log.info("wrote cue take %s (%s, model %s)", take_id, rel, provenance["model"])
    result["takes"] = [take_id]
    return result


def place_cue(
    p: Project, episode_id: str, take_id: str, *, start: float, volume: float, duck: bool
) -> list[dict[str, Any]]:
    """Add a cue take to the episode ``audio`` list: one line, after the others.

    Returns:
        The new audio list.

    Raises:
        OlfError: The take is not a cue take of this episode, or a value is out of range.
    """
    episode = _episode(p, episode_id)
    if (
        not take_id.startswith(f"{episode_id}/cue/")
        or p.kind(take_id) != "take"
        or take_id not in p.docs
    ):
        raise OlfError(f"{take_id}: no such cue take in {episode_id}")
    if start < 0 or not 0 <= volume <= 4:
        raise OlfError("start must be 0 s or more, and volume 0 to 4")
    rows = [r for r in episode.data.get("audio") or [] if isinstance(r, dict)]
    row = {"take": take_id, "start": f"{round(start, 3):g}s", "volume": round(volume, 3)}
    row["duck_under_dialogue"] = bool(duck)
    lines = episode.path.read_text(encoding="utf-8").splitlines(keepends=True)
    flow = [
        "  - { "
        + ", ".join(f"{k}: {str(v).lower() if isinstance(v, bool) else v}" for k, v in r.items())
        + " }\n"
        for r in [*rows, row]
    ]
    _put(lines, 0, len(lines), "", "audio", flow)
    _save(episode.path, lines, lambda data: (data.get("audio") or [])[-1:] == [row])
    log.info(
        "episode %s: placed %s at %s (volume %s, ducked: %s)",
        episode_id,
        take_id,
        row["start"],
        volume,
        duck,
    )
    return [*rows, row]
