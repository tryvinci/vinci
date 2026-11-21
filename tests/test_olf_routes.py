"""Daemon /olf routes for the Studio Shows page: open the sample, render, review, select, serve."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_runtime.engine import Engine

SHOT = "e02/s03/sh014"
SAMPLE = Path(__file__).resolve().parents[1] / "packages/olf/conformance/tidewatch"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path / "home")
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_routes_are_listed_for_the_studio(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/olf/sample",
        "/olf/project",
        "/olf/shot",
        "/olf/render",
        "/olf/batch",
        "/olf/take",
        "/olf/select",
        "/olf/file",
        "/olf/camerawork",
        "/olf/previs",
        "/olf/shows",
        "/olf/import",
        "/olf/scene",
        "/olf/scene/build",
        "/olf/scene/paste",
        "/olf/scene/room",
        "/olf/scene/use",
    ):
        assert path in paths  # the Studio feature-detects the Shows page with /olf/project


def test_the_open_screen_lists_the_shows(client: TestClient) -> None:
    """``GET /olf/shows``: each show in ``$VINCI_HOME/shows`` with its title, newest first."""
    assert client.get("/olf/shows").json() == {"shows": []}
    sample = client.post("/olf/sample").json()["path"]
    made = client.post("/olf/new", json={"title": "Night Ferry"}).json()["path"]
    rows = client.get("/olf/shows").json()["shows"]
    assert {(row["path"], row["title"]) for row in rows} == {
        (sample, "Tidewatch"),
        (made, "Night Ferry"),
    }
    assert [row["updated_at"] for row in rows] == sorted(
        (r["updated_at"] for r in rows), reverse=True
    )


def test_shows_flow(client: TestClient) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("the mock video model runs ffmpeg")
    path = client.post("/olf/sample").json()["path"]
    assert client.post("/olf/sample").json()["path"] == path  # copied once
    show = client.get("/olf/project", params={"path": path}).json()
    assert show["issues"] == [] and show["takes"] == {} and SHOT in show["shots"]
    detail = client.get("/olf/shot", params={"path": path, "shot": SHOT}).json()
    assert (
        detail["plans"]["video"]["total"] == 0
        and detail["references"][0]["file"] == "bible/characters/mira/sheet.png"
    )
    assert detail["plans"]["audio"]["plan"][0]["model"] == "mock:wav:v1"  # the dialogue price
    done = client.post("/olf/render", json={"path": path, "shot": SHOT}).json()
    assert done["takes"] == [f"{SHOT}/kf1", f"{SHOT}/v1"]
    why = client.get("/olf/stale", params={"path": path, "take": f"{SHOT}/kf1"}).json()
    assert (why["stale"], why["known"], why["changes"]) == (False, True, [])
    kept = client.post("/olf/keep", json={"path": path, "take": f"{SHOT}/kf1"}).json()
    assert kept["kept"] is False  # a fresh take has nothing to keep
    speech = client.post("/olf/render", json={"path": path, "shot": SHOT, "kind": "audio"})
    assert speech.json()["takes"] == [f"{SHOT}/a1"]
    batch = {"path": path, "episode": "e02", "mode": "stale", "dry_run": True}
    assert client.post("/olf/batch", json=batch).json()["jobs"] == []  # every take is fresh
    review = {"path": path, "take": f"{SHOT}/v1", "status": "approved"}
    assert client.patch("/olf/take", json=review).json()["status"] == "approved"
    pick = {"path": path, "shot": SHOT, "choices": {"keyframe": "kf1", "video": "v1"}}
    assert client.patch("/olf/select", json=pick).json() == {
        "select": {"keyframe": "kf1", "video": "v1"}
    }
    show = client.get("/olf/project", params={"path": path}).json()
    assert show["shots"][SHOT]["select"] == {"keyframe": "kf1", "video": "v1"}
    assert {k: (v["status"], v["stale"]) for k, v in show["takes"].items()} == {
        f"{SHOT}/a1": ("draft", False),
        f"{SHOT}/kf1": ("draft", False),
        f"{SHOT}/v1": ("approved", False),
    }
    voice = client.get(
        "/olf/file", params={"path": path, "rel": show["takes"][f"{SHOT}/a1"]["file"]}
    )
    assert voice.status_code == 200 and voice.headers["content-type"] in (
        "audio/wav",
        "audio/x-wav",
    )
    media = client.get(
        "/olf/file", params={"path": path, "rel": show["takes"][f"{SHOT}/v1"]["file"]}
    )
    assert media.status_code == 200 and media.headers["content-type"] == "video/mp4"
    cut = client.patch(
        "/olf/cut", json={"path": path, "episode": "e02", "use_approved": True}
    ).json()
    assert [clip["take"] for clip in cut["clips"]] == [f"{SHOT}/v1"]  # the approved video
    faded = client.patch(
        "/olf/cut", json={"path": path, "episode": "e02", "clip": 0, "fields": {"out": 3}}
    )
    assert faded.json()["duration"] == 3.0
    done = client.post(
        "/olf/export", json={"path": path, "episode": "e02", "aspects": ["16:9"]}
    ).json()
    assert done["files"] == ["exports/e02/e02.srt", "exports/e02/e02-16x9.mp4"]
    wide = client.get("/olf/file", params={"path": path, "rel": done["files"][1]})
    assert wide.status_code == 200 and wide.headers["content-type"] == "video/mp4"


def test_errors_are_plain(client: TestClient) -> None:
    path = client.post("/olf/sample").json()["path"]
    assert client.get("/olf/project", params={"path": "/no/such/show"}).status_code == 404
    assert (
        client.get("/olf/file", params={"path": path, "rel": "../../escape.png"}).status_code == 400
    )
    assert client.get("/olf/file", params={"path": path, "rel": "project.yaml"}).status_code == 404
    bad = client.patch(
        "/olf/take", json={"path": path, "take": f"{SHOT}/kf9", "status": "approved"}
    )
    assert bad.status_code == 400 and "no such take" in bad.json()["detail"]
    music = client.post("/olf/render", json={"path": path, "shot": SHOT, "kind": "music"})
    assert music.status_code == 400 and "kind must be keyframe, video" in music.json()["detail"]
    # A wrong shape in a show file is an issue on the page, never a 500 (PR-Agent on #517).
    episode = Path(path) / "episodes/e02/episode.yaml"
    episode.write_text(episode.read_text().replace("forms: { char/mira: winter }", "forms: winter"))
    broken = client.get("/olf/project", params={"path": path})
    assert broken.status_code == 200 and broken.json()["shots"][SHOT]["error"]
    client.app.state.engine._journal = object()  # durable mode: renders must not skip the journal
    blocked = client.post("/olf/render", json={"path": path, "shot": SHOT})
    assert blocked.status_code == 409 and "VINCI_DURABLE_JOURNAL=off" in blocked.json()["detail"]
    batch = {"path": path, "episode": "e02", "mode": "stale"}
    assert client.post("/olf/batch", json=batch).status_code == 409
    client.app.state.engine._journal = None
    wrong = client.post("/olf/batch", json=batch | {"mode": "all"})
    assert (
        wrong.status_code == 400 and "mode must be one of stale, animate" in wrong.json()["detail"]
    )


def test_mcp_olf_tools(client: TestClient) -> None:
    path = client.post("/olf/sample").json()["path"]

    def call(name: str, **arguments: Any) -> dict[str, Any]:
        params = {"name": name, "arguments": arguments}
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
        reply = client.post("/mcp", json=rpc).json()
        return reply.get("error") or json.loads(reply["result"]["content"][0]["text"])

    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"}).json()
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {
        "vinci.olf_validate",
        "vinci.olf_resolve",
        "vinci.olf_status",
        "vinci.olf_render",
    } <= names
    assert call("vinci.olf_validate", path=path)["ok"] is True
    assert call("vinci.olf_resolve", path=path, shot=SHOT)["hashes"]["audio"].startswith("sha256:")
    plan = call("vinci.olf_render", path=path, shot=SHOT, kind="audio", dry_run=True)
    assert plan["plan"][0]["model"] == "mock:wav:v1" and plan["takes"] == []
    done = call("vinci.olf_render", path=path, shot=SHOT, kind="keyframe", count=2)
    assert done["takes"] == [f"{SHOT}/kf1", f"{SHOT}/kf2"]  # $0 in demo mode: no max_cost needed
    status = call("vinci.olf_status", path=path, prefix=SHOT)
    assert status["count"] == 2 and {take["stale"] for take in status["takes"]} == {False}
    assert "no such shot" in call("vinci.olf_resolve", path=path, shot="e02/s03/sh999")["message"]


def test_mcp_olf_render_spends_only_within_max_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    import vinci_olf.render
    from vinci_mcp import olf_tools
    from vinci_olf import OlfError

    runs: list[bool] = []
    bounds: list[Any] = []
    price = {"total": 0.42, "unpriced": []}

    def fake(p: Any, shot: str, *, dry_run: bool = False, yes: bool = False, **kw: Any) -> Any:
        if not dry_run:
            runs.append(yes)
            bounds.append(kw.get("max_total"))
        return price | {"plan": [], "takes": [] if dry_run else [f"{shot}/v1"]}

    monkeypatch.setattr(vinci_olf.render, "render", fake)
    engine, args = SimpleNamespace(_journal=None), {"path": str(SAMPLE), "shot": SHOT}
    with pytest.raises(OlfError, match=r"costs \$0.42: pass max_cost"):
        olf_tools.call(engine, "vinci.olf_render", args)
    with pytest.raises(OlfError, match="max_cost of at least"):
        olf_tools.call(engine, "vinci.olf_render", args | {"max_cost": 0.4})
    assert runs == []  # nothing ran over the limit
    done = olf_tools.call(engine, "vinci.olf_render", args | {"max_cost": 0.5})
    assert done["takes"] == [f"{SHOT}/v1"] and runs == [True]
    assert bounds == [0.5]  # the real render may not cost more than max_cost (PR-Agent on #523)
    price["unpriced"] = ["openai:img"]  # no flat price: max_cost cannot bound it
    with pytest.raises(OlfError, match="openai:img has no flat price"):
        olf_tools.call(engine, "vinci.olf_render", args | {"max_cost": 5})
    with pytest.raises(OlfError, match="VINCI_DURABLE_JOURNAL=off"):
        olf_tools.call(SimpleNamespace(_journal=object()), "vinci.olf_render", args)


def test_authoring_routes(client: TestClient) -> None:
    import base64
    import io

    from PIL import Image

    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)  # a fresh copy: other tests edit the same sample folder
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "teal").save(buf, "PNG")
    image = base64.b64encode(buf.getvalue()).decode()
    edit = client.patch("/olf/shot", json={"path": path, "shot": SHOT, "fields": {"lens": "35mm"}})
    assert edit.status_code == 200 and edit.json() == {
        "camera": {"framing": "close_up", "angle": "eye_level", "lens": "35mm", "move": "push_in"}
    }
    bad = client.patch(
        "/olf/shot", json={"path": path, "shot": SHOT, "fields": {"framing": "huge"}}
    )
    assert bad.status_code == 400 and "camera.framing must be one of" in bad.json()["detail"]
    shot = client.post(
        "/olf/shot", json={"path": path, "scene": "e02/s03", "description": "A gust."}
    )
    assert shot.json() == {"shot": "e02/s03/sh020"}
    episode = client.post(
        "/olf/episode", json={"path": path, "title": "Three", "season": "season/01"}
    )
    scene = client.post("/olf/scene", json={"path": path, "episode": "e03", "heading": "INT. HALL"})
    assert (episode.json(), scene.json()) == ({"episode": "e03"}, {"scene": "e03/s01"})
    sheet = client.post("/olf/sheet", json={"path": path, "entry": "char/mira", "data": image})
    assert sheet.json() == {"file": "bible/characters/mira/sheet.png"}
    form = {
        "path": path,
        "entry": "char/mira",
        "name": "storm",
        "description": "Grey.",
        "front": image,
    }
    assert client.post("/olf/form", json=form).json() == {"form": "storm"}
    body = {"path": path, "entry": "char/mira", "data": image, "add": True}
    assert client.post("/olf/sheet", json=body).json() == {"sheet": "sheet-2.png"}
    show = client.get("/olf/project", params={"path": path}).json()
    assert show["issues"] == []  # whole sheets: no crop can fall outside a smaller image
    assert client.patch("/olf/region", json=body).status_code in (404, 405)  # removed 2026-11-09
    assert "e03" in [e["id"] for e in show["episodes"]]
    assert show["hashes"]["bible/characters/mira/sheet.png"]  # a replaced image gets a new URL


def test_model_choices_and_share(client: TestClient) -> None:
    import io
    import zipfile

    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)
    (Path(path) / "exports" / "e02").mkdir(parents=True)
    (Path(path) / "exports" / "e02" / "e02-16x9.mp4").write_bytes(b"derived")
    detail = client.get("/olf/shot", params={"path": path, "shot": SHOT}).json()
    video = detail["plans"]["video"]
    assert video["plan"][-1]["capability"] == "i2v"  # the menu lists models for the last step
    assert [c["id"] for c in video["choices"]] == ["mock:mp4:v1"]  # demo mode: mock only
    assert detail["plans"]["audio"]["choices"][0]["id"] == "mock:wav:v1"
    shared = client.get("/olf/share", params={"path": path})
    assert (
        shared.status_code == 200 and "tidewatch.volf" in shared.headers["content-disposition"]
    )
    names = zipfile.ZipFile(io.BytesIO(shared.content)).namelist()
    assert (
        "tidewatch/project.yaml" in names and "tidewatch/bible/characters/mira/sheet.png" in names
    )
    assert not [n for n in names if "/exports/" in n]  # derived files stay out


def test_menu_prices_the_shot_length() -> None:
    """A video row costs the clip the engine asks, not its 5 s price (bug found 2026-11-20: the
    confirm said $1.10 for a 6 s Seedance reference shot that bills $1.32)."""
    from vinci_core.catalog import load_bundled_catalog
    from vinci_daemon.olf_routes import _choices

    rows = load_bundled_catalog("wavespeed").by_capability("r2v")
    engine = SimpleNamespace(
        routing_providers=lambda: {"wavespeed"},
        catalog=lambda: SimpleNamespace(by_capability=lambda capability: rows),
    )
    prices = {c["id"]: c["amount"] for c in _choices(engine, "r2v", 6)}
    assert prices["wavespeed:seedance-2.5-r2v:2026-11"] == 1.32
    assert {c["id"]: c["amount"] for c in _choices(engine, "r2v")}[
        "wavespeed:seedance-2.5-r2v:2026-11"
    ] == 1.1


def test_share_leaves_no_temp_file_when_zipping_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed share removes its temp zip (PR-Agent on #525): no file left per failed try."""
    import tempfile
    import zipfile

    path = client.post("/olf/sample").json()["path"]
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))

    def full_disk(*args: Any, **kwargs: Any) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(zipfile.ZipFile, "write", full_disk)
    failing = TestClient(client.app, raise_server_exceptions=False)
    assert failing.get("/olf/share", params={"path": path}).status_code == 500
    assert not list(temp.glob("olf-share-*"))  # any suffix: .volf since 2026-11-18


