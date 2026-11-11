"""OpenTimelineIO export of a cut (COREPRODUC-544): for edits beyond order, trims, cuts and fades.

``timeline`` turns the Cut view into OTIO JSON (``Timeline.1``) without the OTIO library: a Video
track (each clip with its trims; a fade is a centered ``SMPTE_Dissolve``), a Dialogue track
(separate dialogue takes), and one audio track per music or SFX row (a gap, then the cue take,
with its volume and ducking as metadata). Media references are take files, relative to the
export folder, so an editor opens the takes in place.
"""

from __future__ import annotations

from typing import Any

FADE = 0.5  # seconds of a fade (vinci_olf.cut.FADE)
COMMON = {"metadata": {}, "effects": [], "markers": [], "enabled": True}


def _time(seconds: float, rate: float) -> dict[str, Any]:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(rate), "value": round(seconds * rate, 3)}


def _range(start: float, duration: float, rate: float) -> dict[str, Any]:
    span = {"start_time": _time(start, rate), "duration": _time(duration, rate)}
    return {"OTIO_SCHEMA": "TimeRange.1", **span}


def _clip(name: str, url: str, start: float, duration: float, rate: float) -> dict[str, Any]:
    media: dict[str, Any] = {"OTIO_SCHEMA": "ExternalReference.1", "name": "", "target_url": url}
    media |= {"available_range": None, "metadata": {}}
    return {
        "OTIO_SCHEMA": "Clip.2",
        "name": name,
        "source_range": _range(start, duration, rate),
        "media_references": {"DEFAULT_MEDIA": media},
        "active_media_reference_key": "DEFAULT_MEDIA",
        **COMMON,
    }


def _gap(duration: float, rate: float) -> dict[str, Any]:
    return {"OTIO_SCHEMA": "Gap.1", "name": "", "source_range": _range(0, duration, rate), **COMMON}


def _track(name: str, kind: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    body = {"name": name, "kind": kind, "children": children, "source_range": None}
    return {"OTIO_SCHEMA": "Track.1", **body, **COMMON}


def timeline(view: dict[str, Any], *, rate: float, base: str) -> dict[str, Any]:
    """Return the cut as an OTIO ``Timeline.1`` document.

    Args:
        view: ``vinci_olf.cut.cut_view`` of the episode.
        rate: Frames per second of the project (``defaults.fps``).
        base: The path from the export folder to the project folder, for example ``../..``.
    """
    clips = view["clips"]
    # A fade of d seconds becomes a dissolve centered on the cut: the clip before loses d/2 at
    # its tail and the clip after loses d/2 at its head, so the length stays the cut's length.
    fades = [
        min(FADE, clip["length"] / 2, clips[i - 1]["length"] / 2)
        if clip["transition"] == "fade"
        else 0.0
        for i, clip in enumerate(clips)
    ]
    video: list[dict[str, Any]] = []
    for i, clip in enumerate(clips):
        head, tail = fades[i] / 2, (fades[i + 1] / 2 if i + 1 < len(clips) else 0.0)
        if fades[i]:
            dissolve: dict[str, Any] = {
                "OTIO_SCHEMA": "Transition.1",
                "name": "fade",
                "transition_type": "SMPTE_Dissolve",
            }
            dissolve |= {
                "in_offset": _time(head, rate),
                "out_offset": _time(head, rate),
                "metadata": {},
            }
            video.append(dissolve)
        length = max(clip["length"] - head - tail, 0.0)
        video.append(_clip(clip["take"], f"{base}/{clip['file']}", clip["in"] + head, length, rate))
    dialogue: list[dict[str, Any]] = []
    at = 0.0
    for clip in clips:
        speech = clip["dialogue_take"] if clip["audio"] == "separate" else None
        if speech and speech.get("file"):  # it plays from the start of its clip
            dialogue += [_gap(clip["start"] - at, rate)] if clip["start"] > at else []
            length = min(float(speech.get("length") or clip["length"]), clip["length"])
            dialogue.append(_clip(speech["take"], f"{base}/{speech['file']}", 0.0, length, rate))
            at = clip["start"] + length
    tracks = [_track("Video", "Video", video), _track("Dialogue", "Audio", dialogue)]
    for row in view["audio"]:
        cue = _clip(row["take"], f"{base}/{row['file']}", 0.0, row["length"], rate)
        cue["metadata"] = {"olf": {"volume": row["volume"], "duck_under_dialogue": row["duck"]}}
        name = f"{'SFX' if row['kind'] == 'sfx' else 'Music'}: {row['label']}"
        tracks.append(
            _track(name, "Audio", [*([_gap(row["start"], rate)] if row["start"] else []), cue])
        )
    stack = {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": tracks, "source_range": None}
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": view["episode"],
        "global_start_time": None,
        "tracks": stack | COMMON,
        "metadata": {"olf": {"episode": view["episode"], "file": view["file"]}},
    }
