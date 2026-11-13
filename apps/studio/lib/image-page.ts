/**
 * Image page rules (Higgsfield Image).
 *
 * Membership is `modelsFor` (text-to-image, then image edit). Featured is
 * catalog `quality_tier === "quality"`, not an invented shortlist.
 * Quality chips exist only for providers that already read `quality` (OpenAI).
 * Feed rows come from GET /library?tool=image when that index exists, else /runs.
 */

import { modelsFor, tieBreakAvailability, withoutMockWhenConnected } from "./model-capabilities";
import { filterMentions, insertMention, mentionOpen, type MentionRow } from "./library";

export type { MentionRow };
export { filterMentions, insertMention, mentionOpen };

export type ImageModel = {
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

export type ImageFeedItem = {
  id: string;
  assetId: string;
  prompt: string;
  modelId: string;
  createdAt: string;
  favorite: boolean;
  pending?: boolean;
  mediaKind: string;
};

export type ImageControls = {
  aspect: boolean;
  quality: boolean;
  resolution: boolean;
  batch: boolean;
};

export type ImageRun = {
  id?: string;
  state?: string;
  outputs?: string[];
  created_at?: string;
  inputs?: { prompt?: unknown; model_id?: unknown };
  skill?: string;
  workflow?: { nodes?: { model_id?: string; capability?: string }[] };
};

export type ImageAsset = { id: string; mime?: string; kind?: string };

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
};

/** Higgsfield Video empty strip, applied to Image: prompt, model, generate. */
export const IMAGE_HOW_STEPS = [
  { n: "1", title: "Write a prompt", copy: "Describe the still. Type @ to mention a person, place, or prop." },
  { n: "2", title: "Pick a model", copy: "Open the model list. Featured is at the top. All is under it." },
  { n: "3", title: "Generate", copy: "The price is on the button. The still shows up at the top." },
] as const;

/** Batch sizes Higgsfield Image exposes. */
export const IMAGE_BATCH = [1, 4] as const;

/** OpenAI image plugin reads these `quality` values. No other catalog lists a quality input. */
const OPENAI_QUALITY = ["low", "medium", "high"] as const;

/**
 * Models that belong on the Image page.
 *
 * Text-to-image from `modelsFor("image")`, then editors from `image_edit`
 * that are not already listed. Motion rows stay out. Mock is hidden when
 * `connectedProviders` includes a real provider. `availability` breaks ties
 * only after the modelsFor rank (mock, role, quality, price).
 *
 * Args:
 *   models: Catalog rows. A full catalog or an already filtered list.
 *   connectedProviders: Doctor ids. Omit to keep every provider in `models`, including mock.
 *   availability: Lower is more usable. Omit to keep modelsFor order.
 * Returns:
 *   Image rows for the picker.
 */
export function imageModels(
  models: readonly ImageModel[],
  connectedProviders?: readonly string[],
  availability?: (row: ImageModel) => number,
): ImageModel[] {
  const providers = connectedProviders?.length
    ? connectedProviders
    : [...new Set(models.map((row) => row.provider).filter(Boolean))];
  const seen = new Set<string>();
  let listed: ImageModel[] = [];
  for (const surface of ["image", "image_edit"] as const) {
    for (const row of modelsFor(surface, providers, models)) {
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      listed.push(row);
    }
  }
  if (connectedProviders) listed = withoutMockWhenConnected(listed, connectedProviders);
  if (availability) listed = tieBreakAvailability("image", listed, availability);
  return listed;
}

/** True when the row is a still generator or editor. */
export function isImageModel(model: ImageModel | undefined): boolean {
  const caps = model?.capabilities || [];
  if (caps.includes("t2v") || caps.includes("i2v")) return false;
  return caps.includes("t2i") || caps.includes("i2i");
}

/**
 * Featured list: catalog quality models only.
 *
 * Args:
 *   models: Already filtered image rows.
 */
export function featuredModels(models: readonly ImageModel[]): ImageModel[] {
  return models.filter((row) => row.quality_tier === "quality");
}

/**
 * One-line description from capabilities. No marketing copy.
 *
 * Args:
 *   model: Catalog row.
 */
export function modelBlurb(model: ImageModel | undefined): string {
  const caps = model?.capabilities || [];
  if (caps.includes("t2v") || caps.includes("i2v")) {
    const t2v = caps.includes("t2v");
    const i2v = caps.includes("i2v");
    if (t2v && i2v) return "Text to video and image to video";
    if (i2v) return "Image to video";
    return "Text to video";
  }
  const t2i = caps.includes("t2i");
  const i2i = caps.includes("i2i");
  if (t2i && i2i) return "Text to image and edit";
  if (i2i) return "Image edit";
  return "Text to image";
}

