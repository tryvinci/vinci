/**
 * Shows page (OLF movie engine): types and pure helpers.
 *
 * The daemon serves an OLF project folder under `/olf/*` (vinci_olf). A show is a bible
 * (characters, locations, props, voices, style) plus seasons (optional), episodes, scenes
 * and shots. Each shot has keyframe and video takes; a take is stale when its inputs changed.
 * Flow: the bible locks the look, the storyboard approves keyframes (cheap stills), and the
 * shot page renders video from the chosen keyframe.
 *
 * Pure functions. No React, DOM, or imports: tests load this file on its own
 * (tests/test_shows_lib.py). The page is app/shows-page.tsx.
 */

export const OLF_API = "/vinci-api/olf";
export const RECENT_KEY = "vinci-shows-recent-v1";
export const TEXT_MODEL_KEY = "vinci-shows-text-model-v1"; // the text model a person picked last
export const RECENT_LIMIT = 6;

export type OlfIssue = { level: "error" | "warning"; where: string; message: string };
/**
 * A shot's camera as resolved: its own fields, plus the ones its camerawork template fills. Of
 * the template, the view has its ID and its words for the prompts.
 */
export type OlfCamera = {
  framing?: string;
  angle?: string;
  lens?: string;
  move?: string;
  direction?: string;
  amount?: number;
  ease?: string;
  hold_start?: number;
  hold_end?: number;
  center?: number[];
  /** `engine`: a held drawing, only the frame moves ($0, no video model). Default: `model`. */
  render?: string;
  /** The shape of a drawing larger than the frame (`21:9`), for a pan or a tilt across it. */
  canvas?: string;
  template?: { id: string; keyframe?: string; prompt?: string; avoid?: string[] };
};
export type OlfShot = {
  id: string;
  scene: string;
  error: string | null;
  takes: string[];
  duration?: number | string;
  description?: string;
  camera?: OlfCamera;
  select?: Record<string, string> | null;
  control?: Record<string, string> | null;
  /** The staging plan: one pill per character (vinci_olf.layout). It is in no hash. */
  pills?: OlfPills;
};

/** A flat stand-in for one character: its centre and eye line (0 to 1 of the frame), its head
 * height as a part of the frame height, and where it looks. */
export type OlfPill = { slot: string; id: string | null; name: string | null; x: number; y: number; size: number; facing: string | null; color?: string };
/** A shot's pills when it starts (and ends, when they move), and the 180° line warning. */
export type OlfPills = { start: OlfPill[]; end: OlfPill[] | null; aspect: string; stated: boolean; crosses: string | null };
/** `POST /olf/previs`: the e-conte sheet and the animatic in previs/<episode>/. */
export type OlfPrevis = { files: string[]; cuts: number; runtime: number };
export type OlfTake = {
  id: string;
  kind: "keyframe" | "video" | "audio";
  status: string;
  stale: boolean | null;
  file: string | null;
  output?: string;
  duration?: string;
  notes?: string;
  inputs?: Record<string, unknown>;
  provenance?: {
    provider?: string;
    model?: string;
    model_version?: string;
    seed?: number;
    created?: string;
    prompt?: string;
    negative_prompt?: string;
    cost?: { amount: number; currency: string };
  };
  audio_source?: string;
  /** Checks on the render (the palette check: does it keep the forms' colors?). */
  qa?: { check: string; score?: number; pass?: boolean }[];
};
export type OlfLicense = { owner: string; terms: string; attribution?: string; ai_training?: string };
// Bible data is free-form YAML, so its fields are read loosely.
export type OlfData = Record<string, any>;
export type OlfEntry = {
  id: string;
  /** The entry's YAML file, relative to the project. */
  file?: string;
  data: OlfData;
  files: Record<string, string>;
  used_in: string[];
  /** Takes that go stale when the entry's render fields change. */
  impact?: number;
  /** License of the main asset from the lock file; null before the first render locks it. */
  license?: OlfLicense | null;
  /** Characters: shots per form. */
  forms_usage?: Record<string, number>;
};
export type OlfLook = { form: string | null; outfit: string | null };
export type OlfScene = {
  id: string;
  heading?: string;
  location?: string;
  variant?: string;
  mood?: string;
  characters?: string[];
  script?: string;
  /** Each cast member's form and outfit for the whole scene. */
  looks?: Record<string, OlfLook>;
  shots: string[];
};
export type OlfSeason = { id: string; title?: string | null; synopsis?: string | null; episodes: string[] };
export type OlfEpisode = {
  id: string;
  /** The episode's YAML file, relative to the project. */
  file?: string;
  season?: string | null;
  title?: string;
  synopsis?: string;
  forms?: Record<string, string> | null;
  outfits?: Record<string, string> | null;
  scenes: OlfScene[];
};
export type BibleKind = "character" | "location" | "prop" | "voice" | "camerawork";
export type OlfShow = {
  path: string;
  spec: string;
  show: string;
  title: string;
  license?: OlfLicense | null;
  issues: OlfIssue[];
  style: OlfEntry | null;
  bible: Record<BibleKind, OlfEntry[]>;
  seasons: OlfSeason[];
  episodes: OlfEpisode[];
  shots: Record<string, OlfShot>;
  takes: Record<string, OlfTake>;
  /** Bible file -> short content hash: a replaced image keeps its name but gets a new URL. */
  hashes?: Record<string, string>;
};
/**
 * A model a person may pick for a step (design: the video model menu). Currency `PLAN` is an agent
 * CLI (Claude Code, Codex...): it bills the person's own sign-in, so Vinci shows no price for it.
 * `tools`: the CLI keeps some of its own tools (file reads, for example), so the question warns.
 */