def test_import_a_volf_package(client: TestClient) -> None:
    """Export then Import (COREPRODUC-699): a new folder next to the show, never over it."""
    path = client.post("/olf/sample").json()["path"]
    package = client.get("/olf/share", params={"path": path}).content
    first = client.post("/olf/import", files={"file": ("tidewatch.volf", package)})
    assert first.status_code == 200, first.text
    assert first.json() == {"path": str(Path(path).parent / "tidewatch-2"), "title": "Tidewatch"}
    again = client.post("/olf/import", files={"file": ("tidewatch.volf", package)}).json()
    assert again["path"].endswith("tidewatch-3")
    opened = client.get("/olf/project", params={"path": first.json()["path"]}).json()
    assert opened["shots"] and not [i for i in opened["issues"] if i["level"] == "error"]
    rows = client.get("/olf/shows").json()["shows"]
    assert {Path(r["path"]).name for r in rows} >= {"tidewatch", "tidewatch-2", "tidewatch-3"}
    bad = client.post("/olf/import", files={"file": ("notes.volf", b"not a zip")})
    assert bad.status_code == 400 and "not a .volf package" in bad.json()["detail"]
    shows = Path(path).parent
    assert not [p for p in shows.iterdir() if p.name.startswith(".import-")]  # no staging left
    # A show whose manifest is project.json lists too (SPEC.md: the JSON form is valid).
    (shows / "jsonshow").mkdir()
    (shows / "jsonshow" / "project.json").write_text('{"spec": "olf/0.1", "show": "j", "title": "J"}')
    titles = {r["title"] for r in client.get("/olf/shows").json()["shows"]}
    assert "J" in titles
    # A very long show ID is cut to a folder name the disk accepts.
    long = shows / "longshow"
    shutil.copytree(path, long)
    manifest = long / "project.yaml"
    manifest.write_text(manifest.read_text().replace("show: tidewatch", "show: " + "a" * 300))
    pkg = client.get("/olf/share", params={"path": str(long)}).content
    named = client.post("/olf/import", files={"file": ("long.volf", pkg)})
    assert named.status_code == 200 and Path(named.json()["path"]).name == "a" * 64


