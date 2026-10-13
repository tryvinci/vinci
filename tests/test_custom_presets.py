from __future__ import annotations

from pathlib import Path

import pytest
from vinci_media.adapt import presets_document, resolve_preset
from vinci_media.custom_presets import create_custom_preset, delete_custom_preset


def test_custom_preset_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    created = create_custom_preset(
        {
            "label": "Lobby strip",
            "partner": "axis",
            "width": 640,
            "height": 100,
            "byte_cap": {"max_bytes": 20 * 1024, "op": "lt"},
        },
        tmp_path,
    )
    assert created["source"] == "custom"
    assert resolve_preset(created["id"], tmp_path) is not None
    ids = {row["id"]: row["source"] for row in presets_document(tmp_path)}
    assert ids[created["id"]] == "custom"
    assert ids["amazon_828x300"] == "partner"
    delete_custom_preset(created["id"], tmp_path)
    assert resolve_preset(created["id"], tmp_path) is None


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    body = {"id": "axis_strip", "label": "Strip", "platform": "axis", "width": 100, "height": 40}
    create_custom_preset(body, tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        create_custom_preset(body, tmp_path)
    with pytest.raises(KeyError):
        delete_custom_preset("amazon_828x300", tmp_path)
