from __future__ import annotations

import platform
import subprocess


def ffmpeg_executable() -> str:
    from vinci_media.ops import _resolve_tool

    return _resolve_tool("ffmpeg", "VINCI_FFMPEG")


def pick_video_encoder() -> str:
    ffmpeg = ffmpeg_executable()
    if platform.system() == "Darwin":
        return "h264_videotoolbox"
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = proc.stdout or ""
    if "libx264" in text:
        return "libx264"
    return "mpeg4"
