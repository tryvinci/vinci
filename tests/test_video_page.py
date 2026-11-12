"""Video page rules. Acceptance: Extend settings, preset fill, 3-step how strip."""

from __future__ import annotations

from ts_module import ROOT, run_ts

MODULE = "apps/studio/lib/video-page.ts"
NAMES = [
    "VIDEO_HOW_STEPS",
    "VIDEO_TABS",
    "applyFavorites",
    "applyPreset",
    "closestAspect",
    "defaultVideoModelId",
    "durationOptions",
    "extendFromItem",
    "feedFromLibrary",
    "feedFromRuns",
    "filterPresets",
    "generateCost",
    "hasAudio",
    "isVideoModel",
    "modelFamily",
    "needsStartFrame",
    "presetFilterChips",
    "presetFixes",
    "presetTabs",
    "supportsEndFrame",
    "toggleFavorite",
    "videoModels",
    "visibleVideoControls",
    "withPendingCards",
]


def _run(body: str):
    return run_ts(MODULE, NAMES, body)


def test_video_models_hide_stills() -> None:
    script = """
const rows = [
  { id: "mock:png:v1", display_name: "Mock PNG", provider: "mock", capabilities: ["t2i", "i2i"] },
  { id: "mock:mp4:v1", display_name: "Mock MP4", provider: "mock", capabilities: ["t2v", "i2v"] },
  { id: "kling", display_name: "Kling 3", provider: "wavespeed", capabilities: ["i2v"] },
];
const ids = videoModels(rows).map((row) => row.id).join();
if (ids !== "kling,mock:mp4:v1") throw new Error("video set: " + ids);
if (isVideoModel(rows[0])) throw new Error("still leaked");
const hidden = videoModels(rows, ["wavespeed", "mock"]).map((row) => row.id).join();
if (hidden !== "kling") throw new Error("mock should hide when a provider is connected: " + hidden);
const demo = videoModels(rows, ["mock"]).map((row) => row.id).join();
if (demo !== "mock:mp4:v1") throw new Error("demo keeps mock: " + demo);
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_duration_and_aspect_come_from_catalog() -> None:
    script = """
if (durationOptions(8).join() !== "3,5,6,8") throw new Error("dur 8");
if (durationOptions(0).length) throw new Error("no invented duration");
// The exact lengths from the catalog win (provider API docs): Kling 2.6 takes 5 or 10 s only.
if (durationOptions(10, [5, 10]).join() !== "5,10") throw new Error("kling 2.6: " + durationOptions(10, [5, 10]));
if (durationOptions(8, [4, 6, 8]).join() !== "4,6,8") throw new Error("veo 3.1 fast");
const kling3 = Array.from({ length: 13 }, (_, i) => i + 3); // 3..15 s
if (durationOptions(15, kling3).join() !== "3,5,6,8,10,15") throw new Error("kling 3: Studio picks among them");
if (closestAspect(960, 540, ["16:9", "9:16", "1:1"]) !== "16:9") throw new Error("landscape");
if (closestAspect(540, 960, ["16:9", "9:16"]) !== "9:16") throw new Error("portrait");
const mock = {
  id: "mock:mp4:v1",
  display_name: "Mock MP4",
  provider: "mock",
  capabilities: ["t2v", "i2v"],
  constraints: { aspect_ratios: ["16:9", "9:16"], max_duration: 8, resolutions: ["1280x720"] },
};
const v = visibleVideoControls(mock);
if (!v.duration || !v.aspect || !v.quality || v.audio || v.endFrame || !v.advanced) throw new Error("mock tiles");
const audio = { id: "seedance", display_name: "Seedance", provider: "wavespeed", capabilities: ["t2v"], pricing: { unit: "video_5s_audio" } };
if (!hasAudio(audio)) throw new Error("audio unit");
if (!needsStartFrame({ id: "i2v", display_name: "I2V", provider: "fal", capabilities: ["i2v"] })) throw new Error("i2v start");
if (!supportsEndFrame({ id: "x-flf", display_name: "FLF", provider: "higgsfield", capabilities: ["i2v"] })) throw new Error("flf");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_preset_overlay_tabs_and_chips_from_catalog() -> None:
    script = """
const rows = [
  { id: "wavespeed:kling-2.6-pro:2026-08", display_name: "Kling 2.6 Pro", provider: "wavespeed", capabilities: ["t2v", "i2v"] },
  { id: "wavespeed:wan-2.6:2026-08", display_name: "Wan 2.6", provider: "wavespeed", capabilities: ["t2v"] },
  { id: "wavespeed:seedance-2.0-turbo:2026-08", display_name: "Seedance 2.0 Turbo", provider: "wavespeed", capabilities: ["t2v"], pricing: { unit: "video_5s_audio" } },
  { id: "mock:mp4:v1", display_name: "Mock MP4", provider: "mock", capabilities: ["t2v", "i2v"] },
];
if (modelFamily(rows[0]) !== "Kling") throw new Error("kling family");
const tabs = presetTabs(rows).join();
if (tabs !== "All,Kling,Wan,Seedance,Mock") throw new Error("tabs " + tabs);
const chips = presetFilterChips(rows).join();
if (chips !== "All,t2v,i2v,Audio") throw new Error("chips " + chips);
const kling = filterPresets(rows, "Kling", "All", "").map((row) => row.id).join();
if (kling !== "wavespeed:kling-2.6-pro:2026-08") throw new Error("tab filter");
const audio = filterPresets(rows, "All", "Audio", "").map((row) => row.id).join();
if (audio !== "wavespeed:seedance-2.0-turbo:2026-08") throw new Error("audio chip");
const search = filterPresets(rows, "All", "All", "mock").map((row) => row.id).join();
if (search !== "mock:mp4:v1") throw new Error("search");
const filled = applyPreset({
  id: "mock:mp4:v1",
  display_name: "Mock MP4",
  provider: "mock",
  capabilities: ["t2v"],
  constraints: { aspect_ratios: ["16:9", "9:16"], max_duration: 8, resolutions: ["1280x720"] },
});
if (filled.modelId !== "mock:mp4:v1" || filled.duration !== "5" || filled.aspect !== "16:9" || filled.resolution !== "1280x720") {
  throw new Error(JSON.stringify(filled));
}
// A kept model keeps the settings it can use; only the others get its presets (live UI check, 2026-11-12).
const kept = { id: "mock:mp4:v1", display_name: "Mock MP4", provider: "mock", capabilities: ["t2v"], constraints: { aspect_ratios: ["16:9", "9:16"], max_duration: 8, resolutions: ["1280x720"] } };
const fixes = presetFixes(kept, { duration: "3", aspect: "9:16", resolution: "" });
if (JSON.stringify(fixes) !== JSON.stringify({ resolution: "1280x720" })) throw new Error("fixes " + JSON.stringify(fixes));
const wrong = presetFixes(kept, { duration: "3", aspect: "1:1", resolution: "1280x720" });
if (JSON.stringify(wrong) !== JSON.stringify({ aspect: "16:9" })) throw new Error("wrong aspect " + JSON.stringify(wrong));
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_video_feed_and_extend_copy_settings() -> None:
    script = """
