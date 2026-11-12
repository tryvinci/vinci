/**
 * Video page rules (Higgsfield Video).
 *
 * Membership is `modelsFor("video")` (text-to-video, then image-to-video).
 * Preset cards are those catalog rows (no invented effect names).
 * Quality tiles are catalog resolutions. Duration tiles are the Studio list
 * already used on the inspector, clipped by `max_duration`.
 * Extend copies the clip's last frame plus the run's own settings.
 */

import { modelsFor, tieBreakAvailability, withoutMockWhenConnected } from "./model-capabilities";
import { filterMentions, insertMention, mentionOpen, type MentionRow } from "./library";

export type { MentionRow };
export { filterMentions, insertMention, mentionOpen };

export type VideoModel = {
  id: string;
  display_name: string;
  provider: string;
  capabilities: string[];
  available?: boolean;
  pricing?: { amount?: number; unit?: string; currency?: string };
  constraints?: {
    aspect_ratios?: string[];
    resolutions?: string[];
    max_input_images?: number | null;
    max_duration?: number;
    durations?: number[];
  };
  quality_tier?: string;
  status?: string;
};

export type VideoFeedItem = {
  id: string;
  assetId: string;
  prompt: string;
  modelId: string;
  createdAt: string;
  favorite: boolean;
  pending?: boolean;
  mediaKind: string;
  duration?: string;
  aspect?: string;
  resolution?: string;
  seed?: string;
  steps?: string;
};

export type VideoControls = {
  duration: boolean;
  aspect: boolean;
  quality: boolean;
  audio: boolean;
  endFrame: boolean;
  advanced: boolean;
};

export type VideoRun = {
  id?: string;
  state?: string;
  outputs?: string[];
  created_at?: string;
  inputs?: {
    prompt?: unknown;
    model_id?: unknown;
    duration?: unknown;
    aspect_ratio?: unknown;
    resolution?: unknown;
    seed?: unknown;
    steps?: unknown;
  };
  skill?: string;
  workflow?: { nodes?: { model_id?: string; capability?: string }[] };
};

export type VideoAsset = { id: string; mime?: string; kind?: string; width?: number; height?: number };

export type LibraryRow = {
  id?: string;
  asset_id?: string;
  prompt?: string;
  model_id?: string;
  saved_at?: string;
  run_completed_at?: string;
  favorite?: boolean;
  media_kind?: string;
  mime?: string;
  trashed_at?: string | null;
  duration?: unknown;
  aspect_ratio?: unknown;
  resolution?: unknown;
};


export type VideoExtend = {
  clipId: string;
  prompt: string;
  modelId: string;
  duration: string;
  aspect: string;
  resolution: string;
  seed: string;
  steps: string;
};

export type VideoPresetDefaults = {
  modelId: string;
  duration: string;
  aspect: string;
  resolution: string;
};

/** Higgsfield Video empty strip: prompt, preset, generate. */
export const VIDEO_HOW_STEPS = [
  { n: "1", title: "Write a prompt", copy: "Describe the clip. Type @ to mention a person, place, or prop." },
  { n: "2", title: "Pick a preset", copy: "Press Change to pick a model. The form follows that model." },
  { n: "3", title: "Generate", copy: "The price is on the button. The clip shows up in History." },
] as const;

/** Duration tiles already used by Studio. Do not add values the catalog cannot run. */
export const VIDEO_DURATION_PICKS = [3, 5, 6, 8, 10, 15] as const;

export const VIDEO_TABS = ["Create", "Edit", "Motion control"] as const;

/** Families taken from catalog ids / display names. No invented labels. */
const FAMILIES: [string, string][] = [
  ["kling", "Kling"],
  ["wan", "Wan"],
  ["seedance", "Seedance"],
  ["hailuo", "Hailuo"],
  ["veo", "Veo"],
  ["dop", "DoP"],
];

/**
 * Models that belong on the Video page.
 *
 * `modelsFor("video")` keeps text-to-video and image-to-video. Stills stay out.
 * Mock is hidden when `connectedProviders` includes a real provider.
 * `availability` breaks ties only after the modelsFor rank.
 *
 * Args:
 *   models: Catalog rows.
 *   connectedProviders: Doctor ids. Omit to keep every provider in `models`, including mock.
 *   availability: Lower is more usable. Omit to keep modelsFor order.
 * Returns:
 *   Video rows for the picker and the preset overlay.
 */
