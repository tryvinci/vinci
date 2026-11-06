from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_runtime.engine import Engine
from vinci_storage.library import LibraryIndex, item_id_for_asset
from vinci_storage.output_destinations import build_sidecar


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    return tmp_path


def test_empty_library_when_destination_is_none(home: Path) -> None:
    engine = Engine(home)
    engine.init_home(demo=True)
    body = engine.list_library()
    assert body["items"] == []
    assert body["status"]["reason"] == "empty"
    assert body["status"]["library_exists"] is False
    assert body["status"]["destination_kind"] == "none"


def test_empty_library_when_destination_is_local(home: Path) -> None:
    engine = Engine(home)
    engine.init_home(demo=True)
    engine.update_settings(output_destination_kind="local", output_local_dir=str(home / "exports"))
    body = engine.list_library()
    assert body["items"] == []
    assert body["status"]["reason"] == "empty"


def test_destination_none_indexes_cas_run(home: Path) -> None:
    engine = Engine(home)
    engine.init_home(demo=True)
    run = engine.start_run("@tryvinci/image-generate", {"prompt": "unsaved cube"})
    assert run.get("state") == "completed"
    assert not run.get("exported_outputs")
    body = engine.list_library()
    assert body["status"]["reason"] == "ready"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert "unsaved cube" in item["prompt"]
    assert item["origin"] == "cas"
    assert item["destination_kind"] in {"none", ""}
    assert item["id"] == item_id_for_asset(item["asset_id"])
    path, blob, mime = engine.library_media(item["id"])
    assert path is None
    assert blob
    assert mime.startswith("image/")


def test_engine_indexes_exported_sidecar(home: Path) -> None:
    engine = Engine(home)
    engine.init_home(demo=True)
    export_dir = home / "exports"
    engine.update_settings(output_destination_kind="local", output_local_dir=str(export_dir))
    run = engine.start_run("@tryvinci/image-generate", {"prompt": "library cube"})
    assert run.get("state") == "completed"
    assert run.get("exported_outputs")
    body = engine.list_library()
    assert body["status"]["reason"] == "ready"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert "library cube" in item["prompt"]
    assert item["rerun_page"] == "image"
    assert item["local"] is True
    assert item["origin"] == "cas"

    hits = engine.list_library(q="cube")
    assert len(hits["items"]) == 1
    none = engine.list_library(q="no-such-prompt")
    assert none["items"] == []
    assert none["status"]["total"] == 1

    detail = engine.get_library_item(item["id"])
    assert detail is not None
    path, blob, mime = engine.library_media(item["id"])
    assert path is not None and path.is_file()
    assert blob is None
    assert mime.startswith("image/")

    engine.delete_library_item(item["id"])
    assert engine.list_library()["items"] == []
    trashed = engine.list_library(section="trash")
    assert len(trashed["items"]) == 1
    again = engine.list_library(section="trash")
    assert [row["id"] for row in again["items"]] == [item["id"]]
    engine.restore_library_item(item["id"])
    assert len(engine.list_library()["items"]) == 1


def test_tool_feed_and_favorite(home: Path) -> None:
    engine = Engine(home)
    engine.init_home(demo=True)
    engine.start_run("@tryvinci/image-generate", {"prompt": "feed still"})
    engine.start_run("@tryvinci/video-generate", {"prompt": "feed clip"})
    images = engine.list_library(tool="image")
    videos = engine.list_library(tool="video")
    assert [row["prompt"] for row in images["items"]] == ["feed still"]
    assert [row["prompt"] for row in videos["items"]] == ["feed clip"]
    item = images["items"][0]
    loved = engine.favorite_library_item(item["id"], True)
    assert loved["favorite"] is True
    favs = engine.list_library(section="favorites")
    assert [row["id"] for row in favs["items"]] == [item["id"]]


def test_daemon_library_routes(home: Path) -> None:
    engine = Engine(home)
    engine.init_home(demo=True)
    client = TestClient(create_app(engine))

    empty = client.get("/library")
    assert empty.status_code == 200
    assert empty.json()["status"]["reason"] == "empty"

    run = client.post(
        "/runs",
        json={"skill": "@tryvinci/image-generate", "inputs": {"prompt": "history still"}},
    )
    assert run.status_code == 200
    listed = client.get("/library", params={"q": "history", "tool": "image"})
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    item_id = items[0]["id"]

    detail = client.get(f"/library/items/{item_id}")
    assert detail.status_code == 200
    assert detail.json()["prompt"] == "history still"

    media = client.get(f"/library/items/{item_id}/file")
    assert media.status_code == 200
    assert media.content

    scanned = client.post("/library/scan")
    assert scanned.status_code == 200
    assert scanned.json()["status"]["total"] == 1

    heart = client.patch(f"/library/items/{item_id}", json={"favorite": True})
    assert heart.status_code == 200
    assert heart.json()["favorite"] is True

    gone = client.delete(f"/library/items/{item_id}")
    assert gone.status_code == 200
    assert gone.json()["trashed"] == item_id
    assert client.get("/library").json()["items"] == []
    trash = client.get("/library", params={"section": "trash"})
    assert len(trash.json()["items"]) == 1
    restored = client.post(f"/library/items/{item_id}/restore")
    assert restored.status_code == 200
    assert client.get("/library").json()["items"][0]["id"] == item_id


def test_library_indexes_orphaned_sidecars(home: Path) -> None:
    """A folder of leftover sidecars is enough even when destination is none."""
    engine = Engine(home)
    engine.init_home(demo=True)
    exports = home / "exports"
    exports.mkdir()
    media = exports / "old.png"
    media.write_bytes(b"\x89PNG")
    sidecar = build_sidecar(
        asset_id="orphan1",
        run_id="old-run",
        mime="image/png",
        prompt="leftover still",
        model_id="mock/t2i",
        provider="mock",
        params={"prompt": "leftover still"},
        source_ids={"capability": "t2i"},
        destination_kind="local",
    )
    (exports / "old.png.vinci.json").write_text(json.dumps(sidecar), encoding="utf-8")
    body = engine.list_library()
    assert body["status"]["reason"] == "ready"
    assert [row["prompt"] for row in body["items"]] == ["leftover still"]


def test_r2_export_indexes_without_local_file(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_R2_MOCK_DIR", str(home / "r2"))
    monkeypatch.setenv("VINCI_R2_BUCKET", "exports")
    engine = Engine(home)
    engine.init_home(demo=True)
    engine.update_settings(output_destination_kind="r2")
    run = engine.start_run("@tryvinci/image-generate", {"prompt": "remote still"})
    assert run.get("exported_outputs")
    body = engine.list_library(refresh=False)
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["local"] is False
    assert item["media_path"].startswith("s3://")
    path, blob, mime = engine.library_media(item["id"])
    assert path is None
    assert blob
    assert mime.startswith("image/")
    assert LibraryIndex(home / "library.sqlite").exists
