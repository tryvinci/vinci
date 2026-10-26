from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from vinci_media.encoders import pick_video_encoder


def _resolve_tool(name: str, env_key: str) -> str:
    override = os.environ.get(env_key, "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path)
    bundled = os.environ.get(f"VINCI_BUNDLED_{name.upper()}", "").strip()
    if bundled:
        path = Path(bundled).expanduser()
        if path.is_file():
            return str(path)
    found = shutil.which(name)
    return found or name


FFMPEG = _resolve_tool("ffmpeg", "VINCI_FFMPEG")
FFPROBE = _resolve_tool("ffprobe", "VINCI_FFPROBE")


def _fontfile() -> str | None:
    for candidate in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ):
        if candidate.is_file():
            return str(candidate)
    return None


class MediaError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    ffmpeg = _resolve_tool("ffmpeg", "VINCI_FFMPEG")
    ffprobe = _resolve_tool("ffprobe", "VINCI_FFPROBE")
    if not Path(ffmpeg).is_file() and shutil.which(ffmpeg) is None:
        raise MediaError("ffmpeg not found (set VINCI_FFMPEG or PATH)")
    if not Path(ffprobe).is_file() and shutil.which(ffprobe) is None:
        raise MediaError("ffprobe not found (set VINCI_FFPROBE or PATH)")


def probe(path: Path) -> dict[str, Any]:
    require_ffmpeg()
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffprobe failed")
    data = json.loads(proc.stdout or "{}")
    duration = float((data.get("format") or {}).get("duration") or 0)
    width = height = None
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video":
            width = stream.get("width")
            height = stream.get("height")
    return {"duration": duration, "width": width, "height": height}


def cut(src: Path, dst: Path, start: float, end: float) -> Path:
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(src),
            "-c",
            "copy",
            str(dst),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not dst.is_file():
        proc = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-ss",
                f"{start:.3f}",
                "-to",
                f"{end:.3f}",
                "-i",
                str(src),
                "-c:v",
                pick_video_encoder(),
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                str(dst),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg cut failed")
    return dst


def reframe_9x16(src: Path, dst: Path) -> Path:
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
    proc = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            "-vf",
            vf,
            "-c:v",
            pick_video_encoder(),
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg reframe failed")
    return dst


def burn_captions(src: Path, dst: Path, text: str) -> Path:
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    safe = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")[:80]
    font = _fontfile()
    font_opt = f":fontfile='{font}'" if font else ""
    vf = (
        f"drawtext=text='{safe}'{font_opt}:fontcolor=white:fontsize=24:"
        "x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.5"
    )
    proc = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            "-vf",
            vf,
            "-c:v",
            pick_video_encoder(),
            "-c:a",
            "copy",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(src),
                "-vf",
                vf,
                "-c:v",
                pick_video_encoder(),
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                str(dst),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg caption failed")
    return dst


def concat(paths: list[Path], dst: Path) -> Path:
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    listing = dst.with_suffix(".txt")
    listing.write_text("".join(f"file '{p}'\n" for p in paths), encoding="utf-8")
    proc = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(dst),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            [
                FFMPEG,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c:v",
                pick_video_encoder(),
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                str(dst),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg concat failed")
    return dst


def render_timeline(paths: list[Path], dst: Path) -> Path:
    """Concatenate clip files into one video. Cuts happen before this call."""
    if not paths:
        raise MediaError("timeline has no clips")
    if len(paths) == 1:
        require_ffmpeg()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths[0], dst)
        return dst
    return concat(paths, dst)


def mock_transcribe(path: Path) -> dict[str, Any]:
    """Deterministic local transcript. Not copied from any AGPL source."""
    try:
        # Probe regardless of extension: engine-materialized CAS blobs have no
        # suffix, and ffprobe sniffs the container anyway.
        info = probe(path)
    except MediaError:
        info = {"duration": 3.0}
    duration = max(float(info.get("duration") or 3.0), 1.0)
    mid = duration / 2
    return {
        "text": "Welcome to the show. Today we mention pricing and then wrap up.",
        "words": [
            {"start": 0.0, "end": max(mid - 0.4, 0.2), "text": "Welcome to the show."},
            {"start": max(mid - 0.4, 0.2), "end": mid + 0.6, "text": "Today we mention pricing"},
            {"start": mid + 0.6, "end": duration, "text": "and then wrap up."},
        ],
        "duration": duration,
    }


