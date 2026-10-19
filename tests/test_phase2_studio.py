from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_media.ops import make_fixture_video
from vinci_runtime.engine import Engine


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_studio_smoke(client: TestClient) -> None:
    page = client.get("/studio")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")
    body = page.text
    assert "Vinci Studio" in body
    assert "Cinema stack" in body
    assert "Explore" in body
    assert "Canvas" in body
    assert "Templates" in body
    assert "Higgsfield" in body
    assert "Magnific" in body
    assert "Custom MCP" in body
    assert "run.nodes" in body
    assert "fillDrawer" in body
    assert "nodeDigest" in body
    assert "generateInFlight" in body
    assert "compose-gallery" in body
    assert "composeModels" in body
    assert "model-card" in body
    assert "aspect-pills" in body
    assert "duration-pills" in body
    assert "first-frame" in body
    assert "camera-pills" in body
    assert "lens-pills" in body
    assert "look-pills" in body
    assert "cast-pills" in body
    assert "applyOpticalToNode" in body
    assert "stampOptical" in body
    assert "opticalLabel" in body
    assert "Cinema stack" in body
    assert "Generate this node" in body
    assert "Generate graph" in body
    assert "Play timeline" in body
    assert "motion-pills" in body
    assert "aperture-pills" in body
    assert "genre-pills" in body
    assert "lighting-pills" in body
    assert "palette-pills" in body
    assert "image_urls" in body
    assert "add-shot" in body
    assert "creativity" in body
    assert "resemblance" in body
    assert "optimized-pills" in body
    assert "element-kind-pills" in body
    assert "Cinema sequences stay at 6 shots." in body
    assert "Local named stills for characters, locations, and props" in body
    assert "node-model" in body
    assert "split-view" in body
    assert "playTimeline" in body
    assert "fillNodeModel" in body
    assert "modelIdForNode" in body
    assert "fillShotControls" in body
    assert "placeholder || \"north-light oak cube tumbling\"" in body
    assert "Magnific / Freepik" in body
    assert "if (picked) return picked;" in body
    assert "startsWith(\"north-light oak cube\")" in body
    assert "defaults.prompt" in body
    assert "Skills" in body
    assert "Cost report" in body
    assert "Speak" in body
    assert "Speech from a line of text. Add a still only when the model animates a photo." in body
    assert 'm.provider !== "mock"' in body
    assert 'state.page === "upscale" && !mode.showMagnific' in body
    skills = client.get("/skills").json()["skills"]
    ids = {s["id"] for s in skills}
    assert "@tryvinci/podcast-to-shorts" in ids
    assert "@tryvinci/image-generate" in ids
    assert "@tryvinci/cinema-still" in ids
    assert "@tryvinci/still-to-talk" in ids
    assert "@tryvinci/cinema-sequence" in ids
    assert "@tryvinci/first-last-frame" in ids
    assert "@tryvinci/soul-character" in ids
    assert "Bring your own keys" in body
    assert "New connector" in body
    assert "connector-mark" in body
    assert "connect-select" in body
    assert "Named MCP" in body
    assert "Supercomputer" in body
    assert "Collab" in body
    assert "wavespeed" in body
    assert "Upscale still" in body
    assert "manifest.webmanifest" in body
    assert "/assets/${a.id}/file" in body
    assert "vinci://assets/" in body
    assert body.count("let models = [];") == 1
    assert body.count("let doctor = {};") == 1
    assert "t.defaults" in body
    assert 't.page || "canvas"' in body
    assert "Speak scenes open Speak" in body
    assert "Skip for now" in body
    assert "vinci-onboard-v1" in body
    assert "Inter Tight" in body
    assert "Instrument Serif" in body
    assert "north-light oak cube" in body
    tpls = client.get("/templates").json()["templates"]
    ids = {row["id"] for row in tpls}
    assert "cinema-still" in ids
    assert "cinema-sequence" in ids
    assert "first-last-frame" in ids
    assert "soul-character" in ids
    assert "speak-selfie" in ids
    assert "speak-podcast" in ids
    assert "speak-car" in ids
    seq = next(row for row in tpls if row["id"] == "cinema-sequence")
    assert seq["skill"] == "@tryvinci/cinema-sequence"
    assert seq.get("preview_kind") == "storyboard"
    soul = next(row for row in tpls if row["id"] == "soul-character")
    assert soul["skill"] == "@tryvinci/soul-character"
    assert soul["defaults"]["lighting"] == "studio"
    assert soul["defaults"]["lens"] == "85mm"
    selfie = next(row for row in tpls if row["id"] == "speak-selfie")
    assert selfie["page"] == "speak"
    assert selfie["defaults"]["scene"] == "selfie"
    preview = client.get("/templates/cinema-still/preview.svg")
    assert preview.status_code == 200
    assert "svg" in preview.headers.get("content-type", "")
    board = client.get("/templates/cinema-sequence/preview.svg")
    assert board.status_code == 200
    assert board.text.count("<rect") >= 4
    doctor = client.get("/doctor").json()
    assert doctor["providers"]["higgsfield"]["kind"] == "http"
    assert doctor["providers"]["magnific"]["kind"] == "http"
    assert doctor["providers"]["mcp"]["kind"] == "mcp"
    assert doctor["providers"]["mcp"]["display_name"] == "Custom MCP"


