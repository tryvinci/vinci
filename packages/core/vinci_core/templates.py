from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any


def _catalog() -> dict[str, Any]:
    raw = (files("vinci_core") / "templates" / "catalog.json").read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


def list_templates() -> list[dict[str, Any]]:
    items = _catalog().get("templates") or []
    return [dict(item) for item in items if isinstance(item, dict)]


def get_template(template_id: str) -> dict[str, Any]:
    for item in list_templates():
        if item.get("id") == template_id:
            return item
    raise KeyError(template_id)


def preview_svg(template_id: str) -> str:
    """Original 16:9 poster. Geometric, not scraped stills."""
    try:
        item = get_template(template_id)
    except KeyError:
        item = {"id": template_id, "category": "image", "title": template_id}
    digest = hashlib.sha256(template_id.encode("utf-8")).hexdigest()
    hue = int(digest[:2], 16) * 360 // 255
    hue2 = (hue + 42 + int(digest[2:4], 16) // 6) % 360
    sat = 18 + int(digest[4:6], 16) % 16
    category = str(item.get("category") or "image")
    kind = str(item.get("preview_kind") or category)
    gid = "g" + digest[:8]
    if kind == "storyboard":
        shapes = "".join(
            f'<rect x="{36 + (i % 2) * 128}" y="{40 + (i // 2) * 62}" width="116" height="52" '
            f'rx="2" fill="hsl({(hue + i * 28) % 360} {sat}% {14 + i * 4}%)"/>'
            for i in range(4)
        )
    elif category == "motion":
        shapes = (
            f'<rect x="40" y="48" width="168" height="94" rx="2" fill="hsl({hue} {sat}% 10%)"/>'
            f'<polygon points="112,78 112,112 148,95" fill="hsl({hue2} 12% 86%)"/>'
        )
    elif category == "upscale":
        shapes = (
            f'<rect x="48" y="64" width="72" height="72" fill="hsl({hue} {sat}% 16%)"/>'
            f'<rect x="108" y="40" width="132" height="118" fill="none" '
            f'stroke="hsl({hue2} 14% 78%)" stroke-width="1.2"/>'
        )
    elif category == "clips":
        shapes = "".join(
            f'<rect x="{36 + i * 70}" y="{52 + (i % 2) * 8}" width="62" height="88" '
            f'fill="hsl({(hue + i * 22) % 360} {sat}% {12 + i * 5}%)"/>'
            for i in range(4)
        )
    elif category == "audio":
        bars = "".join(
            f'<rect x="{56 + i * 18}" y="{148 - h}" width="10" height="{h}" rx="1" '
            f'fill="hsl({hue2} 10% {70 - i}%)"/>'
            for i, h in enumerate((28, 52, 86, 44, 104, 36, 72, 24, 60, 40))
        )
        shapes = bars
    elif category == "ads":
        shapes = (
            f'<rect x="36" y="44" width="248" height="108" fill="hsl({hue} {sat}% 11%)"/>'
            f'<rect x="36" y="44" width="8" height="108" fill="hsl({hue2} 40% 52%)"/>'
        )
    elif category == "cinema":
        shapes = (
            f'<rect x="0" y="28" width="320" height="124" fill="#050505"/>'
            f'<rect x="0" y="28" width="320" height="10" fill="hsl({hue} 8% 18%)"/>'
            f'<rect x="0" y="142" width="320" height="10" fill="hsl({hue} 8% 18%)"/>'
            f'<circle cx="64" cy="90" r="18" fill="hsl({hue2} {sat}% 28%)"/>'
            f'<rect x="108" y="72" width="160" height="36" fill="hsl({hue} {sat}% 14%)"/>'
        )
    else:
        shapes = (
            f'<path d="M0 152 L90 78 L150 108 L210 58 L320 140 V180 H0 Z" '
            f'fill="hsl({hue} {sat}% 18%)"/>'
            f'<circle cx="78" cy="52" r="22" fill="hsl({hue2} 24% 62%)" opacity="0.55"/>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue} {sat}% 16%)"/>'
        f'<stop offset="1" stop-color="#09090b"/>'
        f"</linearGradient></defs>"
        f'<rect width="320" height="180" fill="url(#{gid})"/>'
        f"{shapes}"
        f"</svg>\n"
    )
