"""The model menu (COREPRODUC-666) and the Video page's input modes (COREPRODUC-667)."""

from __future__ import annotations

from ts_module import run_ts

MENU = "apps/studio/lib/model-menu.ts"
VIDEO = "apps/studio/lib/video-page.ts"

ROWS = """
const kling26 = { id: "kwaivgi/kling-v2.6-std", display_name: "Kling 2.6 Standard", provider: "vinci", capabilities: ["t2v", "i2v"],
  quality_tier: "fast", constraints: { resolutions: [], durations: [5, 10], max_duration: 10, end_frame: false, max_references: 0 } };
const seedance = { id: "bytedance/seedance-2.5", display_name: "Seedance 2.5", provider: "vinci", capabilities: ["t2v", "i2v"],
  quality_tier: "quality", pricing: { unit: "video_5s_audio" },
  constraints: { resolutions: ["480p", "1080p", "720p"], durations: [4, 30], max_duration: 30, end_frame: true, max_references: 30 } };
const veo = { id: "google/veo3.1", display_name: "Veo 3.1", provider: "vinci", capabilities: ["t2v", "i2v"], quality_tier: "quality",
  constraints: { resolutions: ["720p"], durations: [4, 8], max_duration: 8, end_frame: true, max_references: 0 } };
const hf = { id: "mcp_higgsfield:minimax_hailuo", display_name: "Higgsfield Hailuo 2.3 Fast", provider: "mcp_higgsfield", capabilities: ["i2v"],
  constraints: { durations: [6], max_duration: 6 } };
const t2vOnly = { id: "wan-2.5", display_name: "Wan 2.5", provider: "vinci", capabilities: ["t2v"], constraints: {} };
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(m + ": " + JSON.stringify(a)); };
"""


def test_rows_are_one_line_with_chips_grouped_by_family() -> None:
    body = ROWS + """
eq(menuChips(seedance), ["Refs", "Start/End", "1080p", "4–30s", "Audio"], "seedance chips: top resolution, the length range");
eq(menuChips(kling26), ["Start", "5–10s"], "kling 2.6: a start frame only");
eq([menuFamily(kling26), menuFamily(seedance), menuFamily(veo), menuFamily(hf)], ["Kling", "ByteDance", "Google", "Higgsfield"], "families");
eq(menuFamily({ ...veo, display_name: "Vinci Video Ultra", brand: "Vinci" }), "Vinci", "a host's brand is the family");
const rows = [kling26, seedance, veo, hf, t2vOnly];
const all = menuSections(rows, "");
eq(all.featured.map((m) => m.id), ["bytedance/seedance-2.5", "google/veo3.1"], "featured: the quality tier");
eq(all.groups.map((g) => [g.family, g.models.length]), [["Kling", 1], ["Higgsfield", 1], ["Alibaba", 1]], "a featured row is not listed twice");
eq(menuSections(rows, "veo").featured, [], "a search shows no Featured");
eq(menuSections(rows, "", "All", "References").groups.flatMap((g) => g.models).length + menuSections(rows, "", "All", "References").featured.length, 1, "the References filter");
eq(menuFilters(rows).features, ["All", "Start frame", "Start & end", "References", "Audio"], "features present");
"""
    run_ts(MENU, ["menuChips", "menuFamily", "menuFilters", "menuSections"], body)


def test_input_modes_gray_out_with_a_reason_and_refit_on_a_model_change() -> None:
    body = ROWS + """
eq(refModeBlock(seedance, "refs"), "", "seedance takes references");
eq(refModeBlock(kling26, "start-end"), "Kling 2.6 Standard takes a start frame only, no end frame.", "no end frame");
eq(refModeBlock(kling26, "refs"), "Kling 2.6 Standard takes no reference images.", "no references");
eq(refModeBlock(t2vOnly, "start"), "Wan 2.5 takes no start frame.", "text only");
eq(fitRefMode(kling26, "refs"), "start", "refs on Kling 2.6 moves to Start frame");
eq(fitRefMode(veo, "start-end"), "start-end", "a mode the model takes stays");
eq(fitRefMode(t2vOnly, "start"), "start", "nothing fits: the mode stays (all grayed out)");
eq(supportsEndFrame(veo) && !supportsEndFrame(kling26), true, "end frame from the catalog flag");
"""
    run_ts(VIDEO, ["fitRefMode", "refModeBlock", "supportsEndFrame"], body)
