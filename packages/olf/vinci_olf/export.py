"""Export an episode's cut: 16:9 and 9:16 video files with subtitles, after a license check.

Export assembles takes that exist: no model renders anything and nothing costs money. Files go
to ``exports/<episode>/`` (derived output, not in ``assets/lock.yaml``; SPEC.md).
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from vinci_olf import provenance
from vinci_olf.cut import FADE, cut_view
from vinci_olf.otio import timeline
from vinci_olf.project import OlfError, Project

log = logging.getLogger(__name__)
# 9:16 is a center crop of the episode frame (vinci_media.reframe_9x16), at 1080 x 1920 for X.
ASPECTS: dict[str, tuple[int, int] | None] = {"16:9": None, "9:16": (1080, 1920)}
NO_DERIVATIVES = re.compile(r"\bnd\b|no[-_ ]?deriv", re.IGNORECASE)


def check_licenses(p: Project, view: dict[str, Any]) -> list[str]:
    """Return the problems that stop an export.

    Every asset in the cut (each take's output, the references it used, a separate dialogue
    take, and each music and SFX take) needs a license with ``owner`` and ``terms`` in the lock
    file, and its terms must allow derivatives.
    """
    problems: set[str] = set()
    music = [{"take": row["take"], "audio": "own", "dialogue_take": None} for row in view["audio"]]
    for clip in [*view["clips"], *music]:
        speech = clip["dialogue_take"] if clip["audio"] == "separate" else None
        for take_id in [clip["take"], *([speech["take"]] if speech else [])]:
            take = p.docs.get(take_id)
            if take is None:
                continue
            references = (take.data.get("inputs") or {}).get("references") or []
            for asset in [take.data.get("output"), *references]:
                key = str(asset or "").partition("#")[0]
                if not key:
                    continue
                license_ = (p.lock.get(key) or {}).get("license") or {}
                if not (license_.get("owner") and license_.get("terms")):
                    problems.add(
                        f"{key} (in {take_id}): no license owner and terms in assets/lock.yaml"
                    )
                elif NO_DERIVATIVES.search(str(license_["terms"])):
                    problems.add(f"{key} (in {take_id}): {license_['terms']} forbids derivatives")
    return sorted(problems)


def cues(
    view: dict[str, Any], names: dict[str, str] | None = None
) -> list[tuple[float, float, str]]:
    """Subtitles from shot dialogue: each line of a clip gets an equal share of the clip's time,
    in order (SPEC.md, Subtitles). With ``names`` (speaker ID -> name), each line starts with its
    speaker's name, as a no-sound export needs: no voice says who speaks."""
    out: list[tuple[float, float, str]] = []
    for clip in view["clips"]:
        lines = [
            f"{names.get(str(line.get('speaker')), line.get('speaker'))}: {line['line']}"
            if names is not None
            else str(line["line"])
            for line in clip["dialogue"]
            if line.get("line")
        ]
        step = clip["length"] / len(lines) if lines else 0.0
        out += [
            (clip["start"] + i * step, clip["start"] + (i + 1) * step, text)
            for i, text in enumerate(lines)
        ]
    return out


def srt(cue_list: list[tuple[float, float, str]]) -> str:
    """Write subtitles as SubRip (``.srt``)."""

    def stamp(value: float) -> str:
        ms = round(value * 1000)
        return (
            f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
        )

    return "".join(
        f"{i}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(cue_list, 1)
    )


