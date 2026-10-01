"""User-defined adapt presets stored at ~/.vinci/custom_presets.json.

The on-disk shape matches PartnerAdaptPreset: id, label, partner, width,
height, optional byte_cap, optional safe_rect_margins_px.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from vinci_core.paths import default_home

from vinci_media.partner_presets import (
    PARTNER_ADAPT_PRESETS,
    ByteCap,
    ByteCapOp,
    PartnerAdaptPreset,
    SafeRectMarginsPx,
    partner_preset_document,
)

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_DIMENSION = 8192
_MAX_BYTES = 20 * 1024 * 1024
_FILENAME = "custom_presets.json"

_PARTNER_IDS = frozenset(preset.id for preset in PARTNER_ADAPT_PRESETS)


def _reserved_ids(home: Path | None = None) -> set[str]:
    from vinci_media.adapt import ADAPT_PRESETS

    taken = {preset.id for preset in ADAPT_PRESETS}
    taken.update(_PARTNER_IDS)
    taken.update(preset.id for preset in load_custom_presets(home))
    return taken


def presets_path(home: Path | None = None) -> Path:
    root = home if home is not None else default_home()
    return root / _FILENAME


def load_custom_presets(home: Path | None = None) -> list[PartnerAdaptPreset]:
    path = presets_path(home)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("presets") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("custom_presets.json must contain a presets array")
    presets: list[PartnerAdaptPreset] = []
    for row in rows:
        if isinstance(row, dict):
            presets.append(_preset_from_document(row))
    return presets


def save_custom_presets(presets: list[PartnerAdaptPreset], home: Path | None = None) -> Path:
    path = presets_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"presets": [_preset_to_storage(preset) for preset in presets]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def custom_preset_by_id(preset_id: str, home: Path | None = None) -> PartnerAdaptPreset | None:
    for preset in load_custom_presets(home):
        if preset.id == preset_id:
            return preset
    return None


def custom_presets_document(home: Path | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for preset in load_custom_presets(home):
        doc = partner_preset_document(preset)
        doc["source"] = "custom"
        rows.append(doc)
    return rows


def create_custom_preset(body: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    preset = validate_custom_preset(body, home=home)
    existing = load_custom_presets(home)
    if preset.id in _reserved_ids(home):
        raise ValueError(f"preset id already exists: {preset.id}")
    existing.append(preset)
    save_custom_presets(existing, home)
    doc = partner_preset_document(preset)
    doc["source"] = "custom"
    return doc


def delete_custom_preset(preset_id: str, home: Path | None = None) -> None:
    if preset_id in _reserved_ids(home) and custom_preset_by_id(preset_id, home) is None:
        raise KeyError(preset_id)
    existing = load_custom_presets(home)
    kept = [row for row in existing if row.id != preset_id]
    if len(kept) == len(existing):
        raise KeyError(preset_id)
    save_custom_presets(kept, home)


def validate_custom_preset(body: dict[str, Any], home: Path | None = None) -> PartnerAdaptPreset:
    if not isinstance(body, dict):
        raise ValueError("preset body must be an object")
    label = str(body.get("label") or "").strip()
    if not label or len(label) > 80:
        raise ValueError("label is required (1–80 characters)")
    partner = str(body.get("partner") or body.get("platform") or "").strip().lower()
    if not partner or len(partner) > 40:
        raise ValueError("platform is required")
    width = _positive_int(body.get("width"), "width")
    height = _positive_int(body.get("height"), "height")
    if width > _MAX_DIMENSION or height > _MAX_DIMENSION:
        raise ValueError(f"dimensions must be 1–{_MAX_DIMENSION} px")
    preset_id = str(body.get("id") or "").strip()
    if preset_id:
        if not _ID_RE.fullmatch(preset_id):
            raise ValueError("id must match [a-z][a-z0-9_]{0,63}")
    else:
        preset_id = _allocate_id(label, partner, width, height, home)
    byte_cap = _parse_byte_cap(body.get("byte_cap"))
    margins = _parse_margins(body.get("safe_rect_margins_px"), width, height)
    return PartnerAdaptPreset(
        id=preset_id,
        label=label,
        partner=partner,
        width=width,
        height=height,
        spec_kind="custom",
        byte_cap=byte_cap,
        safe_rect_margins_px=margins,
    )


def _allocate_id(
    label: str, partner: str, width: int, height: int, home: Path | None
) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"{re.sub(r'[^a-z0-9]+', '_', partner).strip('_') or 'custom'}_{width}x{height}"
    slug = slug[:48]
    taken = _reserved_ids(home)
    candidate = slug
    n = 2
    while candidate in taken or not _ID_RE.fullmatch(candidate):
        suffix = f"_{n}"
        candidate = f"{slug[: 64 - len(suffix)]}{suffix}"
        n += 1
        if n > 1000:
            raise ValueError("could not allocate a unique preset id")
    return candidate


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a positive integer")
    number = int(value)
    if number != value or number < 1:
        raise ValueError(f"{name} must be a positive integer")
    return number


def _parse_byte_cap(raw: Any) -> ByteCap | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("byte_cap must be an object with max_bytes and op")
    max_bytes = raw.get("max_bytes")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("byte_cap.max_bytes must be a positive integer")
    if max_bytes > _MAX_BYTES:
        raise ValueError(f"byte_cap.max_bytes must be ≤ {_MAX_BYTES}")
    op_raw = str(raw.get("op") or "lte")
    if op_raw not in {"lte", "lt"}:
        raise ValueError("byte_cap.op must be lte or lt")
    op: ByteCapOp = "lte" if op_raw == "lte" else "lt"
    return ByteCap(max_bytes=max_bytes, op=op)


def _parse_margins(raw: Any, width: int, height: int) -> SafeRectMarginsPx | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("safe_rect_margins_px must be an object")
    edges = {}
    for key in ("left", "right", "top", "bottom"):
        value = raw.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"safe_rect_margins_px.{key} must be a non-negative integer")
        edges[key] = value
    if edges["left"] + edges["right"] >= width or edges["top"] + edges["bottom"] >= height:
        raise ValueError("safe-area margins must leave a positive content rectangle")
    return SafeRectMarginsPx(**edges)


def _preset_from_document(row: dict[str, Any]) -> PartnerAdaptPreset:
    margins = row.get("safe_rect_margins_px")
    safe: SafeRectMarginsPx | None = None
    if isinstance(margins, dict):
        safe = SafeRectMarginsPx(
            left=int(margins.get("left") or 0),
            right=int(margins.get("right") or 0),
            top=int(margins.get("top") or 0),
            bottom=int(margins.get("bottom") or 0),
        )
    cap_raw = row.get("byte_cap")
    cap: ByteCap | None = None
    if isinstance(cap_raw, dict) and cap_raw.get("max_bytes"):
        op_raw = str(cap_raw.get("op") or "lte")
        stored_op: ByteCapOp = "lt" if op_raw == "lt" else "lte"
        cap = ByteCap(max_bytes=int(cap_raw["max_bytes"]), op=stored_op)
    return PartnerAdaptPreset(
        id=str(row["id"]),
        label=str(row.get("label") or row["id"]),
        partner=str(row.get("partner") or row.get("platform") or "custom"),
        width=int(row["width"]),
        height=int(row["height"]),
        spec_kind="custom",
        byte_cap=cap,
        safe_rect_margins_px=safe,
    )


def _preset_to_storage(preset: PartnerAdaptPreset) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": preset.id,
        "label": preset.label,
        "partner": preset.partner,
        "width": preset.width,
        "height": preset.height,
    }
    if preset.byte_cap is not None:
        body["byte_cap"] = {"max_bytes": preset.byte_cap.max_bytes, "op": preset.byte_cap.op}
    if preset.safe_rect_margins_px is not None:
        margins = preset.safe_rect_margins_px
        body["safe_rect_margins_px"] = {
            "left": margins.left,
            "right": margins.right,
            "top": margins.top,
            "bottom": margins.bottom,
        }
    return body