def test_upload_mp4_sniffs_video_from_filename(client: TestClient, tmp_path: Path) -> None:
    media = make_fixture_video(tmp_path / "pod.mp4", duration=1.0)
    res = client.post(
        "/assets",
        files={"file": ("pod.mp4", media.read_bytes(), "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kind"] == "video"
    assert body["mime"] == "video/mp4"


def test_find_and_podcast_via_http(client: TestClient, tmp_path: Path) -> None:
    media = make_fixture_video(tmp_path / "pod.mp4", duration=3.0)
    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/podcast-to-shorts",
            "inputs": {"media": str(media), "query": "pricing"},
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    found = client.get("/find", params={"q": "pricing"})
    assert found.status_code == 200
    assert "hits" in found.json()
    listed = client.get("/runs")
    assert listed.status_code == 200
    assert listed.json()["runs"]


def test_still_to_talk_workflow_is_zero_on_mock(client: TestClient) -> None:
    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/still-to-talk",
            "inputs": {"prompt": "a speaker in a quiet room"},
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    assert len(body["job_ids"]) == 2
    assert body["outputs"]
    assert body["nodes"]["still"]["output"]
    assert body["nodes"]["talk"]["output"]
    assert body["nodes"]["talk"]["output"] == body["outputs"][0]


def test_cinema_still_workflow_is_zero_on_mock(client: TestClient) -> None:
    run = client.post(
        "/runs",
        json={"skill": "@tryvinci/cinema-still", "inputs": {"prompt": "a red cube tumbling"}},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    assert len(body["job_ids"]) == 3
    assert body["outputs"]
    assert body["nodes"]["still"]["output"]
    assert body["nodes"]["upscale"]["output"]
    assert body["nodes"]["motion"]["output"]
    assert body["nodes"]["motion"]["output"] == body["outputs"][0]


def test_cinema_sequence_workflow_is_zero_on_mock(client: TestClient) -> None:
    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/cinema-sequence",
            "inputs": {"prompt": "a four-beat oak cube sequence"},
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    assert len(body["job_ids"]) == 4
    assert body["outputs"]
    for node_id in ("establish", "coverage", "close", "reverse"):
        assert body["nodes"][node_id]["output"]
    assert body["nodes"]["reverse"]["output"] == body["outputs"][0]
    shots = {body["nodes"][nid]["output"] for nid in ("establish", "coverage", "close", "reverse")}
    assert len(shots) == 4


def test_first_last_frame_workflow_is_zero_on_mock(client: TestClient) -> None:
    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/first-last-frame",
            "inputs": {"prompt": "oak cube first last frame", "duration": 5},
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    assert len(body["job_ids"]) == 3
    assert body["nodes"]["first"]["output"]
    assert body["nodes"]["last"]["output"]
    assert body["nodes"]["motion"]["output"] == body["outputs"][0]
    assert body["nodes"]["first"]["output"] != body["nodes"]["last"]["output"]


def test_soul_character_workflow_is_zero_on_mock(client: TestClient) -> None:
    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/soul-character",
            "inputs": {"prompt": "oak cube character sheet", "lighting": "studio"},
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    assert len(body["job_ids"]) == 2
    assert body["nodes"]["sheet"]["output"]
    assert body["nodes"]["lock"]["output"]
    assert body["nodes"]["sheet"]["output"] != body["nodes"]["lock"]["output"]
    assert body["nodes"]["lock"]["output"] == body["outputs"][0]


def test_cinema_sequence_accepts_cast_image_urls(client: TestClient) -> None:
    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/cinema-sequence",
            "inputs": {
                "prompt": "oak cube sequence with cast refs",
                "image_urls": ["cast-ref-a", "cast-ref-b"],
            },
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    assert len(body["job_ids"]) == 4


def test_still_to_talk_honors_speak_scene(client: TestClient) -> None:
    general = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/still-to-talk",
            "inputs": {"prompt": "a speaker in a quiet room"},
        },
    )
    selfie = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/still-to-talk",
            "inputs": {"prompt": "a speaker in a quiet room", "scene": "selfie"},
        },
    )
    assert general.status_code == 200, general.text
    assert selfie.status_code == 200, selfie.text
    assert general.json()["state"] == "completed"
    assert selfie.json()["state"] == "completed"
    assert general.json()["estimate"]["total"] == 0
    assert selfie.json()["estimate"]["total"] == 0
    assert general.json()["nodes"]["still"]["output"] != selfie.json()["nodes"]["still"]["output"]