def test_export_too_large_is_a_plain_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from functools import partial

    from vinci_daemon import olf_routes
    from vinci_olf.package import pack

    path = client.post("/olf/sample").json()["path"]
    monkeypatch.setattr(olf_routes, "pack", partial(pack, max_files=3))
    shared = client.get("/olf/share", params={"path": path})
    assert shared.status_code == 400 and "too large for one package" in shared.json()["detail"]


def test_voice_routes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Design: Voice. Without ElevenLabs the list is empty (demo speech has one voice); with it,
    the account's voices. New show and the bible page set a character's voice."""
    import base64
    import io

    from PIL import Image

    assert client.get("/olf/voices").json() == {"provider": None, "voices": []}
    engine: Any = client.app.state.engine  # type: ignore[attr-defined]
    rows = [{"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "category": "premade"}]
    monkeypatch.setattr(engine, "provider_available", lambda name: True)
    monkeypatch.setattr(engine.providers["elevenlabs"], "voices", lambda: rows)
    assert client.get("/olf/voices").json() == {"provider": "elevenlabs", "voices": rows}
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "teal").save(buf, "PNG")
    cast = {"name": "Mira Sol", "sheet": base64.b64encode(buf.getvalue()).decode()}
    cast |= {"voice_id": "EXAVITQu4vr4xnSDxMaL", "voice_name": "Sarah"}
    made = client.post("/olf/new", json={"title": "Voices", "character": cast}).json()
    voice = Path(made["path"], "bible/voices/mira/mira.yaml")
    assert "voice_id: EXAVITQu4vr4xnSDxMaL" in voice.read_text()
    body = {"path": made["path"], "character": "char/mira", "voice_id": "other_1", "name": "Rae"}
    assert client.post("/olf/voice", json=body).json() == {"voice": "voice/mira"}
    assert "voice_id: other_1" in voice.read_text()
    bad = client.post("/olf/voice", json=body | {"voice_id": "a b"})
    assert bad.status_code == 400 and "is not a voice ID" in bad.json()["detail"]


def test_voice_clone_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Design: Clone from sample (COREPRODUC-559). It needs consent and ElevenLabs; a refused
    clone gives ElevenLabs' reason and writes nothing."""
    import base64
    import io
    import urllib.error

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "teal").save(buf, "PNG")
    cast = {"name": "Mira Sol", "sheet": base64.b64encode(buf.getvalue()).decode()}
    path = client.post("/olf/new", json={"title": "Clones", "character": cast}).json()["path"]
    mp3 = base64.b64encode(b"ID3\x04\x00" + b"\x00" * 64).decode()
    body = {"path": path, "character": "char/mira", "name": "Mira", "sample": mp3}
    no_consent = client.post("/olf/voice/clone", json=body)
    assert no_consent.status_code == 400 and "consent" in no_consent.json()["detail"]
    body["consent"] = True
    offline = client.post("/olf/voice/clone", json=body)
    assert offline.status_code == 400 and "connect ElevenLabs" in offline.json()["detail"]
    engine: Any = client.app.state.engine  # type: ignore[attr-defined]
    monkeypatch.setattr(engine, "provider_available", lambda name: True)
    eleven = engine.providers["elevenlabs"]

    def refuse(name: str, samples: list[tuple[str, bytes]]) -> str:
        detail = io.BytesIO(b'{"detail": {"message": "The audio is too short."}}')
        raise urllib.error.HTTPError("https://api.elevenlabs.io", 422, "", {}, detail)  # type: ignore[arg-type]

    monkeypatch.setattr(eleven, "clone_voice", refuse)
    refused = client.post("/olf/voice/clone", json=body)
    assert refused.status_code == 400
    assert refused.json()["detail"].startswith("ElevenLabs refused the clone (HTTP 422)")
    assert not Path(path, "bible/voices").exists()
    # No network, a timeout, or no voice_id: a readable 400, not a bare HTTP 500 (review of #528).
    for error, why in (
        (urllib.error.URLError(TimeoutError("timed out")), "timed out"),
        (RuntimeError("ElevenLabs gave no voice_id for the clone"), "gave no voice_id"),
    ):

        def lose(name: str, samples: list[tuple[str, bytes]], error: Exception = error) -> str:
            raise error

        monkeypatch.setattr(eleven, "clone_voice", lose)
        lost = client.post("/olf/voice/clone", json=body)
        assert lost.status_code == 400 and why in lost.json()["detail"], lost.text
        assert lost.json()["detail"].startswith("ElevenLabs could not clone the voice: ")
    assert not Path(path, "bible/voices").exists()
    monkeypatch.setattr(eleven, "clone_voice", lambda name, samples: "clone_9")
    assert client.post("/olf/voice/clone", json=body).json() == {"voice": "voice/mira"}
    assert "voice_id: clone_9" in Path(path, "bible/voices/mira/mira.yaml").read_text()


