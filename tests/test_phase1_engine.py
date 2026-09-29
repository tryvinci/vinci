from __future__ import annotations

import json
from pathlib import Path

import pytest
from vinci_core.catalog import load_bundled_catalog, reject_sunset_defaults
from vinci_protocol.enums import Capability, NodeType
from vinci_protocol.models import JobRequest, WorkflowEdge, WorkflowNode, WorkflowSpec
from vinci_provider_cloudflare import CloudflareProvider
from vinci_provider_elevenlabs import ElevenLabsProvider
from vinci_provider_fal import FalProvider
from vinci_provider_google import GoogleProvider
from vinci_provider_higgsfield import HiggsfieldProvider
from vinci_provider_magnific import MagnificProvider
from vinci_provider_openai import OpenAIProvider
from vinci_provider_sdk.catalog_provider import LiveSpendDisabled
from vinci_provider_sdk.mock import mp4_dimensions
from vinci_provider_wavespeed import WavespeedProvider
from vinci_runtime.engine import Engine
from vinci_skills import SkillLoader


def test_bundled_catalogs_exclude_sora() -> None:
    for name in (
        "mock",
        "wavespeed",
        "google",
        "openai",
        "fal",
        "elevenlabs",
        "cloudflare",
        "higgsfield",
        "magnific",
    ):
        catalog = load_bundled_catalog(name)
        assert catalog.models
        for model in catalog.models:
            reject_sunset_defaults(model.id)


def test_plugins_estimate_without_keys_and_refuse_live_spend() -> None:
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "offline"})
    tts = JobRequest(capability=Capability.TTS, inputs={"prompt": "hello"})
    for provider in (WavespeedProvider(), GoogleProvider(), OpenAIProvider(), FalProvider()):
        if Capability.T2I not in provider.capabilities():
            continue
        provider.estimate(req)
        with pytest.raises(PermissionError):
            provider.submit(req)
    labs = ElevenLabsProvider()
    labs.estimate(tts)
    with pytest.raises(PermissionError):
        labs.submit(tts)
    cf = CloudflareProvider()
    cf.estimate(req)
    with pytest.raises(PermissionError):
        cf.submit(req)
    live_cf = CloudflareProvider(api_key="sk-never-spend", account_id="acct")
    live_cf.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        live_cf.submit(req)
    live = WavespeedProvider(api_key="sk-never-spend")
    live.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        live.submit(req)
    hf = HiggsfieldProvider()
    hf.estimate(req)
    with pytest.raises(PermissionError):
        hf.submit(req)
    hf_live = HiggsfieldProvider(api_key="sk-never-spend", api_secret="sk-secret-never-spend")
    hf_live.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        hf_live.submit(req)
    mag = MagnificProvider()
    mag.estimate(req)
    with pytest.raises(PermissionError):
        mag.submit(req)
    mag_live = MagnificProvider(api_key="sk-never-spend")
    mag_live.estimate(req)
    with pytest.raises(LiveSpendDisabled):
        mag_live.submit(req)


def test_skills_load_and_search() -> None:
    loader = SkillLoader()
    skills = {s.id: s for s in loader.list_skills()}
    assert "@tryvinci/image-generate" in skills
    assert "@tryvinci/video-generate" in skills
    assert "@tryvinci/product-reveal-5s" in skills
    assert "@tryvinci/podcast-to-shorts" in skills
    assert "@tryvinci/cinema-still" in skills
    assert "@tryvinci/still-to-upscale" in skills
    assert "@tryvinci/still-to-talk" in skills
    assert "@tryvinci/cinema-sequence" in skills
    assert "@tryvinci/first-last-frame" in skills
    assert "@tryvinci/soul-character" in skills
    hits = loader.search("podcast")
    assert any(s.id.endswith("podcast-to-shorts") for s in hits)
    product = loader.search("product reveal")
    assert any(s.id.endswith("product-reveal-5s") for s in product)
    inspect = loader.inspect("@tryvinci/image-generate")
    assert inspect["permissions"] == []
    assert inspect["est_cost"]["max"] >= 0


def test_demo_image_generate_receipt_and_cas_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("MOCK_API_KEY", "supersecret-demo-key")
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    first = engine.start_run(
        "@tryvinci/image-generate", {"prompt": "a red cube supersecret-demo-key"}
    )
    assert first["state"] == "completed"
    assert first["outputs"]
    assert first["asset_uris"] == [f"vinci://assets/{first['outputs'][0]}"]
    assert first["job_uris"] == [f"vinci://jobs/{first['job_ids'][0]}"]
    assert first["receipt_uris"] == [f"vinci://receipts/{first['job_ids'][0]}"]
    assert first["estimate"]["total"] == 0
    dumped = json.dumps(first)
    assert "supersecret-demo-key" not in dumped
    job = engine.store.get_job(first["job_ids"][0])
    assert job is not None
    assert job.receipt is not None
    assert job.receipt.computed_cost == 0
    second = engine.start_run(
        "@tryvinci/image-generate", {"prompt": "a red cube supersecret-demo-key"}
    )
    replay = engine.store.get_job(second["job_ids"][0])
    assert replay is not None
    assert replay.receipt is not None
    assert replay.receipt.cached is True
    assert replay.receipt.computed_cost == 0
    assert replay.outputs == first["outputs"]
    doc = engine.doctor()
    assert doc["ffmpeg"] is True
    assert doc["ok"] is True
    assert doc["demo"] is True