export type OlfChoice = { id: string; name: string; provider: string; amount: number; currency?: string; unpriced: boolean; tools?: boolean };
/** `GET /olf/models`: the choices, and the model routing picks with no choice (null: none). */
export type OlfModels = { choices: OlfChoice[]; auto: { model: string; amount: number; unpriced: boolean } | null };
export type OlfPlan = {
  plan?: { node: string; model: string; amount: number; capability?: string; extensions?: string[] }[];
  choices?: OlfChoice[];
  total?: number;
  /** Live models with no flat price (per-token billing): they need a confirm, like a paid total. */
  unpriced?: string[];
  takes?: string[];
  error?: string;
  /** Things to know before the render, such as an engine move that enlarges its keyframe. */
  notes?: string[];
};
export type RenderKind = "keyframe" | "video" | "audio";
/** Why a take is stale (`GET /olf/stale`): the changed fields since it was rendered or kept. */
export type OlfStaleCause = {
  take: string;
  stale: boolean;
  known: boolean;
  summary: string;
  changes: { field: string; label: string; before: unknown; after: unknown }[];
};
/** Camera values a shot may use (SPEC.md, Shots; the same enums as schema.json). */
export const FRAMINGS = ["extreme_wide", "wide", "medium", "medium_close", "close_up", "extreme_close_up", "insert"];
export const ANGLES = ["eye_level", "low", "high", "overhead", "dutch"];
export const MOVES = ["static", "pan", "tilt", "push_in", "pull_out", "dolly", "truck", "crane", "orbit", "handheld", "shake"];
export const EASES = ["none", "in", "out", "in_out"];
export const RENDERS = ["model", "engine"];
/** Drawing shapes for a pan (wider than the frame) or a tilt (taller). */
export const CANVASES = ["21:9", "2:1", "9:16", "1:1"];
/** A pill's stripe when it has no color of its own (a pill keeps its character's color). */
export const SLOT_COLORS: Record<string, string> = { a: "#1c9fb8", b: "#e08a00", c: "#c2255c" };
/** Frames in one second of seconds+frames notation (`3+12` is 3.5 s), as in the engine. */
export const FRAMES = 24;
/** One render of a batch (`POST /olf/batch`): what, why, its price, and its takes or error. */
export type OlfBatchJob = {
  shot: string;
  kind: RenderKind | null;
  /** Keyframe variations to draw (the `keyframes` batch draws 2 per shot). */
  count?: number;
  why?: string;
  total?: number;
  unpriced?: string[];
  takes?: string[];
  error?: string;
};
export type OlfBatch = { mode: "stale" | "animate"; jobs: OlfBatchJob[]; total: number; unpriced: string[]; takes: string[] };
export type OlfShotDetail = {
  resolved: OlfData;
  /** Which level set each field (`project`, `bible`, `season`, `episode`, `scene`, `shot`). */
  origins: {
    forms: Record<string, string>;
    outfits: Record<string, string>;
    /** Each camera field's origin: a level, or the camerawork template that fills it (`cam/tu-slow`). */
    camera_fields?: Record<string, string>;
  } & Record<string, unknown>;
  hashes: { keyframe: string; video: string | null; audio: string };
  prompts: { keyframe: string; video: string };
  references: { asset: string; file: string | null }[];
  plans: { video: OlfPlan; keyframe: OlfPlan; audio?: OlfPlan };
};
export type ShotState = "error" | "empty" | "fresh" | "stale";
/** One clip of the cut on the timeline (vinci_olf.cut.cut_view). */
export type OlfClip = {
  index: number;
  take: string;
  shot: string;
  kind: "keyframe" | "video";
  file: string | null;
  in: number;
  out: number;
  length: number;
  /** Seconds from the start of the episode; a fade starts 0.5 s before the clip before it ends. */
  start: number;
  transition: "cut" | "fade";
  audio: "own" | "separate";
  /** The shot's chosen dialogue take (`select.audio`), which plays when `audio` is `separate`. */
  dialogue_take: { take: string; file: string | null; length: number; status?: string; stale?: boolean | null } | null;
  stale: boolean | null;
  missing: boolean;
  dialogue: { speaker?: string; line?: string; delivery?: string }[];
};
export type OlfCut = {
  episode: string;
  file: string;
  format: { resolution: string; fps: number };
  clips: OlfClip[];
  duration: number;
  stale: number;
  missing: number;
  audio: OlfCueRow[];
  /** The daemon can sign exports with C2PA (c2pa-python is installed). */
  c2pa?: boolean;
};
/** One music or SFX take of the episode's audio list, on the timeline (COREPRODUC-551). */
export type OlfCueRow = {
  index: number;
  take: string;
  cue: string;
  kind: string | null;
  label: string;
  file: string | null;
  start: number;
  length: number;
  volume: number;
  duck: boolean;
  stale: boolean | null;
  missing: boolean;
};
export type OlfExport = { files: string[]; duration: number; clips: number; subtitles: number };

