from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vinci_storage.library import (
    LibraryIndex,
    date_bounds,
    item_id_for_asset,
    item_id_for_sidecar,
    media_kind_from_mime,
    media_path_for_sidecar,
    rerun_hints,
)
from vinci_storage.output_destinations import build_sidecar


def _write_sidecar(
    folder: Path,
    *,
    asset_id: str,
    prompt: str,
    mime: str = "image/png",
    model_id: str = "mock/t2i",
    provider: str = "mock",
    saved_at: datetime | None = None,
) -> Path:
    media = folder / f"{asset_id[:8]}.png"
    media.write_bytes(b"\x89PNG")
    sidecar = build_sidecar(
        asset_id=asset_id,
        run_id="run-1",
        mime=mime,
        prompt=prompt,
        model_id=model_id,
        provider=provider,
        params={"prompt": prompt, "aspect_ratio": "16:9"},
        source_ids={"job_id": "job-1", "capability": "t2i"},
        saved_at=saved_at,
        destination_kind="local",
    )
    path = media.with_name(media.name + ".vinci.json")
    path.write_text(json.dumps(sidecar), encoding="utf-8")
    return path


def test_media_kind_and_sidecar_pairing(tmp_path: Path) -> None:
    assert media_kind_from_mime("image/png") == "image"
    assert media_kind_from_mime("video/mp4") == "video"
    assert media_kind_from_mime("audio/mpeg") == "audio"
    side = tmp_path / "shot.png.vinci.json"
    assert media_path_for_sidecar(side).name == "shot.png"
    assert item_id_for_sidecar(str(side)) == item_id_for_sidecar(str(side))
    assert item_id_for_asset("abc") == item_id_for_asset("abc")
    assert item_id_for_asset("abc") != item_id_for_sidecar("abc")


def test_rerun_hints() -> None:
    image = rerun_hints(mime="image/png", model_id="m", source_ids={})
    video = rerun_hints(mime="video/mp4", model_id="m", source_ids={})
    speak = rerun_hints(mime="audio/mpeg", model_id="m", source_ids={"capability": "tts"})
    upscale = rerun_hints(mime="image/png", model_id="x-upscale", source_ids={})
    assert image["page"] == "image"
    assert video["skill"] == "@tryvinci/video-generate"
    assert speak["page"] == "speak"
    assert upscale["page"] == "upscale"


def test_missing_library_has_no_sqlite(tmp_path: Path) -> None:
    index = LibraryIndex(tmp_path / "library.sqlite")
    assert index.exists is False
    assert index.count() == 0
    assert index.query() == []
    assert index.facets()["kinds"] == []
    assert index.get("missing") is None


