from __future__ import annotations

import json
from datetime import UTC, datetime
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
from vinci_runtime.engine import Engine, all_secret_names
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
    # A seed joins the job inputs: a batch's runs are new jobs, and one seed again is a cache hit.
    seeded = [
        engine.start_run("@tryvinci/image-generate", {"prompt": "a red cube", "seed": seed})
        for seed in (7, 8, 7)
    ]
    jobs = [engine.store.get_job(run["job_ids"][0]) for run in seeded]
    assert [job.inputs.get("seed") for job in jobs if job] == [7, 8, 7]
    keys = [job.idempotency_key for job in jobs if job]
    assert keys[0] != keys[1] and keys[0] == keys[2] and job.idempotency_key not in keys
    # In demo mode too: each seed of a batch is its own picture.
    assert seeded[0]["outputs"] != seeded[1]["outputs"] and seeded[0]["outputs"] == seeded[2]["outputs"]
    assert jobs[2] is not None and jobs[2].receipt is not None and jobs[2].receipt.cached is True
    doc = engine.doctor()
    assert doc["ffmpeg"] is True
    assert doc["ok"] is True
    assert doc["demo"] is True


def test_a_clip_is_priced_by_its_length() -> None:
    """A row with clip_prices prices the clip the model makes, in the plan from a node's duration
    or an {{inputs.duration}} template; a row's amount is its default clip (COREPRODUC-555)."""
    from vinci_core.cost import clip_price, fit_duration, plan_workflow

    wavespeed = load_bundled_catalog("wavespeed")
    kling = wavespeed.by_id("wavespeed:kling-2.6-pro:2026-08")
    assert [clip_price(kling, s) for s in (None, 5, 10, 7, 30)] == [0.35, 0.35, 0.7, 0.7, 0.7]
    node = {"id": "v", "type": "generate", "capability": "t2v", "model_id": kling.id,
            "params": {"prompt": "x", "duration": "{{inputs.duration}}"}}
    spec = WorkflowSpec.model_validate({"id": "t", "version": "0.1.0", "nodes": [node], "edges": []})
    assert plan_workflow(wavespeed, spec, inputs={"duration": 10})[0]["estimate"].amount == 0.7
    assert plan_workflow(wavespeed, spec)[0]["estimate"].amount == 0.35  # no length: default clip
    alternative = plan_workflow(wavespeed, spec, inputs={"duration": 10})[0]["estimate"].alternative
    assert alternative == {"model_id": "wavespeed:hailuo-2.3-t2v:2026-09", "provider": "wavespeed",
                           "amount": 0.56, "currency": "USD"}  # the cheaper model at 10 s too
    for name in ("wavespeed", "fal", "google", "higgsfield", "magnific"):
        for row in load_bundled_catalog(name).models:
            table = row.pricing.clip_prices
            if table:  # a price for every length the row takes; amount is its default clip's
                listed = {str(fit_duration(d, row.constraints)) for d in row.constraints.durations}
                assert listed <= set(table), row.id
                assert row.pricing.amount in table.values(), row.id  # fal Veo's default is 8 s


def test_speech_and_music_are_priced_by_their_measure() -> None:
    """Speech is billed per character and music and sound effects per second, not per job
    (COREPRODUC-603): the plan and the job estimate price the text and the length."""
    from vinci_core.cost import asked_chars, clip_price, plan_workflow

    eleven = load_bundled_catalog("elevenlabs")
    speech = eleven.by_id("elevenlabs:multilingual-v2:2026-08")  # $0.08 per 1,000 characters
    assert [clip_price(speech, chars=n) for n in (None, 500, 2000)] == [0.08, 0.04, 0.16]
    assert asked_chars({"text": "Say {{inputs.line}}"}, {"line": "hi"}) == 6
    assert asked_chars({"prompt": "{{nodes.script.text}}"}) is None  # not known yet: 1,000
    music = eleven.by_id("elevenlabs:music-v1:2026-11")  # $0.15 a minute, at most 60 s
    assert [clip_price(music, s) for s in (None, 30, 90)] == [0.15, 0.075, 0.15]
    sfx = eleven.by_id("elevenlabs:sound-effects-v2:2026-11")  # $0.06 for its 30 s maximum
    assert round(clip_price(sfx, 10), 4) == 0.02
    node = {"id": "say", "type": "generate", "capability": "tts", "model_id": speech.id,
            "params": {"prompt": "{{inputs.line}}"}}
    spec = WorkflowSpec.model_validate({"id": "t", "version": "0.1.0", "nodes": [node], "edges": []})
    assert plan_workflow(eleven, spec, inputs={"line": "x" * 250})[0]["estimate"].amount == 0.02
    req = JobRequest(capability=Capability.TTS, model_id=speech.id, inputs={"prompt": "x" * 1500})
    assert round(ElevenLabsProvider(api_key="k").estimate(req).amount, 4) == 0.12


