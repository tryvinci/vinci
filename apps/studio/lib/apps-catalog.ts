/** Declarative Studio Apps registry.

 * Each app is a one-click preset: a skill, a preferred provider/model,
 * fixed params, a prompt template, and a short input form. Append to
 * `STUDIO_APPS` to add another. No daemon change is required; Generate
 * posts the built payload to the existing `/runs` API.
 *
 * Preferred models are catalog ids that already ship in
 * `packages/core/vinci_core/catalogs`. The UI pins `model_id` only when
 * that row is ready (key + live spend). Otherwise the runtime routes
 * cheapest, which is mock in demo mode.
 */

import { clipPrice } from "./canvas-node";
import { modelsFor, withoutMockWhenConnected } from "./model-capabilities";

export type AppCategory = "image" | "motion" | "cinema" | "ads" | "audio" | "upscale";
export type AppInputType = "text" | "textarea" | "select" | "number" | "media";
export type AppOutputKind = "image" | "video" | "audio";

export type AppInput = {
  id: string;
  label: string;
  type: AppInputType;
  required?: boolean;
  placeholder?: string;
  options?: string[];
  default?: string | number;
  /** Prompt slot (default) or a `/runs` input key such as `media`. */
  slot?: string;
  /** Number fields with both bounds render as a slider. */
  min?: number;
  max?: number;
  /** Shown under Advanced instead of the main form. */
  advanced?: boolean;
};

/** Magnific Creative upscaler settings (Precision ignores them). Same names as the Magnific API. */
export const MAG_STYLES = ["standard", "soft_portraits", "hard_portraits", "art_n_illustration", "films_n_photography", "3d_renders"];
export const MAG_ENGINES = ["automatic", "magnific_illusio", "magnific_sharpy", "magnific_sparkle"];
const magSlider = (id: string, label: string): AppInput => ({
  id, label, type: "number", default: 0, min: -10, max: 10, slot: id, advanced: true,
});

export type EffectPage = "speak" | "upscale" | "adapts";

export type StudioApp = {
  id: string;
  name: string;
  description: string;
  category: AppCategory;
  skill: string;
  provider: string;
  preferred_model_id: string;
  prompt_template: string;
  params: Record<string, string | number>;
  inputs: AppInput[];
  output_kind: AppOutputKind;
  /** False for multi-node skills. The runtime must pick each node. */
  pin_model?: boolean;
};

/** Default catalog app when opening an Effects rail page. */
export const EFFECT_PAGE_DEFAULTS: Readonly<Record<EffectPage, string>> = {
  speak: "talking-photo",
  upscale: "still-4k",
  adapts: "product-reveal",
};

/** Map a Studio page to its default preset id.
 *
 * Args:
 *   page: Speak, Upscale, or Adapts rail target.
 */
export function defaultAppIdForPage(page: EffectPage): string {
  return EFFECT_PAGE_DEFAULTS[page];
}

export const APP_CATEGORIES: readonly ("all" | AppCategory)[] = [
  "all",
  "image",
  "motion",
  "cinema",
  "ads",
  "audio",
  "upscale",
];