def test_image_generate_honors_portrait_aspect(client: TestClient) -> None:
    import struct

    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/image-generate",
            "inputs": {"prompt": "portrait oak cube", "aspect_ratio": "9:16"},
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    png = client.get(f"/assets/{body['outputs'][0]}/file")
    assert png.status_code == 200
    width, height = struct.unpack(">II", png.content[16:24])
    assert (width, height) == (540, 960)


def test_cinema_still_honors_portrait_aspect(client: TestClient) -> None:
    import struct

    from vinci_provider_sdk.mock import mp4_dimensions, mp4_duration_seconds

    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/cinema-still",
            "inputs": {
                "prompt": "portrait oak cube tumbling",
                "aspect_ratio": "9:16",
                "duration": 8,
            },
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    still = client.get(f"/assets/{body['nodes']['still']['output']}/file")
    width, height = struct.unpack(">II", still.content[16:24])
    assert (width, height) == (540, 960)
    motion = client.get(f"/assets/{body['nodes']['motion']['output']}/file")
    assert mp4_dimensions(motion.content) == (540, 960)
    seconds = mp4_duration_seconds(motion.content)
    assert seconds is not None and 7.5 <= seconds <= 8.5


def test_higgsfield_needs_key_and_secret(client: TestClient) -> None:
    res = client.post(
        "/providers",
        json={"id": "higgsfield", "secret": "hf-key-id", "extra_secret": "hf-secret"},
    )
    assert res.status_code == 200, res.text
    assert "hf-key-id" not in res.text
    assert "hf-secret" not in res.text
    body = res.json()
    assert body["kind"] == "http"
    assert body["display_name"] == "Higgsfield"
    assert "HIGGSFIELD_API_SECRET" in body["extra_secret_names"]
    doctor = client.get("/doctor").json()
    assert doctor["providers"]["higgsfield"]["configured"] is True
    models = client.get("/models").json()["models"]
    assert any(m["id"].startswith("higgsfield:") for m in models)
    assert not any("sora" in m["id"].lower() for m in models)


def test_image_generate_honors_optical_stack(client: TestClient) -> None:
    plain = client.post(
        "/runs",
        json={"skill": "@tryvinci/image-generate", "inputs": {"prompt": "oak cube optical"}},
    )
    optic = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/image-generate",
            "inputs": {
                "prompt": "oak cube optical",
                "camera": "handheld",
                "lens": "50mm",
                "look": "noir",
            },
        },
    )
    cinema = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/image-generate",
            "inputs": {
                "prompt": "oak cube optical",
                "camera": "handheld",
                "lens": "50mm",
                "look": "noir",
                "aperture": "f/1.4",
                "genre": "drama",
            },
        },
    )
    assert plain.status_code == 200, plain.text
    assert optic.status_code == 200, optic.text
    assert cinema.status_code == 200, cinema.text
    assert plain.json()["state"] == "completed"
    assert optic.json()["state"] == "completed"
    assert cinema.json()["state"] == "completed"
    assert plain.json()["estimate"]["total"] == 0
    assert optic.json()["estimate"]["total"] == 0
    assert cinema.json()["estimate"]["total"] == 0
    assert plain.json()["outputs"][0] != optic.json()["outputs"][0]
    assert optic.json()["outputs"][0] != cinema.json()["outputs"][0]


