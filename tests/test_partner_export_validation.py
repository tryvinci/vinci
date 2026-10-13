from __future__ import annotations

from pathlib import Path

import pytest
from vinci_media.adapt import (
    presets_document,
    safe_area_report,
    validate_export_for_preset,
)
from vinci_media.partner_presets import ByteCap, check_export_bytes, partner_preset_by_id
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_runtime.engine import Engine


def test_partner_presets_in_catalog() -> None:
    ids = {row["id"] for row in presets_document()}
    assert "amazon_828x300" in ids
    assert "inuxu_1200x720" in ids
    assert "jio_1200x627" in ids
    assert "bpn_360x180" in ids
    assert "meta_google_1200x1200" in ids


def test_inclusive_byte_cap_boundary() -> None:
    cap = ByteCap(100 * 1024, "lte")
    assert check_export_bytes(100 * 1024, cap)
    assert not check_export_bytes(100 * 1024 + 1, cap)


def test_strict_byte_cap_boundary() -> None:
    cap = ByteCap(200 * 1024, "lt")
    assert check_export_bytes(200 * 1024 - 1, cap)
    assert not check_export_bytes(200 * 1024, cap)


def test_validate_export_inclusive_raises(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"x" * (100 * 1024 + 1))
    with pytest.raises(Exception, match="fails preset amazon_828x300"):
        validate_export_for_preset(path, "amazon_828x300", 828, 300)


def test_validate_export_strict_jio_raises(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"x" * (200 * 1024))
    with pytest.raises(Exception, match="fails preset jio_1200x627"):
        validate_export_for_preset(path, "jio_1200x627", 1200, 627)


def test_validate_export_strict_bpn_passes_below(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"x" * (40 * 1024 - 1))
    body = validate_export_for_preset(path, "bpn_360x180", 360, 180)
    assert body["automated"]["byte_cap_ok"] is True


def test_amazon_safe_rect_overlay() -> None:
    report = safe_area_report("amazon_828x300", 828, 300)
    rect = report["safe_rect"]
    assert rect == {"x": 94, "y": 0, "w": 640, "h": 300}
    assert report["spec_kind"] == "client_partner"


def test_inuxu_safe_rect_overlay() -> None:
    report = safe_area_report("inuxu_1200x720", 1200, 720)
    rect = report["safe_rect"]
    assert rect == {"x": 175, "y": 110, "w": 850, "h": 500}


def test_jio_uncapped_presets_have_no_byte_cap() -> None:
    for pid in ("jio_320x50", "jio_1274x546", "jio_1440x448"):
        preset = partner_preset_by_id(pid)
        assert preset is not None
        assert preset.byte_cap is None


def test_bpn_human_review_advisories_labeled() -> None:
    report = safe_area_report("bpn_360x180", 360, 180)
    advisories = report["human_review_advisories"]
    assert any("Buy Now" in line for line in advisories)
    assert any("No logos" in line for line in advisories)
    assert any("IRDAI" in line for line in advisories)


def test_engine_run_adapt_two_partner_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path / "home"))
    eng = Engine()
    eng.init_home(demo=True)
    asset = eng.ingest_bytes(PNG_SWATCH, mime="image/png", filename="creative.png")
    result = eng.run_adapt(
        source_asset=asset.id,
        targets=[{"preset_id": "jio_320x50"}, {"preset_id": "inuxu_728x90"}],
        layout="fit_pad_crop",
        fit_mode="pad",
    )
    assert len(result["digests"]) == 2
    for out in result["outputs"]:
        assert out["safe_area"]["spec_kind"] == "client_partner"
