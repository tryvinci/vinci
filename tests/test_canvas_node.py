"""Magnific node-card controls (apps/studio/lib/canvas-node.ts)."""

from __future__ import annotations

from pathlib import Path

from ts_module import run_ts

MODULE = "apps/studio/lib/canvas-node.ts"
NAMES = [
    "START_CARDS",
    "REF_LIMIT",
    "ASPECTS",
    "RESOLUTIONS",
    "clampCount",
    "countValue",
    "countPatch",
    "promptValue",
    "usesPagePrompt",
    "pickListed",
    "listedOr",
    "fitToModel",
    "clipPrice",
    "refsOf",
    "slotRef",
    "nextRefRole",
    "addRef",
    "removeRef",
    "seedValue",
    "showsCount",
    "showsFrame",
    "shotRows",
    "shotValue",
    "shotPatch",
]
SETUP = """
const eq = (a, b, msg) => {
  const [x, y] = [JSON.stringify(a), JSON.stringify(b)];
  if (x !== y) throw new Error(`${msg}: ${x} !== ${y}`);
};
"""


def _check(body: str) -> None:
    result = run_ts(MODULE, NAMES, SETUP + body)
    assert result.returncode == 0, result.stderr or result.stdout


def test_empty_space_has_five_start_cards() -> None:
    _check("""
eq(START_CARDS.length, 5, "five Magnific starters");
eq(START_CARDS.map((c) => c.capability), ["t2i", "t2v", "upscale", "i2i", "tts"], "order");
eq([...new Set(START_CARDS.map((c) => c.label))].length, 5, "unique labels");
""")


def test_prompt_card_and_inspector_read_the_same_value() -> None:
    _check("""
const params = { prompt: "oak cube" };
eq(promptValue(params), "oak cube", "typed prompt");
eq(promptValue({ prompt: "{{inputs.prompt}}" }), "", "page prompt is empty on the card");
eq(usesPagePrompt({ prompt: "{{ inputs.prompt }}" }), true, "template");
eq(promptValue({}), "", "missing");
""")


def test_count_stepper_clamps_and_mirrors_num_images() -> None:
    _check("""
eq(clampCount(0), 1, "min");
eq(clampCount(11), 10, "max");
eq(clampCount("3.6"), 4, "round");
eq(countValue({}), 1, "default");
eq(countValue({ num_images: 4 }), 4, "legacy num_images");
eq(countPatch(8), { count: 8, num_images: 8 }, "providers that read num_images stay in sync");
eq(showsCount("t2i"), true, "image gen");
eq(showsCount("upscale"), false, "upscale has no count stepper");
""")


def test_aspect_and_resolution_prefer_the_model_list() -> None:
    _check("""
eq(pickListed("9:16", ASPECTS), "9:16", "keep a listed value");
eq(pickListed("{{inputs.aspect_ratio}}", ASPECTS), "1:1", "drop templates");
eq(pickListed("21:9", ["16:9", "9:16"]), "16:9", "snap when the model dropped it");
eq(listedOr(["1024x1024"], RESOLUTIONS), ["1024x1024"], "model list wins");
eq(listedOr([], RESOLUTIONS), RESOLUTIONS, "empty model list uses Magnific 1K/2K/4K");
eq(showsFrame("t2v"), true, "video");
eq(showsFrame("tts"), false, "voice");
""")


