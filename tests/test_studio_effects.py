"""Studio Effects shell: catalog helpers, wiring, and /runs payloads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_provider_sdk.mock import PNG_SWATCH
from vinci_runtime.engine import Engine

from ts_module import ROOT, run_ts

CATALOG = "apps/studio/lib/apps-catalog.ts"
CATALOG_NAMES = [
    "STUDIO_APPS",
    "APP_CATEGORIES",
    "EFFECT_PAGE_DEFAULTS",
    "getApp",
    "appDefaults",
    "filterApps",
    "fillPrompt",
    "missingAppInputs",
    "buildRunPayload",
    "resolveAppModel",
    "appModelChoices",
    "defaultAppIdForPage",
    "filterEffectHistory",
    "historyOutputIds",
    "applyEffectParams",
    "generateButtonLabel",
    "effectiveAspect",
]
SHELL = "apps/studio/lib/apps-catalog.ts"
STUDIO_CLIENT = ROOT / "apps" / "studio" / "app" / "studio-client.tsx"


def _check(module: str, names: list[str], body: str) -> None:
    result = run_ts(module, names, body)
    assert result.returncode == 0, result.stderr or result.stdout


def _catalog_rows() -> list[dict[str, object]]:
    result = run_ts(
        CATALOG,
        CATALOG_NAMES,
        """
const rows = STUDIO_APPS.map((app) => ({
  id: app.id,
  skill: app.skill,
  provider: app.provider,
  model: app.preferred_model_id,
  pin: app.pin_model !== false,
}));
console.log(JSON.stringify(rows));
""",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_catalog_has_starter_apps_and_unique_ids() -> None:
    _check(
        CATALOG,
        CATALOG_NAMES,
        """
if (STUDIO_APPS.length < 6) throw new Error("need a handful of starter apps");
const ids = STUDIO_APPS.map((app) => app.id);
if (new Set(ids).size !== ids.length) throw new Error("duplicate app id");
if (!getApp("product-hero")) throw new Error("product-hero missing");
if (getApp("nope")) throw new Error("unknown id should be undefined");
if (defaultAppIdForPage("upscale") !== "still-4k") throw new Error("upscale default");
if (defaultAppIdForPage("speak") !== "talking-photo") throw new Error("speak default");
""",
    )


def test_filter_and_search() -> None:
    _check(
        CATALOG,
        CATALOG_NAMES,
        """
const image = filterApps(STUDIO_APPS, "image", "");
if (!image.length || image.some((app) => app.category !== "image")) {
  throw new Error("image category leaked");
}
const hit = filterApps(STUDIO_APPS, "all", "voiceover");
if (hit.length !== 1 || hit[0].id !== "voiceover") throw new Error("search name");
""",
    )


def test_effect_history_filters_by_skill() -> None:
    _check(
        CATALOG,
        CATALOG_NAMES,
        """
const app = getApp("still-4k");
if (!app) throw new Error("app");
const rows = filterEffectHistory([
  { id: "a", state: "completed", skill: app.skill, outputs: ["x"] },
  { id: "b", state: "completed", skill: "@tryvinci/other", outputs: ["y"] },
], app);
if (rows.length !== 1 || rows[0].id !== "a") throw new Error("filter");
const ids = historyOutputIds(rows);
if (ids.join(",") !== "x") throw new Error("outputs");
""",
    )


def test_build_run_payload_and_apply_params() -> None:
    _check(
        CATALOG,
        CATALOG_NAMES,
        """
const app = getApp("product-hero");
const payload = buildRunPayload(app, { product: "oak cube", surface: "honed slate" });
if (!String(payload.inputs.prompt).includes("oak cube")) throw new Error("prompt");
const up = getApp("still-4k");
const base = buildRunPayload(up, { still: "asset-1" });
const merged = applyEffectParams(base.inputs, up, "16:9", "4K");
if (merged.aspect_ratio !== "16:9") throw new Error("aspect");
if (merged.resolution !== "4k") throw new Error("resolution");
const label = generateButtonLabel(up, [], false, (n) => `$${n ?? 0}`);
if (!label.startsWith("Generate ·")) throw new Error(label);
""",
    )


def test_effect_model_list_uses_the_registry() -> None:
    """Compatible connected models, preset first. Mock hides when a key exists."""
    _check(
        CATALOG,
        CATALOG_NAMES,
        """
const app = getApp("product-hero");
const models = [
  { id: app.preferred_model_id, provider: "openai", available: true, capabilities: ["t2i"], display_name: "Preset" },
  { id: "mock:png:v1", provider: "mock", available: true, capabilities: ["t2i", "i2i"], display_name: "Mock PNG" },
  { id: "mock:mp4:v1", provider: "mock", capabilities: ["t2v"], display_name: "Mock MP4" },
];
const both = appModelChoices(app, models, ["openai", "mock"]).map((row) => row.id);
if (both[0] !== app.preferred_model_id) throw new Error("preset should lead: " + both);
if (both.includes("mock:png:v1") || both.includes("mock:mp4:v1")) throw new Error("mock hidden: " + both);
if (resolveAppModel(app, models, true, ["openai", "mock"]) !== app.preferred_model_id) {
  throw new Error("live spend pins the preset");
}
if (resolveAppModel(app, models, false, ["openai", "mock"])) {
  throw new Error("spend off should not pin an unusable preset");
}
const demo = appModelChoices(app, models, ["mock"]).map((row) => row.id);
if (demo.join() !== "mock:png:v1") throw new Error("demo list: " + demo);
if (resolveAppModel(app, models, false, ["mock"]) !== "mock:png:v1") throw new Error("demo pins mock");
""",
    )


def test_studio_client_wires_effect_shell_not_apps_rail() -> None:
    text = STUDIO_CLIENT.read_text()
    assert '| "apps"' not in text
    assert "<EffectShell" in text
    assert "<AppsPage" not in text


def test_starter_apps_reference_real_skills_and_models() -> None:
    rows = _catalog_rows()
    assert len(rows) >= 6
    skills_root = ROOT / "skills"
    catalogs = ""
    for path in (ROOT / "packages" / "core" / "vinci_core" / "catalogs").glob("*.json"):
        catalogs += path.read_text()
    for row in rows:
        slug = str(row["skill"]).removeprefix("@tryvinci/")
        assert (skills_root / slug / "vinci.yaml").is_file(), row["skill"]
        assert str(row["model"]) in catalogs, row["model"]
        assert str(row["provider"]) in str(row["model"])


def test_product_hero_payload_runs_on_mock(client: TestClient) -> None:
    result = run_ts(
        CATALOG,
        CATALOG_NAMES,
        """
const app = getApp("product-hero");
const payload = buildRunPayload(app, { product: "oak cube", surface: "honed slate" });
console.log(JSON.stringify(payload));
""",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    res = client.post("/runs", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "completed"
    assert body["outputs"]


def test_still_4k_payload_runs_on_mock(client: TestClient) -> None:
    upload = client.post("/assets", files={"file": ("face.png", PNG_SWATCH, "image/png")})
    assert upload.status_code == 200
    asset_id = upload.json()["id"]
    result = run_ts(
        CATALOG,
        CATALOG_NAMES,
        f"""
const app = getApp("still-4k");
const payload = buildRunPayload(app, {{ still: {asset_id!r} }});
console.log(JSON.stringify(payload));
""",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["inputs"]["media"] == asset_id
    res = client.post("/runs", json=payload)
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "completed"
