/**
 * The model menu of the Image and Video pages (COREPRODUC-666), after Magnific's: search on top,
 * family and feature filters, a short Featured list, then every model grouped by family, one line
 * each with small chips (references, frames, resolution, length, audio) and the price. No previews.
 */

import { featuredModels, searchImageModels, type ImageModel } from "./image-page";
import { isVideoRow, takesEndFrame, takesReferences } from "./model-inputs";

export { isVideoRow, takesEndFrame, takesReferences };

/** A catalog row the menu lists (image or video). */
export type MenuModel = ImageModel & {
  constraints?: ImageModel["constraints"] & { end_frame?: boolean; max_references?: number };
};

export type MenuSections = { featured: MenuModel[]; groups: { family: string; models: MenuModel[] }[] };

const FEATURED_MAX = 6;
// Family from the model name, then from the provider (hosted rows all have provider "vinci").
const MENU_FAMILIES: [RegExp, string][] = [
  [/kling/, "Kling"],
  [/seedance|seedream|bytedance/, "ByteDance"],
  [/\bveo\b|veo\d|imagen|gemini|nano.?banana/, "Google"],
  [/\bwan\b|wan-|qwen|alibaba/, "Alibaba"],
  [/hailuo|minimax/, "MiniMax"],
  [/flux/, "FLUX"],
  [/gpt.?image|dall|openai/, "OpenAI"],
  [/ideogram/, "Ideogram"],
  [/recraft/, "Recraft"],
];
const MENU_PROVIDERS: Record<string, string> = {
  mcp_higgsfield: "Higgsfield",
  mcp_magnific: "Magnific",
  mock: "Mock",
  openai: "OpenAI",
  google: "Google",
  wavespeed: "Wavespeed",
  fal: "fal",
  elevenlabs: "ElevenLabs",
};

/** The family a model is grouped under: "Kling", "Google", "Higgsfield"… */
export function menuFamily(model: MenuModel): string {
  if (MENU_PROVIDERS[model.provider] && model.provider.startsWith("mcp_")) return MENU_PROVIDERS[model.provider]!;
  const blob = `${model.id} ${model.display_name}`.toLowerCase();
  for (const [needle, label] of MENU_FAMILIES) if (needle.test(blob)) return label;
  return MENU_PROVIDERS[model.provider] || model.provider || "Other";
}

/** The features a row has, for the Features filter: "Start frame", "Start & end", "References", "Audio", "Edit". */
export function menuFeatures(model: MenuModel): string[] {
  const caps = model.capabilities || [];
  const out: string[] = [];
  if (isVideoRow(model)) {
    if (caps.includes("i2v")) out.push("Start frame", ...(takesEndFrame(model) ? ["Start & end"] : []));
  } else if (caps.includes("i2i")) out.push("Edit");
  if (takesReferences(model)) out.push("References");
  if ((model.pricing?.unit || "").toLowerCase().includes("audio")) out.push("Audio");
  return out;
}

/** The chips at the end of a row: "Refs", "Start/End" or "Start", the top resolution, the length range, "Audio". */
export function menuChips(model: MenuModel): string[] {
  const caps = model.capabilities || [];
  const chips: string[] = [];
  if (takesReferences(model)) chips.push("Refs");
  if (isVideoRow(model) && caps.includes("i2v")) chips.push(takesEndFrame(model) ? "Start/End" : "Start");
  const sizes = model.constraints?.resolutions || [];
  const top = [...sizes].sort((a, b) => (parseInt(b, 10) || 0) - (parseInt(a, 10) || 0))[0];
  if (top) chips.push(top);
  const lengths = (model.constraints?.durations || []).map(Number).filter((n) => n > 0);
  const max = Number(model.constraints?.max_duration || 0) || (lengths.length ? Math.max(...lengths) : 0);
  const min = lengths.length ? Math.min(...lengths) : max;
  if (max) chips.push(min && min < max ? `${min}–${max}s` : `${max}s`);
  if ((model.pricing?.unit || "").toLowerCase().includes("audio")) chips.push("Audio");
  return chips;
}

/** Filter chips: the families and features present in these rows, each after "All". */
export function menuFilters(models: readonly MenuModel[]): { families: string[]; features: string[] } {
  const families = [...new Set(models.map(menuFamily))];
  const order = ["Start frame", "Start & end", "References", "Edit", "Audio"];
  const features = order.filter((f) => models.some((m) => menuFeatures(m).includes(f)));
  return { families: ["All", ...families], features: ["All", ...features] };
}

/**
 * The menu's lists for a search and the filters: Featured (up to 6 quality-tier rows, only with no
 * search), then the other matches grouped by family in catalog order.
 */
export function menuSections(models: readonly MenuModel[], query: string, family = "All", feature = "All"): MenuSections {
  const hits = (searchImageModels(models, query) as MenuModel[]).filter(
    (m) => (family === "All" || menuFamily(m) === family) && (feature === "All" || menuFeatures(m).includes(feature)),
  );
  const featured = query.trim() ? [] : (featuredModels(hits) as MenuModel[]).slice(0, FEATURED_MAX);
  const shown = new Set(featured.map((m) => m.id)); // a featured row is not listed twice
  const groups: MenuSections["groups"] = [];
  for (const m of hits.filter((row) => !shown.has(row.id))) {
    const name = menuFamily(m);
    const group = groups.find((g) => g.family === name) || groups[groups.push({ family: name, models: [] }) - 1]!;
    group.models.push(m);
  }
  return { featured, groups };
}

