"""Episode assembly for exports: clips in one format, joined with cuts or fades, with subtitles.

The OLF engine (``vinci_olf.export``) uses these. Subtitles are caption images drawn with Pillow
and laid over the video with ffmpeg's ``overlay`` filter, so they work with any ffmpeg build:
Homebrew ffmpeg has neither ``drawtext`` nor ``subtitles`` (libass).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from vinci_media.encoders import pick_video_encoder
from vinci_media.ops import FFMPEG, FFPROBE, MediaError, _fontfile, probe, require_ffmpeg

BITRATE = "8M"  # h264_videotoolbox needs a bitrate; 8 Mb/s keeps 1080p clean


def _run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip()[-600:] or f"ffmpeg {what} failed")


def has_audio(path: Path) -> bool:
    """Return True when the file has a sound stream."""
    require_ffmpeg()
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return bool(proc.stdout.strip())


def normalize_clip(
    src: Path,
    dst: Path,
    start: float,
    end: float,
    width: int,
    height: int,
    fps: int,
    *,
    still: bool = False,
    audio: Path | None = None,
) -> Path:
    """Cut ``start`` to ``end`` seconds of a clip into the episode format.

    The result is ``width`` x ``height`` (fit, then pad), ``fps`` frames a second, with stereo
    AAC sound, so clips can be joined with fades. The sound is ``audio`` when given (from the
    start of the clip), else the clip's own, else silence; a shorter sound ends in silence.

    Args:
        src: A video, or a still image when ``still`` is True (it plays for ``end - start`` s).
        dst: The output file.
        start: First second of the clip to keep.
        end: Last second of the clip to keep.
        width: Frame width of the episode.
        height: Frame height of the episode.
        fps: Frames per second of the episode.
        still: ``src`` is an image (a keyframe take in the cut).
        audio: A separate sound for the clip, such as an OLF dialogue take.
    """
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    length = f"{max(end - start, 0.04):.3f}"
    inputs = (
        ["-loop", "1", "-t", length, "-i", str(src)]
        if still
        else ["-ss", f"{start:.3f}", "-t", length, "-i", str(src)]
    )
    sound = audio is None and not still and has_audio(src)
    if audio is not None:
        inputs += ["-i", str(audio)]
    elif not sound:
        inputs += [
            "-f",
            "lavfi",
            "-t",
            length,
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p"
    )
    _run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            *inputs,
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if sound else "1:a:0",
            "-af",
            "apad",  # a shorter sound ends in silence; -t cuts the clip to its length
            "-t",
            length,
            "-c:v",
            pick_video_encoder(),
            "-b:v",
            BITRATE,
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(dst),
        ],
        "normalize",
    )
    return dst


def join_clips(paths: list[Path], transitions: list[str], dst: Path, *, fade: float = 0.5) -> Path:
    """Join clips (all in one format, see ``normalize_clip``) in order.

    Each clip after the first starts with a cut, or with a crossfade of ``fade`` seconds when
    its transition is ``fade``. A fade overlaps the end of the clip before it.
    """
    require_ffmpeg()
    if not paths:
        raise MediaError("the cut has no clips")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if len(paths) == 1:
        shutil.copyfile(paths[0], dst)
        return dst
    lengths = [float(probe(path)["duration"]) for path in paths]
    graph: list[str] = []
    video, audio, total = "[0:v]", "[0:a]", lengths[0]
    for i in range(1, len(paths)):
        if transitions[i] == "fade":
            d = min(fade, lengths[i] / 2, total / 2)  # a short clip gets a shorter fade
            graph.append(
                f"{video}[{i}:v]xfade=transition=fade:duration={d:.3f}:offset={total - d:.3f}[v{i}]"
            )
            graph.append(f"{audio}[{i}:a]acrossfade=d={d:.3f}[a{i}]")
            total += lengths[i] - d
        else:
            graph.append(f"{video}{audio}[{i}:v][{i}:a]concat=n=2:v=1:a=1[v{i}][a{i}]")
            total += lengths[i]
        video, audio = f"[v{i}]", f"[a{i}]"
    inputs = [arg for path in paths for arg in ("-i", str(path))]
    _run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            *inputs,
            "-filter_complex",
            ";".join(graph),
            "-map",
            video,
            "-map",
            audio,
            "-c:v",
            pick_video_encoder(),
            "-b:v",
            BITRATE,
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ],
        "join",
    )
    return dst


CUE_FORMAT = "aformat=sample_rates=48000:channel_layouts=stereo"


def _placed(i: int, cue: dict[str, Any]) -> str:
    """The filter chain of input ``i``: the cue at its start (``adelay``) and its volume."""
    delay = round(float(cue["start"]) * 1000)
    return f"[{i}:a]{CUE_FORMAT},adelay={delay}:all=1,volume={float(cue['volume']):.3f}"


def mix_cues(video: Path, cues: list[dict[str, Any]], dst: Path) -> Path:
    """Lay music and SFX cues over a video's sound (OLF episode ``audio`` list).

    Each cue starts at ``start`` seconds, plays at ``volume``, and with ``duck`` gets quieter
    while the video's own sound (the dialogue) plays: ffmpeg ``sidechaincompress`` keyed by that
    sound. The video stream is copied, and the mix lasts as long as the video.

    Args:
        video: The joined episode, with a sound stream (``normalize_clip`` gives every clip one).
        cues: ``[{"file": Path, "start": s, "volume": v, "duck": bool}]``.
    """
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not cues:
        shutil.copyfile(video, dst)
        return dst
    keys = [i for i, cue in enumerate(cues, 1) if cue["duck"]]  # one copy of the sound per duck
    graph = [f"[0:a]{CUE_FORMAT},asplit={len(keys) + 1}[main]" + "".join(f"[key{i}]" for i in keys)]
    for i, cue in enumerate(cues, 1):
        chain = _placed(i, cue)
        if cue["duck"]:
            graph += [
                f"{chain}[raw{i}]",
                f"[raw{i}][key{i}]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[c{i}]",
            ]
        else:
            graph.append(f"{chain}[c{i}]")
    mix = "".join(f"[c{i}]" for i in range(1, len(cues) + 1))
    graph.append(f"[main]{mix}amix=inputs={len(cues) + 1}:duration=first:normalize=0[out]")
    inputs = [arg for path in [video, *(cue["file"] for cue in cues)] for arg in ("-i", str(path))]
    _run(
        [FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph)]
        + ["-map", "0:v", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", str(dst)],
        "mix cues",
    )
    return dst


def extract_audio(video: Path, dst: Path) -> Path:
    """The sound of a video as a WAV: the dialogue stem of an OLF export."""
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [FFMPEG, "-y", "-v", "error", "-i", str(video), "-vn", "-c:a", "pcm_s16le", str(dst)],
        "audio",
    )
    return dst


def stem_cues(cues: list[dict[str, Any]], seconds: float, dst: Path) -> Path:
    """One WAV of ``seconds`` with each cue at its ``start`` and ``volume``, not ducked: a music
    or SFX stem of an OLF export (``cues`` as for ``mix_cues``)."""
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    graph = [f"{_placed(i, cue)}[c{i}]" for i, cue in enumerate(cues, 1)]
    mix = "".join(f"[c{i}]" for i in range(1, len(cues) + 1))
    graph.append(f"[0:a]{mix}amix=inputs={len(cues) + 1}:duration=first:normalize=0[out]")
    silence = ["-f", "lavfi", "-t", f"{seconds:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    inputs = [arg for cue in cues for arg in ("-i", str(cue["file"]))]
    _run(
        [FFMPEG, "-y", "-v", "error", *silence, *inputs, "-filter_complex", ";".join(graph)]
        + ["-map", "[out]", "-c:a", "pcm_s16le", str(dst)],
        "stem",
    )
    return dst


def join_audio(paths: list[Path], dst: Path, *, gap: float = 0.3) -> Path:
    """Join speech files in order into one WAV (mono, 48 kHz), with ``gap`` seconds between.

    The OLF engine joins the lines of a shot's dialogue into one audio take with this. The
    files can differ in format (MP3 from a provider, WAV from the mock); ffmpeg decodes each.
    """
    require_ffmpeg()
    if not paths:
        raise MediaError("no audio to join")
    dst.parent.mkdir(parents=True, exist_ok=True)
    graph = [
        f"[{i}:a]aformat=sample_rates=48000:channel_layouts=mono"
        + (f",apad=pad_dur={gap:.3f}" if i < len(paths) - 1 else "")
        + f"[a{i}]"
        for i in range(len(paths))
    ]
    graph.append(
        "".join(f"[a{i}]" for i in range(len(paths))) + f"concat=n={len(paths)}:v=0:a=1[out]"
    )
    inputs = [arg for path in paths for arg in ("-i", str(path))]
    _run(
        [FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph)]
        + ["-map", "[out]", "-c:a", "pcm_s16le", str(dst)],
        "join audio",
    )
    return dst


def burn_cues(
    src: Path,
    dst: Path,
    cues: list[tuple[float, float, str]],
    *,
    width: int,
    height: int,
    sound: bool = True,
) -> Path:
    """Burn subtitles into a video: each cue ``(start, end, text)`` shows between its times.

    Each cue is a caption image (white text on a dark box, bottom center) drawn with Pillow and
    laid over the video with ``overlay``. Without cues the video is copied as it is. With
    ``sound=False`` the result has no audio stream.
    """
    from PIL import ImageFont  # imported here: only exports need Pillow

    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not cues and sound:
        shutil.copyfile(src, dst)
        return dst
    if not cues:  # no subtitles to burn: copy the picture only
        _run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-i",
                str(src),
                "-map",
                "0:v",
                "-c:v",
                "copy",
                "-an",
                str(dst),
            ],
            "mute",
        )
        return dst
    size = max(20, height // 24)  # 45 px on a 1080 px frame, 80 px on a 1920 px frame
    path = _fontfile()
    font: Any = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
    margin = int(height * 0.06)
    with tempfile.TemporaryDirectory(prefix="vinci-cues-") as raw:
        images = [
            _caption(Path(raw) / f"cue{i}.png", text, font, width)
            for i, (_, _, text) in enumerate(cues)
        ]
        graph, label = [], "[0:v]"
        for i, (start, end, _) in enumerate(cues, 1):
            graph.append(
                f"{label}[{i}:v]overlay=x=(W-w)/2:y=H-h-{margin}:enable='between(t,{start:.3f},{end:.3f})'[o{i}]"
            )
            label = f"[o{i}]"
        inputs = ["-i", str(src), *[arg for image in images for arg in ("-i", str(image))]]
        _run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                *inputs,
                "-filter_complex",
                ";".join(graph),
                "-map",
                label,
                *(["-map", "0:a?", "-c:a", "copy"] if sound else ["-an"]),
                "-c:v",
                pick_video_encoder(),
                "-b:v",
                BITRATE,
                "-pix_fmt",
                "yuv420p",
                str(dst),
            ],
            "subtitles",
        )
    return dst


def _caption(path: Path, text: str, font: Any, width: int) -> Path:
    """Draw one caption image: the text wrapped to 86% of the frame width, on a rounded dark box."""
    from PIL import Image, ImageDraw

    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and measure.textlength(trial, font=font) > width * 0.86:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    pad, step = int(font.size * 0.45), int(font.size * 1.25)
    box_w = int(max(measure.textlength(row, font=font) for row in lines)) + 2 * pad
    box_h = step * (len(lines) - 1) + font.size + 2 * pad
    image = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=pad, fill=(0, 0, 0, 150))
    for i, row in enumerate(lines):
        draw.text(
            ((box_w - measure.textlength(row, font=font)) / 2, pad + i * step),
            row,
            font=font,
            fill="white",
        )
    image.save(path)
    return path