export const STUDIO_APPS: readonly StudioApp[] = [
  {
    id: "product-hero",
    name: "Product Hero",
    description: "Catalog packshot. Name the product and the surface.",
    category: "image",
    skill: "@tryvinci/image-generate",
    provider: "openai",
    preferred_model_id: "openai:gpt-image-2.5-flare:2026-09",
    prompt_template:
      "Professional product photograph of {{product}} on {{surface}}, north studio light, sharp catalog hero, no text, no hands",
    params: { aspect_ratio: "4:5", look: "product", lighting: "studio", lens: "85mm" },
    inputs: [
      { id: "product", label: "Product", type: "text", required: true, placeholder: "matte black bottle" },
      {
        id: "surface",
        label: "Surface",
        type: "select",
        required: true,
        default: "honed slate",
        options: ["honed slate", "oak table", "white cyclorama", "wet terrazzo"],
      },
    ],
    output_kind: "image",
  },
  {
    id: "editorial-portrait",
    name: "Editorial Portrait",
    description: "Magazine cover still. Subject and mood only.",
    category: "image",
    skill: "@tryvinci/image-generate",
    provider: "fal",
    preferred_model_id: "fal:flux-pro:2026-09",
    prompt_template:
      "Editorial portrait of {{subject}}, {{mood}} light, 85mm, shallow depth, print magazine cover, no type",
    params: { aspect_ratio: "4:5", look: "fashion", lens: "85mm", aperture: "f/1.4" },
    inputs: [
      { id: "subject", label: "Subject", type: "text", required: true, placeholder: "cast in a wool coat" },
      {
        id: "mood",
        label: "Mood",
        type: "select",
        required: true,
        default: "window",
        options: ["window", "hard noon", "neon night", "overcast"],
      },
    ],
    output_kind: "image",
  },
  {
    id: "renaissance-still",
    name: "Renaissance Still",
    description: "Oil-painting treatment of a scene you name.",
    category: "image",
    skill: "@tryvinci/image-generate",
    provider: "google",
    preferred_model_id: "google:gemini-flash-image:2026-08",
    prompt_template:
      "Oil painting of {{scene}} in the manner of a Northern Renaissance panel, glaze, umber ground, museum light, no frame text",
    params: { aspect_ratio: "4:5", look: "documentary", lighting: "available", palette: "filmic" },
    inputs: [{ id: "scene", label: "Scene", type: "textarea", required: true, placeholder: "a cartographer at a lit desk" }],
    output_kind: "image",
  },
  {
    id: "cinema-still",
    name: "Cinema Still",
    description: "A still, a sharper pass, then a short move. Write one scene.",
    category: "cinema",
    skill: "@tryvinci/cinema-still",
    provider: "higgsfield",
    preferred_model_id: "higgsfield:dop-lite:2026-09",
    prompt_template: "{{scene}}",
    params: {
      aspect_ratio: "16:9",
      duration: 5,
      camera: "locked-off",
      lens: "35mm",
      aperture: "f/2.8",
      look: "commercial",
      lighting: "golden-hour",
      palette: "filmic",
      motion: "push-in",
    },
    inputs: [{ id: "scene", label: "Scene", type: "textarea", required: true, placeholder: "a diner booth at last light" }],
    output_kind: "video",
    pin_model: false,
  },
  {
    id: "motion-clip",
    name: "Motion Clip",
    description: "Six-second clip from one action line.",
    category: "motion",
    skill: "@tryvinci/video-generate",
    provider: "google",
    preferred_model_id: "google:veo-3.1-lite:2026-08",
    prompt_template: "{{action}}, {{lens}} lens, {{motion}} camera, natural sound off",
    params: { aspect_ratio: "16:9", duration: 6, look: "documentary" }, // Veo 3.1 takes 4, 6 or 8 s
    inputs: [
      { id: "action", label: "Action", type: "textarea", required: true, placeholder: "a paper cup slides down a wet bar" },
      {
        id: "lens",
        label: "Lens",
        type: "select",
        required: true,
        default: "35mm",
        options: ["24mm", "35mm", "50mm", "85mm"],
        slot: "lens",
      },
      {
        id: "motion",
        label: "Move",
        type: "select",
        required: true,
        default: "push-in",
        options: ["static", "pan", "orbit", "push-in", "pull-out"],
        slot: "motion",
      },
    ],
    output_kind: "video",
  },
  {
    id: "product-reveal",
    name: "Product Reveal",
    description: "Still plus a five-second reveal. Product and setting.",
    category: "ads",
    skill: "@tryvinci/product-reveal-5s",
    provider: "fal",
    preferred_model_id: "fal:kling-2.6-pro:2026-09",
    prompt_template: "A slow reveal of {{product}} in {{setting}}, commercial lighting, no logos",
    params: {
      aspect_ratio: "9:16",
      duration: 5,
      camera: "locked-off",
      lens: "50mm",
      look: "product",
      motion: "push-in",
    },
    inputs: [
      { id: "product", label: "Product", type: "text", required: true, placeholder: "glass perfume bottle" },
      { id: "setting", label: "Setting", type: "text", required: true, placeholder: "black marble plinth" },
    ],
    output_kind: "video",
    pin_model: false,
  },
  {
    id: "talking-photo",
    name: "Talking Photo",
    description: "Hold a still and a line. The still speaks.",
    category: "audio",
    skill: "@tryvinci/talking-photo",
    provider: "fal",
    preferred_model_id: "fal:kling-2.6-pro-i2v:2026-09",
    prompt_template: "{{line}}",
    params: {},
    inputs: [
      { id: "still", label: "Still", type: "media", required: true, slot: "image" },
      { id: "line", label: "Line", type: "textarea", required: true, placeholder: "We ship Tuesday." },
    ],
    output_kind: "video",
  },
  {
    id: "voiceover",
    name: "Voiceover",
    description: "Spoken line from a script. No picture.",
    category: "audio",
    skill: "@tryvinci/tts",
    provider: "elevenlabs",
    preferred_model_id: "elevenlabs:flash-v2.5:2026-08",
    prompt_template: "{{script}}",
    params: {},
    inputs: [{ id: "script", label: "Script", type: "textarea", required: true, placeholder: "Tonight, the shop stays open." }],
    output_kind: "audio",
  },
  {
    id: "still-4k",
    name: "Still to 4K",
    description: "Make a still sharper. Drop the file in.",
    category: "upscale",
    skill: "@tryvinci/image-upscale",
    provider: "magnific",
    preferred_model_id: "magnific:upscaler-creative:2026-09",
    prompt_template: "upscale",
    params: { scale: "4x" },
    inputs: [
      { id: "still", label: "Still", type: "media", required: true, slot: "media" },
      // Magnific's own upscaler controls (COREPRODUC-525), under Advanced.
      magSlider("creativity", "Creativity"),
      magSlider("resemblance", "Resemblance"),
      magSlider("hdr", "HDR"),
      magSlider("fractality", "Fractality"),
      { id: "optimized_for", label: "Optimized for", type: "select", options: MAG_STYLES, default: "standard", slot: "optimized_for", advanced: true },
      { id: "engine", label: "Engine", type: "select", options: MAG_ENGINES, default: "automatic", slot: "engine", advanced: true },
    ],
    output_kind: "image",
  },
];

