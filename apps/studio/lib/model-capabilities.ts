/**
 * Capability registry for Studio pickers.
 *
 * Catalog rows stay a capability list, constraints, and `quality_tier`.
 * This module classifies each row into functions (text, image, video, upscale,
 * audio, and the rest) and the inputs that model accepts. `modelsFor` is the
 * only picker filter. Connecting a provider key changes `connectedProviders`;
 * the user never sees or edits the mapping.
 *
 * No imports: `tests/test_model_capabilities.py` transpiles this file alone.
 */

export type Surface =
  | "image"
  | "image_edit"
  | "video"
  | "video_t2v"
  | "video_i2v"
  | "video_extend"
  | "upscale"
  | "video_upscale"
  | "audio"
  | "speak"
  | "text"
  | "effects"
  | "canvas";

/** What a model can do. One catalog capability can set more than one function. */
export type ModelFunction =
  | "text"
  | "image_gen"
  | "image_edit"
  | "video_t2v"
  | "video_i2v"
  | "video_extend"
  | "image_upscale"
  | "video_upscale"
  | "audio_tts"
  | "audio_sts"
  | "audio_voice"
  | "audio_music"
  | "audio_sfx"
  | "lipsync"
  | "transcribe"
  | "reframe"
  | "caption";

/** Inputs a model accepts. Aspect ratios and resolutions stay on the classified row. */
export type ModelInput =
  | "prompt"
  | "references"
  | "start_frame"
  | "end_frame"
  | "mask"
  | "audio"
  | "aspect_ratio"
  | "resolution"
  | "duration";

export type CatalogRow = {
  id: string;
  display_name?: string;
  provider?: string;
  capabilities?: readonly string[];
  quality_tier?: string;
  status?: string;
  pricing?: { amount?: number; unit?: string; currency?: string };
  constraints?: {
    aspect_ratios?: readonly string[];
    resolutions?: readonly string[];
    max_duration?: number | null;
    max_input_images?: number | null;
  };
  available?: boolean;
};

export type ClassifiedModel = {
  id: string;
  provider: string;
  functions: ModelFunction[];
  /** Supported inputs. `required` is the subset the run cannot omit. */
  inputs: ModelInput[];
  required: ModelInput[];
  aspectRatios: string[];
  resolutions: string[];
  maxDuration: number | null;
  /** Declared reference cap. Null means the catalog does not give a number. */
  maxReferences: number | null;
  qualityTier: string;
  /** Model emits an audio track (TTS, or a video unit priced with audio). */
  generatesAudio: boolean;
  status: string;
  price: number;
  /** The row's own `pricing.currency`, when it has one (a model on the user's own key on a host). */
  currency?: string;
};

export type ModelsForOptions = {
  /** Canvas node capability, or the capability an Effects preset needs. */
  capability?: string;
  /** Keep rows that support every listed input. */
  requireInputs?: readonly ModelInput[];
  /** Drop sunset and deprecated rows. Default true. */
  activeOnly?: boolean;
};

const FUNCTIONS: ModelFunction[] = [
  "text",
  "image_gen",
  "image_edit",
  "video_t2v",
  "video_i2v",
  "video_extend",
  "image_upscale",
  "video_upscale",
  "audio_tts",
  "audio_sts",
  "audio_voice",
  "audio_music",
  "audio_sfx",
  "lipsync",
  "transcribe",
  "reframe",
  "caption",
];

const INPUTS: ModelInput[] = [
  "prompt",
  "references",
  "start_frame",
  "end_frame",
  "mask",
  "audio",
  "aspect_ratio",
  "resolution",
  "duration",
];

const SURFACES: Surface[] = [
  "image",
  "image_edit",
  "video",
  "video_t2v",
  "video_i2v",
  "video_extend",
  "upscale",
  "video_upscale",
  "audio",
  "speak",
  "text",
  "effects",
  "canvas",
];