def export(
    p: Project,
    episode_id: str,
    *,
    aspects: tuple[str, ...] = ("16:9", "9:16"),
    subtitles: bool = True,
    c2pa: bool = False,
    otio: bool = False,
    home: Path | None = None,
    sound: bool = True,
) -> dict[str, Any]:
    """Export the episode's cut.

    Each clip is trimmed and brought to the project format (``defaults.resolution`` and
    ``defaults.fps``), with its sound: the take's own, or (``audio: separate``) the shot's
    chosen dialogue take from the start of the clip. The clips are joined (a cut, or a fade),
    and each aspect gets its file with the subtitles burned in. The subtitles are also written
    as ``<episode>.srt``. Music and SFX from the audio list are mixed in (COREPRODUC-551).

    Args:
        p: The loaded project.
        episode_id: The episode to export.
        aspects: ``16:9`` (the project frame) and/or ``9:16`` (a center crop, 1080 x 1920).
        subtitles: Burn subtitles from shot dialogue in, and write the ``.srt``.
        c2pa: Sign each MP4 with a C2PA manifest of its takes (``vinci_olf.provenance``).
        otio: Also write ``<episode>.otio`` (OpenTimelineIO) and WAV stems: the dialogue (the
            cut's own sound), and the music and the SFX of the audio list (COREPRODUC-544).
        home: The Vinci home that keeps the local C2PA signer. Default: ``$VINCI_HOME``.
        sound: False: the files have no audio stream (no take sound, dialogue, music or SFX);
            the lines are only subtitles. Stems need sound, so ``otio`` then writes none.

    Returns:
        ``{"files": [project-relative paths], "duration": s, "clips": n, "subtitles": n}``.

    Raises:
        OlfError: The cut is empty, a take file or a separate dialogue take is missing, or a
            license stops the export.
    """
    from vinci_media import (
        burn_cues,
        extract_audio,
        join_clips,
        mix_cues,
        normalize_clip,
        reframe_9x16,
        stem_cues,
    )

    if c2pa and not provenance.available():  # before any work: it would fail at the end
        raise OlfError("C2PA needs c2pa-python: pip install 'vinci-olf[c2pa]'")

    if bad := [aspect for aspect in aspects if aspect not in ASPECTS]:
        raise OlfError(f"aspect must be one of {', '.join(ASPECTS)}, not {bad[0]!r}")
    view = cut_view(p, episode_id)
    if not view["clips"]:
        raise OlfError(
            f"{episode_id} has no cut yet: run `vinci olf cut {episode_id} --use-approved` first"
        )
    if missing := [clip["take"] for clip in view["clips"] if clip["missing"]]:
        raise OlfError(f"the cut has no file for {', '.join(missing)}")
    if sound and (
        silent := [
            clip["take"]
            for clip in view["clips"]
            if clip["audio"] == "separate" and not (clip["dialogue_take"] or {}).get("file")
        ]
    ):
        raise OlfError(
            f"{', '.join(silent)}: audio is separate, but the shot has no chosen dialogue take "
            "(select.audio) with a file. Render and approve dialogue, or use the take's own sound"
        )
    if lost := [row["take"] for row in view["audio"] if row["missing"]]:
        raise OlfError(f"the audio list has no file for {', '.join(lost)}")
    if problems := check_licenses(p, view):
        more = f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""
        raise OlfError(f"export stopped by licenses: {'; '.join(problems[:3])}{more}")
    defaults = p.manifest.get("defaults") or {}
    width, height = (
        int(n) for n in str(defaults.get("resolution") or "1920x1080").lower().split("x")
    )
    fps = int(defaults.get("fps") or 24)
    out = p.inside(p.root / "exports" / episode_id)
    out.mkdir(parents=True, exist_ok=True)
    # With no sound, a subtitle names its speaker (the first name), as the mock render does.
    first = {k: str(d.data.get("name") or k).split()[0] for k, d in p.of_kind("character").items()}
    cue_list = cues(view, None if sound else first) if subtitles else []
    files: list[str] = []
    with tempfile.TemporaryDirectory(prefix="olf-export-") as raw:
        tmp = Path(raw)
        parts = [
            # A file can come from a lock.yaml URI, so it must stay inside the project.
            normalize_clip(
                p.inside(p.root / clip["file"]),
                tmp / f"clip{i}.mp4",
                clip["in"],
                clip["out"],
                width,
                height,
                fps,
                still=clip["kind"] == "keyframe",
                audio=p.inside(p.root / clip["dialogue_take"]["file"])
                if sound and clip["audio"] == "separate"
                else None,
            )
            for i, clip in enumerate(view["clips"])
        ]
        joined = join_clips(
            parts, [clip["transition"] for clip in view["clips"]], tmp / "cut.mp4", fade=FADE
        )
        if otio and sound:  # stems for an editor: the cut's own sound, then each kind of cue alone
            stems = out / "stems"
            files.append(p.rel(extract_audio(joined, stems / f"{episode_id}-dialogue.wav")))
            for kind in ("music", "sfx"):
                rows = [
                    r | {"file": p.inside(p.root / r["file"])}
                    for r in view["audio"]
                    if r["kind"] == kind
                ]
                if rows:
                    stem = stem_cues(rows, view["duration"], stems / f"{episode_id}-{kind}.wav")
                    files.append(p.rel(stem))
        if sound and view["audio"]:  # music and SFX over the cut, ducked under the dialogue
            joined = mix_cues(
                joined,
                [row | {"file": p.inside(p.root / row["file"])} for row in view["audio"]],
                tmp / "mixed.mp4",
            )
        if cue_list:
            (out / f"{episode_id}.srt").write_text(srt(cue_list), encoding="utf-8")
            files.append(p.rel(out / f"{episode_id}.srt"))
        for aspect in aspects:
            size = ASPECTS[aspect] or (width, height)
            frame = (
                joined
                if ASPECTS[aspect] is None
                else reframe_9x16(joined, tmp / "vertical.mp4", *size)
            )
            target = out / f"{episode_id}-{aspect.replace(':', 'x')}.mp4"
            burn_cues(frame, target, cue_list, width=size[0], height=size[1], sound=sound)
            if c2pa:  # last: the manifest hashes the finished file
                provenance.sign(target, provenance.manifest(p, view, target.name), home)
            files.append(p.rel(target))
    if otio:  # take files are project-relative; the export folder is exports/<episode>/
        doc = timeline(view, rate=fps, base="../..")
        (out / f"{episode_id}.otio").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        files.append(p.rel(out / f"{episode_id}.otio"))
    log.info(
        "exported %s: %s (%d clips, %.1f s, %d subtitles)",
        episode_id,
        files,
        len(view["clips"]),
        view["duration"],
        len(cue_list),
    )
    return {
        "files": files,
        "duration": view["duration"],
        "clips": len(view["clips"]),
        "subtitles": len(cue_list),
    }
