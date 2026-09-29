from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from vinci_media.ops import FFMPEG, MediaError, probe, require_ffmpeg
from vinci_media.partner_presets import (
    PARTNER_ADAPT_PRESETS,
    PartnerAdaptPreset,
    check_export_bytes,
    partner_preset_by_id,
    partner_preset_document,
)

AdaptLayout = Literal["fit_pad_crop", "ai_extend"]
FitMode = Literal["fit", "pad", "crop"]

MAX_OUTPUT_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class SafeArea:
    top: float
    bottom: float
    left: float
    right: float


@dataclass(frozen=True)
class AdaptPreset:
    id: str
    label: str
    platform: str
    width: int
    height: int
    safe_area: SafeArea


ADAPT_PRESETS: tuple[AdaptPreset, ...] = (
    AdaptPreset(
        id="instagram_feed",
        label="Instagram feed (1:1)",
        platform="instagram",
        width=1080,
        height=1080,
        safe_area=SafeArea(0.08, 0.12, 0.06, 0.06),
    ),
    AdaptPreset(
        id="instagram_story",
        label="Instagram story (9:16)",
        platform="instagram",
        width=1080,
        height=1920,
        safe_area=SafeArea(0.14, 0.18, 0.06, 0.06),
    ),
    AdaptPreset(
        id="youtube_thumb",
        label="YouTube thumbnail (16:9)",
        platform="youtube",
        width=1280,
        height=720,
        safe_area=SafeArea(0.06, 0.1, 0.05, 0.05),
    ),
    AdaptPreset(
        id="linkedin_post",
        label="LinkedIn post (4:5)",
        platform="linkedin",
        width=1080,
        height=1350,
        safe_area=SafeArea(0.08, 0.12, 0.06, 0.06),
    ),
    AdaptPreset(
        id="x_post",
        label="X / Twitter post (16:9)",
        platform="x",
        width=1600,
        height=900,
        safe_area=SafeArea(0.06, 0.1, 0.05, 0.05),
    ),
)


def presets_document() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for preset in ADAPT_PRESETS:
        rows.append(
            {
                "id": preset.id,
                "label": preset.label,
                "platform": preset.platform,
                "spec_kind": "generic",
                "width": preset.width,
                "height": preset.height,
                "safe_area": {
                    "top": preset.safe_area.top,
                    "bottom": preset.safe_area.bottom,
                    "left": preset.safe_area.left,
                    "right": preset.safe_area.right,
                },
            }
        )
    rows.extend(partner_preset_document(p) for p in PARTNER_ADAPT_PRESETS)
    return rows


def preset_by_id(preset_id: str) -> AdaptPreset | None:
    for preset in ADAPT_PRESETS:
        if preset.id == preset_id:
            return preset
    return None


def resolve_preset(preset_id: str) -> AdaptPreset | PartnerAdaptPreset | None:
    return preset_by_id(preset_id) or partner_preset_by_id(preset_id)


def resolve_target(raw: dict[str, Any]) -> tuple[int, int, str | None]:
    preset_id = raw.get("preset_id")
    if isinstance(preset_id, str) and preset_id:
        preset = resolve_preset(preset_id)
        if preset is None:
            raise ValueError(f"unknown adapt preset: {preset_id}")
        return preset.width, preset.height, preset.id
    width = int(raw.get("width") or 0)
    height = int(raw.get("height") or 0)
    if width < 16 or height < 16 or width > 4096 or height > 4096:
        raise ValueError("custom adapt size must be 16–4096 px")
    return width, height, None


def _vf_fit_pad_crop(width: int, height: int, fit: FitMode) -> str:
    if fit == "crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    if fit == "pad":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease"