def test_new_show_script_and_text_routes(client: TestClient) -> None:
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "teal").save(buf, "PNG")
    sheet = base64.b64encode(buf.getvalue()).decode()
    script = "EXT. CLIFF PATH - DUSK\n\nMira climbs.\n\nMIRA\nAlmost there.\n"
    # The wizard's preview: no show yet, so its first character stands in for the bible.
    view = client.post(
        "/olf/script/preview",
        json={"script": script, "characters": {"char/mira": "Mira Sol"}, "refs": True},
    ).json()
    assert view["shots"] == 2 and view["characters"] == [
        {"name": "Mira Sol", "id": "char/mira", "new": False}
    ]
    assert view["keyframe"] == {"model": "mock:png:v1", "amount": 0.0, "unpriced": False}
    # Draft from idea and a model's shot list run on the demo text model, price first.
    plan = client.post("/olf/draft", json={"idea": "A fox keeps a light.", "dry_run": True}).json()
    assert plan["plan"][0]["model"] == "mock:llm:v1" and plan["text"] is None
    assert (
        client.post("/olf/draft", json={"idea": "A fox keeps a light."})
        .json()["text"]
        .startswith("EXT.")
    )
    split = client.post("/olf/script/model", json={"script": script}).json()
    assert split["preview"]["shots"] == 2 and split["text"].startswith(
        "EXT. CLIFF PATH - DUSK\n\n[WS"
    )
    # "Your agent · copy prompt" (COREPRODUC-713): the whole prompt comes back and no model runs.
    draft = ("/olf/draft", "idea", "A fox keeps a light.")
    for route, field, value in (draft, ("/olf/script/model", "script", script)):
        copied = client.post(route, json={field: value, "copy": True}).json()
        assert copied["text"] is None and "plan" not in copied and "preview" not in copied
        assert copied["prompt"].endswith(f"create no files.\n\n---\n\n{value}")
    assert copied["prompt"].startswith("You turn film scripts into shot lists.")
    # Create the show: project, character with its sheet, and episode 1 from the script.
    body = {
        "title": "Tide Watch",
        "medium": "2D anime",
        "aspect": "16:9",
        "character": {"name": "Mira Sol", "description": "A fox spirit.", "sheet": sheet},
        "script": script,
    }
    made = client.post("/olf/new", json=body).json()
    assert made["path"].endswith("/shows/tide-watch") and made["character"] == "char/mira"
    assert made["episode"] == "e01" and made["scenes"] == ["e01/s01"]
    show = client.get("/olf/project", params={"path": made["path"]}).json()
    assert show["issues"] == [] and sorted(show["shots"]) == ["e01/s01/sh010", "e01/s01/sh020"]
    # Create show and draw keyframes: one price for two options per shot.
    batch = {"path": made["path"], "episode": "e01", "mode": "keyframes"}
    priced = client.post("/olf/batch", json=batch | {"dry_run": True}).json()
    assert [job["count"] for job in priced["jobs"]] == [2, 2] and priced["total"] == 0
    assert len(client.post("/olf/batch", json=batch | {"max_total": 0}).json()["takes"]) == 4
    # Storyboard: Shot list from script adds scenes to an episode of an open show.
    added = client.post(
        "/olf/script",
        json={"path": made["path"], "episode": "e01", "script": "INT. HALL - DAY\n\nRain.\n"},
    ).json()
    assert added == {"scenes": ["e01/s02"], "locations": ["loc/hall"], "characters": []}
    # A second show with the same title gets its own folder; "Skip to an empty project" works.
    empty = client.post("/olf/new", json={"title": "Tide Watch"}).json()
    assert empty["path"].endswith("/shows/tide-watch-2") and "episode" not in empty
    bad = client.post(
        "/olf/new", json=body | {"title": "Broken", "character": {"name": "X", "sheet": "bm90"}}
    )
    assert (
        bad.status_code == 400 and not (Path(made["path"]).parent / "broken").exists()
    )  # no half show


