"""The generation progress bar (COREPRODUC-659): a fake countdown to 90% over the model's average run."""

from __future__ import annotations

from pathlib import Path

import pytest
from vinci_runtime.engine import Engine, all_secret_names

from ts_module import run_ts

MODULE = "apps/studio/lib/progress.ts"
NAMES = ["CAP", "averageSeconds", "fakeProgress", "modelKind", "progressLabel", "runModel"]


def test_average_is_the_models_own_finished_runs_else_a_default_by_kind() -> None:
    body = """
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
const run = (model, secs, extra = {}) => ({ state: "completed", inputs: { model_id: model },
  created_at: "2026-11-16T10:00:00Z", completed_at: new Date(Date.parse("2026-11-16T10:00:00Z") + secs * 1000).toISOString(), ...extra });
const runs = [run("kling", 100), run("kling", 140), run("seedream", 12),
  run("kling", 999, { state: "failed" }),                                   // failed runs do not count
  run("kling", 0.2),                                                         // under a second: a lost clock
  { state: "completed", workflow: { nodes: [{ model_id: "kling" }] }, started_at: "2026-11-16T10:00:00Z", completed_at: "2026-11-16T10:02:00Z", created_at: "2026-11-16T09:00:00Z" }];
eq(averageSeconds(runs, "kling", "video"), 120, "mean of 100, 140 and 120 (started_at beats created_at)");
eq(averageSeconds(runs, "seedream", "image"), 12, "own model only");
eq(averageSeconds(runs, "veo", "video"), 120, "no history: video default");
eq(averageSeconds([], "x", "image"), 20, "image default");
eq(averageSeconds([], "x", "audio"), 30, "audio default");
eq(runModel({ workflow: { nodes: [{ model_id: "a" }, { model_id: "b" }] } }), "", "two models: no single model");
eq(modelKind(["t2v", "i2v"]), "video", "t2v");
eq(modelKind(["t2i", "i2i"]), "image", "t2i");
eq(modelKind(["tts"]), "audio", "tts");
"""
    run_ts(MODULE, NAMES, body)


def test_the_bar_counts_down_to_90_percent_then_waits() -> None:
    body = """
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
eq(fakeProgress(0, 20), { pct: 0, left: 20 }, "start");
eq(fakeProgress(10000, 20), { pct: 45, left: 10 }, "half the average: 45%");
eq(fakeProgress(20000, 20), { pct: CAP, left: 0 }, "the average: 90%");
eq(fakeProgress(600000, 20), { pct: 90, left: 0 }, "long after: still 90%, never 100");
eq(progressLabel(12), "About 12s left", "seconds");
eq(progressLabel(125), "About 2m 05s left", "minutes");
eq(progressLabel(0), "Almost done…", "at 90%");
"""
    run_ts(MODULE, NAMES, body)


def test_a_daemon_run_records_when_it_started_and_ended(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    for name in all_secret_names():
        monkeypatch.delenv(name, raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    run = engine.accept_run("@tryvinci/image-generate", {"prompt": "a kettle"})
    if run["state"] != "completed":
        run = engine.dispatch_run(run["id"])
    stored = engine.store.get_run(run["id"])
    assert stored["state"] == "completed"
    assert stored["started_at"] <= stored["completed_at"]