export function videoModels(
  models: readonly VideoModel[],
  connectedProviders?: readonly string[],
  availability?: (row: VideoModel) => number,
): VideoModel[] {
  const providers = connectedProviders?.length
    ? connectedProviders
    : [...new Set(models.map((row) => row.provider).filter(Boolean))];
  let listed = modelsFor("video", providers, models);
  if (connectedProviders) listed = withoutMockWhenConnected(listed, connectedProviders);
  if (availability) listed = tieBreakAvailability("video", listed, availability);
  return listed;
}

/** True when the row is a video generator. */
export function isVideoModel(model: VideoModel | undefined): boolean {
  const caps = model?.capabilities || [];
  return caps.includes("t2v") || caps.includes("i2v");
}

/**
 * Duration tiles for a model: Studio picks that fit `max_duration`. A model whose catalog row
 * lists the exact lengths it takes (`durations`, from the provider's API docs) shows only those:
 * all of them when there are few (Kling 2.6: 5, 10), else the Studio picks among them.
 *
 * Args:
 *   max: Catalog max duration in seconds.
 *   allowed: Catalog `durations`, the exact lengths the model takes (empty: any up to max).
 */
export function durationOptions(max: number, allowed: readonly number[] = []): number[] {
  if (allowed.length) {
    return allowed.length <= VIDEO_DURATION_PICKS.length
      ? [...allowed]
      : VIDEO_DURATION_PICKS.filter((n) => allowed.includes(n));
  }
  const cap = Number(max || 0);
  if (!cap) return [];
  const picks = VIDEO_DURATION_PICKS.filter((n) => n <= cap);
  if (!picks.length) return [cap];
  return [...new Set(picks)];
}

/**
 * Closest catalog aspect to a start-frame size.
 *
 * Args:
 *   width: Frame width.
 *   height: Frame height.
 *   ratios: Catalog aspect strings (`16:9`).
 */
export function closestAspect(width: number, height: number, ratios: readonly string[]): string {
  if (!width || !height || !ratios.length) return ratios[0] || "";
  const value = width / height;
  let best = ratios[0];
  let diff = Infinity;
  for (const ratio of ratios) {
    const parts = ratio.split(":");
    const a = Number(parts[0]);
    const b = Number(parts[1]);
    if (!a || !b) continue;
    const d = Math.abs(value - a / b);
    if (d < diff) {
      diff = d;
      best = ratio;
    }
  }
  return best;
}

/** True when pricing already includes an audio unit. */
export function hasAudio(model: VideoModel | undefined): boolean {
  return (model?.pricing?.unit || "").toLowerCase().includes("audio");
}

/** True when the catalog id is a first/last-frame model. */
export function supportsEndFrame(model: VideoModel | undefined): boolean {
  const blob = `${model?.id || ""} ${model?.display_name || ""}`.toLowerCase();
  return blob.includes("flf") || blob.includes("first-last") || blob.includes("first_last");
}

/** i2v-only models need a start frame (or an Extend last frame). */
export function needsStartFrame(model: VideoModel | undefined): boolean {
  const caps = model?.capabilities || [];
  return caps.includes("i2v") && !caps.includes("t2v");
}

/**
 * Which left-panel tiles the selected model supports.
 *
 * Args:
 *   model: Catalog row.
 */
export function visibleVideoControls(model: VideoModel | undefined): VideoControls {
  return {
    duration: durationOptions(Number(model?.constraints?.max_duration || 0), model?.constraints?.durations).length > 0,
    aspect: Boolean(model?.constraints?.aspect_ratios?.length),
    quality: Boolean(model?.constraints?.resolutions?.length),
    audio: hasAudio(model),
    endFrame: supportsEndFrame(model),
    advanced: true,
  };
}

/**
 * Family tab label from the catalog name. Falls back to the provider.
 *
 * Args:
 *   model: Catalog row.
 */
export function modelFamily(model: VideoModel | undefined): string {
  const blob = `${model?.id || ""} ${model?.display_name || ""}`.toLowerCase();
  for (const [needle, label] of FAMILIES) {
    if (blob.includes(needle)) return label;
  }
  if (model?.provider === "mock") return "Mock";
  return model?.provider || "All";
}

/**
 * Overlay tabs: All, then families that exist in this catalog.
 *
 * Args:
 *   models: Video rows.
 */
