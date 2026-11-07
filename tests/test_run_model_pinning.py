"""A run keeps the models it was approved with, even if the mode changes mid-run (COREPRODUC-531).

Model choice for an unpinned node used to happen when the node ran, from the then-current
provider config. A run approved in demo mode (mock, $0) could send its later nodes to a paid
provider after `init_home(demo=False)`. Offline: the network is blocked and the key is fake.
"""

from __future__ import annotations

import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import vinci_runtime.engine as engine_mod
from vinci_protocol.enums import JobState
from vinci_runtime.engine import Engine, all_secret_names


def _demo_engine(monkeypatch: pytest.MonkeyPatch, home: Path) -> Engine:
    monkeypatch.setenv("VINCI_HOME", str(home))
    for name in all_secret_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WAVESPEED_API_KEY", "fake-wavespeed-key")  # a live provider is ready
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    engine = Engine(home)
    engine.init_home(demo=True)
    return engine


def _block_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []

    def blocked(request: Any, timeout: int = 30) -> Any:
        urls.append(getattr(request, "full_url", str(request)))
        raise RuntimeError("network blocked in test")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    return urls


def _spy_resolve(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None, str | None]]:
    """Record (node capability, pinned model_id, chosen model) for each node as it runs."""
    seen: list[tuple[str, str | None, str | None]] = []
    real = engine_mod.resolve_model

    def spy(catalog: Any, req: Any, **kwargs: Any) -> Any:
        row: tuple[str, str | None, str | None] = (req.capability.value, req.model_id, None)
        seen.append(row)
        spec = real(catalog, req, **kwargs)
        seen[-1] = (row[0], row[1], spec.id)
        return spec

    monkeypatch.setattr(engine_mod, "resolve_model", spy)
    return seen


def _run_with_mode_flip(engine: Engine, run_id: str) -> Exception | None:
    """Dispatch the run, then turn demo off once the first node is done."""
    failure: list[Exception] = []

    def work() -> None:
        try:
            engine.dispatch_run(run_id)
        except Exception as exc:  # noqa: BLE001 - the run records it; the test reads it
            failure.append(exc)

    thread = threading.Thread(target=work)
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        done = [
            job
            for job in engine.store.list_jobs()
            if job.workflow_run_id == run_id and job.state == JobState.COMPLETED
        ]
        if done:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("first node never finished")
    engine.init_home(demo=False)  # what Studio's boot or a key connect does
    thread.join(timeout=30)
    assert not thread.is_alive()
    return failure[0] if failure else None


def test_mode_change_mid_run_keeps_the_approved_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _demo_engine(monkeypatch, tmp_path)
    monkeypatch.setenv("VINCI_TEST_SLEEP_AFTER_NODE_MS", "1500")
    monkeypatch.setenv("VINCI_TEST_SLEEP_AFTER_NODE_INDEX", "0")
    urls = _block_network(monkeypatch)
    run = engine.accept_run("@tryvinci/soul-character", {"prompt": "a character"})
    planned = {row["node_id"]: row["model_id"] for row in run["estimate"]["nodes"]}
    assert run["estimate"]["total"] == 0
    assert set(planned.values()) == {"mock:png:v1"}, planned  # approved: mock, $0
    seen = _spy_resolve(monkeypatch)

    failure = _run_with_mode_flip(engine, run["id"])

    stored = engine.store.get_run(run["id"]) or {}
    chosen = [model for _cap, _pinned, model in seen if model]
    # The second node must not move to a paid provider.
    assert set(chosen) <= {"mock:png:v1"}, f"re-routed to {chosen}"
    assert not urls, f"paid provider called: {urls}"
    # Mock is off now, so the second node fails closed with a message that names the model.
    assert stored.get("state") == JobState.FAILED.value
    assert "mock:png:v1 is not in the catalog now" in stored["error"]["message"]
    assert isinstance(failure, RuntimeError)


def test_accepted_run_stores_the_planned_model_of_every_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _demo_engine(monkeypatch, tmp_path)
    run = engine.accept_run("@tryvinci/soul-character", {"prompt": "a character"})
    pinned = {n["id"]: n.get("model_id") for n in run["workflow"]["nodes"]}
    planned = {row["node_id"]: row["model_id"] for row in run["estimate"]["nodes"]}
    assert planned and pinned == planned


def test_user_pinned_model_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _demo_engine(monkeypatch, tmp_path)
    run = engine.accept_run(
        "@tryvinci/soul-character", {"prompt": "a character"}, model_id="mock:png:v1"
    )
    assert {n.get("model_id") for n in run["workflow"]["nodes"]} == {"mock:png:v1"}