/**
 * New / Beta badges from the catalog id or display name.
 *
 * Args:
 *   model: Catalog row.
 */
export function modelBadges(model: ImageModel | undefined): string[] {
  const blob = `${model?.id || ""} ${model?.display_name || ""}`.toLowerCase();
  const badges: string[] = [];
  if (/\bnew\b/.test(blob)) badges.push("New");
  if (blob.includes("beta") || blob.includes("preview")) badges.push("Beta");
  return badges;
}

/**
 * Capability chips Higgsfield shows on a picker row: resolutions and refs.
 *
 * Args:
 *   model: Catalog row.
 */
export function capabilityChips(model: ImageModel | undefined): string[] {
  const chips = [...(model?.constraints?.resolutions || [])];
  const maxDur = Number(model?.constraints?.max_duration || 0);
  // The range the catalog prices ("4–30s"), not only the longest (COREPRODUC-642).
  const lengths = (model?.constraints?.durations || []).map(Number).filter((n) => n > 0);
  const minDur = lengths.length ? Math.min(...lengths) : maxDur;
  if (maxDur) chips.push(minDur && minDur < maxDur ? `${minDur}–${maxDur}s` : `${maxDur}s`);
  if ((model?.pricing?.unit || "").includes("audio")) chips.push("Audio");
  if ((model?.capabilities || []).includes("i2i")) chips.push("References");
  const max = model?.constraints?.max_input_images;
  if (max && max > 1 && !chips.includes("References")) chips.push(`References ${max}`);
  return chips;
}

/**
 * Quality values the selected provider already accepts.
 *
 * Args:
 *   model: Catalog row.
 */
export function qualityOptions(model: ImageModel | undefined): string[] {
  if (!model) return [];
  if (model.provider === "openai" && (model.capabilities || []).includes("t2i")) {
    return [...OPENAI_QUALITY];
  }
  return [];
}

/**
 * Which prompt-bar chips the selected model supports.
 *
 * Args:
 *   model: Catalog row.
 */
export function visibleControls(model: ImageModel | undefined): ImageControls {
  return {
    aspect: Boolean(model?.constraints?.aspect_ratios?.length),
    quality: qualityOptions(model).length > 0,
    resolution: Boolean(model?.constraints?.resolutions?.length),
    batch: true,
  };
}

/**
 * Rank image models the same way `rankModels` does (name, provider, id).
 *
 * Args:
 *   models: Image rows.
 *   query: Typed search.
 */
export function searchImageModels(models: readonly ImageModel[], query: string): ImageModel[] {
  const q = query.trim().toLowerCase();
  if (!q) return models.slice();
  const scored: { row: ImageModel; rank: number; index: number }[] = [];
  models.forEach((row, index) => {
    const name = (row.display_name || "").toLowerCase();
    const provider = (row.provider || "").toLowerCase();
    const id = (row.id || "").toLowerCase();
    let rank = 4;
    if (name.startsWith(q)) rank = 0;
    else if (name.includes(q)) rank = 1;
    else if (provider.includes(q)) rank = 2;
    else if (id.includes(q)) rank = 3;
    if (rank < 4) scored.push({ row, rank, index });
  });
  scored.sort((a, b) => a.rank - b.rank || a.index - b.index);
  return scored.map((item) => item.row);
}

/**
 * Split search hits into Featured (quality_tier) and the rest.
 *
 * Args:
 *   models: Search hits.
 */
export function pickerSections(models: readonly ImageModel[]): {
  featured: ImageModel[];
  all: ImageModel[];
} {
  const featured = featuredModels(models);
  const featuredIds = new Set(featured.map((row) => row.id));
  return { featured, all: models.filter((row) => !featuredIds.has(row.id)) };
}

/** First ready image model (mock in demo), else the first row. */
export function defaultImageModelId(
  models: readonly ImageModel[],
  ready: (model: ImageModel) => boolean,
): string {
  const rows = imageModels(models);
  return rows.find((row) => ready(row))?.id || rows[0]?.id || "";
}

/**
 * Build feed cards from GET /library items. Newest first. Skip trash.
 *
 * Args:
 *   items: Library index rows.
 */
export function feedFromLibrary(items: readonly LibraryRow[]): ImageFeedItem[] {
  const rows: ImageFeedItem[] = [];
  for (const item of items) {
    if (item.trashed_at) continue;
    const kind = item.media_kind || (item.mime?.startsWith("video/") ? "video" : "image");
    if (kind !== "image") continue;
    const assetId = item.asset_id || item.id || "";
    if (!assetId) continue;
    rows.push({
      id: item.id || assetId,
      assetId,
      prompt: String(item.prompt || ""),
      modelId: String(item.model_id || ""),
      createdAt: item.saved_at || item.run_completed_at || "",
      favorite: Boolean(item.favorite),
      mediaKind: "image",
    });
  }
  rows.sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0));
  return rows;
}