export const BIBLE_KINDS: { id: BibleKind; label: string }[] = [
  { id: "character", label: "Characters" },
  { id: "location", label: "Locations" },
  { id: "prop", label: "Props" },
  { id: "voice", label: "Voices" },
  { id: "camerawork", label: "Camerawork" },
];

/** `season/01` with title `First Light` -> `Season 1 · First Light`. */
export function seasonLabel(season: OlfSeason): string {
  const number = Number(season.id.slice(season.id.indexOf("/") + 1)) || season.id;
  return [`Season ${number}`, season.title].filter(Boolean).join(" · ");
}

/** Episodes grouped for the navigator: each season in its own order, then episodes in no season. */
export function episodeGroups(show: OlfShow): { season: OlfSeason | null; episodes: OlfEpisode[] }[] {
  const byId = new Map(show.episodes.map((episode) => [episode.id, episode]));
  const groups = (show.seasons || []).map((season) => ({
    season,
    episodes: season.episodes.map((id) => byId.get(id)).filter((ep): ep is OlfEpisode => Boolean(ep)),
  }));
  const placed = new Set(groups.flatMap((group) => group.episodes.map((episode) => episode.id)));
  const rest = show.episodes.filter((episode) => !placed.has(episode.id));
  return [...groups, ...(rest.length ? [{ season: null, episodes: rest }] : [])].filter((group) => group.episodes.length);
}