def test_a_long_prompt_is_text_not_a_file_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run input of more than 255 characters is text: the check for a local file raised
    ENAMETOOLONG for it, and POST /runs failed with HTTP 400 (COREPRODUC-605)."""
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "dummy-not-a-key")  # lists the rows; nothing is sent
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=False)
    line = "Tonight, the shop stays open late. " * 10  # 350 characters, no slash
    run = engine.start_run(
        "@tryvinci/tts", {"prompt": line}, max_cost=0.0001, model_id="elevenlabs:flash-v2.5:2026-08"
    )
    assert run["state"] == "awaiting_approval"
    assert run["estimate"]["total"] == 0.014  # $0.04 per 1,000 characters (COREPRODUC-603)


def test_estimate_skill_uses_the_skills_input_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The preview prices a {{inputs.duration}} from the skill's default, as accept_run does
    (CodeRabbit on #549, COREPRODUC-555)."""
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("WAVESPEED_API_KEY", "dummy-not-a-key")  # lists the rows; nothing is sent
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=False)
    skill = engine.skills.get("@tryvinci/product-reveal-5s")  # a fresh copy on each get()
    skill.manifest["inputs"]["duration"]["default"] = 10
    monkeypatch.setattr(engine.skills, "get", lambda ref: skill)
    # "quality" routes the video node to Seedance 2.0 i2v: $2.40 for 10 s, $1.20 for its 5 s.
    est = engine.estimate_skill("@tryvinci/product-reveal-5s", {"prompt": "x"}, preference="quality")
    assert {n["model_id"]: n["amount"] for n in est["nodes"]}["wavespeed:seedance-2.0-i2v:2026-09"] == 2.4


def test_cache_hit_needs_the_rows_current_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result made under an older catalog row (another price, or another request from the
    plugin) is not reused; the job made again is (COREPRODUC-596)."""
    counter = tmp_path / "mock-submits.txt"  # the mock provider counts each submit here
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("VINCI_TEST_MOCK_SUBMIT_COUNTER_PATH", str(counter))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    ask = {"prompt": "a blue cone"}

    def submits() -> int:
        return int(counter.read_text(encoding="utf-8") or 0) if counter.exists() else 0

    first = engine.store.get_job(engine.start_run("@tryvinci/image-generate", ask)["job_ids"][0])
    assert first is not None and first.receipt is not None and submits() == 1
    old = first.receipt.model_copy(update={"pricing_snapshot_at": datetime(2020, 1, 1, tzinfo=UTC)})
    engine.store.put_job(first.model_copy(update={"receipt": old}))  # as if made under an older row
    engine.start_run("@tryvinci/image-generate", ask)
    assert submits() == 2  # the result made under the older row is not reused
    engine.start_run("@tryvinci/image-generate", ask)
    assert submits() == 2  # the result made again is
    # A newer job that came back empty does not hide the result (CodeRabbit on #549).
    newest = engine.store.find_by_idempotency(first.idempotency_key or "")
    assert newest is not None and newest.outputs
    empty = newest.model_copy(update={"id": "empty-job", "outputs": []})
    engine.store.put_job(empty)
    found = engine.store.find_by_idempotency(first.idempotency_key or "")
    assert found is not None and found.id == newest.id
    # A connector row has one snapshot, not the time of each catalog call: a new time made every
    # cached Higgsfield and Magnific result stale and paid again (CodeRabbit on #549).
    from vinci_mcp.connectors import CONNECTORS, models_for

    stamps = [m.pricing.snapshot_at for _ in range(2) for m in models_for(CONNECTORS["mcp_higgsfield"], None)]
    assert len(set(stamps)) == 1


def test_runtime_fits_a_clip_length_the_model_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A length over the model's max, or not listed, is fitted before the job (the provider refused
    it with HTTP 400); a length the model takes stays, so its cache key stays (COREPRODUC-580)."""
    from vinci_protocol.models import ModelConstraints
    from vinci_runtime.engine import _refused_duration

    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    asked = {}
    for seconds in (12, 5, "6"):  # mock:mp4:v1 takes up to 8 s; the skill sends {{inputs.duration}}
        run = engine.start_run(
            "@tryvinci/video-generate",
            {"prompt": "a lamp on a cliff", "duration": seconds},
            model_id="mock:mp4:v1",
        )
        assert run["state"] == "completed", run
        job = engine.store.get_job(run["job_ids"][0])
        assert job is not None
        asked[str(seconds)] = job.inputs.get("duration")
    assert asked == {"12": 8, "5": 5, "6": "6"}, asked
    six = ModelConstraints(durations=[6])
    assert _refused_duration(5, six) == 5.0 and _refused_duration("6", six) is None
    assert _refused_duration("", six) is None and _refused_duration(True, six) is None
    kling = ModelConstraints(durations=[5, 10])  # "7s" was priced as 10 s but sent as "7" (#553)
    assert _refused_duration("7s", kling) == 7.0 and _refused_duration("10s", kling) is None


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


def test_init_home_auto_mode_needs_live_spend_and_a_live_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Studio boot sends demo=null. Live needs live spend and a ready non-mock model, even for env-only keys."""
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    for name in all_secret_names():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)

    assert Engine(tmp_path).init_home(demo=None)["demo"] is True  # no key, no live spend
    monkeypatch.setenv("VINCI_ALLOW_LIVE_SPEND", "1")
    assert Engine(tmp_path).init_home(demo=None)["demo"] is True  # live spend, no key
    monkeypatch.setenv("WAVESPEED_API_KEY", "not-a-real-key")
    eng = Engine(tmp_path)
    assert eng.init_home(demo=None)["demo"] is False  # env key, no config row yet
    assert eng.config.providers["mock"] == {"enabled": False}
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND")
    assert Engine(tmp_path).init_home(demo=None)["demo"] is True  # key, live spend off


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


def test_init_enables_provider_when_env_key_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("FAL_KEY", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    assert engine.provider_available("openai") is True
    assert engine.provider_available("fal") is False


def test_init_keeps_an_explicit_provider_disable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-wavespeed-key")
    engine = Engine(tmp_path)
    engine.config.providers["wavespeed"] = {"enabled": False}
    engine.init_home(demo=True)
    assert engine.provider_available("wavespeed") is False
