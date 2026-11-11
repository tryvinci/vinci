/**
 * Magnific Spaces node-card controls (Studio UX spec PR 3).
 *
 * Pure functions over node params. No React, DOM, or imports: tests load
 * this file on its own (tests/test_canvas_node.py).
 *
 * Card and inspector read the same params, so a prompt (or model, aspect,
 * resolution, count, seed, refs) typed in one place is what the other shows.
 */

export type RefRole = "style" | "character";
export type NodeReference = { role: RefRole; assetId: string };
export type StartCard = { capability: string; label: string; blurb: string };

export const REF_LIMIT = 8;
export const REF_ROLES: RefRole[] = ["style", "character"];
export const COUNT_MIN = 1;
export const COUNT_MAX = 10;
/** Magnific Image Generator aspect chips when a model does not list its own. */
export const ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4"];
/** Magnific Image Generator resolution chips when a model does not list its own. */
export const RESOLUTIONS = ["1K", "2K", "4K"];

/**
 * Empty-space "Choose your first node" cards.
 *
 * Magnific's five starters that this Studio can insert today (Image Gen, Video
 * Gen, Upscaler, Image Editor, Voiceover). The add-node popover lists Media,
 * Text, List, Note, and Assistant with the rest.
 */
export const START_CARDS: StartCard[] = [
  { capability: "t2i", label: "Image Gen", blurb: "Generate an image from a prompt" },
  { capability: "t2v", label: "Video Gen", blurb: "Generate a video from a prompt" },
  { capability: "upscale", label: "Upscaler", blurb: "Enlarge and sharpen an image" },
  { capability: "i2i", label: "Image Editor", blurb: "Restyle or edit an image with a prompt" },
  { capability: "tts", label: "Voiceover", blurb: "Speak a prompt as audio" },
];

/**
 * Cinema stack rows in the inspector's Advanced section (COREPRODUC-525). The runtime folds a
 * set value into the prompt (compose_shot_prompt), for example "85mm lens" or "neon lighting".
 */
export const SHOT_ROWS = [
  { key: "camera", label: "Camera", values: ["locked-off", "handheld", "tracking", "crane", "aerial"] },
  { key: "lens", label: "Lens", values: ["24mm", "35mm", "50mm", "85mm", "anamorphic"] },
  { key: "aperture", label: "Aperture", values: ["f/1.4", "f/2.8", "f/5.6", "f/11"] },
  { key: "look", label: "Look", values: ["commercial", "documentary", "noir", "fashion", "product"] },
  { key: "genre", label: "Genre", values: ["action", "drama", "documentary", "music-video"] },
  { key: "lighting", label: "Lighting", values: ["available", "studio", "golden-hour", "overcast", "neon", "moonlight", "practical"] },
  { key: "palette", label: "Palette", values: ["filmic", "teal-orange", "bleach", "tungsten", "daylight", "pastel", "verdant"] },
];
export const MOTIONS = ["static", "pan", "orbit", "push-in", "pull-out"];
/** Values that add no words to the prompt: unset, natural light, filmic grade, no camera move. */
export const OPTICAL_NEUTRAL: Record<string, string> = {
  camera: "", lens: "", look: "", lighting: "available", palette: "filmic", motion: "static", aperture: "", genre: "",
};

const COUNTED = new Set(["t2i", "i2i", "t2v", "i2v"]);

/** Shot rows for a node: image and video generators; camera motion only for video. */
export function shotRows(capability?: string): { key: string; label: string; values: string[] }[] {
  if (!COUNTED.has(capability || "")) return [];
  const video = capability === "t2v" || capability === "i2v";
  return video ? [...SHOT_ROWS, { key: "motion", label: "Camera motion", values: MOTIONS }] : SHOT_ROWS;
}

/** The shot value a node has set, or "" (a skill placeholder such as {{inputs.camera}} counts as unset). */
export function shotValue(params: Record<string, unknown> | undefined, key: string): string {
  const raw = params?.[key];
  return typeof raw === "string" && !isTemplate(raw) ? raw : "";
}

/** The patch for a shot pill press: pressing the set value again clears it to the neutral value. */
export function shotPatch(params: Record<string, unknown> | undefined, key: string, value: string): Record<string, string> {
  return { [key]: shotValue(params, key) === value ? OPTICAL_NEUTRAL[key] ?? "" : value };
}

/** True when this capability shows the 1–10 count stepper (Magnific Image / Video Gen). */
export function showsCount(capability?: string): boolean {
  return COUNTED.has(capability || "");
}

/** True when this capability shows aspect and resolution chips. */
export function showsFrame(capability?: string): boolean {
  return capability === "t2i" || capability === "i2i" || capability === "t2v" || capability === "i2v";
}

export function clampCount(value: unknown): number {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return COUNT_MIN;
  return Math.min(COUNT_MAX, Math.max(COUNT_MIN, n));
}

export function isTemplate(value: unknown): boolean {
  return typeof value === "string" && value.trim().startsWith("{{");
}

/** Prompt shown on the card and in the inspector. A page-prompt template reads as empty. */
export function promptValue(params: Record<string, unknown> | undefined): string {
  const v = params?.prompt;
  return typeof v === "string" && !isTemplate(v) ? v : "";
}