def test_a_run_sends_what_the_pills_show_for_the_model() -> None:
    """A canvas run fits its params to the model: `1K` on Seedream and 5 s on Hailuo got HTTP 400."""
    _check("""
const seedream = { aspect_ratios: ["1:1", "16:9", "9:16"], resolutions: ["1024x1024"] };
eq(fitToModel({ aspect_ratio: "16:9", resolution: "1K", prompt: "p" }, seedream),
   { aspect_ratio: "16:9", resolution: "1024x1024", prompt: "p" }, "resolution as the pill shows it");
eq(fitToModel({ duration: 5 }, { durations: [6] }), { duration: 6 }, "the listed length that covers it");
eq(fitToModel({ duration: 8 }, { durations: [10, 6] }), { duration: 10 }, "the shortest that covers it, as fit_duration");
eq(fitToModel({ duration: 12 }, { durations: [6, 10] }), { duration: 10 }, "else the longest");
const kling = { pricing: { amount: 0.35, clip_prices: { "5": 0.35, "10": 0.7 } }, constraints: { durations: [5, 10] } };
eq(clipPrice(kling, 10), 0.7, "a 10 s clip on a row that bills by length (COREPRODUC-555)");
eq(clipPrice(kling, "7"), 0.7, "the length is fitted first, as fit_duration");
eq(clipPrice(kling, "{{inputs.duration}}"), 0.35, "a template prices the default clip");
eq(clipPrice(kling, "{{inputs.duration}}", { duration: 10 }), 0.7, "a template takes the run's length");
eq(clipPrice(kling, "10.0"), 0.7, "a numeric string reads as a number");
eq(clipPrice(kling, " 10 "), 0.7, "spaces too");
eq(clipPrice(kling, undefined), 0.35, "no length: the default clip");
eq(clipPrice({ pricing: { amount: 0.4 } }, 8), 0.4, "a row without a table is one price per job");
const speech = { pricing: { amount: 0.08, unit: "1k_chars" } };
eq(clipPrice(speech, undefined, {}, "x".repeat(500)), 0.04, "speech is priced by its characters (COREPRODUC-603)");
eq(clipPrice(speech, undefined, { prompt: "x".repeat(250) }, "{{inputs.prompt}}"), 0.02, "a template takes the run's text");
eq(clipPrice(speech, undefined, {}, ""), 0.08, "no text: one 1,000 characters");
const listed = { pricing: { amount: 0.08, unit: "1k_chars", clip_prices: {} } }; // as GET /models sends it
eq(clipPrice(listed, undefined, {}, "x".repeat(500)), 0.04, "an empty clip table is no table");
const music = { pricing: { amount: 0.15, unit: "minute" }, constraints: { max_duration: 60 } };
eq(clipPrice(music, 30), 0.075, "music is priced by its seconds");
eq(fitToModel({ duration: 8 }, { max_duration: 6 }), { duration: 6 }, "no longer than the max");
eq(fitToModel({ duration: 5 }, { max_duration: 10 }), { duration: 5 }, "a length that fits stays");
eq(fitToModel({ aspect_ratio: "{{inputs.aspect_ratio}}" }, seedream), { aspect_ratio: "{{inputs.aspect_ratio}}" }, "templates stay");
eq(fitToModel({ resolution: "1K" }, undefined), { resolution: "1K" }, "no catalog row: unchanged");
""")


def test_references_cap_at_eight_with_style_and_character_slots() -> None:
    _check("""
eq(REF_LIMIT, 8, "Magnific 0/8");
let params = addRef({}, "style", "a1");
params = addRef(params, "character", "a2");
eq(refsOf(params), [{ role: "style", assetId: "a1" }, { role: "character", assetId: "a2" }], "slots");
eq(params.image_urls, ["a1", "a2"], "image_urls stay in sync for generate");
eq(slotRef(refsOf(params), "character").assetId, "a2", "character slot");
eq(nextRefRole(refsOf(params)), "style", "further refs are style");
eq(addRef(params, "style", "a1"), params, "duplicate asset is a no-op");
params = removeRef(params, "a1");
eq(refsOf(params).map((r) => r.assetId), ["a2"], "remove");
const full = {};
for (let i = 0; i < 10; i++) Object.assign(full, addRef(full, "style", "x" + i));
eq(refsOf(full).length, 8, "hard cap");
eq(refsOf({ image_urls: ["old"] }), [{ role: "style", assetId: "old" }], "legacy image_urls");
eq(seedValue({ seed: 42 }), "42", "seed");
eq(seedValue({}), "", "random seed");
""")