const MEDIA_CAPS = new Set([
  "t2i",
  "i2i",
  "t2v",
  "i2v",
  "lipsync",
  "tts",
  "sts",
  "voice_clone",
  "upscale",
  "transcribe",
  "reframe",
  "caption",
  "edit_multi",
  "music",
  "sfx",
]);

const TEXT_CAPS = new Set(["llm", "chat", "text", "assistant", "t2t"]);

const CAPABILITY_FUNCTIONS: Record<string, ModelFunction[]> = {
  t2i: ["image_gen"],
  i2i: ["image_edit"],
  edit_multi: ["image_edit"],
  t2v: ["video_t2v"],
  i2v: ["video_i2v"],
  extend: ["video_extend"],
  upscale: ["image_upscale", "video_upscale"],
  tts: ["audio_tts"],
  sts: ["audio_sts"],
  voice_clone: ["audio_voice"],
  music: ["audio_music"],
  sfx: ["audio_sfx"],
  lipsync: ["lipsync"],
  transcribe: ["transcribe"],
  reframe: ["reframe"],
  caption: ["caption"],
  llm: ["text"],
  t2t: ["text"],
  chat: ["text"],
  text: ["text"],
  assistant: ["text"],
};

const SURFACE_FUNCTIONS: Record<string, ModelFunction[]> = {
  image: ["image_gen"],
  image_edit: ["image_edit"],
  video: ["video_t2v", "video_i2v"],
  video_t2v: ["video_t2v"],
  video_i2v: ["video_i2v"],
  video_extend: ["video_extend"],
  upscale: ["image_upscale"],
  video_upscale: ["video_upscale"],
  audio: ["audio_tts", "audio_sts", "audio_voice"],
  speak: ["audio_tts", "lipsync", "video_i2v"],
  text: ["text"],
};

const CANVAS_PAGE_FUNCTIONS: ModelFunction[] = [
  "image_gen",
  "image_edit",
  "video_t2v",
  "video_i2v",
];

function blobOf(model: CatalogRow): string {
  return `${model.id || ""} ${model.display_name || ""}`.toLowerCase();
}

function capSet(model: CatalogRow): Set<string> {
  return new Set((model.capabilities || []).map((cap) => String(cap).toLowerCase()));
}

function hasEndFrame(blob: string): boolean {
  return blob.includes("flf") || blob.includes("first-last") || blob.includes("first_last");
}

function hasMask(blob: string): boolean {
  return blob.includes("inpaint") || blob.includes("mask");
}

/**
 * True when the row is a text model.
 *
 * Media rows that mention gpt or gemini stay media. A row is text when it
 * lists llm/chat/text/assistant/t2t, or when it has no media capability and its
 * id is a chat model. Bundled text rows use t2t (OLF script drafts).
 */
function isTextModel(model: CatalogRow, caps: Set<string>): boolean {
  for (const cap of caps) {
    if (TEXT_CAPS.has(cap)) return true;
  }
  for (const cap of caps) {
    if (MEDIA_CAPS.has(cap)) return false;
  }
  const id = (model.id || "").toLowerCase();
  if (id.includes("image") || id.includes("imagen")) return false;
  return /(^|:)(gpt-[45]|gpt-4o|o1|o3|claude|llama|mistral|gemini)([-:]|$)/.test(id);
}

/** Shown in place of "$0" for a model with no flat price. */
export const PRICE_VARIES = "price varies";

/**
 * True for a non-mock model with no flat price. OpenAI image models bill per token, so the
 * catalog amount is 0, which means "unknown", not "free". Mock is free by design.
 * Mirrors `price_key` in `vinci_core/catalog.py` (COREPRODUC-529).
 */
export function isUnpriced(model: { provider?: string; pricing?: { amount?: number } }): boolean {
  return model.provider !== "mock" && !(Number(model.pricing?.amount) > 0);
}

/** Unit of every price in this Studio: USD (local daemon) or credits (a host that bills in credits). */
let priceUnit: "usd" | "credits" = "usd";

/**
 * Set the price unit from `host.currency` in `GET /doctor`. Any other value means USD.
 *
 * Args:
 *   unit: "credits" for a host such as Vinci Platform, otherwise undefined.
 */