export function usesPagePrompt(params: Record<string, unknown> | undefined): boolean {
  return typeof params?.prompt === "string" && isTemplate(params.prompt);
}

/**
 * Keep `current` when it is on `listed`; otherwise the first listed value.
 * A template or a leftover from another model is not kept.
 */
export function pickListed(current: unknown, listed: string[], fallback = ""): string {
  const v = typeof current === "string" && !isTemplate(current) ? current : "";
  if (v && listed.includes(v)) return v;
  return listed[0] || fallback;
}

export function listedOr(modelList: string[] | undefined, fallback: string[]): string[] {
  return modelList && modelList.length ? modelList : fallback;
}

type FitConstraints = { aspect_ratios?: string[]; resolutions?: string[]; durations?: number[]; max_duration?: number };

/**
 * The params a run sends for a node, fitted to its model as the node's pills show them. A value the
 * model does not list went to the provider raw: a `1K` resolution on Seedream 4.5 (the pill said
 * 1024x1024) or 5 s on a 6 s model got HTTP 400 (COREPRODUC-576). Templates and empty values stay.
 * A duration gets the shortest listed length that covers it, else the longest: the same rule as the
 * runtime's `fit_duration`, which also fits nodes this cannot see (COREPRODUC-580).
 *
 * Args:
 *   params: The node's params.
 *   limits: The model's catalog constraints.
 */
export function fitToModel(params: Record<string, unknown>, limits?: FitConstraints): Record<string, unknown> {
  const out = { ...params };
  const concrete = (v: unknown) => typeof v === "string" && v !== "" && !isTemplate(v);
  if (limits?.aspect_ratios?.length && concrete(out.aspect_ratio)) out.aspect_ratio = pickListed(out.aspect_ratio, limits.aspect_ratios);
  if (limits?.resolutions?.length && concrete(out.resolution)) out.resolution = pickListed(out.resolution, limits.resolutions);
  const seconds = Number(out.duration);
  if (out.duration !== undefined && out.duration !== "" && Number.isFinite(seconds)) {
    const allowed = [...(limits?.durations ?? [])].sort((a, b) => a - b);
    if (allowed.length && !allowed.includes(seconds)) {
      out.duration = allowed.find((d) => d >= seconds) ?? allowed[allowed.length - 1];
    } else if (!allowed.length && limits?.max_duration && seconds > limits.max_duration) {
      out.duration = limits.max_duration;
    }
  }
  return out;
}

export function countValue(params: Record<string, unknown> | undefined): number {
  return clampCount(params?.count ?? params?.num_images ?? COUNT_MIN);
}

/** `count` plus `num_images` so Higgsfield-style providers see the same stepper. */
export function countPatch(value: unknown): { count: number; num_images: number } {
  const count = clampCount(value);
  return { count, num_images: count };
}

export function seedValue(params: Record<string, unknown> | undefined): string {
  const v = params?.seed;
  if (v == null || v === "") return "";
  return String(v);
}

export function refsOf(params: Record<string, unknown> | undefined): NodeReference[] {
  const raw = params?.references;
  if (Array.isArray(raw)) {
    const out: NodeReference[] = [];
    for (const row of raw) {
      if (!row || typeof row !== "object") continue;
      const rec = row as { role?: unknown; assetId?: unknown };
      if ((rec.role === "style" || rec.role === "character") && typeof rec.assetId === "string" && rec.assetId) {
        out.push({ role: rec.role, assetId: rec.assetId });
      }
      if (out.length === REF_LIMIT) break;
    }
    return out;
  }
  const urls = params?.image_urls;
  if (!Array.isArray(urls)) return [];
  return urls
    .filter((id): id is string => typeof id === "string" && id.length > 0)
    .slice(0, REF_LIMIT)
    .map((assetId) => ({ role: "style" as const, assetId }));
}

/** First Style / Character slot (Magnific inspector). Further refs of that role stay in `refsOf`. */
export function slotRef(refs: NodeReference[], role: RefRole): NodeReference | undefined {
  return refs.find((row) => row.role === role);
}

/** Next empty Magnific slot: Style, then Character, then more Style. */
export function nextRefRole(refs: NodeReference[]): RefRole {
  if (!refs.some((row) => row.role === "style")) return "style";
  if (!refs.some((row) => row.role === "character")) return "character";
  return "style";
}

export function withRefs(
  params: Record<string, unknown> | undefined,
  refs: NodeReference[],
): Record<string, unknown> {
  const next = refs.slice(0, REF_LIMIT);
  return { ...(params || {}), references: next, image_urls: next.map((row) => row.assetId) };
}

export function addRef(
  params: Record<string, unknown> | undefined,
  role: RefRole,
  assetId: string,
): Record<string, unknown> {
  const refs = refsOf(params);
  if (!assetId || refs.length >= REF_LIMIT || refs.some((row) => row.assetId === assetId)) {
    return params || {};
  }
  return withRefs(params, [...refs, { role, assetId }]);
}

export function removeRef(params: Record<string, unknown> | undefined, assetId: string): Record<string, unknown> {
  return withRefs(
    params,
    refsOf(params).filter((row) => row.assetId !== assetId),
  );
}