const FRAMING_SHORT: Record<string, string> = {
  extreme_wide: "EWS",
  wide: "WS",
  medium: "MS",
  medium_close: "MCU",
  close_up: "CU",
  extreme_close_up: "ECU",
  insert: "INS",
};

/** Card label: `CU · 50mm`. */
export function framingShort(camera: OlfCamera | undefined): string {
  if (!camera) return "Shot";
  const framing = FRAMING_SHORT[camera.framing || ""] || words(camera.framing) || "Shot";
  return [framing, camera.lens].filter(Boolean).join(" · ");
}

/** An episode's shots in play order: scenes in their order, shots by number. */
export function episodeShots(episode: OlfEpisode | undefined): string[] {
  return (episode?.scenes || []).flatMap((scene) => scene.shots);
}

export function episodeOf(show: OlfShow, shotId: string): OlfEpisode | undefined {
  return show.episodes.find((episode) => episodeShots(episode).includes(shotId));
}

/** The shots before and after `shotId` in its episode. */
export function neighbors(episode: OlfEpisode | undefined, shotId: string): { prev?: string; next?: string } {
  const order = episodeShots(episode);
  const at = order.indexOf(shotId);
  return at < 0 ? {} : { prev: order[at - 1], next: order[at + 1] };
}

/** Seconds as `m:ss`: 52 -> `0:52`. */
export function runtimeText(total: number): string {
  const whole = Math.round(total);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** `4`, `4s`, `2.5` or seconds+frames (`3+12`: a frame is 1/24 s) as seconds. */
export function durationSeconds(value: number | string | undefined): number {
  const text = String(value ?? "");
  const parts = /^(\d+)\+(\d{1,2})$/.exec(text);
  return parts ? Number(parts[1]) + Number(parts[2]) / FRAMES : Number(text.replace(/s$/, "")) || 0;
}

/** A length as seconds+frames, the notation of storyboards, to the nearest frame: 3.5 -> `3+12`. */
export function frames(value: number | string | undefined): string {
  if (value === undefined || value === null || value === "") return "";
  const total = Math.round(durationSeconds(value) * FRAMES);
  return `${Math.floor(total / FRAMES)}+${String(total % FRAMES).padStart(2, "0")}`;
}

/** One row of the Camerawork menu: `Track up to the eyes · T.U. · Engine $0 · 3+00`. */
export function templateLabel(data: OlfData): string {
  const how = data.camera?.render === "engine" ? "Engine $0" : "Model";
  return [data.name || data.id, data.notation, how, data.timing?.default].filter(Boolean).join(" · ");
}

/**
 * The Camerawork menu of a shot: the show's own templates first, then the library by family. A
 * library template that the show has a copy of (its `source`) is listed one time, as the show's.
 */
export function cameraworkMenu(show: OlfShow, library: readonly OlfData[]): { label: string; rows: { value: string; label: string }[] }[] {
  const mine = show.bible.camerawork || [];
  const copied = new Set(mine.map((entry) => String(entry.data.source || "").split("@")[0]));
  const groups = [{ label: "In this show", rows: mine.map((entry) => ({ value: entry.id, label: templateLabel(entry.data) })) }];
  for (const row of library) {
    if (copied.has(row.id)) continue;
    const label = `Library · ${words(row.family)}`;
    const group = groups.find((g) => g.label === label) || groups[groups.push({ label, rows: [] }) - 1];
    group.rows.push({ value: row.id, label: templateLabel(row) });
  }
  return groups.filter((group) => group.rows.length);
}

/** The storyboard numbers: shots, shots with an approved keyframe, stale takes, runtime. */
export function episodeStats(
  show: OlfShow,
  episode: OlfEpisode | undefined,
): { shots: number; approved: number; stale: number; runtime: number } {
  const ids = episodeShots(episode);
  const approved = ids.filter((id) => takesOf(show, id, "keyframe").some((take) => take.status === "approved")).length;
  const runtime = ids.reduce((sum, id) => sum + durationSeconds(show.shots[id]?.duration), 0);
  return { shots: ids.length, approved, stale: countTakes(show, ids).stale, runtime };
}

/** The keyframe a video renders from: only `select.keyframe` (keyframes first). */
export function chosenKeyframe(show: OlfShow, shotId: string): OlfTake | undefined {
  const name = show.shots[shotId]?.select?.keyframe;
  return name ? show.takes[`${shotId}/${name}`] : undefined;
}

/** Card footer: `kf1 · v1 approved`, `kf1 chosen`, `3 keyframes`, or `No takes yet`. */
export function takesSummary(show: OlfShow, shotId: string): string {
  const keyframe = chosenKeyframe(show, shotId);
  const picked = show.shots[shotId]?.select?.video;
  const videos = takesOf(show, shotId, "video");
  const video = videos.find((take) => takeName(take.id) === picked) || videos[0];
  if (keyframe && video) {
    return `${takeName(keyframe.id)} · ${takeName(video.id)}${video.status === "approved" ? " approved" : ""}`;
  }
  if (keyframe) return `${takeName(keyframe.id)} chosen`;
  const count = takesOf(show, shotId, "keyframe").length;
  return count ? `${count} ${count === 1 ? "keyframe" : "keyframes"}` : "No takes yet";
}

/** Where a value came from, for people: `episode` -> `from episode`; none -> `default`. */
export function levelLabel(level: unknown): string {
  return typeof level === "string" && level ? `from ${level}` : "default";
}

/** URL of a media file inside the open project (the daemon checks it stays inside). */
export function fileUrl(projectPath: string, rel: string): string {
  return `${OLF_API}/file?path=${encodeURIComponent(projectPath)}&rel=${encodeURIComponent(rel)}`;
}

/** URL of a bible file; its content hash makes a replaced image (same name) load again. */
export function mediaUrl(show: OlfShow, rel: string): string {
  const hash = show.hashes?.[rel];
  return fileUrl(show.path, rel) + (hash ? `&v=${hash}` : "");
}

/** Last segment of a take ID: `e02/s03/sh014/kf1` -> `kf1`. */
export function takeName(id: string): string {
  return id.slice(id.lastIndexOf("/") + 1);
}

function takeNumber(id: string): number {
  return Number(/\d+$/.exec(id)?.[0] || 0);
}

const KIND_ORDER: Record<string, number> = { keyframe: 0, video: 1, audio: 2 };

/** A shot's takes: keyframes, then videos, then audio; newest first in each kind. */
export function takesOf(show: OlfShow, shotId: string, kind?: OlfTake["kind"]): OlfTake[] {
  const rows = (show.shots[shotId]?.takes || []).map((id) => show.takes[id]).filter(Boolean);
  return rows
    .filter((take) => !kind || take.kind === kind)
    .sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || takeNumber(b.id) - takeNumber(a.id));
}