export function presetTabs(models: readonly VideoModel[]): string[] {
  const seen: string[] = [];
  for (const row of models) {
    const family = modelFamily(row);
    if (!seen.includes(family)) seen.push(family);
  }
  return ["All", ...seen];
}

/**
 * Overlay filter chips derived from the catalog (no invented style tags).
 *
 * Args:
 *   models: Video rows.
 */
export function presetFilterChips(models: readonly VideoModel[]): string[] {
  const chips = ["All"];
  if (models.some((row) => (row.capabilities || []).includes("t2v"))) chips.push("t2v");
  if (models.some((row) => (row.capabilities || []).includes("i2v"))) chips.push("i2v");
  if (models.some((row) => hasAudio(row))) chips.push("Audio");
  if (models.some((row) => modelBadges(row).includes("New"))) chips.push("New");
  if (models.some((row) => modelBadges(row).includes("Beta"))) chips.push("Beta");
  return chips;
}

/**
 * Filter overlay cards by tab, chip, and search.
 *
 * Args:
 *   models: Video rows.
 *   tab: Family tab (`All` or a family).
 *   chip: Capability chip.
 *   query: Typed search.
 */
export function filterPresets(
  models: readonly VideoModel[],
  tab: string,
  chip: string,
  query: string,
): VideoModel[] {
  const q = query.trim().toLowerCase();
  return models.filter((row) => {
    if (tab !== "All" && modelFamily(row) !== tab) return false;
    const caps = row.capabilities || [];
    const badges = modelBadges(row);
    if (chip === "t2v" && !caps.includes("t2v")) return false;
    if (chip === "i2v" && !caps.includes("i2v")) return false;
    if (chip === "Audio" && !hasAudio(row)) return false;
    if (chip === "New" && !badges.includes("New")) return false;
    if (chip === "Beta" && !badges.includes("Beta")) return false;
    if (!q) return true;
    const blob = `${row.display_name} ${row.provider} ${row.id}`.toLowerCase();
    return blob.includes(q);
  });
}

/**
 * Fill the form from a picked catalog model. Prompt stays as typed.
 *
 * Args:
 *   model: Catalog row.
 */
export function applyPreset(model: VideoModel | undefined): VideoPresetDefaults {
  if (!model) return { modelId: "", duration: "", aspect: "", resolution: "" };
  const durs = durationOptions(Number(model.constraints?.max_duration || 0), model.constraints?.durations);
  const ratios = model.constraints?.aspect_ratios || [];
  const res = model.constraints?.resolutions || [];
  return {
    modelId: model.id,
    duration: durs.includes(5) ? "5" : String(durs[0] || ""),
    aspect: ratios[0] || "",
    resolution: res[0] || "",
  };
}

/**
 * Preset values only for the settings the model cannot use, so the settings a person chose stay.
 *
 * Args:
 *   model: The video model.
 *   current: The duration, aspect and resolution set now.
 * Returns:
 *   applyPreset's value for each setting that is empty or not in the model's lists; nothing for the others.
 */
export function presetFixes(
  model: VideoModel | undefined,
  current: { duration: string; aspect: string; resolution: string },
): Partial<VideoPresetDefaults> {
  const preset = applyPreset(model);
  const durs = durationOptions(Number(model?.constraints?.max_duration || 0), model?.constraints?.durations).map(String);
  const fits = (value: string, list: readonly string[]) => Boolean(value) && (!list.length || list.includes(value));
  return {
    ...(fits(current.duration, durs) ? {} : { duration: preset.duration }),
    ...(fits(current.aspect, model?.constraints?.aspect_ratios || []) ? {} : { aspect: preset.aspect }),
    ...(fits(current.resolution, model?.constraints?.resolutions || []) ? {} : { resolution: preset.resolution }),
  };
}

/** New / Beta badges from the catalog id or display name. */
export function modelBadges(model: VideoModel | undefined): string[] {
  const blob = `${model?.id || ""} ${model?.display_name || ""}`.toLowerCase();
  const badges: string[] = [];
  if (/\bnew\b/.test(blob)) badges.push("New");
  if (blob.includes("beta") || blob.includes("preview")) badges.push("Beta");
  return badges;
}

/** First ready video model (mock in demo), else the first row. */
export function defaultVideoModelId(
  models: readonly VideoModel[],
  ready: (model: VideoModel) => boolean,
): string {
  const rows = videoModels(models);
  return rows.find((row) => ready(row))?.id || rows[0]?.id || "";
}

