"""Every Higgsfield and Magnific model, from their free model lists (COREPRODUC-669). No network."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from vinci_mcp.adapter import McpProvider
from vinci_mcp.catalog_live import higgsfield_rows, magnific_rows, price_rows
from vinci_mcp.connectors import CONNECTORS, Row, connector_for, models_for
from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest
from vinci_storage.cas import ContentAddressedStore

# Entries as the lists answered on 2026-11-16 (trimmed to the fields the rows read).
HF_IMAGES = [
    {
        "id": "nano_banana_pro",
        "name": "Nano Banana Pro",
        "output_type": "image",
        "medias": [{"roles": ["image_references"]}],
        "aspect_ratios": ["auto", "1:1", "16:9"],
    },
    {
        "id": "nano_banana_2_shots",
        "name": "Nano Banana Pro",
        "output_type": "image",
        "medias": [{"roles": ["image_references"]}],
    },
    {
        "id": "recraft_v4_1",
        "name": "Recraft V4.1",
        "output_type": "image",
        "medias": [],
        "aspect_ratios": ["1:1"],
    },
    {
        "id": "image_background_remover",
        "name": "Image Background Remover",
        "output_type": "image",
        "medias": [{"roles": ["image_references"]}],
    },
    {
        "id": "marketing_studio_2_image",
        "name": "Marketing Studio Product Shot",
        "output_type": "image",
        "medias": [{"roles": ["product_image"]}],
    },
]
HF_VIDEOS = [
    {
        "id": "kling3_0",
        "name": "Kling v3.0",
        "output_type": "video",
        "medias": [{"roles": ["start_image", "end_image"]}],
        "aspect_ratios": ["16:9", "9:16"],
        "duration_range": {"min": 3, "max": 15},
    },
    {
        "id": "higgsfield_preset",
        "name": "Higgsfield Preset",
        "output_type": "video",
        "medias": [{"roles": ["image"]}],
        "tags": ["image-to-video"],
    },
    {
        "id": "wan2_6",
        "name": "Wan 2.6 Video",
        "output_type": "video",
        "medias": [{"roles": ["image_references"]}],
        "parameters": [{"name": "duration", "options": [5, 10, 15]}],
    },
]
MG_IMAGES = [
    {
        "slug": "seedream-5-pro",
        "name": "Seedream 5 Pro",
        "referenceTypes": ["style", "image"],
        "aspectRatios": ["1:1", "16:9"],
    },
    {"slug": "recraft-v4", "name": "Recraft V4", "referenceTypes": ["style"]},
]
MG_VIDEOS = [
    {
        "slug": "kling-30",
        "name": "Kling 3.0",
        "requiredInputs": ["prompt"],
        "durations": [3, 4, 5, 6, 7, 8, 9, 10],
        "resolutions": ["720p", "1080p", "4K"],
        "aspectRatios": ["16:9", "9:16"],
        "supportsStartFrame": True,
        "supportsEndFrame": True,
        "supportsReferences": True,
    },
    {
        "slug": "bytedance-omnihuman-lipsync",
        "name": "OmniHuman",
        "requiredInputs": ["image", "audio"],
        "supportsStartFrame": True,
    },
]


def test_lists_become_rows_with_their_inputs_and_tools_stay_out() -> None:
    rows = {r.model: r for r in higgsfield_rows(HF_IMAGES, HF_VIDEOS)}
    assert set(rows) == {
        "nano_banana_pro",
        "recraft_v4_1",
        "kling3_0",
        "wan2_6",
    }  # a repeat, tools, a product shot and an i2v-only preset left out
    assert rows["nano_banana_pro"].capabilities == ("t2i", "i2i") and rows[
        "nano_banana_pro"
    ].ratios == ("1:1", "16:9")
    assert rows["recraft_v4_1"].capabilities == ("t2i",) and rows["recraft_v4_1"].refs == 0
    kling = rows["kling3_0"]
    assert (
        kling.capabilities == ("t2v", "i2v")
        and kling.end_frame
        and kling.durations == (3, 4, 5, 6, 8, 10, 12, 15)
    )
    assert (
        rows["wan2_6"].capabilities == ("t2v",)
        and rows["wan2_6"].refs == 4
        and rows["wan2_6"].durations == (5, 10, 15)
    )
    mg = {r.model: r for r in magnific_rows(MG_IMAGES, MG_VIDEOS)}
    assert set(mg) == {"seedream-5-pro", "recraft-v4", "kling-30"}  # lip sync needs audio: left out
    assert mg["seedream-5-pro"].capabilities == ("t2i", "i2i") and mg[
        "recraft-v4"
    ].capabilities == ("t2i",)
    assert mg["kling-30"].durations == (3, 4, 5, 6, 8, 10) and dict(mg["kling-30"].settings) == {
        "resolution": "720p"
    }


def test_each_length_is_priced_with_the_free_preview_and_unpriced_rows_stay() -> None:
    connector = connector_for("mcp_magnific")
    assert connector is not None
    rows = magnific_rows(MG_IMAGES, MG_VIDEOS)
    calls = []

    def call(tool: str, args: dict) -> dict:
        calls.append((tool, args))
        inner = args["arguments"]
        if inner.get("mode") == "recraft-v4":
            raise RuntimeError("settings refused")
        return {"structuredContent": {"credits": 10 * inner.get("duration", 1)}}

    priced = {r.model: r for r in price_rows(connector, rows, call)}
    assert all(tool == "simulate_cost" for tool, _ in calls)  # previews only: nothing generated
    assert priced["seedream-5-pro"].credits == 10 and priced["recraft-v4"].credits is None
    assert dict(priced["kling-30"].clip_credits) == {3: 30, 4: 40, 5: 50, 6: 60, 8: 80, 10: 100}
    spec = next(
        s
        for s in models_for(replace(connector, rows=tuple(priced.values())), None)
        if s.id == "mcp_magnific:kling-30"
    )
    assert (
        spec.pricing.clip_prices["10"] == 100
        and spec.constraints.end_frame
        and spec.constraints.max_references == 4
    )
    assert [c.value for c in spec.capabilities] == ["t2v", "i2v"]


def test_arguments_carry_references_end_frames_and_lengths() -> None:
    hf, mg = connector_for("mcp_higgsfield"), connector_for("mcp_magnific")
    assert hf is not None and mg is not None
    kling = Row(
        "kling3_0",
        "Kling v3.0",
        "i2v",
        40,
        ("16:9",),
        caps=("t2v", "i2v"),
        durations=(5, 10),
        end_frame=True,
    )
    args = hf.arguments(
        kling, {"prompt": "push in", "duration": 9, "aspect_ratio": "16:9"}, "m1", "m2"
    )
    assert args["params"]["duration"] == 10 and args["params"]["medias"] == [
        {"value": "m1", "role": "start_image"},
        {"value": "m2", "role": "end_image"},
    ]
    banana = Row(
        "nano_banana_pro",
        "Nano Banana Pro",
        "t2i",
        2,
        ("1:1",),
        caps=("t2i", "i2i"),
        refs=4,
        ref_role="image_references",
    )
    assert hf.arguments(banana, {"prompt": "same lamp, blue"}, refs=("r1", "r2"))["params"][
        "medias"
    ] == [{"value": "r1", "role": "image_references"}, {"value": "r2", "role": "image_references"}]
    seedream = Row(
        "seedream-5-pro", "Seedream 5 Pro", "t2i", 50, ("1:1",), caps=("t2i", "i2i"), refs=4
    )
    assert mg.arguments(seedream, {"prompt": "x"}, refs=("c1",))["references"] == [
        {"type": "image", "identifier": "c1"}
    ]
    clip = Row(
        "kling-30",
        "Kling 3.0",
        "i2v",
        50,
        ("16:9",),
        (("resolution", "720p"),),
        caps=("t2v", "i2v"),
        durations=(5, 10),
        end_frame=True,
        refs=4,
    )
    video = mg.arguments(clip, {"prompt": "x", "duration": 5}, "c1", "c2")
    assert (video["slug"], video["duration"], video["resolution"], video["keyframes"]) == (
        "kling-30",
        5,
        "720p",
        {"start": "c1", "end": "c2"},
    )
    refs = mg.arguments(clip, {"prompt": "x"}, refs=("c3",))
    assert refs["references"] == [{"type": "image", "url": "c3"}] and "keyframes" not in refs


def test_an_image_edit_uploads_its_references_and_checks_the_price_of_its_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Higgsfield Nano Banana Pro with two references, then a Kling clip whose 10 s price is checked."""
    seen: dict[str, list[dict]] = {}
    answers = {
        "media_import_url": {"media_id": "m-ref"},
        "generate_image": {"results": [{"id": "h1", "status": "queued"}]},
        "generate_video": {"results": [{"id": "v1", "status": "queued"}]},
    }

    class Transport:
        url = "http://127.0.0.1:9/mcp"

        def bearer(self) -> str:
            return "loopback-bearer"

        def call(self, method: str, params: dict) -> dict:
            if method == "tools/list":
                return {"tools": [{"name": n} for n in answers]}
            name, args = str(params["name"]), params.get("arguments") or {}
            seen.setdefault(name, []).append(args)
            if args.get("params", {}).get("get_cost"):
                return {
                    "structuredContent": {
                        "cost": {"credits": 80 if args["params"].get("duration") == 10 else 2}
                    }
                }
            return {"structuredContent": answers[name]}

    banana = Row(
        "nano_banana_pro",
        "Nano Banana Pro",
        "t2i",
        2,
        ("1:1",),
        caps=("t2i", "i2i"),
        refs=4,
        ref_role="image_references",
    )
    kling = Row(
        "kling3_0",
        "Kling v3.0",
        "i2v",
        40,
        ("16:9",),
        caps=("t2v", "i2v"),
        durations=(5, 10),
        clip_credits=((5, 40), (10, 80)),
        end_frame=True,
    )
    monkeypatch.setitem(
        CONNECTORS, "mcp_higgsfield", replace(CONNECTORS["mcp_higgsfield"], rows=(banana, kling))
    )
    provider = McpProvider(
        Transport(), cas=ContentAddressedStore(tmp_path / "cas"), provider_id="mcp_higgsfield"
    )  # type: ignore[arg-type]
    edit = JobRequest(
        capability=Capability.I2I,
        model_id="mcp_higgsfield:nano_banana_pro",
        inputs={
            "prompt": "the same lamp in blue",
            "image_urls": ["https://cdn.test/a.png", "https://cdn.test/b.png"],
        },
    )
    provider.estimate(edit)
    provider.submit(edit)
    assert len(seen["media_import_url"]) == 2
    assert (
        seen["generate_image"][-1]["params"]["medias"]
        == [{"value": "m-ref", "role": "image_references"}] * 2
    )
    clip = JobRequest(
        capability=Capability.T2V,
        model_id="mcp_higgsfield:kling3_0",
        inputs={"prompt": "a kite", "duration": 10},
    )
    provider.estimate(clip)
    provider.submit(clip)  # 80 credits for 10 s: the 10 s price, not the 5 s one, so it runs
    assert (
        seen["generate_video"][-1]["params"]["duration"] == 10
        and "medias" not in seen["generate_video"][-1]["params"]
    )


def test_the_snapshots_list_every_model_after_the_hand_tuned_rows() -> None:
    for provider_id, first in (
        ("mcp_higgsfield", "seedream_v4_5"),
        ("mcp_magnific", "seedream-4-5"),
    ):
        connector = connector_for(provider_id)
        assert connector is not None and connector.rows[0].model == first
        specs = models_for(connector, None)
        assert len(specs) > 50, provider_id  # every model, not 3
        assert len({s.id for s in specs}) == len(specs)  # a hand-tuned model is not listed twice
        assert any("i2i" in [c.value for c in s.capabilities] for s in specs)  # image to image
        assert any(s.constraints.end_frame for s in specs) and any(
            s.constraints.max_references for s in specs
        )