/** The keyframe a shot shows: `select.keyframe`, else its newest keyframe. */
export function shownKeyframe(show: OlfShow, shotId: string): OlfTake | undefined {
  const picked = show.shots[shotId]?.select?.keyframe;
  const keyframes = takesOf(show, shotId, "keyframe");
  return keyframes.find((take) => takeName(take.id) === picked) || keyframes[0];
}

/** Card state: error (cannot resolve), empty (no takes), stale (any take stale), fresh. */
export function shotState(show: OlfShow, shotId: string): ShotState {
  const shot = show.shots[shotId];
  if (!shot || shot.error) return "error";
  const takes = takesOf(show, shotId);
  if (!takes.length) return "empty";
  return takes.some((take) => take.stale) ? "stale" : "fresh";
}

/** Counts for a header line: shots, takes and stale takes. */
export function countTakes(show: OlfShow, shotIds: readonly string[]): { shots: number; takes: number; stale: number } {
  const takes = shotIds.flatMap((id) => takesOf(show, id));
  return { shots: shotIds.length, takes: takes.length, stale: takes.filter((take) => take.stale).length };
}

export function issueCounts(issues: readonly OlfIssue[]): { errors: number; warnings: number } {
  const errors = issues.filter((issue) => issue.level === "error").length;
  return { errors, warnings: issues.length - errors };
}

