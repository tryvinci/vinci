"""Large files (COREPRODUC-710): the daemon states its limits and streams uploads to its store."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_runtime.engine import Engine

from ts_module import run_ts


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path / "home")
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_doctor_states_the_file_limits(client: TestClient) -> None:
    pytest.importorskip("vinci_olf")
    from vinci_olf.package import MAX_BYTES

    limits = client.get("/doctor").json()["limits"]
    assert limits == {"upload_bytes": None, "import_bytes": MAX_BYTES}


def test_an_upload_streams_into_the_store(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 12 MB upload never goes through ingest_bytes (which holds the whole file)."""
    def whole(*args: object, **kwargs: object) -> None:
        raise AssertionError("the upload was read whole into memory")

    monkeypatch.setattr(Engine, "ingest_bytes", whole)
    data = bytes(range(256)) * (12 * 4096)  # 12 MiB
    res = client.post("/assets", files={"file": ("clip.mp4", data, "video/mp4")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == hashlib.sha256(data).hexdigest() and body["bytes"] == len(data)
    assert client.get(f"/assets/{body['id']}/file").content == data
    text = client.post("/assets", files={"file": ("note.txt", b"lighthouse keeper", "text/plain")})
    assert text.status_code == 200 and text.json()["kind"] == "text"


def test_a_large_text_upload_is_not_read_whole_for_search(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Search indexes a small text file's words; a large one (or an unknown type) by its name."""
    from vinci_runtime import engine as engine_module

    monkeypatch.setattr(engine_module, "INDEX_TEXT_BYTES", 1024)
    reads: list[str] = []
    store = type(client.app.state.engine.cas)  # type: ignore[attr-defined]
    get = store.get
    monkeypatch.setattr(store, "get", lambda self, digest: reads.append(digest) or get(self, digest))
    small = client.post("/assets", files={"file": ("note.txt", b"lighthouse keeper", "text/plain")})
    big = client.post("/assets", files={"file": ("tide.log", b"x" * 4096, "application/x-log")})
    assert small.status_code == big.status_code == 200
    assert big.json()["kind"] == "text" and reads == [small.json()["id"]]


def test_studio_upload_helper_words() -> None:
    """lib/upload.ts: the limit check before an upload, and an HTML 413 page as a sentence."""
    proc = run_ts(
        "apps/studio/lib/upload.ts",
        ["setUploadLimits", "tooLarge", "sizeText", "errorText", "HOST_REQUEST_BYTES"],
        """
const eq = (a, b, what) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(what + ": " + JSON.stringify(a)); };
eq([sizeText(850e3), sizeText(40e6), sizeText(2e9)], ["850 KB", "40 MB", "2.0 GB"], "sizes");
setUploadLimits(null);
eq(tooLarge("a.mp4", 9e9, "upload"), "", "no limit stated: no check");
setUploadLimits({ upload_bytes: HOST_REQUEST_BYTES, import_bytes: 5e9 });
eq(tooLarge("lamp-oil.volf", 37e6, "upload"), "lamp-oil.volf is 37 MB; this server takes files up to 31 MB.", "over");
eq(tooLarge("lamp-oil.volf", 37e6, "import"), "", "under the import limit");
const html = new Response("<html><title>413 Request Entity Too Large</title></html>", { status: 413 });
eq(await errorText(html), "The file is larger than this server takes.", "proxy 413 page");
eq(await errorText(new Response(JSON.stringify({ detail: "not a .volf package" }), { status: 400 })), "not a .volf package", "detail");
eq(await errorText(new Response("<html>oops</html>", { status: 502, statusText: "Bad Gateway" })), "Bad Gateway", "other HTML");
""",
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
