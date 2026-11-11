"""An episode's cut list as clips on a timeline (SPEC.md, the episode ``cut`` and ``audio`` lists).

The Studio's Cut screen and ``vinci olf export`` read ``cut_view``. ``use_approved`` writes the
cut from approved takes; ``vinci_olf.edit.set_clip`` changes one clip.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from vinci_olf.api import file_of
from vinci_olf.edit import set_cut
from vinci_olf.project import OlfError, Project, seconds
from vinci_olf.resolve import cue_view, resolve, stale

log = logging.getLogger(__name__)
FADE = 0.5  # seconds a fade overlaps the end of the clip before it (vinci_media.join_clips)
PREFIX = {"keyframe": "kf", "video": "v", "audio": "a"}  # take IDs: kf1, v1, a1


def _episode(p: Project, episode_id: str) -> Any:
    if p.kind(episode_id) != "episode" or episode_id not in p.docs:
        raise OlfError(f"{episode_id}: no such episode")
    return p.docs[episode_id]


def play_order(p: Project, episode_id: str) -> list[str]:
    """The episode's shots in play order: listed scenes first, then the others; shots by ID."""
    episode = _episode(p, episode_id)
    listed = [s for s in episode.data.get("scenes") or [] if isinstance(s, str) and s in p.docs]
    others = sorted(
        s for s in p.of_kind("scene") if s.startswith(f"{episode_id}/") and s not in listed
    )
    shots = sorted(p.of_kind("shot"))
    return [shot for scene in listed + others for shot in shots if shot.rsplit("/", 1)[0] == scene]


def takes(p: Project, shot_id: str, kind: str) -> list[str]:
    """A shot's takes of one kind (``keyframe``, ``video``, ``audio``), oldest first."""
    pattern = re.compile(rf"{re.escape(shot_id)}/{PREFIX[kind]}(\d+)")
    found = [(int(m[1]), t) for t in p.of_kind("take") if (m := pattern.fullmatch(t))]
    return [t for _, t in sorted(found)]


def pick_take(p: Project, shot_id: str) -> str | None:
    """The take a shot gives the cut: an approved video (the chosen one first), else an
    approved keyframe, which plays as a still. ``None`` when nothing is approved."""
    select = p.docs[shot_id].data.get("select") or {}
    for kind in ("video", "keyframe"):
        approved = [
            t for t in takes(p, shot_id, kind) if p.docs[t].data.get("status") == "approved"
        ]
        chosen = f"{shot_id}/{select[kind]}" if select.get(kind) else None
        if chosen in approved:
            return chosen
        if approved:
            return approved[-1]
    return None


def dialogue_take(p: Project, shot_id: str) -> dict[str, Any] | None:
    """The shot's chosen dialogue take (``select.audio``), which a clip plays with
    ``audio: separate``: ``{"take", "file", "length", "status"}``, or ``None``."""
    select = p.docs[shot_id].data.get("select") if shot_id in p.docs else None
    name = select.get("audio") if isinstance(select, dict) else None  # a wrong shape is an issue
    take = p.docs.get(f"{shot_id}/{name}") if name else None
    if take is None:
        return None
    return {
        "take": f"{shot_id}/{name}",
        "file": file_of(p, str(take.data.get("output") or "")),
        "length": seconds(take.data.get("duration")),
        "status": take.data.get("status"),
    }


def use_approved(p: Project, episode_id: str) -> list[dict[str, Any]]:
    """Write the cut from approved takes, in play order. A shot with no approved take is left out.

    A shot whose chosen dialogue take is approved plays it as separate sound (``audio:
    separate``): the dialogue is a take of its own, and a video model's sound rarely has it.

    Raises:
        OlfError: No shot of the episode has an approved take.
    """
    rows: list[dict[str, Any]] = []
    for shot in play_order(p, episode_id):
        if take := pick_take(p, shot):
            speech = dialogue_take(p, shot)
            separate = speech is not None and speech["status"] == "approved"
            rows.append({"take": take} | ({"audio": "separate"} if separate else {}))
    if not rows:
        raise OlfError(f"{episode_id}: no approved takes yet; approve a keyframe or a video first")
    return set_cut(p, episode_id, rows)


