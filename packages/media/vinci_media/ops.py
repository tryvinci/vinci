from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


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
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise MediaError("ffmpeg/ffprobe not on PATH")


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
                "libx264",
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
            "libx264",
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
            "libx264",
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
                "libx264",
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
                "libx264",
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
    info = (
        probe(path)
        if path.suffix in {".mp4", ".mov", ".mkv", ".webm", ".wav", ".mp3"}
        else {"duration": 3.0}
    )
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
            "libx264",
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