/** `close_up` -> `Close up`. */
export function words(value: string | undefined): string {
  const text = String(value || "").replace(/_/g, " ");
  return text.slice(0, 1).toUpperCase() + text.slice(1);
}

/** The jobs of a batch that can run (the others carry the engine's reason). */
export function readyJobs(batch: OlfBatch | null | undefined): OlfBatchJob[] {
  return (batch?.jobs || []).filter((job) => !job.error);
}

/** `kf1`, `kf1 and kf2`, `kf1, kf2 and kf3`. */
export function andList(items: readonly string[]): string {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}` : items[0] || "";
}

/** The question before a paid render: `Spend $0.42 on 2 renders? openai:img has no flat price.` */
export function spendText(total: number | undefined, unpriced: readonly string[] | undefined, what: string): string {
  const extra = unpriced?.length ? ` ${unpriced.join(", ")} ${unpriced.length === 1 ? "has" : "have"} no flat price.` : "";
  return `Spend ${price(total)} on ${what}?${extra}`;
}

/** A model menu row: the name and the price ("your plan" for an agent CLI). */
export function choiceLabel(row: OlfChoice): string {
  return `${row.name} · ${row.currency === "PLAN" ? "your plan" : row.unpriced ? "price varies" : price(row.amount)}`;
}

/** The menu's first row, routing's own pick: `Auto · GPT-6 Luna` (the ID when it is not a choice). */
export function autoLabel(model: string | undefined, choices: readonly OlfChoice[] | undefined): string {
  return model ? `Auto · ${choices?.find((row) => row.id === model)?.name || model}` : "Auto";
}

/**
 * The question before a text step: its price, or for an agent CLI, whose sign-in it bills. A CLI
 * that keeps its tools gets a warning: a script can carry instructions for the agent.
 */
export function textStepQuestion(plan: OlfPlan, choices: readonly OlfChoice[], what: string): string {
  const id = plan.plan?.[0]?.model || "a text model";
  const cli = choices.find((row) => row.id === id && row.currency === "PLAN");
  if (!cli) return spendText(plan.total, plan.unpriced, `${what} from ${id}`);
  const tools = cli.tools ? " It can use its own tools, such as reading your files: use it only with scripts you trust." : "";
  return `Write ${what} with ${cli.name}? It runs on your own ${cli.name} sign-in and bills that account. Vinci adds no charge.${tools}`;
}

/** What a card says while it renders. */
export function busyText(kind: string | undefined): string {
  return kind === "video" ? "Rendering video…" : kind === "audio" ? "Speaking dialogue…" : "Drawing keyframe…";
}

export function price(amount: number | undefined): string {
  const value = Number(amount || 0);
  return value === 0 ? "$0" : `$${value.toFixed(2)}`;
}

/**
 * Display name of a bible entry: its `name`, else its ID slug (`prop/brass-key` -> `Brass key`).
 * A voice without a name is named after its slug, as in the design (`voice/mira` -> `Mira's voice`).
 */
export function entryName(entry: OlfEntry | undefined, fallback = ""): string {
  if (!entry) return fallback;
  if (entry.data.name) return String(entry.data.name);
  const slug = words(entry.id.slice(entry.id.lastIndexOf("/") + 1).replace(/-/g, " "));
  return entry.id.startsWith("voice/") ? `${slug}'s voice` : slug;
}

export function findEntry(show: OlfShow, id: string | undefined): OlfEntry | undefined {
  if (!id) return undefined;
  for (const kind of BIBLE_KINDS) {
    const hit = show.bible[kind.id]?.find((entry) => entry.id === id);
    if (hit) return hit;
  }
  return undefined;
}

/** A character's sheets: the primary `sheet` first, then each of `sheets`, with its project file. */
export function sheetsOf(entry: OlfEntry): { image: string; file?: string }[] {
  const extra = Array.isArray(entry.data.sheets) ? entry.data.sheets : [];
  return [entry.data.sheet, ...extra]
    .filter((image): image is string => typeof image === "string" && !!image)
    .map((image) => ({ image, file: entry.files[image] }));
}