export function setPriceUnit(unit?: string): void {
  priceUnit = unit === "credits" ? "credits" : "usd";
}

/**
 * Price text in the Studio's unit: "$0.160" in USD, "2 credits" when the host bills in credits.
 *
 * Args:
 *   n: Amount in the current unit (catalog `pricing.amount` or a sum of them).
 *   currency: The row's own `pricing.currency`, when it can differ from the Studio's unit: on a
 *     host, a model on the user's own key is priced in USD (COREPRODUC-613).
 * Returns:
 *   The label for Generate buttons, model rows, run bars and totals.
 */
export function money(n: number | undefined, currency?: string): string {
  const v = Number(n || 0);
  const unit = currency ? (currency.toLowerCase() === "credits" ? "credits" : "usd") : priceUnit;
  if (unit === "credits") return `${Number(v.toFixed(2))} ${v === 1 ? "credit" : "credits"}`;
  if (v === 0) return "$0";
  if (v < 0.01) return "$" + v.toFixed(5).replace(/0+$/, "").replace(/\.$/, "");
  return "$" + v.toFixed(3);
}

function ordered<T extends string>(all: readonly T[], picked: Set<T>): T[] {
  return all.filter((item) => picked.has(item));
}

/**
 * Classify one catalog row.
 *
 * Args:
 *   model: A `/models` row or a bundled catalog entry.
 * Returns:
 *   Functions, inputs, and the constraint fields pickers already show.
 */
export function classifyModel(model: CatalogRow): ClassifiedModel {
  const caps = capSet(model);
  const blob = blobOf(model);
  const functions = new Set<ModelFunction>();
  const inputs = new Set<ModelInput>();
  const required = new Set<ModelInput>();

  if (isTextModel(model, caps)) functions.add("text");
  if (caps.has("t2i")) functions.add("image_gen");
  const edits = caps.has("i2i") || caps.has("edit_multi");
  const upscale = caps.has("upscale");
  // An upscaler that also lists i2i is an upscaler, not an image editor.
  if (edits && !(upscale && !caps.has("t2i"))) functions.add("image_edit");
  if (caps.has("t2v")) functions.add("video_t2v");
  if (caps.has("i2v")) {
    functions.add("video_i2v");
    // Extend sends the clip's last frame as the start frame.
    functions.add("video_extend");
  }
  if (upscale) {
    const still = caps.has("i2i") || caps.has("t2i") || caps.has("edit_multi");
    const motion = caps.has("t2v") || caps.has("i2v") || caps.has("reframe") || caps.has("caption");
    const video = blob.includes("video") || (motion && !still);
    if (video && !still) functions.add("video_upscale");
    else functions.add("image_upscale");
  }
  if (caps.has("tts")) functions.add("audio_tts");
  if (caps.has("sts")) functions.add("audio_sts");
  if (caps.has("voice_clone")) functions.add("audio_voice");
  if (caps.has("music")) functions.add("audio_music"); // OLF cues (COREPRODUC-551)
  if (caps.has("sfx")) functions.add("audio_sfx");
  if (caps.has("lipsync")) functions.add("lipsync");
  if (caps.has("transcribe")) functions.add("transcribe");
  if (caps.has("reframe")) functions.add("reframe");
  if (caps.has("caption")) functions.add("caption");

  if (functions.has("image_gen") || functions.has("video_t2v") || functions.has("audio_tts")) {
    inputs.add("prompt");
    required.add("prompt");
  } else if (
    functions.has("image_edit") ||
    functions.has("video_i2v") ||
    functions.has("lipsync")
  ) {
    inputs.add("prompt");
  }

  const declaredRefs = model.constraints?.max_input_images;
  const maxReferences =
    typeof declaredRefs === "number"
      ? declaredRefs
      : blob.includes("popcorn")
        ? 8
        : null;
  const wantsRefs =
    functions.has("image_edit") ||
    blob.includes("r2v") ||
    blob.includes("reference") ||
    (maxReferences != null && maxReferences > 0);
  if (wantsRefs) inputs.add("references");
  if ((functions.has("image_edit") && !functions.has("image_gen")) || blob.includes("r2v")) {
    required.add("references");
  }

  if (functions.has("video_i2v")) inputs.add("start_frame");
  if (functions.has("video_i2v") && !functions.has("video_t2v")) required.add("start_frame");
  if (hasEndFrame(blob)) inputs.add("end_frame");
  if (hasMask(blob)) inputs.add("mask");
  if (functions.has("lipsync") || functions.has("audio_sts") || functions.has("audio_voice")) {
    inputs.add("audio");
    required.add("audio");
  }

  const aspectRatios = [...(model.constraints?.aspect_ratios || [])];
  const resolutions = [...(model.constraints?.resolutions || [])];
  const rawDuration = model.constraints?.max_duration;
  const maxDuration = rawDuration != null ? Number(rawDuration) : null;
  if (aspectRatios.length) inputs.add("aspect_ratio");
  if (resolutions.length) inputs.add("resolution");
  if (maxDuration != null && maxDuration > 0) inputs.add("duration");

  const unit = (model.pricing?.unit || "").toLowerCase();
  const generatesAudio =
    unit.includes("audio") ||
    functions.has("audio_tts") ||
    functions.has("audio_sts") ||
    functions.has("audio_voice");
  const amount = model.pricing?.amount;
  // Within a tier, an unpriced model ranks after the priced ones (the daemon's "cheapest" does the same).
  const price =
    !isUnpriced(model) && typeof amount === "number" && Number.isFinite(amount)
      ? amount
      : Number.POSITIVE_INFINITY;

  return {
    id: model.id,
    provider: model.provider || "",
    functions: ordered(FUNCTIONS, functions),
    inputs: ordered(INPUTS, inputs),
    required: ordered(INPUTS, required),
    aspectRatios,
    resolutions,
    maxDuration: maxDuration != null && Number.isFinite(maxDuration) ? maxDuration : null,
    maxReferences,
    qualityTier: model.quality_tier || "fast",
    generatesAudio,
    status: model.status || "active",
    price,
    currency: (model.pricing as { currency?: string } | undefined)?.currency,
  };
}