def test_studio_wires_card_and_inspector_to_the_same_params() -> None:
    """Acceptance: prompt typed on the card is the inspector value, and the reverse."""
    client = Path(__file__).resolve().parents[1] / "apps/studio/app/studio-client.tsx"
    card = Path(__file__).resolve().parents[1] / "apps/studio/app/canvas-node-card.tsx"
    insp = Path(__file__).resolve().parents[1] / "apps/studio/app/canvas-inspector.tsx"
    empty = Path(__file__).resolve().parents[1] / "apps/studio/app/canvas-empty.tsx"
    body = client.read_text(encoding="utf-8")
    assert "promptValue(n.params)" in body
    assert body.count("promptValue(n.params)") >= 2
    assert body.count("runNodes([n.id])") >= 2
    assert "runNodes([n.id], true)" not in body
    assert "Run this node only" in body
    assert "runNodes([soloNode.id], true)" in body
    assert 'modelsFor("canvas"' in body
    assert "nodeModels(" in body
    assert "modelsForNodeTypes(" in body
    assert '(m.capabilities || []).includes(n.capability' not in body
    card_src = card.read_text(encoding="utf-8")
    assert "data-testid=\"node-run\"" in card_src
    assert "PromptMention" in card_src
    assert "aria-haspopup=\"listbox\"" in card_src
    assert "<select" not in card_src
    assert "id=\"node-prompt\"" in insp.read_text(encoding="utf-8")
    assert "PromptMention" in insp.read_text(encoding="utf-8")
    assert "data-testid=\"canvas-inspector\"" in insp.read_text(encoding="utf-8")
    empty_src = empty.read_text(encoding="utf-8")
    assert "Choose your first node" in empty_src
    assert "data-start={card.capability}" in empty_src
    # On a host, only the cards a listed model can run (live UI check, 2026-11-12, COREPRODUC-624).
    assert "START_CARDS.filter((card) => !canAdd || canAdd(card.capability)).map" in empty_src
    assert "canAdd={doctor.host ? (cap) => nodeModels(cap).length > 0 : undefined}" in body


def test_studio_wires_typed_ports_and_add_popover() -> None:
    """Acceptance: click-output uses insertNode(from); popover has chips + keyboard."""
    root = Path(__file__).resolve().parents[1]
    client = (root / "apps/studio/app/studio-client.tsx").read_text(encoding="utf-8")
    menu = (root / "apps/studio/app/canvas-add-menu.tsx").read_text(encoding="utf-8")
    css = (root / "apps/studio/app/globals.css").read_text(encoding="utf-8")
    assert "insertNode(pick.capability, from" in client
    assert "openAddMenu(n.id)" in client
    assert 'data-port="out"' in client
    assert 'data-port="in"' in client
    assert "CanvasAddMenu" in client
    assert "ADD_CHIPS" in menu
    assert "ArrowRight" in menu
    assert "buildAddMenu" in menu
    assert "kind-text" in css
    assert "add-chips" in css
    assert "add-vendor" in css


def test_shot_rows_values_and_toggle() -> None:
    """Inspector shot rows (COREPRODUC-525): generators only, motion for video, a second press clears."""
    _check("""
eq(shotRows("upscale").length, 0, "no shot rows for upscale");
eq(shotRows("t2i").map((r) => r.key), ["camera", "lens", "aperture", "look", "genre", "lighting", "palette"], "image rows");
eq(shotRows("i2v").at(-1).key, "motion", "video adds camera motion");
eq(shotValue({ camera: "{{inputs.camera}}" }, "camera"), "", "skill placeholder counts as unset");
eq(shotValue({ lens: "85mm" }, "lens"), "85mm", "set value");
eq(shotPatch({}, "lens", "85mm"), { lens: "85mm" }, "set");
eq(shotPatch({ lens: "85mm" }, "lens", "85mm"), { lens: "" }, "second press clears");
eq(shotPatch({ lighting: "neon" }, "lighting", "neon"), { lighting: "available" }, "lighting clears to available");
""")