/** A script as scenes and shots (`POST /olf/script/preview`), before anything is written. */
export type OlfScriptShot = {
  description: string;
  duration: string;
  camera: OlfCamera;
  dialogue?: { speaker: string; line: string; delivery?: string }[];
};
export type OlfScriptPreview = {
  scenes: { heading: string; location: string | null; variant: string | null; characters: string[]; script: string; shots: OlfScriptShot[] }[];
  characters: { name: string; id: string; new: boolean }[];
  locations: { name: string; id: string; new: boolean }[];
  shots: number;
  runtime: number;
  /** One keyframe on the routed model (New show: "2 keyframe options per shot · est."). */
  keyframe?: { model: string; amount: number; unpriced: boolean } | null;
};
/** A text-model step (`/olf/draft`, `/olf/script/model`): the plan, then the model's text. */
export type OlfTextStep = OlfPlan & { text: string | null; preview?: OlfScriptPreview };
export const KEYFRAME_OPTIONS = 2; // keyframes a new show draws per shot (vinci_olf.batch)

/** `2 scenes · 1 character found`, under the script box. */
export function scriptFound(view: OlfScriptPreview | null | undefined): string {
  const scenes = view?.scenes.length || 0;
  const cast = view?.characters.length || 0;
  if (!scenes) return "No scenes yet";
  return `${scenes} ${scenes === 1 ? "scene" : "scenes"} · ${cast} ${cast === 1 ? "character" : "characters"} found`;
}

/** `2 keyframe options per shot · est. $0.84`; a model with no flat price says so instead. */
export function keyframeEstimate(view: OlfScriptPreview | null | undefined): { text: string; total: number; unpriced: boolean } {
  const head = `${KEYFRAME_OPTIONS} keyframe options per shot`;
  const kf = view?.keyframe;
  if (!view?.shots || !kf) return { text: head, total: 0, unpriced: false };
  const total = kf.amount * KEYFRAME_OPTIONS * view.shots;
  return { text: `${head} · ${kf.unpriced ? `${kf.model} has no flat price` : `est. ${price(total)}`}`, total, unpriced: kf.unpriced };
}

/** What a script adds to the bible, as the design's notice says it. A new character needs a sheet. */
export function newEntries(view: OlfScriptPreview | null | undefined): { places: string[]; people: string[]; notes: string[] } {
  const places = (view?.locations || []).filter((row) => row.new).map((row) => row.name);
  const people = (view?.characters || []).filter((row) => row.new).map((row) => row.name);
  const one = (list: string[], a: string, many: string) => (list.length === 1 ? a : many);
  const notes = [
    places.length
      ? `New ${one(places, "location", "locations")} found: ${andList(places)}. We will add ${one(places, "it", "them")} to the bible with a text description. You can upload reference images later.`
      : "",
    people.length
      ? `New ${one(people, "character", "characters")} found: ${andList(people)}. We will add ${one(people, "it", "them")} to the bible. Add a sheet for each in the bible: render stays off until then.`
      : "",
  ].filter(Boolean);
  return { places, people, notes };
}