/** Return the app with `id`, or undefined.
 *
 * Args:
 *   id: Stable catalog slug.
 */
export function getApp(id: string): StudioApp | undefined {
  return STUDIO_APPS.find((app) => app.id === id);
}

/** Seed form values from field defaults.
 *
 * Args:
 *   app: Catalog row.
 */
export function appDefaults(app: StudioApp): Record<string, string | number> {
  const values: Record<string, string | number> = {};
  for (const field of app.inputs) {
    if (field.default !== undefined) values[field.id] = field.default;
  }
  return values;
}

/** Filter the catalog by category pill and a free-text query.
 *
 * Args:
 *   apps: Catalog rows.
 *   category: `all` or an `AppCategory`.
 *   query: Case-insensitive match on name, blurb, skill, provider.
 */
export function filterApps(apps: readonly StudioApp[], category: string, query: string): StudioApp[] {
  const needle = query.trim().toLowerCase();
  return apps.filter((app) => {
    if (category !== "all" && app.category !== category) return false;
    if (!needle) return true;
    const hay = [app.name, app.description, app.category, app.skill, app.provider].join(" ").toLowerCase();
    return hay.includes(needle);
  });
}

/** Replace `{{slot}}` tokens. Unknown slots become empty strings.
 *
 * Args:
 *   template: Prompt with `{{id}}` markers.
 *   values: Form values coerced to string.
 */
export function fillPrompt(template: string, values: Record<string, string>): string {
  return template.replace(/\{\{\s*([a-z0-9_]+)\s*\}\}/gi, (_, key: string) => values[key] ?? "").replace(/\s+/g, " ").trim();
}

