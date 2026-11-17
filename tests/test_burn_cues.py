"""Burned-in subtitles (vinci_media.episode.burn_cues)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_back_to_back_lines_never_share_a_frame(tmp_path: Path) -> None:
    """COREPRODUC-671: two lines of one shot meet at a time (0-1 s and 1-2 s). At exactly 1 s the
    export showed both captions over each other (`between` includes both ends). Now the frame at
    1 s shows only the second line: its caption matches the frame at 1.5 s."""
    if not shutil.which("ffmpeg"):
        pytest.skip("burn_cues runs ffmpeg")
    from PIL import Image, ImageChops
    from vinci_media.episode import burn_cues

    src, dst = tmp_path / "black.mp4", tmp_path / "subtitled.mp4"
    color = "color=c=black:s=640x360:r=24:d=2"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", color, "-pix_fmt", "yuv420p", str(src)],
        check=True,
    )
    cues = [(0.0, 1.0, "Mira: What if it goes out?"), (1.0, 2.0, "Tomas: Then you light it.")]
    burn_cues(src, dst, cues, width=640, height=360, sound=False)

    def frame(seconds: float) -> Image.Image:
        out = tmp_path / f"f{seconds}.png"
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{seconds}", "-i", str(dst), "-frames:v", "1"]
        subprocess.run([*cmd, str(out)], check=True)
        return Image.open(out).convert("L")

    def apart(a: Image.Image, b: Image.Image) -> float:
        """Mean pixel difference: lossy encoders (libx264, VideoToolbox) are not bit-exact."""
        return sum(ImageChops.difference(a, b).getdata()) / (a.width * a.height)

    boundary, second, first = frame(1.0), frame(1.5), frame(0.5)
    assert apart(first, second) > 1  # the two lines differ
    # The old overlap measured 0.22 of the first-to-second distance on this Mac; the fix is 0 here.
    assert apart(boundary, second) < apart(first, second) / 10  # only the second line, not both