const runs = [
  { id: "old", created_at: "2026-01-01", outputs: ["v1"], inputs: { prompt: "oak", duration: 5, aspect_ratio: "16:9" } },
  { id: "new", created_at: "2026-01-02", outputs: ["v2"], inputs: { prompt: "cube", model_id: "mock:mp4:v1", duration: 8, aspect_ratio: "9:16", resolution: "1280x720", seed: "11" } },
];
const assets = [
  { id: "v1", mime: "video/mp4" },
  { id: "v2", mime: "video/mp4" },
  { id: "img", mime: "image/png" },
];
const feed = feedFromRuns(runs, assets);
if (feed[0].assetId !== "v2" || feed[0].prompt !== "cube") throw new Error("newest first");
if (feed.length !== 2) throw new Error("stills leaked");
const pending = withPendingCards(feed, 1);
if (!pending[0].pending || pending[1].assetId !== "v2") throw new Error("pending");
const ext = extendFromItem(feed[0]);
if (ext.clipId !== "v2" || ext.prompt !== "cube" || ext.modelId !== "mock:mp4:v1") throw new Error("extend id");
if (ext.duration !== "8" || ext.aspect !== "9:16" || ext.resolution !== "1280x720" || ext.seed !== "11") {
  throw new Error("extend settings " + JSON.stringify(ext));
}
const lib = feedFromLibrary([
  { id: "1", asset_id: "vid", prompt: "clip", media_kind: "video", saved_at: "2026-02-03" },
  { id: "2", asset_id: "img", prompt: "still", media_kind: "image", saved_at: "2026-02-04" },
  { id: "3", asset_id: "gone", prompt: "x", media_kind: "video", trashed_at: "2026-02-05", saved_at: "2026-02-05" },
]);
if (lib.length !== 1 || lib[0].assetId !== "vid") throw new Error("library filter");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_how_steps_cost_and_demo_default() -> None:
    script = """
if (VIDEO_HOW_STEPS.length !== 3) throw new Error("how steps");
if (VIDEO_TABS.join() !== "Create,Edit,Motion control") throw new Error("tabs");
if (generateCost(0.35) !== 0.35) throw new Error("cost");
if (toggleFavorite(["a"], "a").length !== 0) throw new Error("unfav");
const fav = applyFavorites([{ id: "a", assetId: "a", prompt: "", modelId: "", createdAt: "", favorite: false, mediaKind: "video" }], ["a"]);
if (!fav[0].favorite) throw new Error("apply fav");
const readyId = defaultVideoModelId(
  [
    { id: "live", display_name: "Live", provider: "fal", capabilities: ["t2v"] },
    { id: "mock:mp4:v1", display_name: "Mock MP4", provider: "mock", capabilities: ["t2v"] },
  ],
  (row) => row.provider === "mock",
);
if (readyId !== "mock:mp4:v1") throw new Error("demo default");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_studio_wires_video_page_and_reuses_image_pieces() -> None:
    client = (ROOT / "apps" / "studio" / "app" / "studio-client.tsx").read_text(encoding="utf-8")
    assert "VideoPage" in client
    assert 'page === "video"' in client
    assert "setFirstFrameId(id)" in client
    assert 'openPage("video")' in client
    assert "Your clip is in History." in client
    page = (ROOT / "apps" / "studio" / "app" / "video-page.tsx").read_text(encoding="utf-8")
    assert "/library?tool=video" in page
    assert "videoModels(models, connected, availability)" in page
    assert "isVideoModel" not in page
    assert "ImageFeed" in page
    assert "VideoPresetOverlay" in page
    panel = (ROOT / "apps" / "studio" / "app" / "video-panel.tsx").read_text(encoding="utf-8")
    assert "ImageModelPicker" in panel
    assert "Extend Video" in panel
    assert "video-generate" in panel
    assert "PromptMention" in panel
    overlay = (ROOT / "apps" / "studio" / "app" / "video-preset-overlay.tsx").read_text(encoding="utf-8")
    assert "video-preset-overlay" in overlay
    feed = (ROOT / "apps" / "studio" / "app" / "image-feed.tsx").read_text(encoding="utf-8")
    assert "onExtend" in feed
    assert "Extend" in feed