/** Required field ids that are still blank.
 *
 * Args:
 *   app: Catalog row.
 *   values: Current form values.
 */
export function missingAppInputs(app: StudioApp, values: Record<string, string | number>): string[] {
  return app.inputs
    .filter((field) => field.required && String(values[field.id] ?? "").trim() === "")
    .map((field) => field.id);
}

/** Build the `/runs` body for one app submission.
 *
 * Prompt-slot fields fill `prompt_template`. Other fields write their
 * `slot` (or `id`) onto `inputs` next to the app's fixed `params`.
 *
 * Args:
 *   app: Catalog row.
 *   values: Form values.
 *   modelId: Preferred model when the UI has marked it ready.
 */
export function buildRunPayload(
  app: StudioApp,
  values: Record<string, string | number>,
  modelId?: string,
): { skill: string; model_id?: string; inputs: Record<string, unknown> } {
  const asString: Record<string, string> = {};
  for (const [key, value] of Object.entries(values)) asString[key] = String(value);
  const inputs: Record<string, unknown> = { ...app.params };
  const prompt = fillPrompt(app.prompt_template, asString);
  if (prompt) inputs.prompt = prompt;
  for (const field of app.inputs) {
    const slot = field.slot || "prompt";
    if (slot === "prompt") continue;
    const raw = values[field.id];
    if (raw === undefined || String(raw).trim() === "") continue;
    inputs[slot] = field.type === "number" ? Number(raw) : raw;
  }
  const payload: { skill: string; model_id?: string; inputs: Record<string, unknown> } = {
    skill: app.skill,
    inputs,
  };
  if (app.pin_model !== false && modelId) payload.model_id = modelId;
  return payload;
}

type AppModelRow = {
  id: string;
  provider?: string;
  available?: boolean;
  capabilities?: readonly string[];
};

/** True when a run may pin this row. Mock always. A keyed row needs live spend. */
function appModelCanRun(row: AppModelRow, liveSpend: boolean): boolean {
  if (row.provider === "mock") return true;
  return Boolean(row.available && liveSpend);
}

/**
 * Compatible connected models for one Effects preset.
 *
 * Each capability on the preset's catalog row is a `modelsFor("effects")`
 * query. The preset id is moved to the front when it is in that set, so the
 * picker default is the preset. Mock drops out once a real provider is connected.
 *
 * Args:
 *   app: Preset. `pin_model: false` returns an empty list.
 *   models: Studio `/models` rows. Rows without `capabilities` cannot be matched.
 *   connectedProviders: Doctor ids. Omit to use every provider present on `models`.
 * Returns:
 *   Deduped rows. Preset first when it is compatible.
 */
export function appModelChoices<T extends AppModelRow>(
  app: StudioApp,
  models: readonly T[],
  connectedProviders?: readonly string[],
): T[] {
  if (app.pin_model === false) return [];
  const preferred = models.find((row) => row.id === app.preferred_model_id);
  const caps = preferred?.capabilities || [];
  if (!caps.length) return preferred ? [preferred] : [];
  const providers = connectedProviders?.length
    ? connectedProviders
    : [...new Set(models.map((row) => (row.provider || "").trim()).filter(Boolean))];
  const seen = new Set<string>();
  let rows: T[] = [];
  for (const capability of caps) {
    for (const row of modelsFor("effects", providers, models, { capability })) {
      if (seen.has(row.id)) continue;
      seen.add(row.id);
      rows.push(row);
    }
  }
  if (connectedProviders) rows = withoutMockWhenConnected(rows, connectedProviders);
  const index = rows.findIndex((row) => row.id === app.preferred_model_id);
  if (index > 0) {
    const [hit] = rows.splice(index, 1);
    rows.unshift(hit);
  }
  return rows;
}