/**
 * Build feed cards from GET /library items. Newest first. Video only. Skip trash.
 *
 * Args:
 *   items: Library index rows.
 */
export function feedFromLibrary(items: readonly LibraryRow[]): VideoFeedItem[] {
  const rows: VideoFeedItem[] = [];
  for (const item of items) {
    if (item.trashed_at) continue;
    const kind = item.media_kind || (item.mime?.startsWith("video/") ? "video" : "image");
    if (kind !== "video") continue;
    const assetId = item.asset_id || item.id || "";
    if (!assetId) continue;
    rows.push({
      id: item.id || assetId,
      assetId,
      prompt: String(item.prompt || ""),
      modelId: String(item.model_id || ""),
      createdAt: item.saved_at || item.run_completed_at || "",
      favorite: Boolean(item.favorite),
      mediaKind: "video",
      duration: item.duration == null ? "" : String(item.duration),
      aspect: item.aspect_ratio == null ? "" : String(item.aspect_ratio),
      resolution: item.resolution == null ? "" : String(item.resolution),
    });
  }
  rows.sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0));
  return rows;
}

/**
 * Fallback when /library is missing: video outputs from /runs + /assets.
 *
 * Args:
 *   runs: Daemon run list (oldest first).
 *   assets: Asset index.
 */
export function feedFromRuns(runs: readonly VideoRun[], assets: readonly VideoAsset[]): VideoFeedItem[] {
  const byId = new Map(assets.map((row) => [row.id, row]));
  const rows: VideoFeedItem[] = [];
  for (const run of runs) {
    const prompt = String(run.inputs?.prompt || "");
    const modelId = String(
      run.inputs?.model_id || run.workflow?.nodes?.find((n) => n.model_id)?.model_id || "",
    );
    for (const assetId of run.outputs || []) {
      const asset = byId.get(assetId);
      const mime = asset?.mime || "";
      if (!mime.startsWith("video/") && asset?.kind !== "video") continue;
      rows.push({
        id: `${run.id || "run"}:${assetId}`,
        assetId,
        prompt,
        modelId,
        createdAt: run.created_at || "",
        favorite: false,
        mediaKind: "video",
        duration: run.inputs?.duration == null ? "" : String(run.inputs.duration),
        aspect: run.inputs?.aspect_ratio == null ? "" : String(run.inputs.aspect_ratio),
        resolution: run.inputs?.resolution == null ? "" : String(run.inputs.resolution),
        seed: run.inputs?.seed == null ? "" : String(run.inputs.seed),
        steps: run.inputs?.steps == null ? "" : String(run.inputs.steps),
      });
    }
  }
  return rows.reverse();
}

/**
 * Pending cards sit above completed rows while a run is in flight.
 *
 * Args:
 *   items: Completed feed.
 *   pending: How many Generate slots are running.
 */
export function withPendingCards(items: readonly VideoFeedItem[], pending: number): VideoFeedItem[] {
  const count = Math.max(0, Math.min(4, Math.floor(pending)));
  if (!count) return items.slice();
  const cards: VideoFeedItem[] = [];
  for (let i = 0; i < count; i += 1) {
    cards.push({
      id: `pending-${i}`,
      assetId: "",
      prompt: "",
      modelId: "",
      createdAt: "",
      favorite: false,
      pending: true,
      mediaKind: "video",
    });
  }
  return cards.concat(items);
}

/** Catalog price. Unknown price stays 0. */
export function generateCost(amount: number | undefined): number {
  return Number(amount || 0);
}

/**
 * Extend a History clip: last-frame slot is filled by the page; settings come from the card.
 *
 * Args:
 *   item: Feed card.
 */
export function extendFromItem(item: VideoFeedItem): VideoExtend {
  return {
    clipId: item.assetId,
    prompt: item.prompt,
    modelId: item.modelId,
    duration: item.duration || "",
    aspect: item.aspect || "",
    resolution: item.resolution || "",
    seed: item.seed || "",
    steps: item.steps || "",
  };
}

/** Toggle an id in the local favorite set. */
export function toggleFavorite(ids: readonly string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((row) => row !== id) : [...ids, id];
}

/** Apply local favorite ids onto feed rows. */
export function applyFavorites(items: readonly VideoFeedItem[], ids: readonly string[]): VideoFeedItem[] {
  const set = new Set(ids);
  return items.map((row) => ({ ...row, favorite: row.favorite || set.has(row.id) || set.has(row.assetId) }));
}
