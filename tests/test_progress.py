"""The generation progress bar (COREPRODUC-659): a fake countdown to 90% over the model's average run."""

from __future__ import annotations

from pathlib import Path

import pytest
from vinci_runtime.engine import Engine, all_secret_names

from ts_module import run_ts

MODULE = "apps/studio/lib/progress.ts"
NAMES = ["CAP", "averageSeconds", "defaultSeconds", "fakeProgress", "modelKind", "progressLabel", "runModel"]


def test_average_is_the_models_own_finished_runs_else_a_default_by_kind() -> None:
    body = """
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
const run = (model, secs, extra = {}) => ({ state: "completed", inputs: { model_id: model },
  created_at: "2026-11-16T10:00:00Z", completed_at: new Date(Date.parse("2026-11-16T10:00:00Z") + secs * 1000).toISOString(), ...extra });
const runs = [run("kling", 100), run("kling", 140), run("seedream", 12),
  run("kling", 999, { state: "failed" }),                                   // failed runs do not count
  run("kling", 0.2),                                                         // under a second: a lost clock
  { state: "completed", workflow: { nodes: [{ model_id: "kling" }] }, started_at: "2026-11-16T10:00:00Z", completed_at: "2026-11-16T10:02:00Z", created_at: "2026-11-16T09:00:00Z" }];
eq(averageSeconds(runs, "kling", "video"), 120, "median of 100, 140 and 120 (started_at beats created_at)");
eq(averageSeconds(runs, "seedream", "image"), 12, "own model only");
eq(averageSeconds(runs, "veo", "video"), 120, "no history: video default");
eq(averageSeconds([], "x", "image"), 20, "image default");
eq(averageSeconds([], "x", "audio"), 30, "audio default");
eq(runModel({ workflow: { nodes: [{ model_id: "a" }, { model_id: "b" }] } }), "", "two models: no single model");
eq(modelKind(["t2v", "i2v"]), "video", "t2v");
eq(modelKind(["t2i", "i2i"]), "image", "t2i");
eq(modelKind(["tts"]), "audio", "tts");
"""
    result = run_ts(MODULE, NAMES, body)
    assert result.returncode == 0, result.stderr  # run_ts does not check: a thrown assertion fails here


def test_the_median_ignores_one_slow_run_and_a_sign_in_provider_starts_slower() -> None:
    """COREPRODUC-687: the median, not the mean; defaults by provider for image and video."""
    body = """
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
const run = (model, secs) => ({ state: "completed", inputs: { model_id: model },
  created_at: "2026-11-18T10:00:00Z", completed_at: new Date(Date.parse("2026-11-18T10:00:00Z") + secs * 1000).toISOString() });
const classic = "mcp_magnific:classic";
eq(averageSeconds([run(classic, 28), run(classic, 330), run(classic, 44)], classic), 44, "one 5.5 min run: median 44, not mean 134");
eq(averageSeconds([run(classic, 28), run(classic, 44), run(classic, 330), run(classic, 36)], classic), 40, "even count: middle two");
eq(defaultSeconds("bytedance/seedream-v4.5", "image"), 20, "Wavespeed (hosted) image");
eq(defaultSeconds("wavespeed:flux-dev", "image"), 20, "Wavespeed image");
eq(defaultSeconds("mcp_magnific:mystic", "image"), 60, "Magnific image");
eq(defaultSeconds("mcp_higgsfield:soul_cinema_studio", "image"), 60, "Higgsfield image (hosted row id)");
eq(defaultSeconds("higgsfield:soul-standard:2026-09", "image"), 60, "Higgsfield image (plugin id)");
eq(defaultSeconds("mcp_magnific:kling-30", "video"), 600, "Magnific video (kling-30 took 634 s)");
eq(defaultSeconds("kwaivgi/kling-v2.6-pro", "video"), 120, "other video");
eq(defaultSeconds("mcp_higgsfield:x", "audio"), 30, "sign-in audio: kind default");
eq(averageSeconds([], "mcp_magnific:mystic", "image"), 60, "no history: provider default");
"""
    result = run_ts(MODULE, NAMES, body)
    assert result.returncode == 0, result.stderr  # run_ts does not check: a thrown assertion fails here


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
    result = run_ts(MODULE, NAMES, body)
    assert result.returncode == 0, result.stderr  # run_ts does not check: a thrown assertion fails here


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