/** Pin the preferred model when it is compatible and can run.
 *
 * The preset is the default among compatible connected models. A keyed preset
 * is pinned only when live spend is on. Otherwise the first runnable row
 * (usually mock) is pinned, or nothing so the runtime routes cheapest.
 *
 * Args:
 *   app: Catalog row.
 *   models: Studio `/models` list.
 *   liveSpend: `VINCI_ALLOW_LIVE_SPEND=1`.
 *   connectedProviders: Doctor ids. Omit to treat every provider on `models` as connected.
 * Returns:
 *   A model id to send as `model_id`, or undefined to let the runtime choose.
 */
export function resolveAppModel(
  app: StudioApp,
  models: readonly AppModelRow[],
  liveSpend: boolean,
  connectedProviders?: readonly string[],
): string | undefined {
  if (app.pin_model === false) return undefined;
  const preferredRow = models.find((model) => model.id === app.preferred_model_id);
  if (preferredRow && !(preferredRow.capabilities || []).length) {
    if (preferredRow.provider === "mock") return preferredRow.id;
    if (preferredRow.available && liveSpend) return preferredRow.id;
    return undefined;
  }
  const choices = appModelChoices(app, models, connectedProviders);
  const preferred = choices.find((row) => row.id === app.preferred_model_id);
  if (preferred && appModelCanRun(preferred, liveSpend)) return preferred.id;
  return choices.find((row) => appModelCanRun(row, liveSpend))?.id;
}

export type EffectRunRow = {
  id: string;
  state?: string;
  skill?: string;
  outputs?: string[];
  estimate?: { total?: number };
  created_at?: string;
};

export const EFFECT_ASPECT_OPTIONS = ["1:1", "4:5", "3:4", "16:9", "9:16"] as const;
export const EFFECT_RESOLUTION_OPTIONS = ["1K", "2K", "4K"] as const;

/** Runs whose skill matches the active preset, newest first. */
export function filterEffectHistory(runs: readonly EffectRunRow[], app: StudioApp): EffectRunRow[] {
  return runs
    .filter((row) => row.state === "completed" && row.skill === app.skill && (row.outputs?.length ?? 0) > 0)
    .slice()
    .reverse();
}

/** Collect output asset ids from filtered history. */
export function historyOutputIds(history: readonly EffectRunRow[]): string[] {
  const ids: string[] = [];
  for (const row of history) {
    for (const id of row.outputs ?? []) {
      if (id && !ids.includes(id)) ids.push(id);
    }
  }
  return ids;
}

/** Read aspect ratio from form overrides or preset params. */
export function effectiveAspect(app: StudioApp, aspect: string): string {
  const fromParams = app.params.aspect_ratio;
  if (typeof fromParams === "string" && fromParams) return aspect || fromParams;
  return aspect || "1:1";
}

/** Merge UI aspect/resolution into a `/runs` payload built elsewhere. */
export function applyEffectParams(
  inputs: Record<string, unknown>,
  app: StudioApp,
  aspect: string,
  resolution: string,
): Record<string, unknown> {
  const next = { ...inputs };
  if (app.params.aspect_ratio !== undefined || aspect) {
    next.aspect_ratio = effectiveAspect(app, aspect);
  }
  if (resolution && app.output_kind !== "audio") {
    next.resolution = resolution.toLowerCase();
  }
  return next;
}

type ModelRow = { id: string; provider?: string; available?: boolean; pricing?: { amount?: number; unit?: string; currency?: string } };

/** Label for the Generate button (cost on every button). A spoken line is priced by the text the
 * form sends, as the runtime prices it (COREPRODUC-603). */
export function generateButtonLabel(
  app: StudioApp,
  models: readonly ModelRow[],
  liveSpend: boolean,
  money: (amount?: number, currency?: string) => string,
  values: Record<string, string | number> = {},
): string {
  const modelId = resolveAppModel(app, models, liveSpend);
  const row = modelId ? models.find((m) => m.id === modelId) : models.find((m) => m.provider === app.provider);
  const inputs = buildRunPayload(app, values).inputs;
  const amount = clipPrice(row, inputs.duration, inputs, inputs.prompt);
  const price = money(amount ?? 0, row?.pricing?.currency);
  return `Generate · ${price}`;
}