def split_fixed(duration: float, count: int = 3) -> list[dict[str, Any]]:
    n = max(int(count), 1)
    length = max(float(duration), 0.1) / n
    return [
        {"start": i * length, "end": (i + 1) * length, "reason": f"part {i + 1}"} for i in range(n)
    ]


def make_fixture_video(path: Path, duration: float = 3.0) -> Path:
    """Tiny synthetic MP4 for tests. Not sourced from any AGPL tree."""
    require_ffmpeg()
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=1280x720:d={duration:.3f}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration:.3f}",
            "-shortest",
            "-c:v",
            pick_video_encoder(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg fixture failed")
    return path


def select_windows(
    transcript: dict[str, Any], query: str = "pricing", count: int = 1
) -> list[dict[str, Any]]:
    needle = query.lower()
    hits = [w for w in transcript.get("words") or [] if needle in str(w.get("text", "")).lower()]
    if not hits:
        duration = float(transcript.get("duration") or 3)
        hits = [{"start": 0.0, "end": min(3.0, duration), "text": transcript.get("text", "")}]
    windows: list[dict[str, Any]] = []
    for word in hits[:count]:
        start = max(float(word.get("start") or 0) - 0.2, 0.0)
        end = float(word.get("end") or start + 1.5) + 0.2
        windows.append({"start": start, "end": end, "reason": word.get("text")})
    return windows


FILLER_WORDS = frozenset(
    {"um", "uh", "erm", "like", "basically", "actually", "literally"}
)

EFFECT_KINDS = ("zoom_in", "spotlight", "callout")


def polish_script(transcript: dict[str, Any], style: str = "product-demo") -> dict[str, Any]:
    """Deterministic script polish: drop filler words, split into timed lines.

    $0 by construction - no LLM call; real polish can layer on later behind a key.
    """
    text = str(transcript.get("text") or "")
    words = [w for w in text.split() if w.lower().strip(",.;:!?") not in FILLER_WORDS]
    clean = " ".join(words).strip()
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", clean) if p.strip()]
    if not parts and clean:
        parts = [clean]
    segments = transcript.get("segments") or []
    duration = 0.0
    if segments and isinstance(segments[-1], dict):
        duration = float(segments[-1].get("end") or 0)
    if duration <= 0:
        duration = float(transcript.get("duration") or 0)
    count = max(len(parts), 1)
    step = duration / count if duration > 0 else 0.0
    lines = [
        {
            "line": part,
            "start": round(index * step, 3),
            "end": round((index + 1) * step, 3),
        }
        for index, part in enumerate(parts)
    ]
    return {
        "style": style,
        "text": " ".join(parts),
        "lines": lines,
        "duration": duration,
    }


def plan_effects(script: dict[str, Any], width: int = 1920, height: int = 1080) -> dict[str, Any]:
    """Deterministic effect plan: one effect per script line, kinds rotate."""
    lines = script.get("lines") or []
    effects: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        kind = EFFECT_KINDS[index % len(EFFECT_KINDS)]
        effect: dict[str, Any] = {
            "type": kind,
            "start": float(line.get("start") or 0),
            "end": float(line.get("end") or 0),
        }
        if kind == "zoom_in":
            effect["params"] = {"scale": 1.15, "anchor": "center"}
        elif kind == "spotlight":
            effect["params"] = {
                "x": width // 4,
                "y": height // 4,
                "w": width // 2,
                "h": height // 2,
            }
        else:
            effect["params"] = {
                "text": str(line.get("line") or "")[:48],
                "position": "lower-third",
            }
        effects.append(effect)
    return {
        "effects": effects,
        "duration": float(script.get("duration") or 0),
        "width": width,
        "height": height,
    }


def _effect_filter(effect: dict[str, Any] | None, width: int, height: int) -> str | None:
    if not effect:
        return None
    kind = effect.get("type")
    params = effect.get("params") or {}
    if kind == "zoom_in":
        scale = float(params.get("scale") or 1.15)
        if scale <= 1.0:
            return None
        return f"crop=iw/{scale}:ih/{scale},scale={width}:{height}"
    if kind == "spotlight":
        x = int(params.get("x") or 0)
        y = int(params.get("y") or 0)
        w = int(params.get("w") or width // 2)
        h = int(params.get("h") or height // 2)
        return f"drawbox={x}:{y}:{w}:{h}:color=yellow@0.9:t=8"
    if kind == "callout":
        text = str(params.get("text") or "").replace(":", "\\:").replace("'", "")
        if not text:
            return None
        font = _fontfile()
        if font:
            return (
                f"drawtext=fontfile='{font}':text='{text}'"
                ":x=(w-text_w)/2:y=h-120:fontsize=42:fontcolor=white"
                ":box=1:boxcolor=black@0.6:boxborderw=12"
            )
        return f"drawbox=0:{height - 120}:{width}:80:color=black@0.6:t=fill"
    return None


def apply_effects(src: Path, dst: Path, plan: dict[str, Any]) -> Path:
    """Render the effect plan onto the recording. FFmpeg only, $0."""
    require_ffmpeg()
    effects = plan.get("effects") or []
    if not effects:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return dst
    info = probe(src)
    duration = float(info.get("duration") or 0)
    width = int(info.get("width") or plan.get("width") or 1920)
    height = int(info.get("height") or plan.get("height") or 1080)
    work = dst.parent / (dst.stem + "-segments")
    work.mkdir(parents=True, exist_ok=True)
    timeline: list[tuple[float, float, dict[str, Any] | None]] = []
    cursor = 0.0
    for effect in sorted(effects, key=lambda item: float(item.get("start") or 0)):
        start = float(effect.get("start") or 0)
        end = float(effect.get("end") or 0)
        if end <= start:
            continue
        if start > cursor:
            timeline.append((cursor, start, None))
        timeline.append((start, end, effect))
        cursor = end
    if duration > cursor:
        timeline.append((cursor, duration, None))
    parts: list[Path] = []
    for index, (start, end, effect) in enumerate(timeline):
        if end - start < 0.05:
            continue
        part = work / f"seg-{index:03d}.mp4"
        cmd = [
            FFMPEG,
            "-y",
            "-i",
            str(src),
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
        ]
        vf = _effect_filter(effect, width, height)
        if vf:
            cmd += ["-vf", vf]
        cmd += [
            "-c:v",
            pick_video_encoder(),
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(part),
        ]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MediaError(proc.stderr.strip() or "ffmpeg apply_effects segment failed")
        parts.append(part)
    if not parts:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return dst
    concat(parts, dst)
    return dst


def synth_voiceover(script: dict[str, Any], dst: Path, voice: str | None = None) -> Path:
    """Mock narration track: one soft tone per script line, silence elsewhere.

    $0 and deterministic; a real TTS provider only enters when a key is set,
    which is outside this op.
    """
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    lines = [line for line in (script.get("lines") or []) if isinstance(line, dict)]
    duration = float(script.get("duration") or 0)
    if duration <= 0 and lines:
        duration = max(float(line.get("end") or 0) for line in lines)
    if duration <= 0:
        duration = 1.0
    if not lines:
        cmd = [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=mono:d={duration:.3f}",
            str(dst),
        ]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MediaError(proc.stderr.strip() or "ffmpeg synth_voiceover failed")
        return dst
    filters: list[str] = []
    mix_inputs: list[str] = []
    for index, line in enumerate(lines):
        start = max(float(line.get("start") or 0), 0.0)
        end = max(float(line.get("end") or 0), start + 0.1)
        length = end - start
        freq = 360 + (index % 5) * 60
        delay_ms = int(start * 1000)
        filters.append(
            f"sine=frequency={freq}:duration={length:.3f}[tone{index}]"
        )
        filters.append(
            f"[tone{index}]adelay={delay_ms}|{delay_ms},volume=0.08[d{index}]"
        )
        mix_inputs.append(f"[d{index}]")
    filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:normalize=0,apad,atrim=0:{duration:.3f}[out]"
    )
    cmd = [
        FFMPEG,
        "-y",
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-t",
        f"{duration:.3f}",
        str(dst),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg synth_voiceover failed")
    return dst


def mux_audio(video: Path, audio: Path, dst: Path) -> Path:
    """Mux a narration track under the rendered video."""
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG,
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(dst),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg mux_audio failed")
    return dst