function functionsForCapability(capability: string): ModelFunction[] {
  return CAPABILITY_FUNCTIONS[capability.toLowerCase()] || [];
}

function functionsForSurface(surface: string, capability?: string): ModelFunction[] {
  if (surface === "effects") return capability ? functionsForCapability(capability) : [];
  if (surface === "canvas" && capability) return functionsForCapability(capability);
  if (surface === "canvas") return CANVAS_PAGE_FUNCTIONS;
  return SURFACE_FUNCTIONS[surface] || [];
}

function overlaps(have: readonly string[], want: readonly string[]): boolean {
  return want.some((item) => have.includes(item));
}

function rankOf(info: ClassifiedModel, surface: string): [number, number, number, number, string] {
  // On a host, a model on the user's own key is priced in another unit (USD next to credits). Two
  // units do not compare, so it ranks after the host's models and never becomes the default by a
  // lower number (COREPRODUC-613). Mock stays last.
  const unit = info.currency ? (info.currency.toLowerCase() === "credits" ? "credits" : "usd") : priceUnit;
  const mock = info.provider.toLowerCase() === "mock" ? 2 : unit !== priceUnit ? 1 : 0;
  let role = 0;
  if (surface === "upscale") role = info.functions.includes("image_upscale") ? 0 : 1;
  else if (surface === "video" || surface === "video_t2v") {
    role = info.functions.includes("video_t2v") ? 0 : 1;
  } else if (surface === "speak" || surface === "audio") {
    if (info.functions.includes("audio_tts")) role = 0;
    else if (info.functions.includes("lipsync") || info.functions.includes("audio_sts")) role = 1;
    else role = 2;
  }
  const quality = info.qualityTier === "quality" ? 0 : 1;
  return [mock, role, quality, info.price, info.id];
}