/** Recent show folders from localStorage (newest first). Bad values give an empty list. */
export function parseRecent(raw: string | null | undefined): string[] {
  try {
    const rows = JSON.parse(raw || "[]");
    return Array.isArray(rows) ? rows.filter((row) => typeof row === "string" && row.trim()).slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

export function pushRecent(rows: readonly string[], path: string): string[] {
  return [path, ...rows.filter((row) => row !== path)].slice(0, RECENT_LIMIT);
}

/** Last folder name of a path, for a recent-shows row. */
export function folderName(path: string): string {
  const parts = path.replace(/[\\/]+$/, "").split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** Short hash for display: `sha256:ae3b54…68bc0578`. */
export function shortHash(hash: string | null | undefined): string {
  if (!hash) return "";
  const [algo, hex] = hash.includes(":") ? hash.split(":", 2) : ["", hash];
  return `${algo ? algo + ":" : ""}${hex.slice(0, 8)}…${hex.slice(-8)}`;
}

/** Time on the timeline: 21.43 -> `0:21.4`. */
export function clockText(seconds: number): string {
  const tenths = Math.max(0, Math.round(seconds * 10));
  return `${Math.floor(tenths / 600)}:${((tenths % 600) / 10).toFixed(1).padStart(4, "0")}`;
}

/** The clip under the playhead (inside a fade the later clip wins), and the second inside its take. */
export function clipAt(cut: OlfCut, seconds: number): { clip: OlfClip; offset: number } | null {
  const clip = [...cut.clips].reverse().find((row) => seconds >= row.start) || cut.clips[0];
  return clip ? { clip, offset: clip.in + Math.min(Math.max(seconds - clip.start, 0), clip.length) } : null;
}

export const FADE = 0.5; // seconds a fade overlaps the clip before it (vinci_olf.cut.FADE)

/**
 * The fade under the playhead: the clip before, the clip that fades in, each with its offset
 * in its take, and how far the fade is (`mix`, 0 to 1). `null` outside a fade.
 */
export function fadeAt(
  cut: OlfCut,
  seconds: number,
): { from: { clip: OlfClip; offset: number }; to: { clip: OlfClip; offset: number }; mix: number } | null {
  const index = cut.clips.findIndex(
    (clip, i) => i > 0 && clip.transition === "fade" && seconds >= clip.start && seconds < clip.start + FADE,
  );
  if (index < 1) return null;
  const to = cut.clips[index];
  const from = cut.clips[index - 1];
  return {
    from: { clip: from, offset: from.in + Math.min(seconds - from.start, from.length) },
    to: { clip: to, offset: to.in + (seconds - to.start) },
    mix: Math.min(Math.max((seconds - to.start) / FADE, 0), 1),
  };
}

/** Ruler marks: every 1, 2, 5, 10, 15, 30 or 60 s (at most about eight), then the end. */
export function timelineTicks(duration: number): number[] {
  const step = [1, 2, 5, 10, 15, 30, 60, 120, 300].find((size) => duration / size <= 8) || 600;
  const marks: number[] = [];
  for (let at = 0; at < duration - step * 0.4; at += step) marks.push(at);
  return [...marks, Math.round(duration * 10) / 10];
}

/** Dialogue block words, as in the design: `a1 · Mira Sol` (the take, who speaks, then `stale`). */
export function dialogueLabel(show: OlfShow, clip: OlfClip): string {
  const speakers = [...new Set(clip.dialogue.map((line) => line.speaker).filter(Boolean))] as string[];
  const names = speakers.map((id) => entryName(findEntry(show, id), id));
  const take = clip.dialogue_take;
  return [take ? takeName(take.take) : "no dialogue take", ...names, take?.stale ? "stale" : null].filter(Boolean).join(" · ");
}

/** Clips that play separate dialogue, but whose shot has no chosen dialogue take with a file. */
export function silentClips(cut: OlfCut): OlfClip[] {
  return cut.clips.filter((clip) => clip.audio === "separate" && !clip.dialogue_take?.file);
}

/** Timeline block words, as in the design: `s03/sh014` over `v1 · stale`, `kf only` or `fade`. */
export function clipLabel(clip: OlfClip): { shot: string; take: string } {
  const take = clip.kind === "keyframe" ? "kf only" : takeName(clip.take);
  const marks = [take, clip.transition === "fade" ? "fade" : null, clip.missing ? "missing" : clip.stale ? "stale" : null];
  return { shot: clip.shot.split("/").slice(1).join("/"), take: marks.filter(Boolean).join(" · ") };
}

/** The subtitle showing at a time: each dialogue line gets an equal share of its clip (as in export). */
export function cueAt(cut: OlfCut, seconds: number): string {
  for (const clip of cut.clips) {
    const lines = clip.dialogue.map((row) => row.line).filter((line): line is string => Boolean(line));
    if (!lines.length || seconds < clip.start || seconds >= clip.start + clip.length) continue;
    return lines[Math.min(lines.length - 1, Math.floor(((seconds - clip.start) / clip.length) * lines.length))];
  }
  return "";
}