def test_start_run_honors_model_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    run = engine.start_run(
        "@tryvinci/image-generate",
        {"prompt": "honor model"},
        model_id="mock:png:v1",
    )
    job = engine.store.get_job(run["job_ids"][0])
    assert job is not None
    assert job.model_id == "mock:png:v1"


def test_image_generate_lighting_changes_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    plain = engine.start_run("@tryvinci/image-generate", {"prompt": "oak lighting digest"})
    neon = engine.start_run(
        "@tryvinci/image-generate",
        {"prompt": "oak lighting digest", "lighting": "neon"},
    )
    available = engine.start_run(
        "@tryvinci/image-generate",
        {"prompt": "oak lighting digest", "lighting": "available"},
    )
    assert plain["state"] == "completed"
    assert neon["state"] == "completed"
    assert available["state"] == "completed"
    assert plain["estimate"]["total"] == 0
    assert neon["estimate"]["total"] == 0
    assert plain["outputs"][0] != neon["outputs"][0]
    assert available["outputs"][0] == plain["outputs"][0]


def test_workflow_preserves_per_node_model_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    spec = WorkflowSpec(
        id="mixed-models",
        version="1.0.0",
        nodes=[
            WorkflowNode(
                id="still",
                type=NodeType.GENERATE,
                capability=Capability.T2I,
                model_id="mock:png:v1",
                params={"prompt": "{{inputs.prompt}}"},
            ),
            WorkflowNode(
                id="clip",
                type=NodeType.GENERATE,
                capability=Capability.T2V,
                model_id="mock:mp4:v1",
                params={"prompt": "{{inputs.prompt}}", "duration": 2},
            ),
        ],
        edges=[WorkflowEdge(src="still", dst="clip")],
    )
    run = engine.start_run(
        None,
        {"prompt": "oak mixed models"},
        workflow=spec,
        model_id="mock:png:v1",
    )
    assert run["state"] == "completed"
    still_job = engine.store.get_job(run["nodes"]["still"]["job_id"])
    clip_job = engine.store.get_job(run["nodes"]["clip"]["job_id"])
    assert still_job is not None and still_job.model_id == "mock:png:v1"
    assert clip_job is not None and clip_job.model_id == "mock:mp4:v1"


def test_product_reveal_and_video_generate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    video = engine.start_run("@tryvinci/video-generate", {"prompt": "waves on a beach"})
    assert video["state"] == "completed"
    digest = video["outputs"][0]
    blob = engine.cas.get(digest)
    assert blob[4:8] == b"ftyp"
    assert mp4_dimensions(blob) == (960, 540)
    reveal = engine.start_run("@tryvinci/product-reveal-5s", {"prompt": "a glass bottle of serum"})
    assert reveal["state"] == "completed"
    assert len(reveal["job_ids"]) == 2


def test_catalog_refresh_writes_lockfile_diff_not_bundled_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    import vinci_core

    catalogs = Path(vinci_core.__file__).resolve().parent / "catalogs"
    before = {path.name: path.read_bytes() for path in catalogs.glob("*.json")}
    engine = Engine(tmp_path)
    first = engine.catalog_refresh()
    assert first["path"] == str(tmp_path / "catalog.lock.json")
    assert first["changed"] is True
    assert "+++ catalog.lock.json" in first["diff"]
    assert (tmp_path / "catalog.lock.json").is_file()
    second = engine.catalog_refresh()
    assert second["changed"] is False
    assert second["diff"] == ""
    after = {path.name: path.read_bytes() for path in catalogs.glob("*.json")}
    assert after == before


def test_awaiting_approval_then_approve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    engine.config.budget.require_approval_over = -0.01
    parked = engine.start_run("@tryvinci/image-generate", {"prompt": "park me"})
    assert parked["state"] == "awaiting_approval"
    approved = engine.approve_run(parked["id"])
    assert approved["state"] == "completed"


def test_max_cost_gate_with_priced_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=False)
    engine.add_provider("wavespeed", from_env="WAVESPEED_API_KEY")
    monkeypatch.setenv("WAVESPEED_API_KEY", "not-a-real-key")
    engine = Engine(tmp_path)
    parked = engine.start_run("@tryvinci/image-generate", {"prompt": "seedream"}, max_cost=0.001)
    assert parked["state"] == "awaiting_approval"
    assert parked["estimate"]["total"] > 0.001


def test_add_provider_file_secret_never_hits_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    added = engine.add_provider("wavespeed", secret="file-stored-provider-key")
    assert added["id"] == "wavespeed"
    assert added["ref"] in {"file", "keychain"}
    assert "file-stored-provider-key" not in str(added)
    run = engine.start_run("@tryvinci/image-generate", {"prompt": "file-stored-provider-key cube"})
    assert run["state"] == "completed"
    blob = json.dumps(run, default=str)
    assert "file-stored-provider-key" not in blob
    receipt = engine.store.get_receipt(run["job_ids"][0])
    assert receipt is not None
    dumped_receipt = json.dumps(receipt.model_dump(mode="json"), default=str)
    assert "file-stored-provider-key" not in dumped_receipt
    if added["ref"] == "file":
        key_path = tmp_path / "keys" / "WAVESPEED_API_KEY"
        assert key_path.is_file()
        assert key_path.stat().st_mode & 0o777 == 0o600
        assert "file-stored-provider-key" not in (tmp_path / "config.toml").read_text()


def test_update_settings_preference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    updated = engine.update_settings(preference="quality", monthly_cap_usd=12.5)
    assert updated["preference"] == "quality"
    assert updated["budget"]["monthly_cap_usd"] == 12.5
    assert engine.doctor()["preference"] == "quality"
