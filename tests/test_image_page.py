"""Image page rules. Acceptance: pending card, model-gated chips, Featured/All."""

from __future__ import annotations

from ts_module import ROOT, run_ts

MODULE = "apps/studio/lib/image-page.ts"
NAMES = [
    "IMAGE_HOW_STEPS",
    "applyFavorites",
    "capabilityChips",
    "clampBatch",
    "defaultImageModelId",
    "featuredModels",
    "feedFromLibrary",
    "feedFromRuns",
    "filterMentions",
    "generateCost",
    "imageModels",
    "insertMention",
    "isImageModel",
    "mentionOpen",
    "modelBadges",
    "modelBlurb",
    "needsReference",
    "pickerSections",
    "qualityOptions",
    "searchImageModels",
    "toggleFavorite",
    "visibleControls",
    "withPendingCards",
]


def _run(body: str):
    return run_ts(MODULE, NAMES, body)


def test_image_models_hide_video_and_keep_still() -> None:
    script = """
const rows = [
  { id: "mock:png:v1", display_name: "Mock PNG", provider: "mock", capabilities: ["t2i", "i2i"] },
  { id: "mock:mp4:v1", display_name: "Mock MP4", provider: "mock", capabilities: ["t2v", "i2v"] },
  { id: "soul-ref", display_name: "Soul Reference", provider: "higgsfield", capabilities: ["i2i"] },
];
const ids = imageModels(rows).map((row) => row.id).join();
if (ids !== "mock:png:v1,soul-ref") throw new Error("image set: " + ids);
if (isImageModel(rows[1])) throw new Error("video leaked");
const hidden = imageModels(rows, ["higgsfield", "mock"]).map((row) => row.id).join();
if (hidden !== "soul-ref") throw new Error("mock should hide when a provider is connected: " + hidden);
const demo = imageModels(rows, ["mock"]).map((row) => row.id).join();
if (demo !== "mock:png:v1") throw new Error("demo keeps mock: " + demo);
const tied = imageModels(
  [
    { id: "b", display_name: "B", provider: "fal", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 1 } },
    { id: "a", display_name: "A", provider: "openai", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 1 } },
  ],
  ["fal", "openai"],
  (row) => (row.id === "a" ? 0 : 2),
);
if (tied.map((row) => row.id).join() !== "a,b") throw new Error("availability should break an equal modelsFor rank: " + tied.map((row) => row.id));
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_featured_is_catalog_quality_tier() -> None:
    script = """
const rows = [
  { id: "a", display_name: "A", provider: "fal", capabilities: ["t2i"], quality_tier: "quality" },
  { id: "b", display_name: "B", provider: "mock", capabilities: ["t2i"], quality_tier: "fast" },
];
const featured = featuredModels(rows).map((row) => row.id).join();
if (featured !== "a") throw new Error("featured invented a list: " + featured);
const { featured: feat, all } = pickerSections(rows);
if (feat.map((row) => row.id).join() !== "a") throw new Error("picker featured");
if (all.map((row) => row.id).join() !== "b") throw new Error("picker all should drop featured");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_visible_controls_hide_when_model_lacks_them() -> None:
    script = """
const open = {
  id: "openai:gpt-image-2:2026-04",
  display_name: "GPT Image 2",
  provider: "openai",
  capabilities: ["t2i"],
  constraints: { aspect_ratios: ["1:1"], resolutions: ["1024x1024"] },
};
const mock = {
  id: "mock:png:v1",
  display_name: "Mock PNG",
  provider: "mock",
  capabilities: ["t2i"],
  constraints: { aspect_ratios: ["1:1", "16:9"], resolutions: ["1x1"] },
};
const bare = { id: "bare", display_name: "Bare", provider: "fal", capabilities: ["t2i"] };
const o = visibleControls(open);
if (!o.aspect || !o.quality || !o.resolution || !o.batch) throw new Error("openai chips");
if (qualityOptions(open).join() !== "low,medium,high") throw new Error("openai quality");
const m = visibleControls(mock);
if (!m.aspect || m.quality || !m.resolution) throw new Error("mock should hide quality");
if (qualityOptions(mock).length) throw new Error("mock quality invented");
const b = visibleControls(bare);
if (b.aspect || b.quality || b.resolution || !b.batch) throw new Error("bare chips");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_blurbs_badges_and_chips_from_catalog() -> None:
    script = """