def test_add_music_cue_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)  # a fresh copy: other tests edit the same sample folder
    body = {
        "path": path,
        "episode": "e02",
        "kind": "music",
        "description": "Slow piano",
        "duration": 4,
    }
    plan = client.post("/olf/cue", json=body | {"dry_run": True}).json()
    assert plan["plan"][0]["model"] == "mock:music:v1" and plan["takes"] == []
    assert (
        "cues" not in Path(path, "episodes/e02/episode.yaml").read_text()
    )  # a dry run writes nothing
    made = client.post("/olf/cue", json=body | {"start": 0.5, "volume": 0.4}).json()
    assert made["cue"] == "e02/cue/slow-piano" and made["takes"] == ["e02/cue/slow-piano/a1"]
    cut = client.get("/olf/cut", params={"path": path, "episode": "e02"}).json()
    assert [(row["take"], row["start"], row["volume"], row["duck"]) for row in cut["audio"]] == [
        ("e02/cue/slow-piano/a1", 0.5, 0.4, True)
    ]
    assert (
        client.get("/olf/file", params={"path": path, "rel": cut["audio"][0]["file"]}).status_code
        == 200
    )
    too_long = client.post("/olf/cue", json=body | {"kind": "sfx", "duration": 45})
    assert too_long.status_code == 400 and "0.5 to 30 s" in too_long.json()["detail"]
    # A failed render takes its new cue back out, so a retry does not add storm-drums-2 (#525).
    from vinci_olf.project import OlfError

    def down(*args: Any, **kwargs: Any) -> Any:
        raise OlfError("the music model is down")

    episode = Path(path, "episodes/e02/episode.yaml")
    before = episode.read_text()
    monkeypatch.setattr("vinci_daemon.olf_routes.render_cue", down)
    failed = client.post("/olf/cue", json=body | {"description": "Storm drums"})
    assert failed.status_code == 400 and episode.read_text() == before


def test_scene_lab_routes(client: TestClient) -> None:
    """COREPRODUC-720: build on the demo text model (price first), copy the prompt, paste an
    answer, keep a room try as a version, and use a try as the keyframe layout."""
    import base64
    import io
    import json

    from PIL import Image

    path = client.post("/olf/sample").json()["path"]
    shot, scene = "e02/s03/sh014", "e02/s03"
    body = {"path": path, "target": shot, "request": "Mira in the middle"}
    copied = client.post("/olf/scene/build", json=body | {"copy": True}).json()
    assert copied["text"] is None and "The scene has no set yet" in copied["prompt"]
    assert copied["prompt"].endswith("The person wants:\nMira in the middle")
    plan = client.post("/olf/scene/build", json=body | {"dry_run": True}).json()
    assert plan["plan"][0]["model"] == "mock:llm:v1" and plan["text"] is None
    built = client.post("/olf/scene/build", json=body).json()  # the demo room and staging
    assert built["room"] == 1 and built["try"] == 1
    seen = client.get("/olf/scene", params={"path": path, "target": shot}).json()
    assert seen["versions"] == [1] and [t["try"] for t in seen["tries"]] == [1]
    assert seen["room"]["set"][0]["name"] == "floor" and seen["rooms"] == {"1": seen["room"]}
    pasted = json.dumps(
        {"set": [{"name": "crate", "shape": "box", "size": [1, 1, 1], "at": [2, 0, -2]}]}
    )
    one = {"path": path, "target": scene, "text": f"```json\n{pasted}\n```"}
    assert client.post("/olf/scene/paste", json=one).json() == {"room_try": 1}
    bad = client.post("/olf/scene/paste", json=one | {"text": "{ nope"})
    assert bad.status_code == 400 and "not JSON" in bad.json()["detail"]
    # COREPRODUC-738: a floor slab under the floor is dropped, a sunk piece stands on the floor.
    slab = {"name": "floor", "shape": "box", "size": [8, 0.12, 8], "at": [0, -0.12, 0]}
    sunk = {"name": "lamp", "shape": "cylinder", "size": [1, 1.3, 1], "at": [0, -0.2, -1]}
    settled = one | {"text": json.dumps({"set": [slab, sunk]})}
    assert client.post("/olf/scene/paste", json=settled).json() == {"room_try": 2}
    last = client.get("/olf/scene", params={"path": path, "target": scene}).json()["room_tries"][-1]
    assert [(piece["name"], piece["at"]) for piece in last["set"]] == [("lamp", [0, 0, -1])]
    kept = client.post("/olf/scene/room", json={"path": path, "scene": scene, "room_try": 1})
    assert kept.json() == {"version": 2}
    later = client.get("/olf/scene", params={"path": path, "target": shot}).json()
    assert later["room"]["set"][0]["name"] == "crate"  # the newest room is v2
    assert later["rooms"] == {"1": seen["room"]}  # the try still stands in room v1
    # The scene room screen (COREPRODUC-723): all versions, the room tries, each shot's room.
    room = client.get("/olf/scene", params={"path": path, "target": scene}).json()
    assert list(room["rooms"]) == ["1", "2"] and [t["try"] for t in room["room_tries"]] == [1, 2]
    assert room["shots"][shot] == {"tries": 1, "try": 1, "room": 1}
    assert room["shots"]["e02/s03/sh015"] == {"tries": 0, "try": None, "room": None}
    # A try to start from goes in the prompt (the compare screen's "change for a new try").
    based = client.post("/olf/scene/build", json=body | {"copy": True, "base": 1}).json()
    assert "Start from this staging; change only what the person asks for:" in based["prompt"]
    # A hand edit is checked as saving would check it, and nothing is saved.
    draft = {k: v for k, v in seen["tries"][0].items() if k not in ("try", "issues")}
    far = draft | {"cast": [{"slot": "a", "at": [40, 0, 0]}]}
    checked = client.post("/olf/scene/check", json={"path": path, "shot": shot, "data": far})
    assert any("outside" in i["message"] for i in checked.json()["issues"])
    wrong = draft | {"room": 9}
    checked = client.post("/olf/scene/check", json={"path": path, "shot": shot, "data": wrong})
    assert [i["level"] for i in checked.json()["issues"]] == ["error"]
    buf = io.BytesIO()
    Image.new("RGB", (32, 18), "grey").save(buf, "PNG")
    frame = base64.b64encode(buf.getvalue()).decode()
    # A dutch angle from the shot's template is a choice the 3D camera cannot measure: it stays.
    body = {"path": path, "shot": shot, "template": "anime/tu-slow"}
    assert client.post("/olf/camerawork", json=body).status_code == 200
    template = Path(path) / "bible/camerawork/tu-slow/tu-slow.yaml"
    template.write_text(template.read_text().replace("camera: {", "camera: { angle: dutch,", 1))
    unset = {"path": path, "shot": shot, "fields": {"angle": None}}  # the shot's own angle wins
    assert client.patch("/olf/shot", json=unset).status_code == 200
    used = client.post(
        "/olf/scene/use", json={"path": path, "shot": shot, "n": 1, "frame": frame}
    ).json()
    assert used["room"] == 1 and used["layout"]["start"][0]["slot"] == "a"
    # COREPRODUC-739: the shot takes the framing the try's camera shows; the dutch angle stays.
    lab = client.get("/olf/scene", params={"path": path, "target": shot}).json()
    assert lab["used"]["try"] == 1 and set(lab["used"]) == {"try", "framing"}
    camera = client.get("/olf/shot", params={"path": path, "shot": shot}).json()["resolved"]["camera"]
    assert (camera["framing"], camera["angle"]) == (lab["used"]["framing"], "dutch")
    assert client.get("/olf/project", params={"path": path}).json()["issues"] == []