def cut_view(p: Project, episode_id: str) -> dict[str, Any]:
    """Return the cut as clips on a timeline, for the Cut screen and for export.

    Each clip has its take, kind (a keyframe plays as a still), file, trims, length, start on
    the timeline (a fade starts ``FADE`` seconds before the clip before it ends), transition,
    audio source, the shot's chosen dialogue take (``dialogue_take``), stale flag and dialogue
    lines (for subtitles).
    """
    episode = _episode(p, episode_id)
    cache: dict[str, dict[str, Any]] = {}
    clips: list[dict[str, Any]] = []
    at = 0.0
    for index, row in enumerate(episode.data.get("cut") or []):
        take_id = str(row.get("take") or "")
        take, shot_id = p.docs.get(take_id), take_id.rsplit("/", 1)[0]
        shot = p.docs.get(shot_id)
        kind = (take.data.get("kind") if take else None) or (
            "keyframe" if "/kf" in take_id else "video"
        )
        file = file_of(p, str(take.data.get("output") or "")) if take else None
        length = seconds(shot.data.get("duration")) if shot else 0.0
        full = (seconds(take.data.get("duration")) if take and kind == "video" else 0.0) or length
        start = seconds(row.get("in"))
        # A clip plays for its shot's length unless the row sets `out`: a model's shortest clip
        # is often longer than the shot (a 3.5 s shot gets 5 s from a model with 5 s clips).
        end = seconds(row.get("out")) or (min(full, start + length) if length else full)
        fade = row.get("transition") == "fade" and index > 0
        at = max(at - FADE, 0.0) if fade else at
        speech = dialogue_take(p, shot_id) if shot else None
        try:
            view = cache.setdefault(shot_id, resolve(p, shot_id))
            dialogue = [line for line in view.get("dialogue") or [] if isinstance(line, dict)]
            is_stale = stale(p, take_id, cache) if take else None
            if speech:  # an old line in a stale dialogue take would not match the subtitles
                speech["stale"] = stale(p, speech["take"], cache)
        except OlfError:
            dialogue, is_stale = [], None
        clips.append(
            {
                "index": index,
                "take": take_id,
                "shot": shot_id,
                "kind": kind,
                "file": file,
                "in": start,
                "out": end,
                "length": max(end - start, 0.0),
                "start": round(at, 3),
                "transition": "fade" if fade else "cut",
                "audio": row.get("audio") or "own",
                "dialogue_take": speech,
                "stale": is_stale,
                "missing": take is None or file is None,
                "dialogue": dialogue,
            }
        )
        at += max(end - start, 0.0)
    defaults = p.manifest.get("defaults") or {}
    return {
        "episode": episode_id,
        "file": p.rel(episode.path),
        # The export frame: 16:9 files use it, 9:16 files crop it (vinci_olf.export).
        "format": {
            "resolution": str(defaults.get("resolution") or "1920x1080"),
            "fps": defaults.get("fps") or 24,
        },
        "clips": clips,
        "duration": round(at, 3),
        # A clip is stale when its take is, or when the separate dialogue it plays is.
        "stale": sum(
            1
            for clip in clips
            if clip["stale"]
            or (clip["audio"] == "separate" and (clip["dialogue_take"] or {}).get("stale"))
        ),
        "missing": sum(1 for clip in clips if clip["missing"]),
        "audio": audio_rows(p, episode.data.get("audio")),
    }


def audio_rows(p: Project, rows: Any) -> list[dict[str, Any]]:
    """The episode's audio list as blocks on the timeline (COREPRODUC-551): each music or SFX
    take with its cue, label, file, start, length, volume, ducking and stale flag."""
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        take_id = str(row.get("take") or "")
        take, cue_id = p.docs.get(take_id), take_id.rsplit("/", 1)[0]
        try:
            cue = cue_view(p, cue_id)
        except OlfError:
            cue = {}
        file = file_of(p, str(take.data.get("output") or "")) if take else None
        out.append(
            {
                "index": index,
                "take": take_id,
                "cue": cue_id,
                "kind": cue.get("kind"),
                "label": cue.get("description") or cue_id,
                "file": file,
                "start": seconds(row.get("start"), 0.0),
                "length": seconds(
                    take.data.get("duration") if take else None, float(cue.get("duration") or 0)
                ),
                "volume": float(row.get("volume", 1.0)),
                "duck": bool(row.get("duck_under_dialogue")),
                "stale": stale(p, take_id) if take else None,
                "missing": file is None,
            }
        )
    return out
