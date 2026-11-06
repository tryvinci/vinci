from __future__ import annotations

import json
from pathlib import Path

import pytest
from vinci_core.config import OutputDestinationConfig, load_config
from vinci_runtime.engine import Engine
from vinci_storage.output_destinations import (
    LocalFolderDestination,
    R2OutputDestination,
    build_output_destination,
    build_sidecar,
    export_asset,
    extension_for_mime,
)
from vinci_storage.r2_client import R2Client


def test_extension_for_mime() -> None:
    assert extension_for_mime("image/png") == "png"
    assert extension_for_mime("video/mp4") == "mp4"


def test_local_destination_writes_sidecar(tmp_path: Path) -> None:
    dest = LocalFolderDestination(tmp_path / "out")
    sidecar = build_sidecar(
        asset_id="abc123",
        run_id="run1",
        mime="image/png",
        prompt="a cat",
        model_id="mock/t2i",
        provider="mock",
        params={"prompt": "a cat"},
        source_ids={"job_id": "job1"},
        destination_kind="local",
    )
    saved = dest.save(blob=b"\x89PNG", mime="image/png", asset_id="abc123", sidecar=sidecar)
    assert Path(saved.media_path).is_file()
    side = Path(saved.sidecar_path)
    assert side.is_file()
    doc = json.loads(side.read_text(encoding="utf-8"))
    assert doc["prompt"] == "a cat"
    assert doc["model_id"] == "mock/t2i"
    assert doc["source_ids"]["job_id"] == "job1"


def test_r2_destination_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_root = tmp_path / "r2mock"
    monkeypatch.setenv("VINCI_R2_MOCK_DIR", str(mock_root))
    monkeypatch.setenv("VINCI_R2_BUCKET", "exports")
    client = R2Client.from_env()
    assert client is not None
    dest = R2OutputDestination(client, "vinci/outputs/")
    row = export_asset(
        dest,
        blob=b"hello",
        mime="image/jpeg",
        asset_id="deadbeef" * 4,
        run_id="run-r2",
        prompt="test",
        model_id="m",
        provider="mock",
        params={},
        source_ids={},
    )
    assert row.media_path.startswith("s3://exports/")
    key = row.media_path.split("/", 3)[-1]
    assert client.get_bytes(key) == b"hello"


def test_engine_exports_on_mock_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    export_dir = tmp_path / "exports"
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    engine.update_settings(output_destination_kind="local", output_local_dir=str(export_dir))
    run = engine.start_run("@tryvinci/image-generate", {"prompt": "export test"})
    assert run.get("state") == "completed"
    exported = run.get("exported_outputs") or []
    assert exported
    media_path = Path(str(exported[0]["media_path"]))
    assert media_path.is_file()
    sidecar = Path(str(exported[0]["sidecar_path"]))
    assert sidecar.is_file()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["prompt"]


def test_engine_none_destination_skips_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    engine.update_settings(output_destination_kind="none")
    run = engine.start_run("@tryvinci/image-generate", {"prompt": "no export"})
    assert run.get("state") == "completed"
    assert not run.get("exported_outputs")
    assert list(export_dir.glob("*")) == []


def test_settings_persist_output_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    updated = engine.update_settings(
        output_destination_kind="photos",
        output_photos_album="Campaign",
    )
    assert updated["output_destination"]["kind"] == "photos"
    assert updated["output_destination"]["photos_album"] == "Campaign"
    reloaded = load_config(tmp_path)
    assert reloaded.output_destination.kind == "photos"
    assert reloaded.output_destination.photos_album == "Campaign"


def test_photos_destination_staging_path(tmp_path: Path) -> None:
    built = build_output_destination(
        OutputDestinationConfig(kind="photos", photos_album="My Album"),
        home=tmp_path,
    )
    assert built is not None
    assert built.kind == "photos"