def test_reference_render_routes(client: TestClient, tmp_path: Path) -> None:
    """COREPRODUC-732: a shot renders its video from the scene lab's pin video at $0 on the
    demo models: it waits for a keyframe and a clip, then plans an r2v node with the blockout
    prompt, records the keyframe it took, and goes stale when Use records a new clip."""
    import base64
    import io
    import subprocess

    from PIL import Image

    if not shutil.which("ffmpeg"):
        pytest.skip("a reference video is made with ffmpeg")
    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)  # a fresh copy: other tests edit the same sample folder

    def clip(source: str) -> str:
        out = tmp_path / f"{source}.mp4"
        lavfi = f"{source}=size=320x180:rate=24:duration=3"
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", lavfi, "-pix_fmt", "yuv420p"]
        subprocess.run([*cmd, str(out)], check=True)
        return "data:video/mp4;base64," + base64.b64encode(out.read_bytes()).decode()

    buf = io.BytesIO()
    Image.new("RGB", (64, 36), "grey").save(buf, "PNG")
    frame = base64.b64encode(buf.getvalue()).decode()
    at = {"path": path, "shot": SHOT}
    client.post("/olf/scene/build", json={"path": path, "target": SHOT, "request": "Mira"})
    client.patch("/olf/shot", json=at | {"fields": {"render": "reference"}})

    def plan() -> dict[str, Any]:
        return client.get("/olf/shot", params=at).json()["plans"]["video"]

    assert "approve a keyframe first" in plan()["error"]
    client.post("/olf/render", json=at | {"kind": "keyframe"})
    client.patch("/olf/select", json=at | {"choices": {"keyframe": "kf1"}})
    assert "needs a reference video" in plan()["error"]
    used = client.post("/olf/scene/use", json=at | {"n": 1, "frame": frame, "video": clip("testsrc")})
    assert used.status_code == 200 and used.json()["reference_video"].startswith("asset/")
    # COREPRODUC-742: kf1 was drawn before the layout, so the clip would copy its framing.
    assert "kf1 was not drawn from this shot's keyframe layout" in " ".join(plan().get("notes", []))
    # Hosted, no routed model takes a reference video: the note comes with the error (the #736
    # production check found it missing).
    import vinci_core.cost

    def no_r2v(*args: Any, **kwargs: Any) -> Any:
        raise KeyError("no model for r2v")

    with pytest.MonkeyPatch.context() as m:
        m.setattr(vinci_core.cost, "plan_workflow", no_r2v)
        stopped = plan()
    assert "pick one in the video model menu" in stopped["error"]
    assert "kf1 was not drawn from" in " ".join(stopped.get("notes", []))
    # A stated first frame is the look then, not kf1: no note about kf1 (CodeRabbit on #736).
    scene = Path(path) / "episodes/e02/scenes/s03.yaml"
    text = scene.read_text()
    head, shot = text.split("id: e02/s03/sh014", 1)
    board = re.search(r"storyboard: (asset/[0-9a-f]+)", shot).group(1)
    stated = shot.replace("first_frame: keyframe", f"first_frame: {board}", 1)
    scene.write_text(head + "id: e02/s03/sh014" + stated)
    assert stated != shot and "not drawn from" not in " ".join(plan().get("notes", []))
    scene.write_text(text)
    detail = client.get("/olf/shot", params=at).json()
    assert [(r["model"], r["capability"]) for r in detail["plans"]["video"]["plan"]] == [
        ("mock:mp4:v1", "r2v")
    ]
    words = detail["prompts"]["video"]
    assert "@Video1 is a coarse 3D blockout of this exact shot" in words
    assert "The red-and-black striped pin in @Video1 is Mira Sol" in words
    assert "never grey clay or a 3D blockout" in words
    shows = client.get("/olf/project", params={"path": path}).json()["shots"][SHOT]
    assert shows["reference_video"] == "storyboards/e02/s03/sh014.mp4"
    made = client.post("/olf/render", json=at | {"kind": "video"}).json()
    take = made["takes"][0]
    assert take.endswith("/v1")
    taken = client.get("/olf/project", params={"path": path}).json()["takes"][take]
    assert taken["inputs"]["first_frame"] == f"{SHOT}/kf1" and not taken["stale"]
    # A new clip (a new Use) makes the video stale; the keyframe's state does not change (the
    # first Use already made it stale: its frame is a keyframe input).
    before = client.get("/olf/project", params={"path": path}).json()["takes"]
    client.post("/olf/scene/use", json=at | {"n": 1, "frame": frame, "video": clip("testsrc2")})
    takes = client.get("/olf/project", params={"path": path}).json()["takes"]
    assert takes[take]["stale"] and not before[take]["stale"]
    assert takes[f"{SHOT}/kf1"]["stale"] == before[f"{SHOT}/kf1"]["stale"]
    short = client.post("/olf/scene/use", json=at | {"n": 1, "frame": frame, "video": "AAAA"})
    assert short.status_code == 400 and "does not play" in short.json()["detail"]
    # COREPRODUC-741: the prompt names each move and the first frame's sizes and places, as
    # the pin carries no body; a move under 0.4 m and a still reference shot get warnings.
    first = client.get("/olf/scene", params={"path": path, "target": SHOT}).json()["tries"][0]
    staged = {k: v for k, v in first.items() if k in ("room", "camera", "cast", "groups", "props")}
    mira = staged["cast"][0]
    step = staged | {"cast": [mira | {"end": {"at": [mira["at"][0], 0, mira["at"][2] - 0.7]}}]}
    pasted = client.post("/olf/scene/paste", json=at | {"target": SHOT, "text": json.dumps(step)})
    two = pasted.json()["try"]
    client.post("/olf/scene/use", json=at | {"n": two, "frame": frame, "video": clip("testsrc")})
    words = client.get("/olf/shot", params=at).json()["prompts"]["video"]
    assert "Mira Sol takes one step (0.7 m) away from the camera toward the table, then stops" in words
    assert "In the first frame, as in @Video1: Mira Sol is " in words
    # COREPRODUC-742: a mover's measured end size and place too, and "match" in place of "keep".
    assert "At the end, as in @Video1: Mira Sol is " in words
    assert "Match these sizes and places at those moments" in words
    assert "moving when their pin moves" in words
    small = staged | {"cast": [mira | {"end": {"at": [mira["at"][0] + 0.2, 0, mira["at"][2]]}}]}
    still = staged | {"cast": [mira | {"end": {"at": [mira["at"][0] + 0.5, 0, mira["at"][2]]}}]}
    client.patch("/olf/shot", json=at | {"fields": {"move": "static"}})
    for data, warning in ((small, "Mira Sol moves only 0.2 m"), (still, "the shot hardly moves")):
        checked = client.post("/olf/scene/check", json={"path": path, "shot": SHOT, "data": data})
        assert any(warning in i["message"] for i in checked.json()["issues"]), warning
    # COREPRODUC-742: a keyframe drawn from this pin frame gets no layout note; after a Use with
    # another pin frame it does, as it was drawn from the old one (CodeRabbit on #736).
    client.post("/olf/render", json=at | {"kind": "keyframe"})
    client.patch("/olf/select", json=at | {"choices": {"keyframe": "kf2"}})
    video = plan()
    assert "error" not in video and "not drawn from" not in " ".join(video.get("notes", []))
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), "white").save(buf, "PNG")
    other = base64.b64encode(buf.getvalue()).decode()
    client.post("/olf/scene/use", json=at | {"n": two, "frame": other, "video": clip("testsrc")})
    assert "kf2 was not drawn from" in " ".join(plan().get("notes", []))