/**
 * Fallback when /library is missing: image outputs from /runs + /assets.
 *
 * Args:
 *   runs: Daemon run list (oldest first).
 *   assets: Asset index.
 */
export function feedFromRuns(runs: readonly ImageRun[], assets: readonly ImageAsset[]): ImageFeedItem[] {
  const byId = new Map(assets.map((row) => [row.id, row]));
  const rows: ImageFeedItem[] = [];
  for (const run of runs) {
    const prompt = String(run.inputs?.prompt || "");
    const modelId = String(
      run.inputs?.model_id || run.workflow?.nodes?.find((n) => n.model_id)?.model_id || "",
    );
    for (const assetId of run.outputs || []) {
      const asset = byId.get(assetId);
      const mime = asset?.mime || "";
      if (mime.startsWith("video/") || mime.startsWith("audio/")) continue;
      if (asset?.kind && asset.kind !== "image" && !mime.startsWith("image/")) continue;
      rows.push({
        id: `${run.id || "run"}:${assetId}`,
        assetId,
        prompt,
        modelId,
        createdAt: run.created_at || "",
        favorite: false,
        mediaKind: "image",
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
 *   pending: How many Generate slots are running (1 or 4).
 */
export function withPendingCards(items: readonly ImageFeedItem[], pending: number): ImageFeedItem[] {
  const count = Math.max(0, Math.min(4, Math.floor(pending)));
  if (!count) return items.slice();
  const cards: ImageFeedItem[] = [];
  for (let i = 0; i < count; i += 1) {
    cards.push({
      id: `pending-${i}`,
      assetId: "",
      prompt: "",
      modelId: "",
      createdAt: "",
      favorite: false,
      pending: true,
      mediaKind: "image",
    });
  }
  return cards.concat(items);
}

/** Catalog price times batch. Unknown price stays 0. */
export function generateCost(amount: number | undefined, batch: number): number {
  const n = IMAGE_BATCH.includes(batch as (typeof IMAGE_BATCH)[number]) ? batch : 1;
  return Number(amount || 0) * n;
}

/** Clamp Higgsfield batch to 1 or 4. */
export function clampBatch(value: number): number {
  return value === 4 ? 4 : 1;
}

/** Toggle an id in the local favorite set. */
export function toggleFavorite(ids: readonly string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((row) => row !== id) : [...ids, id];
}

/** Apply local favorite ids onto feed rows (used when /library has no heart yet). */
export function applyFavorites(items: readonly ImageFeedItem[], ids: readonly string[]): ImageFeedItem[] {
  const set = new Set(ids);
  return items.map((row) => ({ ...row, favorite: row.favorite || set.has(row.id) || set.has(row.assetId) }));
}

/** i2i-only models need a reference still. */
export function needsReference(model: ImageModel | undefined): boolean {
  const caps = model?.capabilities || [];
  return caps.includes("i2i") && !caps.includes("t2i");
}

/** True when the Image page sends a reference to this model (the picker's "References" tag). */
export function takesReference(model: ImageModel | undefined): boolean {
  return (model?.capabilities || []).includes("i2i");
}

/**
 * Why Generate is off on the Image page, or "" when it can run. The reason shows under the button.
 * Bug fixed (first occurrence, 2026-11-13 production crawl, COREPRODUC-638): an empty prompt ran a
 * hidden default prompt ("north-light oak cube"), and the user paid for it.
 * Bug fixed (first seen 2026-11-13 crawl, confirmed on production 2026-11-14, COREPRODUC-648): a
 * reference on a text-only model (FLUX Dev) showed a chip, but the run did not send it.
 *
 * Args:
 *   model: The selected model.
 *   prompt: The prompt box text.
 *   refs: How many reference stills are attached.
 *   models: Picker rows, to name a model that takes references. Optional.
 */
export function imageBlock(model: ImageModel | undefined, prompt: string, refs: number, models?: readonly ImageModel[]): string {
  if (model && refs && !takesReference(model)) {
    const alt = models?.find(takesReference)?.display_name;
    return `${model.display_name || "This model"} does not use references. Remove the reference, or pick ${alt || "a model with References"}.`;
  }
  if (needsReference(model) && !refs) return "This model edits a still. Add a reference first.";
  if (!prompt.trim() && (model?.capabilities || []).includes("t2i")) return "Describe the still first.";
  return "";
}