function compareRank(
  a: [number, number, number, number, string],
  b: [number, number, number, number, string],
): number {
  if (a[0] !== b[0]) return a[0] - b[0];
  if (a[1] !== b[1]) return a[1] - b[1];
  if (a[2] !== b[2]) return a[2] - b[2];
  if (a[3] !== b[3]) return a[3] - b[3];
  if (a[4] < b[4]) return -1;
  if (a[4] > b[4]) return 1;
  return 0;
}

/**
 * Models for one surface, from connected providers only.
 *
 * Order is the default order: a connected provider before mock, then
 * `quality_tier === "quality"`, then the lower price. `upscale` is still
 * upscalers (the Upscale still page). Clip upscalers use `video_upscale`.
 * Video prefers a text-to-video model so the default can run from a prompt.
 * Speak and audio prefer TTS.
 *
 * Args:
 *   surface: Image, video, upscale, audio, text, effects, canvas, or a narrower mode.
 *   connectedProviders: Provider ids with a saved key. Mock belongs in this list for demo mode.
 *   models: Catalog rows (bundled or `/models`, including MCP rows).
 *   options: Canvas/Effects capability, required inputs, and whether sunset rows stay.
 * Returns:
 *   The same row objects, filtered and ordered. Empty when none fit.
 */
export function modelsFor<T extends CatalogRow>(
  surface: Surface,
  connectedProviders: readonly string[],
  models: readonly T[],
  options?: ModelsForOptions,
): T[] {
  if (!SURFACES.includes(surface)) return [];
  const want = functionsForSurface(surface, options?.capability);
  if (!want.length) return [];
  const allow = new Set(connectedProviders.map((id) => id.trim().toLowerCase()).filter(Boolean));
  const activeOnly = options?.activeOnly !== false;
  const need = options?.requireInputs || [];
  const ranked: { row: T; rank: [number, number, number, number, string] }[] = [];
  for (const row of models) {
    const provider = (row.provider || "").toLowerCase();
    if (!allow.has(provider)) continue;
    const info = classifyModel(row);
    if (activeOnly && (info.status === "sunset" || info.status === "deprecated")) continue;
    if (!overlaps(info.functions, want)) continue;
    if (need.length && !need.every((input) => info.inputs.includes(input))) continue;
    ranked.push({ row, rank: rankOf(info, surface) });
  }
  ranked.sort((a, b) => compareRank(a.rank, b.rank));
  return ranked.map((item) => item.row);
}

/** Capabilities the add-node popover can place. Canvas page functions are a subset. */
const NODE_TYPE_CAPABILITIES = [
  "t2i",
  "i2i",
  "edit_multi",
  "upscale",
  "t2v",
  "i2v",
  "extend",
  "lipsync",
  "tts",
  "voice_clone",
] as const;

/**
 * Models that can back a canvas node type.
 *
 * Unions `modelsFor("canvas")` per node capability so upscale, speak, and
 * lipsync rows stay in the add popover. The popover chips still group them.
 *
 * Args:
 *   connectedProviders: Provider ids with a saved key, plus mock in demo mode.
 *   models: Catalog rows.
 * Returns:
 *   Deduped rows in capability order. Empty when none fit.
 */
export function modelsForNodeTypes<T extends CatalogRow>(
  connectedProviders: readonly string[],
  models: readonly T[],
): T[] {
  const seen = new Set<string>();
  const rows: T[] = [];
  for (const capability of NODE_TYPE_CAPABILITIES) {
    for (const row of modelsFor("canvas", connectedProviders, models, { capability })) {
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      rows.push(row);
    }
  }
  return rows;
}

/**
 * Drop mock when any other provider is connected.
 *
 * Demo mode (mock alone) keeps mock so Generate still has a model.
 * Do not filter with `provider !== "mock"` on the raw catalog; that string
 * hides mock even when it is the only provider.
 *
 * Args:
 *   rows: Already filtered by `modelsFor`.
 *   connectedProviders: Same ids passed to `modelsFor`.
 * Returns:
 *   `rows` unchanged when every connected id is mock or blank.
 */