def test_a_walk_into_the_frame_gets_its_end_numbers() -> None:
    """CodeRabbit on #740: a person who starts outside the frame still gets the end framing."""
    from vinci_olf.scene import Frame
    from vinci_olf.scene_lab import _motion_words

    lens = Frame([0, 1.5, 5], [0, 0, -1], [1, 0, 0], [0, 1, 0], 0.5, 0.28)
    staged = {"cast": [{"slot": "a", "at": [-9, 0, 0], "end": {"at": [0, 0, 0]}}]}
    framing = _motion_words(staged, ["Mira"], [], lens, lens)["framing"]
    assert framing.startswith("At the end, as in @Video1: Mira is about")
    assert "In the first frame" not in framing and "Match these sizes" in framing
    # One who walks out of the frame has no end numbers, and still "match", never "keep".
    staged = {"cast": [{"slot": "a", "at": [0, 0, 0], "end": {"at": [-9, 0, 0]}}]}
    framing = _motion_words(staged, ["Mira"], [], lens, lens)["framing"]
    assert "At the end" not in framing and "Match these sizes" in framing
    # The end frame is where a push or a pull ends, as the lab's cameraAt moves it (same numbers
    # as tests/test_scenelab.py): the end numbers match the pin video (CodeRabbit on #740).
    from vinci_olf.scene_lab import _pushed

    shot = {"camera": {"at": [0, 1.5, 10], "looks_at": [0, 1.5, 0]}, "cast": []}
    assert _pushed(shot, {"move": "push_in", "amount": 0.35})["camera"]["at"][2] == pytest.approx(6.5)
    assert _pushed(shot, {"move": "pull_out", "amount": 0.5})["camera"]["at"][2] == pytest.approx(20)
    assert _pushed(shot, {"move": "push_in"})["camera"]["at"][2] == pytest.approx(7.5)
    assert _pushed(shot, {"move": "pan"}) is shot


def test_camerawork_has_no_still_words() -> None:
    """COREPRODUC-741: no library template tells a person to stand still. The banned words of
    github.com/sirioberati/ai-filmmaking-camera-control-seedance-2-5 (MIT; qa4.py rule Q4) turn
    the person into a statue."""
    from vinci_olf.project import LIBRARY

    still = re.compile(
        r"\b(very still|motionless|does not move|stands still|completely still|frozen|"
        r"without moving|stays (at|in|still))\b",
        re.I,
    )
    found = [f.name for f in LIBRARY.rglob("*.yaml") if still.search(f.read_text())]
    assert found == []


def test_engine_move_routes(client: TestClient) -> None:
    """COREPRODUC-564: the shot page sets an engine move, prices it at $0 and renders it."""
    if not shutil.which("ffmpeg"):
        pytest.skip("an engine move runs ffmpeg")
    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)  # a fresh copy: other tests edit the same sample folder
    client.post("/olf/render", json={"path": path, "shot": SHOT, "kind": "keyframe"})
    client.patch("/olf/select", json={"path": path, "shot": SHOT, "choices": {"keyframe": "kf1"}})
    fields = {"render": "engine", "amount": "0.3", "ease": "out", "duration": "0+18"}
    edit = client.patch("/olf/shot", json={"path": path, "shot": SHOT, "fields": fields})
    assert edit.status_code == 200 and edit.json() == {
        "duration": "0+18",  # seconds+frames stays as typed
        "camera": {
            "framing": "close_up",
            "angle": "eye_level",
            "lens": "50mm",
            "move": "push_in",
            "amount": 0.3,
            "ease": "out",
            "render": "engine",
        },
    }
    plan = client.get("/olf/shot", params={"path": path, "shot": SHOT}).json()["plans"]["video"]
    row = {"node": "video", "model": "local:ffmpeg:v1", "amount": 0.0, "capability": None}
    assert plan["plan"] == [row] and plan["choices"] == [] and "enlarges it" in plan["notes"][0]
    done = client.post("/olf/render", json={"path": path, "shot": SHOT, "max_total": 0})
    assert done.status_code == 200 and done.json()["takes"] == [f"{SHOT}/v1"]
    take = client.get("/olf/project", params={"path": path}).json()["takes"][f"{SHOT}/v1"]
    assert (take["provenance"]["provider"], take["duration"]) == ("local", "0.750s")
    bad = {"path": path, "shot": SHOT, "fields": {"move": "orbit"}}
    assert client.patch("/olf/shot", json=bad).status_code == 200  # a model can orbit
    plan = client.get("/olf/shot", params={"path": path, "shot": SHOT}).json()["plans"]["video"]
    assert "cannot make a orbit move from a held drawing" in plan["error"]