def test_video_generate_honors_duration(client: TestClient) -> None:
    from vinci_provider_sdk.mock import mp4_duration_seconds

    run = client.post(
        "/runs",
        json={
            "skill": "@tryvinci/video-generate",
            "inputs": {"prompt": "oak cube duration", "duration": 3},
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    clip = client.get(f"/assets/{body['outputs'][0]}/file")
    seconds = mp4_duration_seconds(clip.content)
    assert seconds is not None and 2.5 <= seconds <= 3.5


def test_canvas_node_workflow_honors_optical_and_aspect(client: TestClient) -> None:
    import struct

    run = client.post(
        "/runs",
        json={
            "workflow": {
                "id": "canvas-node",
                "version": "1.0.0",
                "preference": "cheapest",
                "nodes": [
                    {
                        "id": "still",
                        "type": "generate",
                        "capability": "t2i",
                        "params": {
                            "prompt": "{{inputs.prompt}}",
                            "aspect_ratio": "{{inputs.aspect_ratio}}",
                            "camera": "{{inputs.camera}}",
                            "lens": "{{inputs.lens}}",
                            "look": "{{inputs.look}}",
                            "aperture": "{{inputs.aperture}}",
                            "genre": "{{inputs.genre}}",
                        },
                    }
                ],
                "edges": [],
            },
            "inputs": {
                "prompt": "oak cube node",
                "aspect_ratio": "9:16",
                "camera": "handheld",
                "lens": "50mm",
                "look": "noir",
                "aperture": "f/1.4",
                "genre": "drama",
            },
            "model_id": "mock:png:v1",
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    assert body["nodes"]["still"]["output"]
    png = client.get(f"/assets/{body['outputs'][0]}/file")
    width, height = struct.unpack(">II", png.content[16:24])
    assert (width, height) == (540, 960)


def test_canvas_node_honors_per_node_model_id(client: TestClient) -> None:
    run = client.post(
        "/runs",
        json={
            "workflow": {
                "id": "canvas-node",
                "version": "1.0.0",
                "preference": "cheapest",
                "nodes": [
                    {
                        "id": "clip",
                        "type": "generate",
                        "capability": "t2v",
                        "model_id": "mock:mp4:v1",
                        "params": {
                            "prompt": "{{inputs.prompt}}",
                            "duration": "{{inputs.duration}}",
                            "motion": "{{inputs.motion}}",
                        },
                    }
                ],
                "edges": [],
            },
            "inputs": {
                "prompt": "oak cube orbit",
                "duration": 2,
                "motion": "orbit",
            },
            "model_id": "mock:png:v1",
        },
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["state"] == "completed"
    assert body["estimate"]["total"] == 0
    clip = client.get(f"/assets/{body['outputs'][0]}/file")
    assert clip.content[4:8] == b"ftyp"


def test_named_mcp_oauth_plan_and_collab(client: TestClient) -> None:
    bad = client.post(
        "/providers",
        json={"id": "mcp_Nope", "url": "http://127.0.0.1:9/mcp"},
    )
    assert bad.status_code == 400
    added = client.post(
        "/providers",
        json={
            "id": "mcp_comfy",
            "url": "http://127.0.0.1:9/mcp",
            "label": "ComfyUI",
            "authorize_url": "http://127.0.0.1:9/oauth",
        },
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["id"] == "mcp_comfy"
    assert body["display_name"] == "ComfyUI"
    assert body["kind"] == "mcp"
    assert body["auth"] == "oauth_or_key"
    assert body["available"] is True
    doctor = client.get("/doctor").json()
    assert doctor["providers"]["mcp_comfy"]["url"] == "http://127.0.0.1:9/mcp"
    oauth = client.post("/providers/mcp_comfy/oauth")
    assert oauth.status_code == 200
    assert oauth.json()["authorize_url"] == "http://127.0.0.1:9/oauth"
    http_oauth = client.post("/providers/fal/oauth")
    assert http_oauth.status_code == 200
    assert http_oauth.json()["mode"] == "key"
    plan = client.post(
        "/agent/plan",
        json={"brief": "luxury watch still then cinema sequence"},
    )
    assert plan.status_code == 200
    steps = plan.json()["steps"]
    assert steps
    assert all("skill" in step and "title" in step for step in steps)
    created = client.post("/collab/sessions", json={"name": "LAN cut"})
    assert created.status_code == 200
    sid = created.json()["id"]
    listed = client.get("/collab/sessions").json()["sessions"]
    assert any(row["id"] == sid for row in listed)
    put = client.put(
        f"/collab/sessions/{sid}",
        json={"name": "LAN cut", "snapshot": {"prompt": "oak", "page": "canvas"}},
    )
    assert put.status_code == 200
    got = client.get(f"/collab/sessions/{sid}")
    assert got.status_code == 200
    assert got.json()["snapshot"]["prompt"] == "oak"
    missing = client.get("/collab/sessions/missing")
    assert missing.status_code == 404

