from __future__ import annotations

from pathlib import Path

import pytest
from vinci_media.adapt import (
    adapt_image_fit_pad_crop,
    estimate_adapt_targets,
    presets_document,
    validate_output_image,
)
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_runtime.engine import Engine


def test_adapt_presets_include_platforms() -> None:
    presets = presets_document()
    ids = {row["id"] for row in presets}
    assert "instagram_feed" in ids
    assert "youtube_thumb" in ids


def test_estimate_fit_pad_crop_is_zero() -> None:
    body = estimate_adapt_targets(
        [{"preset_id": "instagram_feed"}],
        layout="fit_pad_crop",
        unit_cost_ai=0.034,
    )
    assert body["total"] == 0.0
    assert body["targets"][0]["layout"] == "fit_pad_crop"


def test_estimate_ai_extend_unknown_when_no_catalog_usd() -> None:
    body = estimate_adapt_targets(
        [{"preset_id": "instagram_feed"}, {"width": 800, "height": 600}],
        layout="ai_extend",
        unit_cost_ai=0.0,
    )
    assert body["total"] == 0.0
    assert body["pricing_unknown"] is True


def test_adapt_fit_pad_crop_writes_valid_png(tmp_path: Path) -> None:
    src = tmp_path / "src.png"
    src.write_bytes(PNG_SWATCH)
    dest = tmp_path / "out.png"
    adapt_image_fit_pad_crop(src, dest, width=1080, height=1080, fit="pad")
    meta = validate_output_image(dest, width=1080, height=1080)
    assert meta["width"] == 1080


def test_engine_run_adapt_fanout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path / "home"))
    eng = Engine()
    eng.init_home(demo=True)
    asset = eng.ingest_bytes(PNG_SWATCH, mime="image/png", filename="creative.png")
    result = eng.run_adapt(
        source_asset=asset.id,
        targets=[{"preset_id": "instagram_feed"}, {"preset_id": "youtube_thumb"}],
        layout="fit_pad_crop",
        fit_mode="pad",
    )
    assert len(result["digests"]) == 2
    assert result["estimate"]["total"] == 0.0
