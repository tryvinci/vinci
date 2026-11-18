"""Studio projects on the local daemon (COREPRODUC-702): the hosted ``/projects`` contract on SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_daemon.projects import DEFAULT_ID
from vinci_runtime.engine import Engine

IMAGE = {
    "id": "still",
    "version": "1.0.0",
    "edges": [],
    "nodes": [
        {
            "id": "a",
            "type": "generate",
            "capability": "t2i",
            "model_id": "mock:png:v1",
            "params": {"prompt": "{{inputs.prompt}}"},
        }
    ],
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def _run(
    client: TestClient, prompt: str, project_id: str | None = None, workflow: dict | None = None
) -> dict:
    body = {"inputs": {"prompt": prompt}, "workflow": workflow or IMAGE}
    if project_id:
        body["project_id"] = project_id
    res = client.post("/runs", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _ids(client: TestClient, path: str, project: str) -> list[str]:
    key = path.strip("/")
    return [row["id"] for row in client.get(path, params={"project": project}).json()[key]]


def test_the_default_project_is_there_and_cannot_go(client: TestClient) -> None:
    rows = client.get("/projects").json()["projects"]
    assert [(p["id"], p["name"], p["default"]) for p in rows] == [(DEFAULT_ID, "My work", True)]
    assert client.patch(f"/projects/{DEFAULT_ID}", json={"archived": True}).status_code == 400
    assert client.delete(f"/projects/{DEFAULT_ID}").status_code == 400
    assert (
        client.patch(f"/projects/{DEFAULT_ID}", json={"name": " Old  stuff "}).json()["name"]
        == "Old stuff"
    )
    assert client.post("/projects", json={"name": " "}).status_code == 400
    assert client.get("/projects/nope").status_code == 404
    assert client.get("/runs", params={"project": "nope"}).status_code == 404


def test_a_run_and_its_output_stay_in_the_project_they_started_in(client: TestClient) -> None:
    a = client.post("/projects", json={"name": "A"}).json()["id"]
    b = client.post("/projects", json={"name": "B"}).json()["id"]
    in_a = _run(client, "oak cube", a)
    legacy = _run(client, "pine cube")  # no project_id: the default project
    upload = client.post(
        "/assets", files={"file": ("ref.png", b"\x89PNG-ref", "image/png")}, data={"project_id": b}
    ).json()
    assert in_a["state"] == "completed" and in_a["outputs"]
    assert _ids(client, "/runs", a) == [in_a["id"]]
    assert _ids(client, "/runs", DEFAULT_ID) == [legacy["id"]]
    assert _ids(client, "/runs", b) == []
    assert {r["id"] for r in client.get("/runs").json()["runs"]} == {
        in_a["id"],
        legacy["id"],
    }  # no ?project=: all
    assert set(_ids(client, "/assets", a)) == set(in_a["outputs"])
    assert _ids(client, "/assets", b) == [upload["id"]]
    assert set(_ids(client, "/assets", DEFAULT_ID)) == set(legacy["outputs"])
    library = client.get("/library", params={"project": a}).json()["items"]
    assert {item["asset_id"] for item in library} == set(in_a["outputs"])


def test_shows_renders_stay_out_and_archived_projects_take_no_work(client: TestClient) -> None:
    pid = client.post("/projects", json={"name": "Pilot"}).json()["id"]
    _run(client, "keyframe", pid, IMAGE | {"id": "olf:e01/s01/sh001"})
    assert _ids(client, "/runs", pid) == []  # a show keeps its own takes
    assert client.patch(f"/projects/{pid}", json={"archived": True}).json()["archived_at"]
    assert (
        client.post(
            "/runs", json={"inputs": {"prompt": "x"}, "workflow": IMAGE, "project_id": pid}
        ).status_code
        == 409
    )
    assert client.patch(f"/projects/{pid}", json={"archived": False}).json()["archived_at"] is None


def test_a_stale_board_save_is_refused(client: TestClient) -> None:
    pid = client.post("/projects", json={"name": "Board"}).json()["id"]
    assert client.get(f"/projects/{pid}/board").json() == {"board": None, "board_rev": 0}
    page = {"version": 1, "pages": [{"id": "p1", "name": "Page 1"}], "active": "p1"}
    assert (
        client.put(f"/projects/{pid}/board", json={"board": page, "board_rev": 0}).json()[
            "board_rev"
        ]
        == 1
    )
    stale = client.put(f"/projects/{pid}/board", json={"board": {"pages": []}, "board_rev": 0})
    assert stale.status_code == 409 and "another window" in stale.json()["detail"]
    assert client.get(f"/projects/{pid}/board").json() == {"board": page, "board_rev": 1}
    assert (
        client.put(f"/projects/{pid}/board", json={"board": "nope", "board_rev": 1}).status_code
        == 400
    )


def test_only_an_empty_project_can_be_deleted(client: TestClient) -> None:
    empty = client.post("/projects", json={"name": "Empty"}).json()["id"]
    used = client.post("/projects", json={"name": "Used"}).json()["id"]
    _run(client, "oak", used)
    assert client.delete(f"/projects/{empty}").json()["deleted"] is True
    assert client.get(f"/projects/{empty}").status_code == 404
    assert client.delete(f"/projects/{used}").status_code == 409


def test_shows_are_listed_per_project(client: TestClient) -> None:
    pytest.importorskip("vinci_olf")
    pid = client.post("/projects", json={"name": "Series"}).json()["id"]
    pilot = client.post("/olf/new", json={"title": "Pilot", "project_id": pid}).json()["path"]
    old = client.post("/olf/new", json={"title": "Old"}).json()["path"]

    def listed(project: str) -> list[str]:
        shows = client.get("/olf/shows", params={"project": project}).json()["shows"]
        return [row["path"] for row in shows]

    assert listed(pid) == [str(Path(pilot).resolve())]
    assert listed(DEFAULT_ID) == [str(Path(old).resolve())]
    assert len(listed("")) == 2
    assert client.post("/olf/new", json={"title": "X", "project_id": "nope"}).status_code == 404
    assert client.delete(f"/projects/{pid}").status_code == 409


def test_projects_survive_a_journal_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the durable journal on, project writes are acknowledged and replay is idempotent."""
    monkeypatch.setenv("VINCI_DURABLE_JOURNAL", "local")
    monkeypatch.setenv("VINCI_HOME", str(tmp_path / "vinci"))
    client = TestClient(create_app())
    client.post("/init", json={"demo": True})
    made = client.post("/projects", json={"name": "Journaled"})
    assert made.status_code == 200 and made.json().get("operation_id")
    pid = made.json()["id"]
    assert (
        client.put(f"/projects/{pid}/board", json={"board": {"pages": []}, "board_rev": 0}).json()[
            "board_rev"
        ]
        == 1
    )
    from vinci_daemon.ledger_replay import rebuild_acknowledged_metadata

    engine = client.app.state.engine
    engine._ledger_applied_op_ids = set()  # replay every committed operation again
    rebuild_acknowledged_metadata(client.app.state.journal, engine)
    assert client.get(f"/projects/{pid}").json()["name"] == "Journaled"
    assert client.get(f"/projects/{pid}/board").json() == {"board": {"pages": []}, "board_rev": 1}


