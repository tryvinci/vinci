"""Ranker for Studio model search. The HTML copy must stay aligned with the TS module."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RANKER = ROOT / "apps" / "studio" / "lib" / "model-search.ts"
STUDIO = ROOT / "apps" / "daemon" / "vinci_daemon" / "studio.html"


def _run_module(body: str) -> subprocess.CompletedProcess[str]:
    """Run assertions against the TS module using the repo TypeScript compiler.

    Node 20 is the OSS CI runtime and cannot import .ts via --experimental-strip-types.
    """
    script = f"""
import ts from "typescript";
import {{ readFileSync }} from "node:fs";
const src = readFileSync("apps/studio/lib/model-search.ts", "utf8");
const js = ts.transpileModule(src, {{
  compilerOptions: {{ module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 }},
}}).outputText;
const mod = await import("data:text/javascript," + encodeURIComponent(js));
const {{ rankModels, modelAvailability, studioVisible }} = mod;
{body}
"""
    return subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_rank_models() -> None:
    script = """
const rows = [
  { id: "fal:flux", display_name: "Flux Dev", provider: "fal" },
  { id: "higgs:soul", display_name: "Soul", provider: "higgsfield" },
  { id: "google:imagen", display_name: "Imagen", provider: "google" },
];
const empty = rankModels(rows, "  ");
if (empty.map((row) => row.id).join() !== "fal:flux,higgs:soul,google:imagen") {
  throw new Error("empty query should keep order");
}
const ranked = rankModels(
  [
    { id: "p", display_name: "Other", provider: "fluxpro" },
    { id: "n", display_name: "Flux Dev", provider: "fal" },
  ],
  "flux",
);
if (ranked[0]?.id !== "n") throw new Error("name prefix should beat a provider hit");
const idOnly = rankModels(
  [{ id: "fal:xyz", display_name: "Portrait", provider: "fal" }],
  "xyz",
);
if (idOnly.length !== 1 || idOnly[0]?.id !== "fal:xyz") throw new Error("id-only hit");
if (rankModels(rows, "zzzz-nope").length !== 0) throw new Error("no match");
"""
    result = _run_module(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_model_availability() -> None:
    script = """
const model = { provider: "openai", available: true };
if (modelAvailability(model, { configured: true }, true) !== "ready") throw new Error("ready");
if (modelAvailability(model, { configured: true }, false) !== "spend_off") throw new Error("spend");
const disabled = { provider: "fal", available: false };
if (modelAvailability(disabled, { configured: true }, true) !== "not_enabled") {
  throw new Error("not enabled");
}
if (modelAvailability(disabled, { configured: false }, false) !== "needs_key") {
  throw new Error("needs key");
}
const mock = { provider: "mock", available: false };
if (modelAvailability(mock, undefined, false) !== "ready") throw new Error("mock");
"""
    result = _run_module(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_html_ranker_matches_ts_source() -> None:
    ts = RANKER.read_text(encoding="utf-8")
    html = STUDIO.read_text(encoding="utf-8")
    assert "function rankModels(rows, query)" in html
    assert "function inheritQueryMatches(query)" in html
    assert "function modelAvailability(model, provider, liveSpend)" in html
    assert "function studioVisible(m)" in html
    assert "studioVisible" in ts
    assert "spend off" in html
    assert "not enabled" in html
    assert "apps/studio/lib/model-search.ts" in html
    for needle in ("display_name", "provider", "inherit skill default"):
        assert needle in ts
        assert needle in html


def test_studio_visible_keeps_demo_mock_models() -> None:
    """Demo mode: /models marks mock practice models available; Studio must keep them."""
    script = """
const demoCatalog = [
  { id: "mock:png:v1", provider: "mock", available: true },
  { id: "mock:mp4:v1", provider: "mock", available: true },
  { id: "wavespeed:kling-2.6-pro:2026-08", provider: "wavespeed", available: false },
  { id: "fal:flux-dev:2026-01", provider: "fal", available: true },
];
const visible = demoCatalog.filter(studioVisible).map((m) => m.id);
if (visible.length !== 4) throw new Error("demo mode lost mock models: " + visible.join());
if (visible[0] !== "mock:png:v1") throw new Error("mock models stay first in demo");
const normalCatalog = [
  { id: "mock:png:v1", provider: "mock", available: false },
  { id: "fal:flux-dev:2026-01", provider: "fal", available: true },
];
const normalVisible = normalCatalog.filter(studioVisible).map((m) => m.id);
if (normalVisible.length !== 1 || normalVisible[0] !== "fal:flux-dev:2026-01") {
  throw new Error("non-demo mode should still hide unavailable mock models");
}
"""
    result = _run_module(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_studio_filter_sites_use_studio_visible() -> None:
    """Both Studio UIs must route catalog filtering through studioVisible."""
    ts = RANKER.read_text(encoding="utf-8")
    html = STUDIO.read_text(encoding="utf-8")
    client = (ROOT / "apps" / "studio" / "app" / "studio-client.tsx").read_text(encoding="utf-8")
    assert "export function studioVisible" in ts
    assert html.count(".filter(studioVisible)") == 1
    assert client.count(".filter(studioVisible)") == 2
    assert client.count(".find(studioVisible)") == 1
    assert 'provider !== "mock")' not in html
    assert 'provider !== "mock")' not in client