def test_camerawork_routes(client: TestClient) -> None:
    """COREPRODUC-564: the Camerawork menu lists the library and puts a template on a shot."""
    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)  # a fresh copy: other tests edit the same sample folder
    rows = client.get("/olf/camerawork").json()["library"]
    assert len(rows) == 32 and rows[0]["id"] == "anime/ambient-hold" and rows[0]["version"] == 2
    body = {"path": path, "shot": SHOT, "template": "anime/tu-slow"}
    done = client.post("/olf/camerawork", json=body)
    assert done.status_code == 200 and (done.json()["template"], done.json()["duration"]) == (
        "cam/tu-slow",
        "4+00",
    )
    show = client.get("/olf/project", params={"path": path}).json()
    entry = show["bible"]["camerawork"][1]  # after the sample's own cam/key-insert
    assert (entry["id"], entry["file"], entry["used_in"]) == (
        "cam/tu-slow",
        "bible/camerawork/tu-slow/tu-slow.yaml",
        [SHOT],
    )
    camera = show["shots"][SHOT]["camera"]
    assert show["issues"] == [] and (camera["amount"], camera["render"]) == (0.12, "engine")
    detail = client.get("/olf/shot", params={"path": path, "shot": SHOT}).json()
    assert detail["origins"]["camera_fields"]["amount"] == "cam/tu-slow"
    assert detail["plans"]["video"]["plan"][-1]["model"] == "local:ffmpeg:v1"  # an engine move
    again = client.post("/olf/camerawork", json=body | {"template": "cam/tu-slow"})
    assert again.status_code == 200  # a template of the show
    off = client.post("/olf/camerawork", json=body | {"template": None})
    assert off.json()["template"] is None
    wrong = client.post("/olf/camerawork", json=body | {"template": "anime/nope"})
    assert wrong.status_code == 400 and "library has no template" in wrong.json()["detail"]


def test_previs_route_serves_the_sheet_and_share_leaves_it_out(client: TestClient) -> None:
    """COREPRODUC-565: the e-conte sheet is made at $0, served as a PDF, and kept out of Share."""
    import io
    import zipfile

    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)
    done = client.post("/olf/previs", json={"path": path, "episode": "e02", "animatic": False})
    assert done.status_code == 200, done.text
    assert done.json() == {
        "files": ["previs/e02/e02-sheet.pdf", "previs/e02/e02-sheet-01.png"],
        "cuts": 3,
        "runtime": 8.5,
    }
    pdf = client.get("/olf/file", params={"path": path, "rel": "previs/e02/e02-sheet.pdf"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    shared = client.get("/olf/share", params={"path": path}).content
    assert not [n for n in zipfile.ZipFile(io.BytesIO(shared)).namelist() if "/previs/" in n]
    missing = client.post("/olf/previs", json={"path": path, "episode": "e09"})
    assert missing.status_code == 400 and "e09: no such episode" in missing.json()["detail"]


def test_bible_edit_routes(client: TestClient) -> None:
    """COREPRODUC-682: a location's name, description, references and variants."""
    import base64
    import io

    from PIL import Image

    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)
    buf = io.BytesIO()
    Image.new("RGB", (64, 32), "red").save(buf, "PNG")
    image = base64.b64encode(buf.getvalue()).decode()
    loc = {"path": path, "entry": "loc/lighthouse"}
    entry = client.patch("/olf/entry", json=loc | {"description": "Glass and brass."})
    assert entry.json() == {"entry": "loc/lighthouse"}
    added = client.post("/olf/reference", json=loc | {"data": image, "label": "Gate"})
    assert added.json() == {"reference": "gate.png"}
    replaced = client.post("/olf/reference", json=loc | {"data": image, "ref": "gate.png"})
    assert replaced.json() == {"reference": "bible/locations/lighthouse/gate.png"}
    empty = client.post("/olf/reference", json=loc)
    assert empty.status_code == 400 and "send an image" in empty.json()["detail"]
    fog = client.post("/olf/variant", json=loc | {"name": "fog"})
    assert fog.json() == {"variants": ["day", "dusk", "night", "storm", "fog"]}
    used = client.post("/olf/variant", json=loc | {"name": "night", "remove": True})
    assert used.status_code == 400 and "scene e02/s03 uses the variant" in used.json()["detail"]
    show = client.get("/olf/project", params={"path": path}).json()
    lighthouse = next(e for e in show["bible"]["location"] if e["id"] == "loc/lighthouse")
    assert lighthouse["data"]["description"] == "Glass and brass." and show["issues"] == []
    assert lighthouse["data"]["references"]["gate"] == "gate.png"
    gone = client.post("/olf/reference", json=loc | {"ref": "gate.png", "remove": True})
    assert gone.json() == {"reference": "bible/locations/lighthouse/gate.png"}


def test_edit_yaml_routes(client: TestClient) -> None:
    """COREPRODUC-683: read and save a bible entry's YAML; a bad edit is a 400 and saves nothing."""
    path = client.post("/olf/sample").json()["path"]
    shutil.rmtree(path)
    shutil.copytree(SAMPLE, path)
    q = {"path": path, "entry": "prop/bell"}
    source = client.get("/olf/source", params=q).json()
    assert source == {"file": "bible/props/bell/bell.yaml", "text": source["text"]}
    text = source["text"] + "name: Silver bell  # shown in the bible list\n"
    assert client.put("/olf/source", json=q | {"text": text}).json() == {"file": source["file"]}
    assert client.get("/olf/source", params=q).json()["text"] == text
    bad = client.put("/olf/source", json=q | {"text": text + "colour: red\n"})
    assert bad.status_code == 400 and "nothing was saved" in bad.json()["detail"]
    assert client.get("/olf/source", params=q).json()["text"] == text