if (modelBlurb({ id: "x", display_name: "X", provider: "fal", capabilities: ["t2i", "i2i"] }) !== "Text to image and edit") {
  throw new Error("blurb");
}
const badges = modelBadges({ id: "wan-25-preview", display_name: "Wan 2.5 Preview", provider: "higgsfield", capabilities: ["t2i"] });
if (badges.join() !== "Beta") throw new Error("badges " + badges);
const chips = capabilityChips({
  id: "soul",
  display_name: "Soul",
  provider: "higgsfield",
  capabilities: ["t2i", "i2i"],
  constraints: { resolutions: ["2K", "4K"] },
});
if (chips.join() !== "2K,4K,References") throw new Error("chips " + chips);
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_pending_cards_sit_on_top_of_the_feed() -> None:
    script = """
const runs = [
  { id: "old", created_at: "2026-01-01", outputs: ["a1"], inputs: { prompt: "oak" } },
  { id: "new", created_at: "2026-01-02", outputs: ["a2"], inputs: { prompt: "cube" } },
];
const assets = [
  { id: "a1", mime: "image/png" },
  { id: "a2", mime: "image/png" },
];
const feed = feedFromRuns(runs, assets);
if (feed[0].assetId !== "a2" || feed[0].prompt !== "cube") throw new Error("newest first");
const pending = withPendingCards(feed, 1);
if (!pending[0].pending || pending[0].id !== "pending-0") throw new Error("pending first");
if (pending[1].assetId !== "a2") throw new Error("completed after pending");
const four = withPendingCards(feed, 4);
if (four.filter((row) => row.pending).length !== 4) throw new Error("batch pending");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_image_feed_scrolls_down_not_sideways() -> None:
    """The columns sit inside the scroll box: on it, extra pictures made new columns (COREPRODUC-579)."""
    css = (ROOT / "apps" / "studio" / "app" / "globals.css").read_text(encoding="utf-8")
    scroll_box = css.split(".image-feed {", 1)[1].split("}", 1)[0]
    assert "overflow: auto" in scroll_box and "column-count" not in scroll_box
    assert ".image-feed-cols { column-count: 3;" in css
    feed = (ROOT / "apps" / "studio" / "app" / "image-feed.tsx").read_text(encoding="utf-8")
    assert '<div className="image-feed" data-testid={feedTestId}>\n      <div className="image-feed-cols">' in feed


def test_library_feed_skips_trash_and_video() -> None:
    script = """
const items = [
  { id: "1", asset_id: "img", prompt: "still", media_kind: "image", saved_at: "2026-02-02" },
  { id: "2", asset_id: "vid", prompt: "clip", media_kind: "video", saved_at: "2026-02-03" },
  { id: "3", asset_id: "gone", prompt: "x", media_kind: "image", trashed_at: "2026-02-04", saved_at: "2026-02-04" },
];
const feed = feedFromLibrary(items);
if (feed.length !== 1 || feed[0].assetId !== "img") throw new Error("library filter");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_mentions_cost_favorites_and_defaults() -> None:
    script = """
if (!mentionOpen("hello @so", 8)) throw new Error("mention open");
if (mentionOpen("hello @so there", 15)) throw new Error("mention closed after space");
const next = insertMention("hello @so", 8, "Soldier");
if (next.text !== "hello @Soldier") throw new Error(next.text);
const hits = filterMentions(
  [{ name: "Soldier", assetId: "s" }, { name: "Room", assetId: "r" }],
  "hello @so",
  8,
);
if (hits.map((row) => row.name).join() !== "Soldier") throw new Error("filter");
if (generateCost(0.04, 4) !== 0.16) throw new Error("batch cost");
if (clampBatch(3) !== 1 || clampBatch(4) !== 4) throw new Error("batch clamp");
if (toggleFavorite(["a"], "a").length !== 0) throw new Error("unfav");
const fav = applyFavorites([{ id: "a", assetId: "a", prompt: "", modelId: "", createdAt: "", favorite: false, mediaKind: "image" }], ["a"]);
if (!fav[0].favorite) throw new Error("apply fav");
const readyId = defaultImageModelId(
  [
    { id: "live", display_name: "Live", provider: "fal", capabilities: ["t2i"] },
    { id: "mock:png:v1", display_name: "Mock PNG", provider: "mock", capabilities: ["t2i"] },
  ],
  (row) => row.provider === "mock",
);
if (readyId !== "mock:png:v1") throw new Error("demo default");
if (!needsReference({ id: "ref", display_name: "Ref", provider: "higgsfield", capabilities: ["i2i"] })) {
  throw new Error("i2i-only needs ref");
}
if (IMAGE_HOW_STEPS.length !== 3) throw new Error("how steps");
const ranked = searchImageModels(
  [{ id: "p", display_name: "Other", provider: "fluxpro" }, { id: "n", display_name: "Flux Dev", provider: "fal" }],
  "flux",
);
if (ranked[0]?.id !== "n") throw new Error("search rank");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_studio_wires_image_page_and_animate_to_video() -> None:
    client = (ROOT / "apps" / "studio" / "app" / "studio-client.tsx").read_text(encoding="utf-8")
    assert "ImagePage" in client
    assert 'page === "image"' in client
    assert "setFirstFrameId(id)" in client
    assert 'setPage("video")' in client
    assert "Your still is in the feed." in client
    page = (ROOT / "apps" / "studio" / "app" / "image-page.tsx").read_text(encoding="utf-8")
    assert "imageModels(models, connected, availability)" in page
    assert "isImageModel" not in page
    assert "/library?tool=image" in page
    bar = (ROOT / "apps" / "studio" / "app" / "image-prompt-bar.tsx").read_text(encoding="utf-8")
    assert "image-model-picker" in bar
    assert "image-generate" in bar
    assert "image-elements" in bar
    assert "PromptMention" in bar
    assert "MentionPopover" in (ROOT / "apps" / "studio" / "app" / "mention-popover.tsx").read_text(encoding="utf-8")
    feed = (ROOT / "apps" / "studio" / "app" / "image-feed.tsx").read_text(encoding="utf-8")
    assert "Use as reference" in feed
    assert "Animate" in feed
    assert "Copy prompt" in feed
