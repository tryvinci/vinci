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

const COUNTED = new Set(["t2i", "i2i", "t2v", "i2v"]);

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