def test_review_fixes_of_682(client: TestClient) -> None:
    """CodeRabbit on #682: a rename keeps a newer board; the same upload stays in My work; each
    project opens its own sample copy."""
    pid = client.post("/projects", json={"name": "Fixes"}).json()["id"]
    assert (
        client.put(f"/projects/{pid}/board", json={"board": {"pages": []}, "board_rev": 0}).json()[
            "board_rev"
        ]
        == 1
    )
    assert client.patch(f"/projects/{pid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert client.get(f"/projects/{pid}/board").json() == {"board": {"pages": []}, "board_rev": 1}

    png = ("ref.png", b"\x89PNG-same-bytes", "image/png")
    named = client.post("/assets", files={"file": png}, data={"project_id": pid}).json()["id"]
    mine = client.post("/assets", files={"file": png}, data={"project_id": DEFAULT_ID}).json()["id"]
    assert named == mine  # one CAS id
    assert named in _ids(client, "/assets", pid) and named in _ids(client, "/assets", DEFAULT_ID)

    pytest.importorskip("vinci_olf")

    def sample(body: dict) -> str:
        return str(client.post("/olf/sample", json=body).json()["path"])

    def shows(project: str) -> list[str]:
        rows = client.get("/olf/shows", params={"project": project}).json()["shows"]
        return [row["path"] for row in rows]

    default, in_project = sample({}), sample({"project_id": pid})
    assert default != in_project and Path(in_project).name == f"tidewatch-{pid[:8]}"
    assert sample({"project_id": pid}) == in_project  # a repeat reopens the project's own copy
    assert str(Path(in_project).resolve()) in shows(pid)
    assert str(Path(default).resolve()) in shows(DEFAULT_ID)