export function withoutMockWhenConnected<T extends { provider?: string }>(
  rows: readonly T[],
  connectedProviders: readonly string[],
): T[] {
  const real = connectedProviders.some((id) => id.trim().toLowerCase() !== "mock");
  if (!real) return rows.slice();
  return rows.filter((row) => (row.provider || "").toLowerCase() !== "mock");
}

/**
 * Break ties after the `modelsFor` defaults.
 *
 * Defaults stay mock-last, then role, quality, and price. `availability`
 * (0 ready, then higher) applies only when those four match, then id.
 *
 * Args:
 *   surface: Same surface passed to `modelsFor`, so role matches.
 *   rows: `modelsFor` output, mock already removed when required.
 *   availability: Lower is more usable. Callers pass `availabilityRank`.
 * Returns:
 *   The same row objects, reordered.
 */
export function tieBreakAvailability<T extends CatalogRow>(
  surface: string,
  rows: readonly T[],
  availability: (row: T) => number,
): T[] {
  return rows
    .map((row, index) => ({
      row,
      index,
      rank: rankOf(classifyModel(row), surface),
      avail: availability(row),
    }))
    .sort((a, b) => {
      if (a.rank[0] !== b.rank[0]) return a.rank[0] - b.rank[0];
      if (a.rank[1] !== b.rank[1]) return a.rank[1] - b.rank[1];
      if (a.rank[2] !== b.rank[2]) return a.rank[2] - b.rank[2];
      if (a.rank[3] !== b.rank[3]) return a.rank[3] - b.rank[3];
      if (a.avail !== b.avail) return a.avail - b.avail;
      if (a.rank[4] < b.rank[4]) return -1;
      if (a.rank[4] > b.rank[4]) return 1;
      return a.index - b.index;
    })
    .map((item) => item.row);
}

/**
 * Default model for a surface.
 *
 * Args:
 *   surface: Same values as `modelsFor`.
 *   connectedProviders: Provider ids with a saved key.
 *   models: Catalog rows.
 *   options: Passed through to `modelsFor`.
 * Returns:
 *   The first row from `modelsFor`, or undefined when the list is empty.
 */
export function defaultModelFor<T extends CatalogRow>(
  surface: Surface,
  connectedProviders: readonly string[],
  models: readonly T[],
  options?: ModelsForOptions,
): T | undefined {
  return modelsFor(surface, connectedProviders, models, options)[0];
}

/**
 * Provider ids whose models may appear in a picker.
 *
 * A provider is connected when the daemon reports `configured` (key saved)
 * or `available`. Mock is always included so demo mode still has a model.
 *
 * Args:
 *   providers: `doctor.providers`. Undefined while Studio is loading.
 * Returns:
 *   Ids. `mock` is first.
 */
export function connectedProviderIds(
  providers: Record<string, { configured?: boolean; available?: boolean } | undefined> | undefined,
): string[] {
  const ids: string[] = [];
  const push = (id: string) => {
    const key = id.trim();
    if (!key) return;
    if (ids.some((row) => row.toLowerCase() === key.toLowerCase())) return;
    ids.push(key);
  };
  push("mock");
  for (const [id, row] of Object.entries(providers || {})) {
    if (row?.configured || row?.available) push(id);
  }
  return ids;
}

/**
 * Surface for a Studio page id.
 *
 * Args:
 *   page: Rail page (`image`, `video`, `upscale`, `speak`, `canvas`, `audio`).
 * Returns:
 *   The picker surface. Unknown pages use the canvas page set.
 */
export function surfaceForPage(page: string): Surface {
  if (
    page === "image" ||
    page === "video" ||
    page === "upscale" ||
    page === "speak" ||
    page === "canvas" ||
    page === "audio" ||
    page === "text" ||
    page === "effects"
  ) {
    return page;
  }
  return "canvas";
}
