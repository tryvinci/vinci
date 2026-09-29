from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def compose_shot_prompt(inputs: Mapping[str, Any] | None) -> str:
    """Fold camera / lens / look / lighting / palette / motion into the prompt.

    Empty extras stay off the seed.
    """
    blob = dict(inputs or {})
    prompt = str(blob.get("prompt") or blob.get("text") or "")
    extras: list[str] = []
    camera = str(blob.get("camera") or "").strip()
    lens = str(blob.get("lens") or "").strip()
    look = str(blob.get("look") or "").strip()
    motion = str(blob.get("motion") or "").strip()
    aperture = str(blob.get("aperture") or "").strip()
    genre = str(blob.get("genre") or "").strip()
    scene = str(blob.get("scene") or "").strip()
    lighting = str(blob.get("lighting") or "").strip()
    palette = str(blob.get("palette") or "").strip()
    if camera:
        extras.append(f"shot on {camera}")
    if lens:
        extras.append(f"{lens} lens")
    if aperture:
        extras.append(f"{aperture} aperture")
    if look:
        extras.append(f"{look} look")
    if genre:
        extras.append(f"{genre} genre")
    if lighting and lighting not in {"available", ""}:
        extras.append(f"{lighting} lighting")
    if palette and palette not in {"filmic", ""}:
        extras.append(f"{palette} palette")
    if scene and scene not in {"general", ""}:
        extras.append(f"{scene} talking scene")
    if motion and motion not in {"static", ""}:
        extras.append(f"{motion} camera move")
    if not extras:
        return prompt
    if prompt:
        return f"{prompt}, {', '.join(extras)}"
    return ", ".join(extras)


def mock_duration_seconds(duration: object | None = None) -> float:
    """Unset duration stays 1s so default mock clips match the fixture swatch path."""
    if duration in (None, ""):
        return 1.0
    try:
        value = float(duration)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    if value <= 0:
        return 1.0
    return min(value, 15.0)
