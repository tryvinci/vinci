"""Checks on a rendered take, written to the take's ``qa`` list (SPEC.md, Takes).

The palette check needs no model: it asks whether the take's main colors match the palettes of
the forms of the characters in the shot. Each palette color counts by how close the nearest
main color is, so a render that loses a character's colors scores low. It is a cheap signal,
not a likeness check (no identity model runs locally).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
PASS = 0.6  # the lowest palette score that passes
FAR = 120.0  # an RGB distance (0-441) at which a color counts as missing


def palettes(view: dict[str, Any]) -> list[str]:
    """The ``#rrggbb`` colors the shot should show: each character's form palette."""
    colors = [
        str(color)
        for char in view.get("characters") or []
        for color in ((char.get("form") or {}).get("palette") or [])
    ]
    return list(dict.fromkeys(c for c in colors if len(c) == 7 and c.startswith("#")))


def _still(path: Path, tmp: Path) -> Path:
    """The image to check: the file itself, or the middle frame of a video (ffmpeg)."""
    if path.suffix.lower() not in (".mp4", ".webm", ".mov"):
        return path
    from vinci_media import probe
    from vinci_media.ops import FFMPEG

    middle = max(float(probe(path)["duration"]) / 2, 0.0)
    frame = tmp / "frame.png"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v",
            "error",
            "-ss",
            f"{middle:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            str(frame),
        ],
        check=True,
        capture_output=True,
    )
    return frame


def palette_check(path: Path, colors: list[str]) -> dict[str, Any] | None:
    """Score how well an image or video keeps ``colors`` (0 to 1); ``None`` with no palette."""
    if not colors:
        return None
    from PIL import Image

    try:
        with tempfile.TemporaryDirectory(prefix="olf-qa-") as raw:
            image = Image.open(_still(path, Path(raw))).convert("RGB")
            image.thumbnail((160, 160))
            colors_in = image.quantize(colors=12).convert("RGB").getcolors(256) or []
            main: list[Any] = [rgb for _, rgb in colors_in]  # (r, g, b) tuples
    except Exception as exc:  # noqa: BLE001 - a failed check must not lose the take
        log.warning("qa: no palette check for %s: %s", path, exc)
        return None
    wanted = [tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in colors]
    near = [
        min(sum((a - b) ** 2 for a, b in zip(w, m, strict=True)) ** 0.5 for m in main)
        for w in wanted
    ]
    score = round(sum(max(0.0, 1 - d / FAR) for d in near) / len(near), 2)
    return {"check": "palette", "score": score, "pass": score >= PASS}