def adapt_image_fit_pad_crop(
    src: Path,
    dst: Path,
    *,
    width: int,
    height: int,
    fit: FitMode = "fit",
    preset_id: str | None = None,
) -> Path:
    require_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = _vf_fit_pad_crop(width, height, fit)
    args = [FFMPEG, "-y", "-i", str(src), "-vf", vf, "-frames:v", "1"]
    if str(dst).lower().endswith((".jpg", ".jpeg")):
        args.extend(["-q:v", "5"])
    args.append(str(dst))
    proc = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MediaError(proc.stderr.strip() or "ffmpeg adapt failed")
    validate_output_image(dst, width=width, height=height, preset_id=preset_id)
    return dst


def adapt_image_ai_extend_placeholder(
    src: Path,
    dst: Path,
    *,
    width: int,
    height: int,
    preset_id: str | None = None,
) -> Path:
    """Mock/local placeholder: letterbox pad only. Live OpenAI extend uses provider i2i."""
    return adapt_image_fit_pad_crop(
        src, dst, width=width, height=height, fit="pad", preset_id=preset_id
    )


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    out_w = int.from_bytes(header[16:20], "big")
    out_h = int.from_bytes(header[20:24], "big")
    return out_w, out_h


def validate_export_for_preset(
    path: Path,
    preset_id: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    partner = partner_preset_by_id(preset_id)
    if partner is None:
        return {"spec_kind": "generic", "automated": {"dimensions_ok": True, "bytes_ok": True}}
    size = path.stat().st_size
    automated: dict[str, Any] = {
        "dimensions_ok": True,
        "bytes_ok": True,
        "byte_cap_ok": None,
    }
    if partner.byte_cap is not None:
        ok = check_export_bytes(size, partner.byte_cap)
        automated["byte_cap_ok"] = ok
        automated["bytes_ok"] = ok
        if not ok:
            raise MediaError(
                f"export {size} bytes fails preset {preset_id} cap "
                f"({partner.byte_cap.op} {partner.byte_cap.max_bytes})"
            )
    safe_overlay: dict[str, Any] | None = None
    if partner.safe_rect_margins_px is not None:
        m = partner.safe_rect_margins_px
        safe_overlay = {
            "kind": "margins_px",
            "left": m.left,
            "right": m.right,
            "top": m.top,
            "bottom": m.bottom,
            "content_box": {
                "x": m.left,
                "y": m.top,
                "w": width - m.left - m.right,
                "h": height - m.top - m.bottom,
            },
            "note": (
                "Overlay guide for reviewers; ffmpeg fit/pad/crop does not "
                "intelligently re-layout creative inside this box."
            ),
        }
    return {
        "spec_kind": partner.spec_kind,
        "preset_id": preset_id,
        "partner": partner.partner,
        "automated": automated,
        "export_bytes": size,
        "safe_rect_overlay": safe_overlay,
        "human_review_advisories": list(partner.human_review_advisories),
    }


def validate_output_image(
    path: Path,
    *,
    width: int,
    height: int,
    preset_id: str | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        raise MediaError("adapt output missing")
    size = path.stat().st_size
    if size <= 0 or size > MAX_OUTPUT_BYTES:
        raise MediaError(f"adapt output size out of range: {size} bytes")
    dims = _png_dimensions(path)
    if dims is None:
        meta = probe(path)
        streams = meta.get("streams") or []
        image_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if image_stream is None:
            image_stream = streams[0] if streams else {}
        dims = (int(image_stream.get("width") or 0), int(image_stream.get("height") or 0))
    out_w, out_h = dims
    if out_w != width or out_h != height:
        raise MediaError(f"adapt output dimensions {out_w}x{out_h} != {width}x{height}")
    base: dict[str, Any] = {"width": out_w, "height": out_h, "bytes": size, "path": str(path)}
    if preset_id:
        base["export_validation"] = validate_export_for_preset(path, preset_id, width, height)
    return base


def safe_area_report(preset_id: str | None, width: int, height: int) -> dict[str, Any]:
    partner = partner_preset_by_id(preset_id or "") if preset_id else None
    if partner is not None:
        return _partner_safe_area_without_file(partner, width, height)

    preset = preset_by_id(preset_id or "") if preset_id else None
    if preset:
        sa = preset.safe_area
    else:
        sa = SafeArea(0.08, 0.1, 0.06, 0.06)
    return {
        "width": width,
        "height": height,
        "preset_id": preset_id,
        "spec_kind": "generic",
        "safe_rect": {
            "x": int(width * sa.left),
            "y": int(height * sa.top),
            "w": int(width * (1 - sa.left - sa.right)),
            "h": int(height * (1 - sa.top - sa.bottom)),
        },
        "checks": [
            "Keep logos and text inside the safe rect for this preset.",
            "Fit/pad/crop is deterministic ffmpeg scaling only (not intelligent re-layout).",
            "AI extend is a separate OpenAI image-edit path when live spend is on.",
        ],
        "human_review_advisories": [],
    }


def _partner_safe_area_without_file(
    partner: PartnerAdaptPreset, width: int, height: int
) -> dict[str, Any]:
    safe_rect: dict[str, Any] | None = None
    safe_overlay: dict[str, Any] | None = None
    if partner.safe_rect_margins_px is not None:
        m = partner.safe_rect_margins_px
        safe_rect = {
            "x": m.left,
            "y": m.top,
            "w": width - m.left - m.right,
            "h": height - m.top - m.bottom,
        }
        safe_overlay = {
            "kind": "margins_px",
            "left": m.left,
            "right": m.right,
            "top": m.top,
            "bottom": m.bottom,
            "content_box": safe_rect,
            "note": (
                "Client-partner safe rectangle overlay (review guide). "
                "ffmpeg fit/pad/crop does not auto-place creative."
            ),
        }
    return {
        "width": width,
        "height": height,
        "preset_id": partner.id,
        "spec_kind": partner.spec_kind,
        "partner": partner.partner,
        "safe_rect": safe_rect,
        "safe_rect_overlay": safe_overlay,
        "export_validation": partner_preset_document(partner)["export_validation"],
        "human_review_advisories": list(partner.human_review_advisories),
        "checks": [
            "Client-partner spec (not a general platform rule).",
            "Automated checks: export dimensions and file bytes when a cap is defined.",
            "Human-review advisories are listed separately and are not auto-validated.",
            "Fit/pad/crop is deterministic ffmpeg scaling only (not intelligent re-layout).",
            "AI extend is a separate OpenAI image-edit path when live spend is on.",
        ],
    }


def estimate_adapt_targets(
    targets: list[dict[str, Any]],
    *,
    layout: AdaptLayout,
    unit_cost_ai: float,
) -> dict[str, Any]:
    if not targets:
        raise ValueError("at least one adapt target required")
    per_target: list[dict[str, Any]] = []
    total = 0.0
    for index, raw in enumerate(targets):
        width, height, preset_id = resolve_target(raw)
        amount = 0.0 if layout == "fit_pad_crop" else unit_cost_ai
        total += amount
        per_target.append(
            {
                "index": index,
                "preset_id": preset_id,
                "width": width,
                "height": height,
                "layout": layout,
                "amount_usd": amount,
                "safe_area": safe_area_report(preset_id, width, height),
            }
        )
    pricing_unknown = layout == "ai_extend" and unit_cost_ai <= 0
    return {
        "currency": "USD",
        "total": total,
        "layout": layout,
        "targets": per_target,
        "pricing_unknown": pricing_unknown,
        "note": (
            "AI extend uses OpenAI image edit (usage-based; GPT Image 2.5 is token-billed). "
            "Fit/pad/crop is local ffmpeg only ($0) and does not intelligently re-layout creative."
            if layout == "ai_extend"
            else "Fit/pad/crop uses ffmpeg only ($0); not intelligent re-layout."
        ),
    }


def targets_from_json(text: str) -> list[dict[str, Any]]:
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("targets must be a JSON array")
    return [item for item in parsed if isinstance(item, dict)]