def test_scan_query_trash_restore_purge(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    now = datetime.now(tz=UTC)
    _write_sidecar(exports, asset_id="aaa111", prompt="a red cube", saved_at=now)
    _write_sidecar(
        exports,
        asset_id="bbb222",
        prompt="a blue lake",
        mime="video/mp4",
        model_id="mock/t2v",
        saved_at=now - timedelta(days=10),
    )
    index = LibraryIndex(tmp_path / "library.sqlite")
    assert index.scan([exports]) == 2
    assert index.exists is True
    assert index.count() == 2

    images = index.query(kind="image")
    assert len(images) == 1
    assert images[0]["prompt"] == "a red cube"
    assert images[0]["rerun_skill"] == "@tryvinci/image-generate"
    assert images[0]["id"] == item_id_for_asset("aaa111")

    hits = index.query(q="lake")
    assert len(hits) == 1
    assert hits[0]["media_kind"] == "video"

    recent = index.query(date="7d")
    assert [row["asset_id"] for row in recent] == ["aaa111"]

    models = index.facets()["models"]
    assert {row["model_id"] for row in models} == {"mock/t2i", "mock/t2v"}

    media = exports / "aaa111.png"
    assert media.is_file()
    trashed = index.trash(images[0]["id"])
    assert trashed["trashed"] == images[0]["id"]
    assert index.count() == 1
    assert index.query()[0]["asset_id"] == "bbb222"
    assert index.query(section="trash")[0]["asset_id"] == "aaa111"
    assert media.is_file()

    restored = index.restore(images[0]["id"])
    assert restored["asset_id"] == "aaa111"
    assert restored["trashed_at"] is None
    assert index.count() == 2

    index.purge(images[0]["id"], roots=[exports])
    assert index.count() == 1
    assert not media.exists()
    assert not list(exports.glob("aaa111*.vinci.json"))


def test_cas_row_survives_missing_sidecar(tmp_path: Path) -> None:
    index = LibraryIndex(tmp_path / "library.sqlite")
    item = index.ingest_run_asset(
        asset_id="casdigest1",
        run_id="run-cas",
        mime="image/png",
        prompt="unsaved still",
        model_id="mock/t2i",
        provider="mock",
        destination_kind="none",
    )
    assert item["origin"] == "cas"
    assert item["id"] == item_id_for_asset("casdigest1")
    exports = tmp_path / "exports"
    exports.mkdir()
    index.scan([exports])
    assert index.count() == 1
    assert index.get(item["id"]) is not None


def test_scan_prunes_missing_sidecar_only(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    side = _write_sidecar(exports, asset_id="ccc333", prompt="gone soon")
    index = LibraryIndex(tmp_path / "library.sqlite")
    index.scan([exports])
    assert index.count() == 1
    side.unlink()
    index.scan([exports])
    assert index.count() == 0


def test_sidecar_overlays_cas_same_id(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    exports.mkdir()
    index = LibraryIndex(tmp_path / "library.sqlite")
    cas = index.ingest_run_asset(
        asset_id="aaa111",
        run_id="run-1",
        mime="image/png",
        prompt="a red cube",
        destination_kind="none",
    )
    side = _write_sidecar(exports, asset_id="aaa111", prompt="a red cube")
    merged = index.ingest_sidecar(side)
    assert merged is not None
    assert merged["id"] == cas["id"]
    assert merged["origin"] == "cas"
    assert merged["media_path"]
    assert merged["destination_kind"] == "local"
    assert index.count() == 1


def test_favorite_and_tool_filters(tmp_path: Path) -> None:
    index = LibraryIndex(tmp_path / "library.sqlite")
    still = index.ingest_run_asset(
        asset_id="img1", run_id="r1", mime="image/png", prompt="still", model_id="mock/t2i"
    )
    index.ingest_run_asset(
        asset_id="vid1", run_id="r2", mime="video/mp4", prompt="clip", model_id="mock/t2v",
        source_ids={"capability": "t2v"},
    )
    index.ingest_run_asset(
        asset_id="up1",
        run_id="r3",
        mime="image/png",
        prompt="crisp still",
        model_id="mock/upscale",
        source_ids={"capability": "upscale"},
    )
    assert [row["asset_id"] for row in index.query(tool="image")] == ["img1"]
    assert [row["asset_id"] for row in index.query(tool="video")] == ["vid1"]
    assert [row["asset_id"] for row in index.query(tool="enhanced")] == ["up1"]
    loved = index.set_favorite(still["id"], True)
    assert loved["favorite"] is True
    assert [row["asset_id"] for row in index.query(section="favorites")] == ["img1"]


def test_purge_refuses_path_outside_roots(tmp_path: Path) -> None:
    inside = tmp_path / "exports"
    outside = tmp_path / "other"
    inside.mkdir()
    outside.mkdir()
    side = _write_sidecar(outside, asset_id="ddd444", prompt="keep me")
    media = media_path_for_sidecar(side)
    index = LibraryIndex(tmp_path / "library.sqlite")
    item = index.ingest_sidecar(side)
    assert item is not None
    index.purge(item["id"], roots=[inside])
    assert media.is_file()
    assert side.is_file()
    assert index.get(item["id"]) is None


def test_date_bounds_presets() -> None:
    start, end = date_bounds("today", None, None)
    assert start and end
    start7, _ = date_bounds("7d", None, None)
    assert start7
    explicit = date_bounds("all", "2026-01-01T00:00:00+00:00", None)
    assert explicit[0] == "2026-01-01T00:00:00+00:00"
