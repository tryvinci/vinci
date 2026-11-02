"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { AdaptFlowCanvas } from "./adapt-flow-canvas";
import { AdaptsPanel, EMPTY_PRESET_DRAFT, type PresetDraft } from "./adapts-panel";
import type { AdaptPresetRow, AdaptTarget, BatchStatus } from "./adapt-ui-shared";
import { ModelCombo, type ComboModel } from "./model-combo";
import { availabilityRank, modelAvailability, rankModels } from "../lib/model-search";
import {
  EMPTY_GRAPH,
  HOME_VIEW,
  NODE_H,
  NODE_W,
  SHORTCUTS,
  NODE_CATALOG,
  addNode as addGraphNode,
  blockedReason,
  commit,
  connect,
  curve,
  defaultsFor,
  disconnect,
  duplicateNode,
  estimateRun,
  fitView,
  GROUP_COLORS,
  groupBounds,
  groupNodes,
  groupOf,
  moveNodes,
  nodesInRect,
  freeSpot,
  outputOf,
  portY,
  portsFor,
  isEdited,
  preview,
  redo,
  removeNodes,
  searchCatalog,
  setParams,
  settle,
  shortcutFor,
  startHistory,
  startParams,
  toWorkflowNodes,
  undo,
  ungroupNodes,
  updateGroup,
  updateNode,
  wheelZoomFactor,
  wirePath,
  withAncestors,
  withKeys,
  zoomAt,
  type Graph,
  type GraphEdge,
  type GraphNode,
  type MediaKind,
  type ShortcutId,
  type Viewport,
} from "../lib/canvas-graph";

const API = "/vinci-api";
const CAMERAS = ["locked-off", "handheld", "tracking", "crane", "aerial"];
const LENSES = ["24mm", "35mm", "50mm", "85mm", "anamorphic"];
const LOOKS = ["commercial", "documentary", "noir", "fashion", "product"];
const LIGHTING = ["available", "studio", "golden-hour", "overcast", "neon", "moonlight", "practical"];
const PALETTES = ["filmic", "teal-orange", "bleach", "tungsten", "daylight", "pastel", "verdant"];
const MOTIONS = ["static", "pan", "orbit", "push-in", "pull-out"];
const APERTURES = ["f/1.4", "f/2.8", "f/5.6", "f/11"];
const GENRES = ["action", "drama", "documentary", "music-video"];
const SCENES = ["general", "selfie", "podcast", "car-talking"];
const ELEMENT_KINDS = ["character", "location", "prop"] as const;
const MAG_STYLES = ["standard", "soft_portraits", "hard_portraits", "art_n_illustration", "films_n_photography", "3d_renders"];
const MAG_ENGINES = ["automatic", "magnific_illusio", "magnific_sharpy", "magnific_sparkle"];
const CATS = ["all", "image", "motion", "upscale", "cinema", "ads", "clips", "audio"];
const KEY_ORDER = ["higgsfield", "magnific", "wavespeed", "google", "fal", "elevenlabs", "cloudflare", "mcp"];
const CONNECTOR_ORDER = ["mock", ...KEY_ORDER];
const ONBOARD_KEY = "vinci-onboard-v1";
const ONBOARD_STEPS = [
  {
    kicker: "1 / 3",
    title: "Intelligent generative media",
    copy: "Your Brand's Superagency — stills, video, and campaigns in one Studio. Connect a provider when you want live models.",
    next: "Continue",
    alt: "",
  },
  {
    kicker: "2 / 3",
    title: "Connect when you need live models",
    copy: "Work locally now. Paste a Higgsfield or Magnific key under Connect, or add a custom MCP URL.",
    next: "Start generating",
    alt: "Connect a key",
  },
  {
    kicker: "3 / 3",
    title: "Make a still",
    copy: "Open Image, pick a model, then Generate. Estimates appear on the button.",
    next: "Open Image",
    alt: "",
  },
];
const CONNECTOR_GLYPH: Record<string, string> = {
  mock: "L",
  higgsfield: "H",
  magnific: "M",
  wavespeed: "W",
  google: "G",
  fal: "f",
  elevenlabs: "11",
  cloudflare: "CF",
  mcp: "MCP",
};

function ConnectorGlyph({ id }: { id: string }) {
  const common = { viewBox: "0 0 48 48", width: 28, height: 28, "aria-hidden": true as const };
  switch (id) {
    case "mock":
      return (
        <svg {...common}>
          <text x="24" y="30" textAnchor="middle" fontSize="14" fontWeight="700" fill="currentColor">
            L
          </text>
        </svg>
      );
    case "higgsfield":
      return (
        <svg {...common}>
          <path d="M24 9l13 15-13 15L11 24z" fill="none" stroke="currentColor" strokeWidth="2.5" />
        </svg>
      );
    case "magnific":
      return (
        <svg {...common}>
          <circle cx="19" cy="24" r="8" fill="none" stroke="currentColor" strokeWidth="2.5" />
          <circle cx="29" cy="24" r="8" fill="none" stroke="currentColor" strokeWidth="2.5" />
        </svg>
      );
    case "wavespeed":
      return (
        <svg {...common}>
          <path d="M10 30c4-10 8-10 12 0s8 10 12 0" fill="none" stroke="currentColor" strokeWidth="2.5" />
          <path d="M10 22c4-10 8-10 12 0s8 10 12 0" fill="none" stroke="currentColor" strokeWidth="2.5" />
        </svg>
      );
    case "google":
      return (
        <svg {...common}>
          <circle cx="18" cy="18" r="4" fill="currentColor" />
          <circle cx="30" cy="18" r="4" fill="currentColor" />
          <circle cx="18" cy="30" r="4" fill="currentColor" />
          <circle cx="30" cy="30" r="4" fill="currentColor" />
        </svg>
      );
    case "fal":
      return (
        <svg {...common}>
          <path d="M16 34V14h16" fill="none" stroke="currentColor" strokeWidth="2.8" />
          <path d="M16 24h11" stroke="currentColor" strokeWidth="2.8" />
        </svg>
      );
    case "elevenlabs":
      return (
        <svg {...common}>
          <rect x="14" y="12" width="6" height="24" rx="1.5" fill="currentColor" />
          <rect x="28" y="12" width="6" height="24" rx="1.5" fill="currentColor" />
        </svg>
      );
    case "cloudflare":
      return (
        <svg {...common}>
          <path d="M10 28h22l-6-12H16z" fill="none" stroke="currentColor" strokeWidth="2.5" />
        </svg>
      );
    default:
      if (id === "mcp" || id.startsWith("mcp_")) {
        return (
          <svg {...common}>
            <rect x="18" y="16" width="12" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="2.4" />
            <path d="M22 16V11M26 16V11" stroke="currentColor" strokeWidth="2.4" />
          </svg>
        );
      }
      return <>{CONNECTOR_GLYPH[id] || id.slice(0, 2).toUpperCase()}</>;
  }
}

function openConnectorPicker() {
  const el = document.getElementById("connect-select") as HTMLSelectElement | null;
  if (!el) return;
  el.focus();
  try {
    el.showPicker?.();
  } catch {
    /* ignore */
  }
}

type Model = {
  id: string;
  display_name: string;
  provider: string;
  capabilities: string[];
  available?: boolean;
  pricing?: { amount?: number };
  constraints?: { aspect_ratios?: string[]; max_duration?: number; resolutions?: string[] };
};
type Skill = { id: string; tags?: string[]; workflow?: { nodes?: GraphNode[]; edges?: GraphEdge[] } };
type Run = {
  id: string;
  state?: string;
  outputs?: string[];
  estimate?: { total?: number };
  nodes?: Record<string, { output?: string; outputs?: string[]; job_id?: string }>;
  error?: unknown;
};
type Asset = { id: string; mime?: string; kind?: string; uri?: string };
type PlanStep = { id: string; title: string; skill: string; blurb?: string; note?: string };
type CastRow = { name: string; assetId: string; kind?: string };
type ProviderRow = {
  available?: boolean;
  configured?: boolean;
  display_name?: string;
  kind?: string;
  secret_name?: string;
  extra_secret_names?: string[];
  docs?: string;
  url?: string;
  authorize_url?: string;
  auth?: string;
  auth_state?: string;
};
type Doctor = {
  live_spend?: boolean;
  preference?: string;
  providers?: Record<string, ProviderRow>;
  budget?: { monthly_cap_usd?: number };
};
type PageId =
  | "explore"
  | "image"
  | "adapts"
  | "video"
  | "speak"
  | "upscale"
  | "canvas"
  | "library"
  | "agent"
  | "space"
  | "collab"
  | "skills"
  | "find"
  | "cost"
  | "keys";

type AdaptEstimateBody = {
  total: number;
  note?: string;
  targets?: { safe_area?: Record<string, unknown> }[];
  pricing_unknown?: boolean;
};

type AdaptRunBody = {
  digests: string[];
  estimate: AdaptEstimateBody;
  outputs?: { validation?: Record<string, unknown> }[];
};

type Template = {
  id: string;
  title: string;
  blurb: string;
  category: string;
  skill: string;
  page?: PageId;
  defaults?: Record<string, string | number>;
};

async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function money(n: number | undefined): string {
  const v = Number(n || 0);
  if (v === 0) return "$0";
  if (v < 0.01) return "$" + v.toFixed(5).replace(/0+$/, "").replace(/\.$/, "");
  return "$" + v.toFixed(3);
}

function comboModels(rows: Model[], withPrice: boolean, suffix: (row: Model) => string): ComboModel[] {
  return rows.map((row) => {
    const who = withPrice && row.provider === "mock" ? "Local" : row.provider;
    const price = withPrice ? ` · ${money(row.pricing?.amount)}` : "";
    const label = `${row.display_name} · ${who}${price}${suffix(row)}`;
    return { id: row.id, display_name: row.display_name, provider: row.provider, label };
  });
}

function MagRange({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="range-row">
      <label htmlFor={id}>
        {label} <span id={id + "-val"}>{value}</span>
      </label>
      <input
        id={id}
        type="range"
        min={-10}
        max={10}
        value={value}
        onChange={(ev) => onChange(Number(ev.target.value))}
      />
    </div>
  );
}

function opticalValue(value: unknown, fallback: string): string {
  if (value == null || value === "" || String(value).includes("{{")) return fallback;
  return String(value);
}

function stampOptical(
  params: Record<string, unknown> | undefined,
  camera: string,
  lens: string,
  look: string,
  motion: string,
  aperture: string,
  genre: string,
  lighting: string,
  palette: string,
): Record<string, unknown> {
  const out = { ...(params || {}) };
  out.camera = opticalValue(out.camera, camera);
  out.lens = opticalValue(out.lens, lens);
  out.look = opticalValue(out.look, look);
  out.aperture = opticalValue(out.aperture, aperture);
  out.genre = opticalValue(out.genre, genre);
  out.lighting = opticalValue(out.lighting, lighting);
  out.palette = opticalValue(out.palette, palette);
  out.motion = opticalValue(out.motion, motion);
  return out;
}

function opticalLabel(
  node: GraphNode,
  camera: string,
  lens: string,
  look: string,
  motion: string,
  aperture: string,
  genre: string,
  lighting: string,
  palette: string,
): string {
  const params = node.params || {};
  const bits = [
    opticalValue(params.lens, lens),
    opticalValue(params.aperture, aperture),
    opticalValue(params.look, look),
    opticalValue(params.genre, genre),
    opticalValue(params.camera, camera),
  ];
  const light = opticalValue(params.lighting, lighting);
  if (light && light !== "available") bits.push(light);
  const pal = opticalValue(params.palette, palette);
  if (pal && pal !== "filmic") bits.push(pal);
  const move = opticalValue(params.motion, motion);
  if (move && move !== "static") bits.push(move);
  return bits.filter(Boolean).join(" · ");
}

function wantsFrames(model?: Model): boolean {
  const blob = `${model?.id || ""} ${model?.display_name || ""}`.toLowerCase();
  return blob.includes("flf") || blob.includes("first-last") || blob.includes("first_last");
}

function panelFor(model: Model | undefined, page: string) {
  const caps = model?.capabilities || [];
  const blob = `${model?.id || ""} ${model?.display_name || ""}`.toLowerCase();
  const t2v = caps.includes("t2v");
  const i2v = caps.includes("i2v");
  const t2i = caps.includes("t2i");
  const i2i = caps.includes("i2i");
  const upscale = caps.includes("upscale");
  const videoJob = t2v || i2v;
  const tts = caps.includes("tts") && !videoJob && !t2i;
  const lipsync = caps.includes("lipsync") && !videoJob;
  const voice = (caps.includes("voice_clone") || caps.includes("sts")) && !videoJob && !t2i;
  const clip = upscale && !i2i && !videoJob && blob.includes("video");
  const imageUpscale = upscale && !videoJob && !clip;
  let stillAccept = "image/*";
  let stillLabel = "Still";
  let stillHint = "Optional.";
  if (clip) {
    stillAccept = "video/*";
    stillLabel = "Clip";
    stillHint = "Required.";
  } else if (lipsync) {
    stillAccept = "video/*,audio/*";
    stillLabel = "Video and audio";
    stillHint = "Required.";
  } else if (voice) {
    stillAccept = "audio/*";
    stillLabel = "Reference audio";
    stillHint = "Required.";
  } else if (imageUpscale || (i2v && !t2v) || (i2i && !t2i) || blob.includes("r2v")) {
    stillHint = "Required.";
  } else if (i2v && t2v) {
    stillHint = "Optional. A still runs image-to-video.";
  } else if (i2i && t2i) {
    stillHint = "Optional. A still edits this image.";
  }
  return {
    showStill: Boolean(i2v || (i2i && !videoJob) || clip || imageUpscale || lipsync || voice || blob.includes("r2v")),
    showFrames: wantsFrames(model),
    showOptical: Boolean((t2i || i2i || videoJob) && !tts && !lipsync && !voice),
    showMotion: videoJob,
    showScale: Boolean(upscale && i2i && !videoJob),
    showMagnific: Boolean(model?.provider === "magnific" && upscale && !blob.includes("precision") && !videoJob),
    showScene: page === "speak" && Boolean((t2i || i2v) && !tts && !lipsync && !voice),
    showCast: Boolean(t2i || i2i || i2v),
    stillAccept,
    stillLabel,
    stillHint,
  };
}

function modelIdForNode(node: GraphNode, fallbackId: string, catalog: Model[]): string {
  const cap = node.capability;
  for (const id of [node.model_id, fallbackId]) {
    if (!id) continue;
    const row = catalog.find((m) => m.id === id);
    if (row && (!cap || row.capabilities.includes(cap))) return id;
  }
  const match = catalog.find((m) => !cap || m.capabilities.includes(cap));
  return match?.id || fallbackId;
}

function graphFromSkill(
  skill: Skill,
  camera: string,
  lens: string,
  look: string,
  motion: string,
  aperture: string,
  genre: string,
  lighting: string,
  palette: string,
) {
  const wf = skill.workflow || { nodes: [], edges: [] };
  return {
    nodes: (wf.nodes || []).map((n, i) => ({
      ...n,
      params: stampOptical(n.params, camera, lens, look, motion, aperture, genre, lighting, palette),
      x: 40 + (i % 3) * 230,
      y: 36 + Math.floor(i / 3) * 168,
    })),
    edges: wf.edges || [],
  };
}

function RailIcon({ d, title }: { d: string; title: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <title>{title}</title>
      <path d={d} stroke="currentColor" />
    </svg>
  );
}

export function StudioClient() {
  const [page, setPage] = useState<PageId>("explore");
  const [navOpen, setNavOpen] = useState(false);
  const [view, setView] = useState<"canvas" | "timeline">("canvas");
  const [category, setCategory] = useState("all");
  const [models, setModels] = useState<Model[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [doctor, setDoctor] = useState<Doctor>({});
  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState("");
  const [camera, setCamera] = useState("locked-off");
  const [lens, setLens] = useState("50mm");
  const [look, setLook] = useState("commercial");
  const [lighting, setLighting] = useState("available");
  const [palette, setPalette] = useState("filmic");
  const [motion, setMotion] = useState("static");
  const [aperture, setAperture] = useState("f/2.8");
  const [genre, setGenre] = useState("drama");
  const [scene, setScene] = useState("general");
  const [creativity, setCreativity] = useState(0);
  const [resemblance, setResemblance] = useState(0);
  const [hdr, setHdr] = useState(0);
  const [fractality, setFractality] = useState(0);
  const [optimizedFor, setOptimizedFor] = useState("standard");
  const [engine, setEngine] = useState("automatic");
  const [elementKind, setElementKind] = useState<(typeof ELEMENT_KINDS)[number]>("character");
  const [aspectRatio, setAspectRatio] = useState("");
  const [duration, setDuration] = useState("");
  const [scale, setScale] = useState("4x");
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [graphHistory, setGraphHistory] = useState(() => startHistory(EMPTY_GRAPH));
  const graph = graphHistory.present;
  /** Every canvas edit goes through here so it can be undone. */
  const setGraph = useCallback((next: Graph | ((g: Graph) => Graph)) => {
    setGraphHistory((h) => commit(h, typeof next === "function" ? next(h.present) : next));
  }, []);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [viewport, setViewport] = useState<Viewport>(HOME_VIEW);
  const [canvasTool, setCanvasTool] = useState<"select" | "pan">("select");
  const [panning, setPanning] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  /** Add menu at board coords; `from` set when opened from a node's output port. */
  const [addMenu, setAddMenu] = useState<{ x: number; y: number; from?: string; kind?: MediaKind | null } | null>(null);
  const [addQuery, setAddQuery] = useState("");
  const [addIndex, setAddIndex] = useState(0);
  /** Graph before the current prompt edit; the whole edit lands as one undo step on blur. */
  const promptBaseRef = useRef<Graph | null>(null);
  // Removing a focused textarea need not fire blur (Firefox), and it unmounts on node switch (keyed),
  // page change, or leaving the canvas; settle the edit then too. Stable, since settlePrompt reads refs.
  const settleOnUnmount = useCallback((el: HTMLTextAreaElement | null) => {
    if (!el) settlePrompt();
  }, []);
  const boardRef = useRef<HTMLDivElement>(null);
  const spaceRef = useRef(false);
  const panRef = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const viewportRef = useRef(viewport);
  viewportRef.current = viewport;
  /** A run-affecting canvas edit since load; Generate then sends the canvas instead of the template skill. */
  const graphEdited = useMemo(() => isEdited(graphHistory), [graphHistory]);
  const [skillRef, setSkillRef] = useState<string | null>(null);
  const [selection, setSelection] = useState<string[]>([]);
  /** The one selected node (drawer, per-node actions); null when none or several are selected. */
  const selectedNode = selection.length === 1 ? selection[0] : null;
  const setSelectedNode = useCallback((id: string | null) => setSelection(id ? [id] : []), []);
  /** Marquee rectangle in board coords while dragging on empty canvas. */
  const [marquee, setMarquee] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const marqueeRef = useRef<{ x: number; y: number; add: boolean } | null>(null);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);
  const [renamingGroup, setRenamingGroup] = useState<string | null>(null);
  /** Last run state per canvas node, shown on its card. */
  const [nodeRuns, setNodeRuns] = useState<Record<string, { state: "running" | "done" | "cached" | "error"; error?: string }>>({});
  /** Bumped per loaded graph, so a run that finishes after a reset cannot badge the new graph's nodes. */
  const graphEpochRef = useRef(0);
  /** Loading a template, skill, or collab snapshot starts a fresh history and drops stale selection or drags. */
  const resetGraph = useCallback((next: Graph) => {
    setGraphHistory(startHistory(next));
    setViewport(HOME_VIEW);
    setSelection([]);
    setSelectedEdge(null);
    setNodeRuns({}); // states are keyed by node id; a new graph may reuse ids
    graphEpochRef.current += 1;
    dragRef.current = null;
  }, []);
  const [runIds, setRunIds] = useState<string[]>([]);
  const [log, setLog] = useState("");
  const [busy, setBusy] = useState(false);
  const [findQ, setFindQ] = useState("pricing");
  const [findHits, setFindHits] = useState<{ uri?: string; transcript?: string }[]>([]);
  const [costBody, setCostBody] = useState("");
  const [tlStatus, setTlStatus] = useState("Graph outputs in order");
  const [tlMedia, setTlMedia] = useState<{ src: string; video: boolean } | null>(null);
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [connectId, setConnectId] = useState("");
  const [libTab, setLibTab] = useState<"all" | "elements" | "shots">("all");
  const [brief, setBrief] = useState("");
  const [plan, setPlan] = useState<PlanStep[]>([]);
  const [yaw, setYaw] = useState(18);
  const [collabId, setCollabId] = useState("");
  const [collabName, setCollabName] = useState("Session");
  const [sessions, setSessions] = useState<{ id: string; name: string }[]>([]);
  const [onboardOpen, setOnboardOpen] = useState(false);
  const [onboardStep, setOnboardStep] = useState(0);
  const [stageReset, setStageReset] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  const [galleryQuery, setGalleryQuery] = useState("");
  const [pref, setPref] = useState("cheapest");
  const [maxCost, setMaxCost] = useState("");
  const [monthlyCap, setMonthlyCap] = useState("");
  const [resolution, setResolution] = useState("");
  const [firstFrameId, setFirstFrameId] = useState<string | null>(null);
  const [lastFrameId, setLastFrameId] = useState<string | null>(null);
  const [cast, setCast] = useState<CastRow[]>([]);
  const [castName, setCastName] = useState("");
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  /** Node or frame drag: pointer start (screen), node starts (graph units), selection on a plain click. */
  const dragRef = useRef<{
    starts: Record<string, { x: number; y: number }>;
    click: string[];
    x: number;
    y: number;
    moved: boolean;
    base: Graph;
  } | null>(null);
  const graphRef = useRef<Graph>(EMPTY_GRAPH);
  const trackedRef = useRef<string[]>([]);
  graphRef.current = graph;
  const linkFromRef = useRef<string | null>(null);
  const castFileRef = useRef<HTMLInputElement>(null);
  const composeStillRef = useRef<HTMLInputElement>(null);
  const adaptFileRef = useRef<HTMLInputElement>(null);
  const oauthAttemptRef = useRef(0);
  const [adaptPresets, setAdaptPresets] = useState<AdaptPresetRow[]>([]);
  const [adaptSourceId, setAdaptSourceId] = useState<string | null>(null);
  const [adaptTargets, setAdaptTargets] = useState<AdaptTarget[]>([
    { preset_id: "amazon_828x300" },
    { preset_id: "inuxu_1200x720" },
  ]);
  const [adaptLayout, setAdaptLayout] = useState<"fit_pad_crop" | "ai_extend">("fit_pad_crop");
  const [adaptFit, setAdaptFit] = useState<"fit" | "pad" | "crop">("pad");
  const [adaptPartnerOnly, setAdaptPartnerOnly] = useState(true);
  const [adaptEstimateUsd, setAdaptEstimateUsd] = useState<number | null>(null);
  const [adaptNote, setAdaptNote] = useState("");
  const [adaptOutputs, setAdaptOutputs] = useState<string[]>([]);
  const [adaptValidations, setAdaptValidations] = useState<Record<string, unknown>[]>([]);
  const [adaptView, setAdaptView] = useState<"form" | "flow">("form");
  const [adaptBatch, setAdaptBatch] = useState<BatchStatus | null>(null);
  const [showSafe, setShowSafe] = useState(true);
  const [presetFormOpen, setPresetFormOpen] = useState(false);
  const [presetDraft, setPresetDraft] = useState<PresetDraft>(EMPTY_PRESET_DRAFT);

  const composeModels = useMemo(() => {
    const list = models.filter((m) => {
      const caps = m.capabilities || [];
      if (page === "image") return caps.includes("t2i");
      if (page === "video") return caps.includes("t2v") || caps.includes("i2v");
      if (page === "upscale") return caps.includes("upscale");
      if (page === "speak") return caps.includes("tts") || caps.includes("lipsync") || caps.includes("i2v");
      return caps.includes("t2i") || caps.includes("t2v") || caps.includes("i2i");
    });
    const rows = (list.length ? list : models).filter((m) => m.provider !== "mock").slice();
    rows.sort((a, b) => {
      if (page === "upscale") {
        const stillA = (a.capabilities || []).includes("i2i") ? 0 : 1;
        const stillB = (b.capabilities || []).includes("i2i") ? 0 : 1;
        if (stillA !== stillB) return stillA - stillB;
      }
      const live = !!doctor.live_spend;
      const rank =
        availabilityRank(modelAvailability(a, doctor.providers?.[a.provider], live)) -
        availabilityRank(modelAvailability(b, doctor.providers?.[b.provider], live));
      if (rank) return rank;
      return (a.display_name || "").localeCompare(b.display_name || "");
    });
    return rows;
  }, [models, page, doctor]);

  function statusSuffix(row: Model): string {
    const status = modelAvailability(row, doctor.providers?.[row.provider], !!doctor.live_spend);
    if (status === "spend_off") return " · spend off";
    if (status === "not_enabled") return " · not enabled";
    if (status === "needs_key") return " · needs key";
    return "";
  }

  const galleryModels = useMemo(
    () => rankModels(composeModels, galleryQuery),
    [composeModels, galleryQuery],
  );

  useEffect(() => {
    setGalleryQuery("");
  }, [page]);

  useEffect(() => {
    if (!composeModels.length) return;
    const current = composeModels.find((m) => m.id === modelId);
    if (page === "upscale") {
      const still = composeModels.find((m) => (m.capabilities || []).includes("i2i"));
      if (still && (!current || !(current.capabilities || []).includes("i2i"))) {
        setModelId(still.id);
        return;
      }
    }
    if (current) return;
    const next = composeModels[0];
    if (next) setModelId(next.id);
  }, [composeModels, modelId, page]);

  const selected = composeModels.find((m) => m.id === modelId) || composeModels[0];
  const mode = panelFor(selected, page);
  const opticalPage = mode.showOptical;
  const videoish = mode.showMotion;

  const loadMedia = useCallback(async () => {
    const [runBody, assetBody] = await Promise.all([
      api<{ runs: Run[] }>("/runs"),
      api<{ assets: Asset[] }>("/assets"),
    ]);
    setRuns(runBody.runs || []);
    setAssets(assetBody.assets || []);
  }, []);

  const adaptPresetChoices = useMemo(() => {
    const rows = adaptPresets.slice();
    if (adaptPartnerOnly) {
      return rows.filter((p) => p.source === "partner" || p.source === "custom" || p.spec_kind === "client_partner");
    }
    return rows;
  }, [adaptPresets, adaptPartnerOnly]);

  const reloadPresets = useCallback(async () => {
    const body = await api<{ presets: AdaptPresetRow[] }>("/presets");
    setAdaptPresets(body.presets || []);
  }, []);

  const uploadAdaptSource = useCallback(
    async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(`${API}/assets`, { method: "POST", body });
      if (!res.ok) {
        throw new Error(await res.text());
      }
      const asset = (await res.json()) as { id: string };
      setAdaptSourceId(asset.id);
      await loadMedia();
      setLog(`Source uploaded · vinci://assets/${asset.id}`);
    },
    [loadMedia],
  );

  const estimateAdapt = useCallback(async () => {
    if (!adaptSourceId) {
      setLog("Upload a source creative first.");
      return;
    }
    const body = await api<AdaptEstimateBody>("/adapt/estimate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        source_asset: adaptSourceId,
        targets: adaptTargets,
        layout: adaptLayout,
      }),
    });
    setAdaptEstimateUsd(body.total);
    setAdaptNote(body.note || "");
    setLog(`Adapt estimate: ${money(body.total)} for ${adaptTargets.length} target(s).`);
  }, [adaptLayout, adaptSourceId, adaptTargets]);

  const runAdapt = useCallback(async () => {
    if (!adaptSourceId) {
      setLog("Upload a source creative first.");
      return;
    }
    const presetIds = adaptTargets.map((row) => row.preset_id).filter((id): id is string => Boolean(id));
    if (!presetIds.length) {
      setLog("Pick at least one preset.");
      return;
    }
    setBusy(true);
    try {
      await estimateAdapt();
      const created = await api<{ batch_id: string }>("/adapts/batch", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          items: [{ asset_id: adaptSourceId, preset_ids: presetIds }],
          fit_mode: adaptFit,
          layout: adaptLayout,
        }),
      });
      const status = await api<BatchStatus>(`/adapts/batch/${created.batch_id}`);
      setAdaptBatch(status);
      const outputs = status.items.flatMap((item) => item.output_asset_ids || []);
      setAdaptOutputs(outputs);
      setAdaptValidations(status.items.flatMap((item) => item.outputs || []));
      await loadMedia();
      const failed = status.items.filter((item) => item.status === "failed").length;
      setLog(
        failed
          ? `Batch ${created.batch_id}: ${failed} item(s) failed.`
          : `Adapts complete: ${outputs.length} outputs.`,
      );
    } catch (err) {
      setLog(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [adaptFit, adaptLayout, adaptSourceId, adaptTargets, estimateAdapt, loadMedia]);

  const createPreset = useCallback(async () => {
    const width = Number(presetDraft.width);
    const height = Number(presetDraft.height);
    const body: Record<string, unknown> = {
      label: presetDraft.label.trim(),
      platform: presetDraft.platform.trim(),
      width,
      height,
    };
    if (presetDraft.kb.trim()) {
      body.byte_cap = { max_bytes: Math.round(Number(presetDraft.kb) * 1024), op: "lte" };
    }
    const margins = {
      left: Number(presetDraft.left || 0),
      right: Number(presetDraft.right || 0),
      top: Number(presetDraft.top || 0),
      bottom: Number(presetDraft.bottom || 0),
    };
    if (margins.left || margins.right || margins.top || margins.bottom) {
      body.safe_rect_margins_px = margins;
    }
    try {
      await api("/presets", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      setPresetDraft(EMPTY_PRESET_DRAFT);
      setPresetFormOpen(false);
      await reloadPresets();
      setLog("Custom preset saved.");
    } catch (err) {
      setLog(err instanceof Error ? err.message : String(err));
    }
  }, [presetDraft, reloadPresets]);

  const deletePreset = useCallback(
    async (id: string) => {
      try {
        await api(`/presets/${id}`, { method: "DELETE" });
        await reloadPresets();
        setLog(`Deleted preset ${id}.`);
      } catch (err) {
        setLog(err instanceof Error ? err.message : String(err));
      }
    },
    [reloadPresets],
  );

  const boot = useCallback(async () => {
    try {
      await api("/init", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ demo: true }),
      });
      const [doc, modelBody, skillBody, tplBody, presetBody] = await Promise.all([
        api<Doctor>("/doctor"),
        api<{ models: Model[] }>("/models"),
        api<{ skills: Skill[] }>("/skills"),
        api<{ templates: Template[] }>("/templates"),
        api<{ presets: AdaptPresetRow[] }>("/presets"),
      ]);
      setDoctor(doc);
      setPref(doc.preference || "cheapest");
      setMonthlyCap(doc.budget?.monthly_cap_usd != null ? String(doc.budget.monthly_cap_usd) : "");
      setModels((modelBody.models || []).filter((m) => m.provider !== "mock"));
      setSkills(skillBody.skills || []);
      setTemplates(tplBody.templates || []);
      setAdaptPresets(presetBody.presets || []);
      const first = (modelBody.models || []).find((m) => m.provider !== "mock");
      setModelId((prev) => prev || first?.id || "");
      await loadMedia();
    } catch (err) {
      setLog(err instanceof Error ? err.message : String(err));
    }
  }, [loadMedia]);

  useEffect(() => {
    void boot();
  }, [boot]);

  useEffect(() => {
    try {
      if (localStorage.getItem(ONBOARD_KEY) !== "done") setOnboardOpen(true);
    } catch {
      setOnboardOpen(true);
    }
  }, []);

  useEffect(() => {
    setModelsOpen(false);
  }, [page]);

  useEffect(() => {
    if (page !== "cost") return;
    void api<{ totals: unknown }>("/cost/report")
      .then((body) => setCostBody(JSON.stringify(body.totals || {}, null, 2)))
      .catch((err) => setCostBody(String(err)));
  }, [page]);

  useEffect(() => {
    if (page !== "collab") return;
    void api<{ sessions: { id: string; name: string }[] }>("/collab/sessions")
      .then((body) => setSessions(body.sessions || []))
      .catch((err) => setLog(String(err)));
  }, [page]);

  useEffect(() => {
    function move(ev: PointerEvent) {
      const pan = panRef.current;
      if (pan) {
        setViewport((v) => ({ ...v, x: pan.vx + ev.clientX - pan.x, y: pan.vy + ev.clientY - pan.y }));
        return;
      }
      const box = marqueeRef.current;
      const rect = boardRef.current?.getBoundingClientRect();
      if (box && rect) {
        const px = ev.clientX - rect.left;
        const py = ev.clientY - rect.top;
        setMarquee({ x: Math.min(box.x, px), y: Math.min(box.y, py), w: Math.abs(px - box.x), h: Math.abs(py - box.y) });
        return;
      }
      const drag = dragRef.current;
      if (!drag) return;
      if (!drag.moved && Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y) < 4) return;
      if (!drag.moved) {
        // What moves becomes the selection, so Delete acts on the node just dragged.
        setSelection(Object.keys(drag.starts));
        setSelectedEdge(null);
      }
      drag.moved = true;
      const zoom = viewportRef.current.zoom;
      const dx = (ev.clientX - drag.x) / zoom;
      const dy = (ev.clientY - drag.y) / zoom;
      setGraphHistory((h) => preview(h, moveNodes(h.present, drag.starts, dx, dy)));
    }
    function up() {
      if (panRef.current) {
        panRef.current = null;
        setPanning(false);
      }
      const box = marqueeRef.current;
      if (box) {
        marqueeRef.current = null;
        setMarquee((m) => {
          if (m && m.w > 4 && m.h > 4) {
            const v = viewportRef.current;
            const hit = nodesInRect(graphRef.current, {
              x: (m.x - v.x) / v.zoom,
              y: (m.y - v.y) / v.zoom,
              w: m.w / v.zoom,
              h: m.h / v.zoom,
            });
            setSelection((sel) => (box.add ? [...new Set([...sel, ...hit])] : hit));
          }
          return null;
        });
      }
      const drag = dragRef.current;
      if (drag && !drag.moved) {
        setSelection(drag.click);
        setSelectedEdge(null);
      } else if (drag) {
        setGraphHistory((h) => settle(h, drag.base));
      }
      dragRef.current = null;
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, []);

  const usable = (model?: Model) => {
    if (!model) return false;
    if (model.provider === "mock") return true;
    return !!model.available && !!doctor.live_spend;
  };

  const ratios = selected?.constraints?.aspect_ratios || [];
  const durs = useMemo(() => {
    const max = Number(selected?.constraints?.max_duration || 0);
    if (!max) return [] as number[];
    const picks = [3, 5, 6, 8, 10, 15].filter((n) => n <= max);
    if (!picks.length) picks.push(max);
    return [...new Set(picks)];
  }, [selected]);

  const projectRuns = useMemo(() => {
    const ids = new Set(runIds);
    return ids.size ? runs.filter((r) => ids.has(r.id)) : runs.slice(-3);
  }, [runIds, runs]);
  const lastRun = projectRuns.at(-1);
  const lastDigest = lastRun?.outputs?.[0];
  const lastAsset = assets.find((a) => a.id === lastDigest);
  const hasComposeMedia = Boolean(
    !stageReset && (lastDigest || ((page === "upscale" || page === "speak") && uploadId)),
  );
  const wantsInsp =
    page === "canvas" ||
    page === "image" ||
    page === "video" ||
    page === "speak" ||
    (page === "upscale" && (hasComposeMedia || busy));
  const lastStill = useMemo(() => {
    for (const run of [...projectRuns].reverse()) {
      for (const id of [...(run.outputs || [])].reverse()) {
        const row = assets.find((a) => a.id === id);
        if (row?.mime?.startsWith("image/")) return id;
      }
    }
    return assets.find((a) => a.mime?.startsWith("image/"))?.id || null;
  }, [assets, projectRuns]);

  function imageAssetId(id: string | null): string | null {
    if (!id) return null;
    const row = assets.find((item) => item.id === id);
    return row?.mime?.startsWith("image/") ? id : null;
  }

  function animateStill(model?: Model): boolean {
    const caps = model?.capabilities || [];
    if (!caps.includes("i2v")) return false;
    if (!caps.includes("t2v")) return true;
    return Boolean(imageAssetId(uploadId) || imageAssetId(firstFrameId));
  }

  function skillFor(model?: Model): string {
    const caps = model?.capabilities || [];
    const videoJob = caps.includes("t2v") || caps.includes("i2v");
    if (page === "canvas" && skillRef && !graphEdited) return skillRef;
    if (caps.includes("voice_clone") && !videoJob && !caps.includes("t2i")) return "@tryvinci/voice-clone";
    if (caps.includes("tts") && !videoJob && !caps.includes("t2i")) return "@tryvinci/tts";
    if (caps.includes("lipsync") && !videoJob) return "@tryvinci/lipsync";
    if (caps.includes("upscale") && !caps.includes("i2i") && !caps.includes("t2i") && !videoJob) return "@tryvinci/video-upscale";
    if ((caps.includes("i2i") || caps.includes("upscale")) && !videoJob && !caps.includes("t2i")) return "@tryvinci/image-upscale";
    if (caps.includes("i2i") && caps.includes("t2i") && Boolean(imageAssetId(uploadId) || imageAssetId(firstFrameId)) && !videoJob) {
      return "@tryvinci/image-upscale";
    }
    if (videoJob) return "@tryvinci/video-generate";
    return "@tryvinci/image-generate";
  }

  function shotInputs(base: Record<string, unknown>) {
    const inputs = { ...base };
    if (aspectRatio && ratios.length) inputs.aspect_ratio = aspectRatio;
    if (duration && mode.showMotion) inputs.duration = Number(duration);
    if (resolution && (selected?.constraints?.resolutions || []).length) inputs.resolution = resolution;
    if (scale && mode.showScale) inputs.scale = scale;
    if (mode.showOptical) {
      if (camera) inputs.camera = camera;
      if (lens) inputs.lens = lens;
      if (look) inputs.look = look;
      if (lighting) inputs.lighting = lighting;
      if (palette) inputs.palette = palette;
      if (aperture) inputs.aperture = aperture;
      if (genre) inputs.genre = genre;
    }
    if (motion && mode.showMotion) inputs.motion = motion;
    if (scene && mode.showScene) inputs.scene = scene;
    if (mode.showMagnific) {
      inputs.creativity = creativity;
      inputs.resemblance = resemblance;
      inputs.hdr = hdr;
      inputs.fractality = fractality;
      inputs.optimized_for = optimizedFor;
      inputs.engine = engine;
    }
    if (mode.showFrames && firstFrameId) {
      inputs.first_frame_url = firstFrameId;
      inputs.start_image_url = firstFrameId;
      inputs.image = firstFrameId;
    }
    if (mode.showFrames && lastFrameId) {
      inputs.last_frame_url = lastFrameId;
      inputs.tail_image_url = lastFrameId;
    }
    if (mode.showStill && uploadId) {
      inputs.media = uploadId;
      if (!inputs.image) inputs.image = uploadId;
    }
    if (mode.showCast || mode.showStill) {
      const urls: string[] = [];
      if (typeof inputs.image === "string" && inputs.image) urls.push(inputs.image);
      if (mode.showCast) {
        for (const row of cast) {
          if (row.assetId && !urls.includes(row.assetId)) urls.push(row.assetId);
        }
      }
      if (urls.length) {
        inputs.image_urls = urls.slice(0, 8);
        if (!inputs.image) inputs.image = urls[0];
      }
    }
    return inputs;
  }

  function stampSelected(patch: Record<string, unknown>) {
    if (!selectedNode) return;
    setGraph((g) => setParams(g, selectedNode, patch));
  }

  function stepHistory(dir: "undo" | "redo") {
    const next = dir === "undo" ? undo(graphHistory) : redo(graphHistory);
    if (next === graphHistory) return;
    setGraphHistory(next);
    // Undoing an insert or duplicate must not leave its id selected (Delete and the drawer would point at nothing).
    const ids = new Set(next.present.nodes.map((n) => n.id));
    setSelection((sel) => sel.filter((id) => ids.has(id)));
    setSelectedEdge(null);
  }

  function boardSize(): { w: number; h: number } {
    const r = boardRef.current?.getBoundingClientRect();
    return { w: r?.width || 0, h: r?.height || 0 };
  }

  /** Zoom by `factor` around the board centre. */
  function zoomBy(factor: number) {
    const { w, h } = boardSize();
    setViewport((v) => zoomAt(v, v.zoom * factor, w / 2, h / 2));
  }

  function fitTo(nodes: GraphNode[]) {
    const { w, h } = boardSize();
    // offsetHeight ignores the board's zoom transform, so these are graph units.
    const heights = new Map<string, number>();
    boardRef.current?.querySelectorAll<HTMLElement>(".node[data-id]").forEach((el) => {
      if (el.dataset.id) heights.set(el.dataset.id, el.offsetHeight);
    });
    setViewport(fitView(nodes, w, h, undefined, heights));
  }

  function runShortcut(id: ShortcutId) {
    switch (id) {
      case "undo":
        return stepHistory("undo");
      case "redo":
        return stepHistory("redo");
      case "delete":
        return deleteSelection();
      case "addNode":
        return openAddMenu();
      case "clear":
        closeAddMenu();
        setCtxMenu(null);
        setRenamingGroup(null);
        setSheetOpen(false);
        setSelectedNode(null);
        setSelectedEdge(null);
        return;
      case "duplicate": {
        if (!selection.length) return;
        const copies = selection.map((id) => {
          const src = graph.nodes.find((n) => n.id === id);
          return [id, (src?.capability || "node") + "-" + Math.random().toString(16).slice(2, 6)] as const;
        });
        setGraph((g) => copies.reduce((acc, [id, copyId]) => duplicateNode(acc, id, copyId), g));
        setSelection(copies.map(([, copyId]) => copyId));
        setLog(copies.length === 1 ? `Duplicated ${copies[0][0]} as ${copies[0][1]}.` : `Duplicated ${copies.length} nodes.`);
        return;
      }
      case "selectAll":
        setSelection(graph.nodes.map((n) => n.id));
        setSelectedEdge(null);
        return;
      case "runSelection":
        return runNodes(selection);
      case "runAll": {
        const blocker = graph.nodes.length ? runBlocker(graph.nodes.map((n) => n.id)) : "Canvas is empty.";
        if (blocker) return setLog(blocker);
        return void generate({ graph: true });
      }
      case "group":
        return groupSelection();
      case "ungroup":
        return ungroupSelection();
      case "fit":
        return fitTo(graph.nodes);
      case "fitSelection": {
        const rows = graph.nodes.filter((n) => selection.includes(n.id));
        return fitTo(rows.length ? rows : graph.nodes);
      }
      case "resetView": {
        const { w, h } = boardSize();
        return setViewport((v) => zoomAt(v, 1, w / 2, h / 2));
      }
      case "zoomIn":
        return zoomBy(1.2);
      case "zoomOut":
        return zoomBy(1 / 1.2);
      case "panMode":
        return setCanvasTool("pan");
      case "selectMode":
        return setCanvasTool("select");
      case "help":
        return setSheetOpen((open) => !open);
    }
  }

  function groupSelection() {
    if (selection.length < 2) {
      setLog("Select two or more nodes to group (shift-click or drag a box).");
      return;
    }
    if (groupOf(graph, selection)) {
      setLog("Already a group. Double-click the title to rename.");
      return;
    }
    const id = "group-" + Math.random().toString(16).slice(2, 6);
    setGraph((g) => groupNodes(g, selection, id));
    setLog(`Grouped ${selection.length} nodes. Double-click the title to rename.`);
  }

  function ungroupSelection() {
    const next = ungroupNodes(graph, selection);
    if (next === graph) {
      setLog("Nothing selected is in a group.");
      return;
    }
    setGraph(next);
    setLog("Ungrouped.");
  }

  /** Start a drag of `ids` (a node, a selection, or a frame's members); a plain click selects `click`. */
  function startDrag(ev: { clientX: number; clientY: number }, ids: string[], click: string[]) {
    dragRef.current = {
      starts: Object.fromEntries(graph.nodes.filter((n) => ids.includes(n.id)).map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }])),
      click,
      x: ev.clientX,
      y: ev.clientY,
      moved: false,
      base: graph,
    };
  }

  /** Right-click menu at the pointer, in board coords. */
  function openCtxMenu(ev: { clientX: number; clientY: number; preventDefault: () => void }) {
    ev.preventDefault();
    const r = boardRef.current?.getBoundingClientRect();
    if (!r) return;
    closeAddMenu();
    setCtxMenu({ x: Math.min(ev.clientX - r.left, r.width - 200), y: Math.min(ev.clientY - r.top, r.height - 220) });
  }

  /** Delete the selected wire, or else the selected nodes and their wires. */
  function deleteSelection() {
    if (selectedEdge) {
      setGraph((g) => disconnect(g, selectedEdge.src, selectedEdge.dst));
      setLog(`Removed the wire ${selectedEdge.src} → ${selectedEdge.dst}.`);
      setSelectedEdge(null);
    } else if (selection.length) {
      const gone = selection;
      setGraph((g) => removeNodes(g, gone));
      setLog(`Deleted ${gone.length === 1 ? gone[0] : gone.length + " nodes"}. Undo with ⌘Z.`);
      setSelection([]);
    } else return;
  }

  async function ingest(file: File): Promise<Asset> {
    const data = new FormData();
    data.append("file", file);
    const res = await fetch(API + "/assets", { method: "POST", body: data });
    if (!res.ok) throw new Error(await res.text());
    const asset = (await res.json()) as Asset;
    const mime = asset.mime && asset.mime !== "application/octet-stream" ? asset.mime : file.type || asset.mime;
    const stored = { ...asset, mime };
    setAssets((rows) => (rows.some((row) => row.id === stored.id) ? rows : [stored, ...rows]));
    return stored;
  }

  function nodeDigest(id: string): string | null {
    for (const run of [...projectRuns].reverse()) {
      const row = run.nodes?.[id];
      if (row?.output) return row.output;
      if (row?.outputs?.[0]) return row.outputs[0];
    }
    return null;
  }

  async function generate(opts?: { nodeIds?: string[]; graph?: boolean }) {
    if (busy) return;
    const epoch = graphEpochRef.current;
    const model = selected;
    // Generate graph and node runs always send the canvas; animating a still is a page run.
    const animating = animateStill(model) && mode.showStill && !opts?.nodeIds?.length && !opts?.graph;
    const skill = skillFor(model);
    if (!model) {
      setLog("Studio is still loading models.");
      return;
    }
    const generateNodes = graph.nodes.filter((n) => n.type === "generate");
    // A canvas run can get its image from an upstream node, so only page runs need one up front.
    const canvasRun = !animating && (!!opts?.nodeIds?.length || ((graphEdited || !!opts?.graph) && generateNodes.length > 0));
    // Canvas nodes run on their pinned model or one the runtime picks: only page runs, targets that fall
    // back to the page model, and nodes pinned to it need it to be usable.
    const targets = new Set(opts?.nodeIds || []);
    const sent = targets.size ? graph.nodes.filter((n) => withAncestors(graph, targets).has(n.id)) : generateNodes;
    const pageModelUsed =
      !canvasRun || sent.some((n) => (targets.has(n.id) ? modelIdForNode(n, model.id, models) : n.model_id) === model.id);
    if (pageModelUsed && model.provider !== "mock" && !usable(model)) {
      const status = modelAvailability(model, doctor.providers?.[model.provider], !!doctor.live_spend);
      if (status === "spend_off") {
        setLog("This model has a key, but live spend is off. Set VINCI_ALLOW_LIVE_SPEND=1 to call it.");
        return;
      }
      setPage("keys");
      setLog(
        status === "not_enabled"
          ? "This provider has a saved key but is not enabled. Open Connect."
          : "This model needs a key. Open Connect.",
      );
      return;
    }
    const inputs = runInputs(model);
    const skillNodes = (skills.find((s) => s.id === skill)?.workflow?.nodes || []).filter((n) => n.type === "generate");
    // Skills like still-to-upscale generate their own media first; only a bare upscale needs a page image.
    const makesMedia = skillNodes.some((n) => n.capability === "t2i" || n.capability === "t2v");
    if (animating) {
      if (!inputs.media) {
        setLog("Add a still, then describe how it should move.");
        return;
      }
    } else if (!canvasRun && ((skill.includes("upscale") && !makesMedia) || page === "upscale") && !uploadId && !lastDigest) {
      setLog("Generate or drop a still first, then upscale.");
      return;
    }
    setBusy(true);
    setStageReset(false);
    setModelsOpen(false);
    setLog("Generating… " + (skillRef || skill));
    try {
      const payload: Record<string, unknown> = { inputs, preference: pref };
      if (animating) {
        payload.workflow = {
          id: "image-to-video",
          version: "1.0.0",
          preference: pref,
          nodes: [
            {
              id: "generate",
              type: "generate",
              capability: "i2v",
              model_id: model.id,
              params: {
                prompt: "{{inputs.prompt}}",
                image: "{{inputs.image}}",
                media: "{{inputs.media}}",
                aspect_ratio: "{{inputs.aspect_ratio}}",
                duration: "{{inputs.duration}}",
                resolution: "{{inputs.resolution}}",
                camera: "{{inputs.camera}}",
                lens: "{{inputs.lens}}",
                look: "{{inputs.look}}",
                lighting: "{{inputs.lighting}}",
                palette: "{{inputs.palette}}",
                motion: "{{inputs.motion}}",
                aperture: "{{inputs.aperture}}",
                genre: "{{inputs.genre}}",
                first_frame_url: "{{inputs.first_frame_url}}",
                last_frame_url: "{{inputs.last_frame_url}}",
                image_urls: "{{inputs.image_urls}}",
              },
            },
          ],
          edges: [],
        };
      }
      const cap = Number(maxCost);
      if (maxCost !== "" && !Number.isNaN(cap)) payload.max_cost = cap;
      // Canvas nodes this run will show state on.
      let tracked: string[] = [];
      if (targets.size) {
        const keep = withAncestors(graph, targets);
        tracked = [...keep];
        payload.workflow = {
          id: "canvas-node",
          version: "1.0.0",
          preference: pref,
          nodes: toWorkflowNodes(graph.nodes.filter((n) => keep.has(n.id))).map((n) =>
            targets.has(n.id) ? { ...n, model_id: modelIdForNode(n, model.id, models) } : n,
          ),
          edges: graph.edges.filter((e) => keep.has(e.src) && keep.has(e.dst)),
        };
      } else if (!payload.workflow && (graphEdited || opts?.graph) && generateNodes.length) {
        tracked = generateNodes.map((n) => n.id);
        payload.workflow = {
          id: "canvas",
          version: "1.0.0",
          preference: pref,
          nodes: toWorkflowNodes(graph.nodes),
          edges: graph.edges,
        };
      } else if (!payload.workflow) {
        payload.skill = skill;
        if (skillNodes.length <= 1) payload.model_id = model.id;
      }
      trackedRef.current = tracked;
      if (tracked.length) setNodeRuns((prev) => ({ ...prev, ...Object.fromEntries(tracked.map((id) => [id, { state: "running" as const }])) }));
      const body = await api<Run>("/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      setRunIds((ids) => [...ids, body.id]);
      if (tracked.length) {
        const results = await nodeRunStates(body, tracked);
        if (epoch === graphEpochRef.current) setNodeRuns((prev) => ({ ...prev, ...results }));
        // Recorded: a later failure (media refresh) is logged but must not mark these nodes as errors.
        trackedRef.current = [];
      }
      await loadMedia();
      const digest = body.outputs?.[0];
      setLog(
        body.state === "completed"
          ? "Shot landed on the canvas." + (digest ? " vinci://assets/" + digest : "")
          : JSON.stringify(body.error || body),
      );
    } catch (err) {
      const message = String(err instanceof Error ? err.message : err);
      setLog(message);
      const failed = trackedRef.current;
      if (failed.length && epoch === graphEpochRef.current) setNodeRuns((prev) => ({ ...prev, ...Object.fromEntries(failed.map((id) => [id, { state: "error" as const, error: message }])) }));
    } finally {
      trackedRef.current = [];
      setBusy(false);
    }
  }

  /** Per-node states after a run: output present (cached when the job hit the runtime cache) or error. */
  async function nodeRunStates(body: Run, ids: string[]) {
    const next: typeof nodeRuns = {};
    const error = body.state === "completed" ? "" : JSON.stringify(body.error || body.state || "failed");
    await Promise.all(
      ids.map(async (id) => {
        const row = body.nodes?.[id];
        if (!row?.output && !row?.outputs?.length) {
          next[id] = { state: "error", error: error || "No output." };
          return;
        }
        const job = row.job_id ? await api<{ estimate?: { cached?: boolean } }>(`/jobs/${row.job_id}`).catch(() => null) : null;
        next[id] = { state: job?.estimate?.cached ? "cached" : "done" };
      }),
    );
    return next;
  }

  /**
   * Price of the model a node runs on, for the pre-run estimate. A run pins its targets (and ancestors
   * that set `model_id`); other ancestors are resolved by the runtime, so they count as unpriced.
   */
  function nodePrice(n: GraphNode, targets: Set<string>): number | null {
    if (!targets.has(n.id) && !n.model_id) return null;
    const id = modelIdForNode(n, selected?.id || "", models);
    return models.find((m) => m.id === id)?.pricing?.amount ?? null;
  }

  /** Short pre-run cost of `ids` and what feeds them; `pinned` are the nodes the run pins to a model. */
  function runCost(ids: string[], pinned = new Set(ids)): { nodes: number; text: string } {
    const e = estimateRun(graph, ids, (n) => nodePrice(n, pinned));
    const parts = [e.nodes > e.unpriced ? `up to ${money(e.total)}` : "", e.unpriced ? `${e.unpriced} not estimated` : ""];
    return { nodes: e.nodes, text: parts.filter(Boolean).join(" + ") };
  }

  function runLabel(ids: string[], pinned?: Set<string>): string {
    const { nodes, text } = runCost(ids, pinned);
    return `Run ${nodes} node${nodes === 1 ? "" : "s"} · ${text}. Unchanged nodes reuse the cache at $0.`;
  }

  /** Run `ids` and what feeds them, unless something required is missing. */
  function runNodes(ids: string[]) {
    if (!ids.length) {
      setLog("Select nodes to run.");
      return;
    }
    const blocker = runBlocker(ids);
    if (blocker) {
      setLog(blocker);
      return;
    }
    void generate({ nodeIds: ids });
  }

  function openTemplate(t: Template) {
    const skill = skills.find((s) => s.id === t.skill);
    const defaults = t.defaults || {};
    const nextPrompt = prompt.trim() || String(defaults.prompt || "") || "north-light oak cube tumbling";
    const nextCamera = String(defaults.camera || camera);
    const nextLens = String(defaults.lens || lens);
    const nextLook = String(defaults.look || look);
    const nextLighting = String(defaults.lighting || lighting);
    const nextPalette = String(defaults.palette || palette);
    const nextMotion = String(defaults.motion || motion);
    const nextAperture = String(defaults.aperture || aperture);
    const nextGenre = String(defaults.genre || genre);
    const nextPage = t.page || "canvas";
    setPrompt(nextPrompt);
    setCamera(nextCamera);
    setLens(nextLens);
    setLook(nextLook);
    setLighting(nextLighting);
    setPalette(nextPalette);
    setMotion(nextMotion);
    setAperture(nextAperture);
    setGenre(nextGenre);
    if (defaults.scene) setScene(String(defaults.scene));
    if (defaults.aspect_ratio) setAspectRatio(String(defaults.aspect_ratio));
    if (defaults.duration != null) setDuration(String(defaults.duration));
    if (defaults.resolution) setResolution(String(defaults.resolution));
    setSkillRef(skill?.id || null);
    resetGraph(
      skill
        ? graphFromSkill(skill, nextCamera, nextLens, nextLook, nextMotion, nextAperture, nextGenre, nextLighting, nextPalette)
        : { nodes: [], edges: [] },
    );
    setSelectedNode(null);
    if (nextPage === "canvas") setView("canvas");
    setPage(nextPage);
  }

  /** A fresh node: its own prompt seeded from the page, the cinema stack, and capability defaults. */
  function buildNode(capability: string, x: number, y: number): GraphNode {
    const video = capability === "t2v" || capability === "i2v";
    return {
      id: capability + "-" + Math.random().toString(16).slice(2, 6),
      type: "generate",
      capability,
      params: {
        camera,
        lens,
        look,
        lighting,
        palette,
        aperture,
        genre,
        ...(video ? { motion } : {}),
        ...startParams(capability, { prompt, aspect_ratio: aspectRatio, duration }),
      },
      x,
      y,
    };
  }

  /** The page prompt a run sends: animating a still may leave it empty; other runs get a default. */
  function runPrompt(model?: Model): string {
    const text = prompt.trim();
    if (page === "upscale") return text || "upscale";
    return animateStill(model) && mode.showStill ? text : text || "north-light oak cube, 50mm cinema still.";
  }

  /** Page inputs a run sends: the shot stack, plus the still as media and image when animating one. */
  function runInputs(model?: Model): Record<string, unknown> {
    const inputs = shotInputs({ prompt: runPrompt(model) });
    if (!(animateStill(model) && mode.showStill)) return inputs;
    const previous = model?.capabilities?.includes("t2v")
      ? null
      : [...projectRuns]
          .reverse()
          .flatMap((run) => [...(run.outputs || [])].reverse())
          .map((id) => imageAssetId(id))
          .find((id) => id) || null;
    const still = imageAssetId(uploadId) || imageAssetId(firstFrameId) || previous;
    return still ? { ...inputs, media: still, image: still } : inputs;
  }

  /** Page inputs a canvas run would send, as has-a-value flags (for `blockedReason`). */
  function pageInputFlags(): Record<string, boolean> {
    const sent = runInputs(selected);
    return Object.fromEntries(Object.entries(sent).map(([k, v]) => [k, v != null && v !== ""]));
  }

  /** First reason the given nodes (and what feeds them) cannot run, or null. */
  function runBlocker(ids: Iterable<string>): string | null {
    const page = pageInputFlags();
    for (const id of withAncestors(graph, ids)) {
      const node = graph.nodes.find((n) => n.id === id);
      const reason = node && node.type === "generate" ? blockedReason(node, page) : null;
      if (reason) return `${id}: ${reason}`;
    }
    return null;
  }

  /** Insert a node: beside `from` (and wired to it when the types fit), else at the board centre. */
  function insertNode(capability: string, from?: string) {
    const src = from ? graph.nodes.find((n) => n.id === from) : undefined;
    const { w, h } = boardSize();
    const want = src
      ? { x: (src.x || 0) + NODE_W + 80, y: src.y || 0 }
      : w
        ? { x: (w / 2 - viewport.x) / viewport.zoom - NODE_W / 2, y: (h / 2 - viewport.y) / viewport.zoom - 80 }
        : { x: 60 + (graph.nodes.length % 3) * 210, y: 80 }; // board not mounted (inspector on another page)
    const at = freeSpot(graph, want.x, want.y);
    const n = buildNode(capability, at.x, at.y);
    const next = addGraphNode(graph, n, src?.id);
    setGraph(next);
    setSelectedNode(n.id);
    setSelectedEdge(null);
    const wired = next.edges.length > graph.edges.length;
    setLog(wired ? `Added ${n.id}, wired from ${src?.id}.` : `Added ${n.id}.`);
    return n.id;
  }

  function addNode(capability: string) {
    insertNode(capability);
    setSkillRef(null);
    setView("canvas");
    setPage("canvas");
  }

  /** Open the add menu at the board centre, or beside `from`'s output port filtered to what fits. */
  function openAddMenu(from?: string) {
    const { w, h } = boardSize();
    const src = from ? graph.nodes.find((n) => n.id === from) : undefined;
    let x = w / 2 - 150;
    let y = h / 2 - 150;
    if (src) {
      const right = ((src.x || 0) + NODE_W) * viewport.zoom + viewport.x;
      x = right + 96;
      y = ((src.y || 0) + portY(0)) * viewport.zoom + viewport.y - 22;
      if (x + 300 > w - 8) {
        // No room on the right: open under the node so the ghost wire stays visible.
        x = right - 280;
        y = ((src.y || 0) + NODE_H) * viewport.zoom + viewport.y + 32;
      }
    }
    setAddMenu({
      x: Math.max(8, Math.min(x, w - 312)),
      y: Math.max(56, Math.min(y, h - 300)),
      from: src?.id,
      kind: src ? portsFor(src).output : null,
    });
    setAddQuery("");
    setAddIndex(0);
  }

  function closeAddMenu() {
    setAddMenu(null);
    linkFromRef.current = null;
    setLinkFrom(null);
  }

  function addShot() {
    const shots = graph.nodes.filter((n) => n.capability === "t2i");
    if (shots.length >= 6) {
      setLog("Cinema sequences stay at 6 shots.");
      return;
    }
    addNode("t2i");
  }

  async function playTimeline() {
    setView("timeline");
    const incoming: Record<string, number> = {};
    for (const n of graph.nodes) incoming[n.id] = 0;
    for (const e of graph.edges) if (incoming[e.dst] != null) incoming[e.dst] += 1;
    const queue = graph.nodes.filter((n) => !incoming[n.id]).map((n) => n.id);
    const ordered: GraphNode[] = [];
    while (queue.length) {
      const id = queue.shift() as string;
      const node = graph.nodes.find((n) => n.id === id);
      if (node) ordered.push(node);
      for (const e of graph.edges) {
        if (e.src === id && incoming[e.dst] != null) {
          incoming[e.dst] -= 1;
          if (incoming[e.dst] === 0) queue.push(e.dst);
        }
      }
    }
    if (!ordered.length) {
      setLog("Canvas is empty.");
      return;
    }
    for (const n of ordered) {
      const digest = nodeDigest(n.id);
      setTlStatus(n.id);
      if (!digest) {
        setTlMedia(null);
        await new Promise((r) => setTimeout(r, 700));
        continue;
      }
      const asset = assets.find((a) => a.id === digest);
      const video = Boolean(
        asset?.mime?.startsWith("video/") || n.capability === "t2v" || n.capability === "i2v",
      );
      setTlMedia({ src: `${API}/assets/${digest}/file`, video });
      await new Promise((r) => setTimeout(r, video ? 5200 : 1400));
    }
    setTlStatus("Done");
  }

  async function saveProvider(id: string) {
    const payload: Record<string, string> = { id };
    if (keyDraft[`key-${id}`]) payload.secret = keyDraft[`key-${id}`];
    else if (keyDraft[`env-${id}`]) payload.from_env = keyDraft[`env-${id}`];
    if (keyDraft[`extra-${id}`]) payload.extra_secret = keyDraft[`extra-${id}`];
    if (keyDraft[`url-${id}`]) payload.url = keyDraft[`url-${id}`];
    if (keyDraft[`acct-${id}`]) payload.account_id = keyDraft[`acct-${id}`];
    if (keyDraft[`label-${id}`]) payload.label = keyDraft[`label-${id}`];
    if (keyDraft[`authurl-${id}`]) payload.authorize_url = keyDraft[`authurl-${id}`];
    try {
      const body = await api<{ available?: boolean; test?: string }>("/providers", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      await boot();
      setLog(
        body.available
          ? id + " enabled." + (doctor.live_spend ? "" : " Live spend is off.")
          : id + " saved. " + (body.test || "missing key"),
      );
      setPage("keys");
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  async function addNamedMcp() {
    const label = (keyDraft["label-mcp_new"] || "").trim();
    const raw = (keyDraft["slug-mcp_new"] || label || "custom").toLowerCase();
    const slug = raw.replace(/^mcp_/, "").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "custom";
    const id = `mcp_${slug}`;
    const payload: Record<string, string> = { id };
    if (label) payload.label = label;
    if (keyDraft["url-mcp_new"]) payload.url = keyDraft["url-mcp_new"];
    if (keyDraft["authurl-mcp_new"]) payload.authorize_url = keyDraft["authurl-mcp_new"];
    if (keyDraft["key-mcp_new"]) payload.secret = keyDraft["key-mcp_new"];
    try {
      const body = await api<{ available?: boolean; test?: string }>("/providers", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      await boot();
      setConnectId(id);
      setLog(body.available ? id + " enabled." : id + " saved. " + (body.test || "needs URL"));
      setPage("keys");
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  async function oauthStart(id: string) {
    try {
      const body = await api<{ hint?: string; authorize_url?: string; mode?: string }>(
        `/providers/${encodeURIComponent(id)}/oauth`,
        { method: "POST" },
      );
      if (body.mode === "key") {
        setLog(body.hint || "This connector uses a pasted API key.");
        return;
      }
      if (body.authorize_url) window.open(body.authorize_url, "_blank", "noopener,noreferrer");
      if (body.mode !== "oauth") {
        setLog(body.hint || "Paste a token.");
        return;
      }
      setLog("Finish sign-in in the browser.");
      const attempt = ++oauthAttemptRef.current;
      for (let i = 0; i < 60; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (attempt !== oauthAttemptRef.current) return;
        let next: Doctor;
        try {
          next = await api<Doctor>("/doctor");
        } catch {
          continue;
        }
        if (attempt !== oauthAttemptRef.current) return;
        const row = next.providers?.[id];
        if (row?.auth_state === "needs_reconnect") {
          setLog(id + " needs reconnect.");
          return;
        }
        if (row?.auth_state === "connected") {
          await boot();
          setLog(id + " connected.");
          return;
        }
      }
      if (attempt === oauthAttemptRef.current) setLog("Still waiting for sign-in.");
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  async function planBrief() {
    try {
      const body = await api<{ steps?: PlanStep[] }>("/agent/plan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ brief }),
      });
      setPlan(body.steps || []);
      setLog((body.steps || []).length ? "Plan ready." : "No matching templates.");
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  async function runPlan() {
    if (!plan.length || busy) return;
    setBusy(true);
    try {
      for (const step of plan) {
        const body = await api<Run>("/runs", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            skill: step.skill,
            inputs: shotInputs({ prompt: brief.trim() || step.blurb || step.title }),
            preference: pref,
            max_cost: 0,
          }),
        });
        setRunIds((ids) => [...ids, body.id]);
      }
      await loadMedia();
      setLog("Plan complete.");
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  }

  async function generate3d() {
    if (busy) return;
    setBusy(true);
    const text = (prompt.trim() || brief.trim() || "north-light oak cube") + ", 3D turntable plate";
    try {
      const body = await api<Run>("/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          skill: "@tryvinci/image-generate",
          inputs: shotInputs({ prompt: text }),
          preference: pref,
          max_cost: 0,
        }),
      });
      setRunIds((ids) => [...ids, body.id]);
      await loadMedia();
      setLog(body.state === "completed" ? "3D plate landed." : JSON.stringify(body.error || body));
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  }

  async function loadSessions() {
    try {
      const body = await api<{ sessions: { id: string; name: string }[] }>("/collab/sessions");
      setSessions(body.sessions || []);
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  async function createCollab() {
    try {
      const body = await api<{ id: string; name: string }>("/collab/sessions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: collabName || "Session" }),
      });
      setCollabId(body.id);
      await pushCollab(body.id);
      await loadSessions();
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  async function joinCollab(sid: string) {
    try {
      const body = await api<{
        id: string;
        name?: string;
        snapshot?: { prompt?: string; graph?: { nodes: GraphNode[]; edges: GraphEdge[] }; cast?: CastRow[]; page?: PageId };
      }>(`/collab/sessions/${encodeURIComponent(sid)}`);
      setCollabId(body.id);
      if (body.name) setCollabName(body.name);
      const snap = body.snapshot || {};
      if (snap.prompt) setPrompt(snap.prompt);
      if (snap.graph) resetGraph(snap.graph);
      if (snap.cast) setCast(snap.cast);
      if (snap.page) setPage(snap.page);
      setLog("Opened collab " + body.id);
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  async function pushCollab(sid: string) {
    try {
      await api(`/collab/sessions/${encodeURIComponent(sid)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: collabName || "Session",
          snapshot: { prompt, graph, cast, page },
        }),
      });
      setCollabId(sid);
      setLog("Pushed graph to " + sid);
      await loadSessions();
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    }
  }

  const titles: Record<PageId, string> = {
    explore: "Explore",
    image: "Image",
    adapts: "Image › Adapts",
    video: "Video",
    speak: "Speak",
    upscale: "Upscale still",
    canvas: "Canvas",
    library: "Library",
    agent: "Supercomputer",
    space: "3D",
    collab: "Collab",
    keys: "Connect",
    skills: "Skills",
    find: "Find",
    cost: "Cost report",
  };

  const live = Object.entries(doctor.providers || {}).filter(([id, row]) => id !== "mock" && row && row.available);
  const spent = projectRuns.reduce((sum, r) => sum + Number(r.estimate?.total || 0), 0);
  const railGroups: {
    label?: string;
    items: { id: PageId; title: string; d: string; flyout?: "image" | "video" }[];
  }[] = [
    {
      items: [{ id: "explore", title: "Explore", d: "M9 2a7 7 0 1 1 0 14A7 7 0 0 1 9 2zm0 2v5l3 2" }],
    },
    {
      label: "Formats",
      items: [
        { id: "image", title: "Image", d: "M3 4h12v10H3zM3 12l3-3 2 2 2-2 4 4", flyout: "image" },
        { id: "video", title: "Video", d: "M2.5 5h9v8h-9zM11.5 8l4-2v6l-4-2z", flyout: "video" },
      ],
    },
    {
      label: "Workflows",
      items: [
        { id: "canvas", title: "Canvas", d: "M3 4h5v4H3zM10 10h5v4h-5zM8 6h3v4" },
        { id: "library", title: "Library", d: "M3 4h4v11H3zM8 4h3v11H8zM12.5 4.5L15 15" },
      ],
    },
  ];
  const imageOn = page === "image" || page === "upscale" || page === "adapts";
  const videoOn = page === "video" || page === "speak";
  const liveSpend = !!doctor.live_spend;
  const flyoutModels = (kind: "image" | "video") => {
    const rows = models.filter((row) => {
      if (row.provider === "mock") return false;
      const caps = row.capabilities || [];
      if (kind === "image") return caps.includes("t2i") || caps.includes("upscale");
      return caps.includes("t2v") || caps.includes("i2v") || caps.includes("lipsync") || caps.includes("tts");
    });
    rows.sort(
      (a, b) =>
        availabilityRank(modelAvailability(a, doctor.providers?.[a.provider], liveSpend)) -
        availabilityRank(modelAvailability(b, doctor.providers?.[b.provider], liveSpend)),
    );
    return rows.slice(0, 8);
  };
  function openFlyoutPage(next: PageId) {
    setPage(next);
    setModelsOpen(false);
    setNavOpen(false);
  }
  function pickFlyoutModel(row: Model, kind: "image" | "video") {
    const caps = row.capabilities || [];
    setModelId(row.id);
    if (kind === "image") {
      openFlyoutPage(caps.includes("t2i") ? "image" : "upscale");
      return;
    }
    const talk = (caps.includes("lipsync") || caps.includes("tts")) && !caps.includes("t2v") && !caps.includes("i2v");
    openFlyoutPage(talk ? "speak" : "video");
  }

  let main: ReactNode = null;
  if (page === "explore") {
    const items = templates.filter((t) => category === "all" || t.category === category);
    main = (
      <div className="explore">
        <h2>Templates</h2>
        <p className="muted">First-party skill graphs. Speak scenes open Speak; the rest land on the canvas.</p>
        <div className="cats">
          {CATS.map((c) => (
            <button key={c} type="button" className={category === c ? "on" : ""} onClick={() => setCategory(c)}>
              {c}
            </button>
          ))}
        </div>
        <div className="grid">
          {items.map((t) => (
            <button key={t.id} className="card" type="button" onClick={() => openTemplate(t)}>
              <img alt="" src={`${API}/templates/${t.id}/preview.svg`} />
              <div>
                <strong>{t.title}</strong>
                <div className="muted">{t.blurb}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    );
  } else if (page === "image" || page === "video" || page === "upscale" || page === "speak") {
    const offers: Record<string, { eyebrow: string; title: ReactNode; copy: string; primary: string; hint: string }> = {
      image: {
        eyebrow: "Create",
        title: "Image",
        copy: "Stills from a prompt. Write what you want, then generate.",
        primary: "Write a prompt",
        hint: "Price sits on Generate.",
      },
      video: {
        eyebrow: "Create",
        title: "Video",
        copy: "Motion from a prompt. Describe the shot, then generate.",
        primary: "Write a prompt",
        hint: "Price sits on Generate.",
      },
      upscale: {
        eyebrow: "Enhance",
        title: (
          <>
            Upscale <em className="serif">still</em>
          </>
        ),
        copy: "Increase resolution on a still you upload or generate.",
        primary: "Upload a still",
        hint: "PNG, JPEG, or WebP.",
      },
      speak: {
        eyebrow: "Create",
        title: "Speak",
        copy: "Speech from a line of text. Add a still only when the model animates a photo.",
        primary: "Write a line",
        hint: "Price sits on Generate.",
      },
    };
    const offer = offers[page];
    let media: React.ReactNode = <p className="hero-empty">Generating…</p>;
    if (page === "upscale" && uploadId && lastDigest && !stageReset && uploadId !== lastDigest) {
      media = (
        <div className="split" id="compose-split">
          <div>
            <span className="muted">Before</span>
            <img src={`${API}/assets/${uploadId}/file`} alt="" />
          </div>
          <div>
            <span className="muted">After</span>
            <img src={`${API}/assets/${lastDigest}/file`} alt="" />
          </div>
        </div>
      );
    } else if (!stageReset && lastDigest && lastAsset?.mime?.startsWith("video/")) {
      media = <video src={`${API}/assets/${lastDigest}/file`} controls />;
    } else if (!stageReset && lastDigest && lastAsset?.mime?.startsWith("image/")) {
      media = <img alt="" src={`${API}/assets/${lastDigest}/file`} />;
    } else if ((page === "upscale" || page === "speak") && uploadId) {
      media = <img alt="" src={`${API}/assets/${uploadId}/file`} />;
    }
    const showOffer = !hasComposeMedia && !busy;
    async function onComposeFile(ev: ChangeEvent<HTMLInputElement>) {
      const file = ev.target.files?.[0];
      ev.target.value = "";
      if (!file) return;
      try {
        const asset = await ingest(file);
        setUploadId(asset.id);
        setStageReset(false);
        setLog("Input loaded. vinci://assets/" + asset.id);
      } catch (err) {
        setLog(String(err instanceof Error ? err.message : err));
      }
    }
    main = (
      <div className={"compose" + (showOffer ? "" : " has-media")}>
        <input
          id="compose-still"
          ref={composeStillRef}
          className="hidden"
          type="file"
          accept="image/*,video/*,audio/*"
          onChange={onComposeFile}
        />
        <div className="compose-body">
          {showOffer ? (
            <div className="compose-offer">
              <div className="compose-sample" data-kind={page} aria-hidden="true">
                {page === "upscale" ? (
                  <div className="compose-sample-split">
                    <div className="compose-sample-before" />
                    <div className="compose-sample-after" />
                    <span className="compose-sample-handle" />
                  </div>
                ) : null}
              </div>
              <p className="eyebrow">{offer.eyebrow}</p>
              <h2>{offer.title}</h2>
              <p className="compose-offer-copy">{offer.copy}</p>
              <div className="compose-offer-actions">
                <button
                  className="run"
                  type="button"
                  onClick={() => {
                    if (page === "upscale") composeStillRef.current?.click();
                    else document.getElementById("prompt")?.focus();
                  }}
                >
                  {offer.primary}
                </button>
                {page === "upscale" && lastStill ? (
                  <button
                    className="ghost"
                    type="button"
                    onClick={() => {
                      setUploadId(lastStill);
                      setStageReset(false);
                    }}
                  >
                    Use last still
                  </button>
                ) : (
                  <button className="ghost" type="button" onClick={() => setModelsOpen(true)}>
                    Choose a model
                  </button>
                )}
              </div>
              <p className="compose-offer-hint">{offer.hint}</p>
            </div>
          ) : (
            <div className="compose-stage">{media}</div>
          )}
        </div>
        <details
          className="compose-models"
          open={modelsOpen}
          onToggle={(ev) => setModelsOpen((ev.target as HTMLDetailsElement).open)}
        >
          <summary>Choose a model</summary>
          <input
            id="gallery-query"
            className="gallery-query"
            type="text"
            placeholder="Search models"
            aria-label="Search models"
            autoComplete="off"
            value={galleryQuery}
            onChange={(ev) => setGalleryQuery(ev.target.value)}
          />
          {galleryQuery.trim() && galleryModels.length === 0 ? (
            <p className="muted gallery-empty">No models match</p>
          ) : null}
          <div className="compose-gallery">
            {galleryModels.map((m) => (
              <button
                key={m.id}
                className={"model-card" + (m.id === selected?.id ? " on" : "")}
                type="button"
                onClick={() => setModelId(m.id)}
              >
                <span className="who">{m.provider === "magnific" ? "Magnific / Freepik" : m.provider === "mock" ? "Local" : m.provider}</span>
                <strong>{m.display_name}</strong>
                <span className="meta">
                  {money(m.pricing?.amount)}
                  {statusSuffix(m)} · {(m.capabilities || []).slice(0, 3).join(" · ")}
                </span>
              </button>
            ))}
          </div>
        </details>
      </div>
    );
  } else if (page === "adapts") {
    const panelProps = {
      apiBase: API,
      liveSpend: Boolean(doctor?.live_spend),
      busy,
      adaptSourceId,
      lastStill,
      adaptPartnerOnly,
      adaptLayout,
      adaptFit,
      adaptTargets,
      adaptPresetChoices,
      adaptNote,
      adaptEstimateUsd,
      batch: adaptBatch,
      showSafe,
      presetFormOpen,
      presetDraft,
      money,
      onPartnerOnlyChange: setAdaptPartnerOnly,
      onLayoutChange: setAdaptLayout,
      onFitChange: setAdaptFit,
      onTargetsChange: setAdaptTargets,
      onUseLastStill: () => lastStill && setAdaptSourceId(lastStill),
      onEstimate: () => void estimateAdapt(),
      onRun: () => void runAdapt(),
      onOpenFlow: () => setAdaptView("flow"),
      onToggleSafe: () => setShowSafe((on) => !on),
      onTogglePresetForm: () => setPresetFormOpen((open) => !open),
      onDraftChange: setPresetDraft,
      onCreatePreset: () => void createPreset(),
      onDeletePreset: (id: string) => void deletePreset(id),
      fileInputRef: adaptFileRef,
    };
    main = (
      <>
        <input
          ref={adaptFileRef}
          className="hidden"
          type="file"
          accept="image/*"
          onChange={(ev) => {
            const file = ev.target.files?.[0];
            if (file) void uploadAdaptSource(file);
          }}
        />
        {adaptView === "flow" ? (
          <AdaptFlowCanvas
            apiBase={API}
            liveSpend={Boolean(doctor?.live_spend)}
            busy={busy}
            sourceId={adaptSourceId}
            targets={adaptTargets}
            presets={adaptPresetChoices}
            layout={adaptLayout}
            fit={adaptFit}
            batch={adaptBatch}
            showSafe={showSafe}
            onToggleSafe={() => setShowSafe((on) => !on)}
            onBack={() => setAdaptView("form")}
            onRun={() => void runAdapt()}
            onPickSource={() => adaptFileRef.current?.click()}
          />
        ) : (
          <AdaptsPanel {...panelProps} />
        )}
      </>
    );
  } else if (page === "canvas") {
    const selectedRow = graph.nodes.find((n) => n.id === selectedNode);
    const pageHas = pageInputFlags();
    const graphIds = graph.nodes.map((n) => n.id);
    const graphBlocker = graph.nodes.length ? runBlocker(graphIds) : null;
    // Generate graph pins nothing: only nodes with their own model_id are priced.
    const graphCost = graph.nodes.length ? runCost(graphIds, new Set()).text : "";
    const nodeBlocker = selectedRow ? runBlocker([selectedRow.id]) : null;
    main = (
      <div className="stage">
        <main
          className="board"
          style={
            view === "canvas"
              ? {
                  backgroundPosition: `${viewport.x}px ${viewport.y}px`,
                  backgroundSize: `${20 * viewport.zoom}px ${20 * viewport.zoom}px`,
                }
              : undefined
          }
        >
          {graph.nodes.length === 0 && view === "canvas" ? (
            <div className="empty">
              <div>
                <h2>Empty canvas.</h2>
                <p>Open a template, or add image / video / upscale nodes.</p>
                <button className="ghost" type="button" onClick={() => setPage("adapts")}>
                  Image › Adapts presets
                </button>
              </div>
            </div>
          ) : null}
          {view === "canvas" ? (
            <div
              ref={boardRef}
              className={"graph" + (canvasTool === "pan" ? " pan" : "") + (panning ? " panning" : "")}
              onPointerDown={(ev) => {
                if (canvasTool === "pan" || spaceRef.current || ev.button === 1) {
                  ev.preventDefault();
                  panRef.current = { x: ev.clientX, y: ev.clientY, vx: viewport.x, vy: viewport.y };
                  setPanning(true);
                  return;
                }
                setCtxMenu(null);
                if (ev.target !== ev.currentTarget || ev.button !== 0) return;
                const r = ev.currentTarget.getBoundingClientRect();
                marqueeRef.current = { x: ev.clientX - r.left, y: ev.clientY - r.top, add: ev.shiftKey };
                if (!ev.shiftKey) setSelection([]);
                setSelectedEdge(null);
                if (addMenu) closeAddMenu();
              }}
              onContextMenu={(ev) => {
                if (ev.target === ev.currentTarget) openCtxMenu(ev);
              }}
            >
              <div
                className="graph-layer"
                style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})` }}
              >
                {(graph.groups || []).map((grp) => {
                  const b = groupBounds(graph, grp);
                  if (!b) return null;
                  const active = groupOf(graph, selection)?.id === grp.id;
                  return (
                    <div
                      key={grp.id}
                      className={"group-frame c-" + grp.color + (active ? " on" : "")}
                      data-group={grp.id}
                      style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
                      onPointerDown={(ev) => {
                        if (canvasTool === "pan" || spaceRef.current || ev.button !== 0) return;
                        ev.stopPropagation();
                        setCtxMenu(null);
                        setSelection(grp.nodeIds);
                        setSelectedEdge(null);
                        startDrag(ev, grp.nodeIds, grp.nodeIds);
                      }}
                      onContextMenu={(ev) => {
                        setSelection(grp.nodeIds);
                        setSelectedEdge(null);
                        openCtxMenu(ev);
                      }}
                    >
                      <div className="group-head">
                        {renamingGroup === grp.id ? (
                          <input
                            autoFocus
                            aria-label="Group name"
                            defaultValue={grp.name}
                            onPointerDown={(ev) => ev.stopPropagation()}
                            onKeyDown={(ev) => {
                              if (ev.key === "Enter") (ev.target as HTMLInputElement).blur();
                              if (ev.key === "Escape") setRenamingGroup(null);
                            }}
                            onBlur={(ev) => {
                              const name = ev.target.value.trim();
                              if (renamingGroup === grp.id && name && name !== grp.name) {
                                setGraph((g) => updateGroup(g, grp.id, { name }));
                              }
                              setRenamingGroup(null);
                            }}
                          />
                        ) : (
                          <button
                            type="button"
                            className="group-name"
                            title="Double-click or press Enter to rename"
                            onFocus={() => {
                              // Tabbing to a frame selects it, which also shows its colour and Ungroup tools.
                              setSelection(grp.nodeIds);
                              setSelectedEdge(null);
                            }}
                            onDoubleClick={() => setRenamingGroup(grp.id)}
                            onKeyDown={(ev) => {
                              if (ev.key !== "Enter" && ev.key !== " ") return;
                              ev.preventDefault();
                              setRenamingGroup(grp.id);
                            }}
                          >
                            {grp.name}
                          </button>
                        )}
                        {active ? (
                          <span className="group-tools" onPointerDown={(ev) => ev.stopPropagation()}>
                            {GROUP_COLORS.map((c) => (
                              <button
                                key={c}
                                type="button"
                                className={"swatch c-" + c + (grp.color === c ? " on" : "")}
                                aria-label={`Colour ${c}`}
                                onClick={() => setGraph((g) => updateGroup(g, grp.id, { color: c }))}
                              />
                            ))}
                            <span className="group-cost">{runCost(grp.nodeIds).text}</span>
                            <button type="button" className="ghost" title={runLabel(grp.nodeIds)} onClick={() => runNodes(grp.nodeIds)}>
                              Run
                            </button>
                            <button type="button" className="ghost" title={withKeys("ungroup")} onClick={ungroupSelection}>
                              Ungroup
                            </button>
                          </span>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
                <svg className="wires" aria-hidden="true">
                  {graph.edges.map((e) => {
                    const a = graph.nodes.find((n) => n.id === e.src);
                    const b = graph.nodes.find((n) => n.id === e.dst);
                    if (!a || !b) return null;
                    const d = wirePath(a, b, e.input_key);
                    const on = selectedEdge?.src === e.src && selectedEdge?.dst === e.dst;
                    return (
                      <g key={e.src + "->" + e.dst}>
                        <path className={"wire" + (on ? " on" : "")} d={d} />
                        <path
                          className="wire-hit"
                          d={d}
                          data-edge={e.src + "->" + e.dst}
                          onPointerDown={(ev) => {
                            if (canvasTool === "pan" || spaceRef.current || ev.button === 1) return;
                            ev.stopPropagation();
                            setSelectedEdge(e);
                            setSelectedNode(null);
                          }}
                        />
                      </g>
                    );
                  })}
                  {addMenu?.from
                    ? (() => {
                        const src = graph.nodes.find((n) => n.id === addMenu.from);
                        if (!src) return null;
                        const x1 = (src.x || 0) + NODE_W;
                        const y1 = (src.y || 0) + portY(0);
                        const g = (sx: number, sy: number) => [(sx - viewport.x) / viewport.zoom, (sy - viewport.y) / viewport.zoom];
                        const [tx, ty] = g(addMenu.x, addMenu.y + 22);
                        if (tx > x1) return <path className="wire ghost" d={curve(x1, y1, tx, ty)} />;
                        // Menu opened under the node: leave the port rightwards, drop into the menu's top edge.
                        const [bx, by] = g(addMenu.x + 290, addMenu.y);
                        return <path className="wire ghost" d={`M${x1} ${y1} C${x1 + 60} ${y1}, ${bx} ${by - 60}, ${bx} ${by}`} />;
                      })()
                    : null}
                </svg>
                {graph.nodes.map((n) => {
                  const digest = nodeDigest(n.id);
                  const cap = n.capability || n.type;
                  const asset = assets.find((a) => a.id === digest);
                  const label = NODE_CATALOG.find((row) => row.capability === n.capability)?.label || cap;
                  const aspect = typeof n.params?.aspect_ratio === "string" && !n.params.aspect_ratio.startsWith("{{") ? n.params.aspect_ratio : "";
                  const ask = n.params?.prompt;
                  const promptLine =
                    typeof ask !== "string" ? "" : ask.startsWith("{{") ? "Page prompt" : ask.trim();
                  const needs = n.type === "generate" ? blockedReason(n, pageHas) : null;
                  return (
                    <div
                      key={n.id}
                      data-id={n.id}
                      className={"node" + (selection.includes(n.id) ? " on" : "") + (nodeRuns[n.id] ? " run-" + nodeRuns[n.id].state : "")}
                      style={{ left: n.x ?? 0, top: n.y ?? 0 }}
                      onPointerDown={(ev) => {
                        if ((ev.target as HTMLElement).classList.contains("port")) return;
                        if (canvasTool === "pan" || spaceRef.current || ev.button !== 0) return;
                        ev.stopPropagation();
                        setCtxMenu(null);
                        if (ev.shiftKey) {
                          setSelection((sel) => (sel.includes(n.id) ? sel.filter((id) => id !== n.id) : [...sel, n.id]));
                          setSelectedEdge(null);
                          return;
                        }
                        const ids = selection.includes(n.id) && selection.length > 1 ? selection : [n.id];
                        startDrag(ev, ids, [n.id]);
                      }}
                      onContextMenu={(ev) => {
                        ev.stopPropagation();
                        if (!selection.includes(n.id)) setSelectedNode(n.id);
                        setSelectedEdge(null);
                        openCtxMenu(ev);
                      }}
                    >
                      {portsFor(n).inputs.map((port, i) => (
                        <div
                          key={port.key}
                          className={"port in kind-" + port.kind}
                          data-port="in"
                          data-id={n.id}
                          data-key={port.key}
                          data-kind={port.kind}
                          style={{ top: portY(i) - 5 }}
                          title={`${port.kind} input (${port.key})`}
                          onPointerDown={(ev) => ev.stopPropagation()}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            const from = linkFromRef.current;
                            if (!from) return;
                            closeAddMenu();
                            const wired = connect(graph, from, n.id, port.key);
                            if (!wired.ok) {
                              setLog(wired.error);
                              return;
                            }
                            setGraph(wired.graph);
                            setLog(`Wired ${from} into ${n.id}.`);
                          }}
                        />
                      ))}
                      {portsFor(n).output ? (
                        <div
                          className={"port out kind-" + portsFor(n).output + (linkFrom === n.id ? " on" : "")}
                          data-port="out"
                          data-id={n.id}
                          data-kind={portsFor(n).output || ""}
                          style={{ top: portY(0) - 5 }}
                          title={`${portsFor(n).output} output: click to add or connect`}
                          onPointerDown={(ev) => ev.stopPropagation()}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            linkFromRef.current = n.id;
                            setLinkFrom(n.id);
                            openAddMenu(n.id);
                            setLog(`Pick a node that takes ${portsFor(n).output}, or click an input port.`);
                          }}
                        />
                      ) : null}
                      <div className="thumb">
                        {digest && asset?.mime?.startsWith("video/") ? (
                          <video src={`${API}/assets/${digest}/file`} muted />
                        ) : digest ? (
                          <img alt="" src={`${API}/assets/${digest}/file`} />
                        ) : null}
                        {nodeRuns[n.id]?.state === "running" ? <span className="spinner" aria-label="Running" /> : null}
                        {nodeRuns[n.id]?.state === "cached" ? <span className="chip-cached">cached</span> : null}
                        {n.type === "generate" ? (
                          <button
                            type="button"
                            className="node-run"
                            aria-label={`Run ${n.id}`}
                            disabled={Boolean(needs) || busy}
                            title={needs || runLabel([n.id])}
                            onPointerDown={(ev) => ev.stopPropagation()}
                            onClick={(ev) => {
                              ev.stopPropagation();
                              runNodes([n.id]);
                            }}
                          >
                            ▶
                          </button>
                        ) : null}
                      </div>
                      <div className="meta">
                        <div className="k">{label}{aspect ? " · " + aspect : ""}</div>
                        <strong>{n.id}</strong>
                        {defaultsFor(n.capability).prompt !== "none" ? (
                          <p className={"prompt-line" + (promptLine ? "" : " is-empty")}>
                            {promptLine || defaultsFor(n.capability).placeholder || "No prompt"}
                          </p>
                        ) : null}
                        {needs ? <p className="needs">{needs}</p> : null}
                        {!needs && nodeRuns[n.id]?.state === "error" ? (
                          <p className="needs" title={nodeRuns[n.id].error}>Run failed. Hover for details.</p>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className={"results" + (view === "canvas" ? "" : " hidden")} id="results">
                {graph.nodes.map((n) => {
                  const digest = nodeDigest(n.id);
                  if (!digest) return null;
                  const asset = assets.find((a) => a.id === digest);
                  return (
                    <button
                      key={n.id}
                      className="shot"
                      type="button"
                      onClick={() => {
                        setSelectedNode(n.id);
                        setSelectedEdge(null);
                      }}
                    >
                      <span className="muted">{n.id}</span>
                      <span className="frame">
                        {asset?.mime?.startsWith("video/") ? (
                          <video src={`${API}/assets/${digest}/file`} muted />
                        ) : (
                          <img alt="" src={`${API}/assets/${digest}/file`} />
                        )}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <>
              <div className="tl-bar">
                <span className="muted" id="tl-status">{tlStatus}</span>
              </div>
              <div className="tl-stage" id="tl-stage">
                {tlMedia?.video ? <video src={tlMedia.src} autoPlay muted /> : tlMedia ? <img alt="" src={tlMedia.src} /> : <p className="muted">No output yet — generate the graph</p>}
              </div>
            </>
          )}
          <div className="canvas-bar">
            {view === "canvas" ? (
              <div className="canvas-view" role="toolbar" aria-label="Canvas view">
                <button type="button" className="ghost" title={withKeys("addNode")} onClick={() => openAddMenu()}>
                  + Add
                </button>
                <div className="views">
                  <button
                    type="button"
                    className={canvasTool === "select" ? "on" : ""}
                    title={withKeys("selectMode")}
                    aria-pressed={canvasTool === "select"}
                    onClick={() => setCanvasTool("select")}
                  >
                    Select
                  </button>
                  <button
                    type="button"
                    className={canvasTool === "pan" ? "on" : ""}
                    title={withKeys("panMode")}
                    aria-pressed={canvasTool === "pan"}
                    onClick={() => setCanvasTool("pan")}
                  >
                    Pan
                  </button>
                </div>
                <div className="views">
                  <button type="button" title={withKeys("zoomOut")} aria-label="Zoom out" onClick={() => zoomBy(1 / 1.2)}>
                    −
                  </button>
                  <button type="button" className="zoom-pct" title={withKeys("resetView")} onClick={() => runShortcut("resetView")}>
                    {Math.round(viewport.zoom * 100)}%
                  </button>
                  <button type="button" title={withKeys("zoomIn")} aria-label="Zoom in" onClick={() => zoomBy(1.2)}>
                    +
                  </button>
                  <button type="button" title={withKeys("fit")} onClick={() => runShortcut("fit")}>
                    Fit
                  </button>
                </div>
                <button
                  type="button"
                  className={"ghost help" + (sheetOpen ? " on" : "")}
                  title={withKeys("help")}
                  aria-expanded={sheetOpen}
                  onClick={() => setSheetOpen((open) => !open)}
                >
                  ?
                </button>
              </div>
            ) : null}
            <div className="canvas-tools">
              <button
                className="ghost"
                type="button"
                title={withKeys("undo")}
                disabled={!graphHistory.past.length}
                onClick={() => stepHistory("undo")}
              >
                Undo
              </button>
              <button
                className="ghost"
                type="button"
                title={withKeys("redo")}
                disabled={!graphHistory.future.length}
                onClick={() => stepHistory("redo")}
              >
                Redo
              </button>
              {selection.length > 1 ? (
                <button className="ghost" type="button" title={withKeys("group")} onClick={groupSelection}>
                  Group
                </button>
              ) : null}
              {selectedEdge || selection.length ? (
                <button className="ghost" type="button" title={withKeys("delete")} onClick={deleteSelection}>
                  {selectedEdge ? "Delete wire" : selection.length > 1 ? `Delete ${selection.length}` : "Delete node"}
                </button>
              ) : null}
              <button className="ghost" type="button" onClick={() => setPage("adapts")}>
                Image › Adapts
              </button>
              <button
                className="ghost"
                type="button"
                disabled={Boolean(graphBlocker)}
                title={graphBlocker || runLabel(graphIds, new Set())}
                onClick={() => void generate({ graph: true })}
              >
                Generate graph{graphCost ? <span className="tool-cost"> · {graphCost}</span> : null}
              </button>
              <button className="ghost" type="button" id="tl-play" onClick={() => void playTimeline()}>
                Play timeline
              </button>
            </div>
          </div>
          {addMenu && view === "canvas"
            ? (() => {
                const rows = searchCatalog(addQuery, addMenu.kind);
                const pick = rows[Math.min(addIndex, rows.length - 1)];
                const choose = (capability: string) => {
                  insertNode(capability, addMenu.from);
                  closeAddMenu();
                };
                return (
                  <div
                    className="add-menu"
                    role="dialog"
                    aria-label="Add node"
                    style={{ left: addMenu.x, top: addMenu.y }}
                    onPointerDown={(ev) => ev.stopPropagation()}
                  >
                    <input
                      autoFocus
                      placeholder={addMenu.kind ? `Nodes that take ${addMenu.kind}` : "Search nodes"}
                      value={addQuery}
                      aria-controls="add-menu-list"
                      onChange={(ev) => {
                        setAddQuery(ev.target.value);
                        setAddIndex(0);
                      }}
                      onKeyDown={(ev) => {
                        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
                          ev.preventDefault();
                          const step = ev.key === "ArrowDown" ? 1 : -1;
                          const at = Math.min(addIndex, rows.length - 1);
                          const next = rows.length ? (at + step + rows.length) % rows.length : 0;
                          setAddIndex(next);
                          // The list scrolls (max-height); keep the keyboard pick visible, not the hovered one.
                          document.getElementById("add-menu-list")?.children[next]?.scrollIntoView({ block: "nearest" });
                        } else if (ev.key === "Enter" && pick && !ev.nativeEvent.isComposing) {
                          ev.preventDefault();
                          choose(pick.capability);
                        } else if (ev.key === "Escape") {
                          ev.preventDefault();
                          closeAddMenu();
                        }
                      }}
                    />
                    <div className="add-list" id="add-menu-list" role="listbox">
                      {rows.map((row) => {
                        const ready = models.filter(
                          (m) =>
                            (m.capabilities || []).includes(row.capability) &&
                            modelAvailability(m, doctor.providers?.[m.provider], !!doctor.live_spend) === "ready",
                        ).length;
                        return (
                          <button
                            key={row.capability}
                            type="button"
                            role="option"
                            aria-selected={row === pick}
                            className={row === pick ? "on" : ""}
                            onMouseMove={(ev) => {
                              // Only real pointer motion: a keyboard scroll can slide rows under a still cursor.
                              if (ev.movementX || ev.movementY) setAddIndex(rows.indexOf(row));
                            }}
                            onClick={() => choose(row.capability)}
                          >
                            <span className={"kind-dot kind-" + (outputOf(row.capability) || "none")} />
                            <span className="what">
                              <strong>{row.label}</strong>
                              <span>{row.blurb}</span>
                            </span>
                            <span className="ready">{ready ? `${ready} ready` : "needs a key"}</span>
                          </button>
                        );
                      })}
                      {!rows.length ? <p className="muted">No node matches.</p> : null}
                    </div>
                    <p className="add-hint">
                      <kbd>↑↓</kbd> move <kbd>⏎</kbd> insert <kbd>Esc</kbd> close
                    </p>
                  </div>
                );
              })()
            : null}
          {marquee ? (
            <div className="marquee" style={{ left: marquee.x, top: marquee.y, width: marquee.w, height: marquee.h }} />
          ) : null}
          {ctxMenu && view === "canvas"
            ? (() => {
                const inGroup = (graph.groups || []).some((grp) => grp.nodeIds.some((id) => selection.includes(id)));
                const item = (id: ShortcutId, label: string, enabled: boolean) => (
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!enabled}
                    onClick={() => {
                      setCtxMenu(null);
                      runShortcut(id);
                    }}
                  >
                    <span>{label}</span>
                    <kbd>{SHORTCUTS.find((row) => row.id === id)?.keys}</kbd>
                  </button>
                );
                return (
                  <div
                    className="ctx-menu"
                    role="menu"
                    style={{ left: ctxMenu.x, top: ctxMenu.y }}
                    onPointerDown={(ev) => ev.stopPropagation()}
                  >
                    {item("addNode", "Add node", true)}
                    {item("group", "Group", selection.length > 1)}
                    {item("ungroup", "Ungroup", inGroup)}
                    {item("duplicate", "Duplicate", selection.length > 0)}
                    {item("selectAll", "Select all", graph.nodes.length > 0)}
                    {item("delete", "Delete", selection.length > 0 || Boolean(selectedEdge))}
                  </div>
                );
              })()
            : null}
          {sheetOpen && view === "canvas" ? (
            <div className="shortcut-sheet" role="dialog" aria-label="Keyboard shortcuts">
              {(["Edit", "View"] as const).map((group) => (
                <section key={group}>
                  <p className="eyebrow">{group}</p>
                  {SHORTCUTS.filter((s) => s.group === group).map((s) => (
                    <div className="row" key={s.id}>
                      <span>{s.label}</span>
                      <kbd>{s.keys}</kbd>
                    </div>
                  ))}
                </section>
              ))}
              <p className="muted">Scroll to pan. Pinch or ⌘ + scroll to zoom.</p>
            </div>
          ) : null}
          {selectedRow ? (
            <aside className="drawer">
              <h3>{selectedRow.id}</h3>
              <p className="muted">{opticalLabel(selectedRow, camera, lens, look, motion, aperture, genre, lighting, palette) || "Set camera, lens, and look in the stack."}</p>
              {nodeDigest(selectedRow.id) ? (
                <img alt="" src={`${API}/assets/${nodeDigest(selectedRow.id)}/file`} />
              ) : (
                <p className="muted">No output on this node yet.</p>
              )}
              {defaultsFor(selectedRow.capability).prompt !== "none" ? (
                <>
                  <label htmlFor="node-prompt">Prompt</label>
                  <textarea
                    key={selectedRow.id}
                    ref={settleOnUnmount}
                    id="node-prompt"
                    className="prompt"
                    value={typeof selectedRow.params?.prompt === "string" && !selectedRow.params.prompt.startsWith("{{") ? selectedRow.params.prompt : ""}
                    placeholder={
                      typeof selectedRow.params?.prompt === "string" && selectedRow.params.prompt.startsWith("{{")
                        ? "Uses the page prompt. Type to give this node its own."
                        : defaultsFor(selectedRow.capability).placeholder
                    }
                    onFocus={() => {
                      promptBaseRef.current = graph;
                    }}
                    onChange={(ev) => {
                      const text = ev.target.value;
                      setGraphHistory((h) => preview(h, setParams(h.present, selectedRow.id, { prompt: text })));
                    }}
                    onBlur={settlePrompt}
                  />
                </>
              ) : null}
              <label htmlFor="node-model">Node model</label>
              <ModelCombo
                inputId="node-model"
                blankLabel="inherit skill default"
                value={selectedRow.model_id || ""}
                models={comboModels(
                  models.filter((m) => (m.capabilities || []).includes(selectedRow.capability || "t2i")),
                  false,
                  statusSuffix,
                )}
                onChange={(value) => {
                  setGraph((g) => updateNode(g, selectedRow.id, { model_id: value || undefined }));
                }}
              />
              <div className="file-row" style={{ marginTop: 10 }}>
                <button
                  className="run"
                  type="button"
                  disabled={Boolean(nodeBlocker)}
                  title={nodeBlocker || runLabel([selectedRow.id])}
                  onClick={() => runNodes([selectedRow.id])}
                >
                  Generate this node
                </button>
                <button className="ghost" type="button" title={withKeys("delete")} onClick={deleteSelection}>
                  Delete
                </button>
                <button className="ghost" type="button" onClick={() => setSelectedNode(null)}>
                  Close
                </button>
              </div>
              {nodeBlocker ? (
                <p className="run-blocker">{nodeBlocker}</p>
              ) : (
                <p className="muted run-estimate">{runLabel([selectedRow.id])}</p>
              )}
            </aside>
          ) : null}
        </main>
      </div>
    );
  } else if (page === "library") {
    const shotIds = [...new Set(projectRuns.flatMap((r) => r.outputs || []))];
    const allIds = libTab === "elements" ? [] : libTab === "shots" ? shotIds : assets.map((a) => a.id);
    const showElements = libTab !== "shots";
    main = (
      <div className="lib-page">
        <h2>Library</h2>
        <p className="muted">Shots from this project and local Elements. Not a scraped community feed.</p>
        <div className="lib-tabs cats">
          {(["all", "elements", "shots"] as const).map((tab) => (
            <button key={tab} type="button" className={libTab === tab ? "on" : ""} onClick={() => setLibTab(tab)}>
              {tab}
            </button>
          ))}
        </div>
        {showElements ? (
          <>
            <p className="eyebrow">Elements</p>
            {cast.length === 0 ? <p className="muted">No characters, locations, or props yet. Add them from Image or Canvas.</p> : null}
            <div className="connect-grid" id="element-kind-pills">
              {cast.map((c) => (
                <button key={c.assetId + c.name} type="button" className="connector-mark on" data-cast={c.name} onClick={() => setFirstFrameId(c.assetId)}>
                  <img className="face" alt="" src={`${API}/assets/${c.assetId}/file`} style={{ objectFit: "cover" }} />
                  <small>{c.name}</small>
                </button>
              ))}
            </div>
          </>
        ) : null}
        {libTab !== "elements" ? (
          <>
            <p className="eyebrow">Shots</p>
            {allIds.length === 0 ? <p className="muted">Nothing in the library yet.</p> : null}
            <div className="lib">
            {allIds.map((id) => {
              const a = assets.find((row) => row.id === id);
              return (
                <div key={id}>
                  {a?.mime?.startsWith("video/") ? (
                    <video src={`${API}/assets/${id}/file`} />
                  ) : (
                    <img alt="" src={`${API}/assets/${id}/file`} />
                  )}
                  <span className="muted">vinci://assets/{id}</span>
                </div>
              );
            })}
            </div>
          </>
        ) : null}
      </div>
    );
  } else if (page === "agent") {
    main = (
      <div className="lib-page">
        <h2>Supercomputer</h2>
        <p className="muted">A brief in. A plan out. Each step is a template you already own — no extra GPU farm.</p>
        <label htmlFor="agent-brief">Brief</label>
        <textarea
          id="agent-brief"
          className="prompt"
          value={brief}
          onChange={(ev) => setBrief(ev.target.value)}
          placeholder="Luxury watch on marble, dusk, 8K still then a slow orbit."
        />
        <div className="file-row" style={{ marginTop: 12 }}>
          <button className="run" type="button" onClick={() => void planBrief()}>
            Plan
          </button>
          <button className="ghost" type="button" onClick={() => void runPlan()} disabled={!plan.length || busy}>
            Run plan
          </button>
        </div>
        {plan.length ? (
          <div className="agent-log">
            {plan.map((step, i) => (
              <p key={`${step.skill}-${i}`}>
                {i + 1}. {step.title} — {step.skill}
                {step.note ? ` · ${step.note}` : ""}
              </p>
            ))}
          </div>
        ) : (
          <p className="muted">Describe the job. Vinci maps it onto Explore templates.</p>
        )}
        {log ? <p className="log">{log}</p> : null}
      </div>
    );
  } else if (page === "space") {
    main = (
      <div className="lib-page">
        <h2>3D</h2>
        <p className="muted">Orbit the last still. Generate a turntable plate when you want a new angle.</p>
        <div className="stage-3d">
          <div className="card3d" style={{ transform: `rotateY(${yaw}deg)` }}>
            {lastStill ? (
              <img src={`${API}/assets/${lastStill}/file`} alt="3D still" />
            ) : (
              <span className="muted">Generate a still first.</span>
            )}
          </div>
        </div>
        <div className="file-row">
          <button className="ghost" type="button" onClick={() => setYaw((y) => y - 25)}>
            Orbit left
          </button>
          <button className="ghost" type="button" onClick={() => setYaw((y) => y + 25)}>
            Orbit right
          </button>
          <button className="run" type="button" onClick={() => void generate3d()} disabled={busy}>
            Generate 3D plate
          </button>
        </div>
        {log ? <p className="log">{log}</p> : null}
      </div>
    );
  } else if (page === "collab") {
    main = (
      <div className="lib-page">
        <h2>Collab</h2>
        <p className="muted">Share a session on this machine. Snapshot the graph, prompt, and cast.</p>
        <div className="file-row">
          <input
            value={collabName}
            onChange={(ev) => setCollabName(ev.target.value)}
            placeholder="Session name"
            style={{ flex: 1, minWidth: 160 }}
          />
          <button className="run" type="button" onClick={() => void createCollab()}>
            New session
          </button>
        </div>
        {collabId ? <p className="muted">Open: {collabId}</p> : null}
        <div className="lib" style={{ marginTop: 16 }}>
          {sessions.map((s) => (
            <article key={s.id} className="collab-card">
              <strong>{s.name}</strong>
              <p className="muted">{s.id}</p>
              <div className="file-row">
                <button className="ghost" type="button" onClick={() => void joinCollab(s.id)}>
                  Open
                </button>
                <button className="ghost" type="button" onClick={() => void pushCollab(s.id)}>
                  Push
                </button>
              </div>
            </article>
          ))}
        </div>
        {!sessions.length ? <p className="muted">No sessions yet. Create one to share this Studio graph.</p> : null}
        {log ? <p className="log">{log}</p> : null}
      </div>
    );
  } else if (page === "keys") {
    const rows = doctor.providers || {};
    const mcpExtra = Object.keys(rows).filter((id) => id.startsWith("mcp_"));
    const connected = CONNECTOR_ORDER.concat(mcpExtra).filter(
      (id, i, arr) => arr.indexOf(id) === i && (id === "mock" || rows[id]?.available || rows[id]?.configured),
    );
    const disconnected = KEY_ORDER.concat(mcpExtra).filter((id) => rows[id] && !connected.includes(id));
    const picked = connectId && rows[connectId] ? rows[connectId] : null;
    const mcpPicked = connectId === "mcp" || connectId.startsWith("mcp_");
    const pickedStatus = !picked
      ? ""
      : picked.available
        ? "ready"
        : picked.configured
          ? "key stored, spend off"
          : "no key";
    const mark = (id: string, on: boolean) => {
      const row = rows[id];
      const label = id === "mock" ? "Local" : row?.display_name || id;
      return (
        <button
          key={id}
          type="button"
          className={"connector-mark " + (on ? "on" : "off") + (connectId === id ? " pick" : "")}
          data-connector={id}
          onClick={() => setConnectId(id)}
        >
          <span className="face">
            <ConnectorGlyph id={id} />
          </span>
          <small>{label}</small>
        </button>
      );
    };
    const httpIds = KEY_ORDER.filter((id) => id !== "mcp" && rows[id]);
    main = (
      <div className="keys connect">
        <p className="eyebrow">Vinci</p>
        <h2>Connect</h2>
        <p className="muted lede">
          Bring your own keys. Higgsfield and Magnific / Freepik are first-class HTTP plugins. Custom MCP is extra. Keys stay on this machine in <code>~/.vinci/keys</code>.
        </p>
        <p className="eyebrow">Connected</p>
        <div className="connect-grid" id="connected-grid">
          {connected.map((id) => mark(id, true))}
          <button
            type="button"
            className="connector-mark add"
            id="new-connector"
            onClick={() => {
              setConnectId("");
              requestAnimationFrame(() => openConnectorPicker());
            }}
          >
            <span className="face">+</span>
            <small>New connector</small>
          </button>
        </div>
        {disconnected.length ? (
          <>
            <p className="eyebrow">Not connected</p>
            <div className="connect-grid" id="disconnected-grid">
              {disconnected.map((id) => mark(id, false))}
            </div>
          </>
        ) : null}
        <div className="connect-add">
          <label htmlFor="connect-select">New connector</label>
          <select
            id="connect-select"
            value={connectId}
            onChange={(ev) => setConnectId(ev.target.value)}
          >
            <option value="">New connector</option>
            <optgroup label="HTTP plugins">
              {httpIds.map((id) => (
                <option key={id} value={id}>
                  {rows[id]?.display_name || id}
                </option>
              ))}
            </optgroup>
            <optgroup label="MCP">
              {mcpExtra.map((id) => (
                <option key={id} value={id}>
                  {rows[id]?.display_name || id}
                </option>
              ))}
              {rows.mcp ? <option value="mcp">Custom MCP</option> : null}
              <option value="mcp_new">Named MCP</option>
            </optgroup>
          </select>
        </div>
        {connectId === "mock" ? (
          <div className="connect-sheet" id="connect-sheet">
            <span className="kind">Local</span>
            <strong>Local</strong>
            <p className="muted">Local provider. No key required.</p>
            <button
              className="ghost"
              type="button"
              onClick={async () => {
                await api("/init", {
                  method: "POST",
                  headers: { "content-type": "application/json" },
                  body: JSON.stringify({ demo: true }),
                });
                await boot();
                setLog("Local models are on.");
              }}
            >
              Use local models
            </button>
          </div>
        ) : connectId === "mcp_new" ? (
          <div className="connect-sheet" id="connect-sheet">
            <span className="kind">Custom MCP</span>
            <strong>Named MCP</strong>
            <p className="muted">
              Extra MCP servers sit beside Custom MCP. Pick a slug, URL, and optional OAuth authorize URL.
            </p>
            <label>Label</label>
            <input
              id="label-mcp_new"
              value={keyDraft["label-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "label-mcp_new": ev.target.value }))}
              placeholder="ComfyUI"
            />
            <label>Id slug</label>
            <input
              id="slug-mcp_new"
              value={keyDraft["slug-mcp_new"] || ""}
              onChange={(ev) =>
                setKeyDraft((d) => ({ ...d, "slug-mcp_new": ev.target.value.replace(/[^a-z0-9_]/gi, "").toLowerCase() }))
              }
              placeholder="comfy"
            />
            <label>MCP URL</label>
            <input
              id="url-mcp_new"
              value={keyDraft["url-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "url-mcp_new": ev.target.value }))}
              placeholder="http://127.0.0.1:8765/mcp"
            />
            <label>Authorize URL (optional)</label>
            <input
              id="authurl-mcp_new"
              value={keyDraft["authurl-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "authurl-mcp_new": ev.target.value }))}
              placeholder="https://…/oauth/authorize"
            />
            <label>Bearer token (optional)</label>
            <input
              id="key-mcp_new"
              type="password"
              autoComplete="off"
              value={keyDraft["key-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "key-mcp_new": ev.target.value }))}
            />
            <button className="run" type="button" onClick={() => void addNamedMcp()}>
              Add MCP
            </button>
          </div>
        ) : picked ? (
          <div className="connect-sheet" id="connect-sheet">
            <span className="kind">{picked.kind === "mcp" ? "Custom MCP" : "HTTP plugin"}</span>
            <strong>{picked.display_name || connectId}</strong>
            <div className="muted">
              {picked.secret_name} · {pickedStatus}
            </div>
            {picked.docs ? (
              <p className="muted">
                <a href={picked.docs} target="_blank" rel="noreferrer">docs</a>
              </p>
            ) : null}
            {mcpPicked ? (
              <>
                <label>MCP URL</label>
                <input
                  value={keyDraft[`url-${connectId}`] ?? picked.url ?? ""}
                  onChange={(ev) => setKeyDraft((d) => ({ ...d, [`url-${connectId}`]: ev.target.value }))}
                  placeholder="http://127.0.0.1:8765/mcp"
                  id={`url-${connectId}`}
                />
                <label>Authorize URL (optional)</label>
                <input
                  value={keyDraft[`authurl-${connectId}`] ?? picked.authorize_url ?? ""}
                  onChange={(ev) => setKeyDraft((d) => ({ ...d, [`authurl-${connectId}`]: ev.target.value }))}
                  placeholder="https://…/oauth/authorize"
                  id={`authurl-${connectId}`}
                />
              </>
            ) : null}
            <label>{mcpPicked ? "Optional key" : "Paste key"}</label>
            <input
              id={`key-${connectId}`}
              type="password"
              autoComplete="off"
              value={keyDraft[`key-${connectId}`] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, [`key-${connectId}`]: ev.target.value }))}
              placeholder={picked.secret_name}
            />
            <label>Or env var name</label>
            <input
              id={`env-${connectId}`}
              value={keyDraft[`env-${connectId}`] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, [`env-${connectId}`]: ev.target.value }))}
              placeholder={picked.secret_name}
            />
            {connectId === "cloudflare" ? (
              <>
                <label>Account id</label>
                <input
                  id={`acct-${connectId}`}
                  value={keyDraft[`acct-${connectId}`] || ""}
                  onChange={(ev) => setKeyDraft((d) => ({ ...d, [`acct-${connectId}`]: ev.target.value }))}
                  placeholder="CLOUDFLARE_ACCOUNT_ID"
                />
              </>
            ) : null}
            {(picked.extra_secret_names || []).map((name) => (
              <div key={name}>
                <label>Paste {name}</label>
                <input
                  id={`extra-${connectId}`}
                  type="password"
                  autoComplete="off"
                  value={keyDraft[`extra-${connectId}`] || ""}
                  onChange={(ev) => setKeyDraft((d) => ({ ...d, [`extra-${connectId}`]: ev.target.value }))}
                  placeholder={name}
                />
              </div>
            ))}
            <div className="file-row">
              <button className="ghost" type="button" onClick={() => void oauthStart(connectId)}>
                {picked.auth === "oauth" ? "Sign in" : "Start OAuth"}
              </button>
              {picked.auth_state === "connected" || picked.auth_state === "needs_reconnect" ? (
                <button
                  className="ghost"
                  type="button"
                  onClick={() => {
                    void api(`/providers/${encodeURIComponent(connectId)}/disconnect`, {
                      method: "POST",
                    })
                      .then(() => boot())
                      .catch((err) => setLog(String(err instanceof Error ? err.message : err)));
                  }}
                >
                  Disconnect
                </button>
              ) : null}
              <button className="run" type="button" onClick={() => void saveProvider(connectId)}>
                Save {picked.display_name || connectId}
              </button>
            </div>
          </div>
        ) : (
          <div className="connect-sheet idle" id="connect-sheet">
            <strong>New connector</strong>
            <p className="muted">Pick a mark or choose from the list. HTTP plugins take a key. Custom MCP takes a URL.</p>
          </div>
        )}
        <div className="connect-routing">
          <p className="eyebrow">Routing</p>
          <label>Preference</label>
          <select value={pref} onChange={(ev) => setPref(ev.target.value)}>
            <option value="cheapest">cheapest</option>
            <option value="fastest">fastest</option>
            <option value="quality">quality</option>
          </select>
          <label>Max cost per run (USD)</label>
          <input id="max-cost" value={maxCost} onChange={(ev) => setMaxCost(ev.target.value)} placeholder="none" />
          <label>Monthly cap USD</label>
          <input id="monthly-cap" value={monthlyCap} onChange={(ev) => setMonthlyCap(ev.target.value)} placeholder="none" />
          <button
            className="ghost"
            type="button"
            onClick={async () => {
              const body: Record<string, unknown> = { preference: pref };
              if (monthlyCap.trim() !== "") body.monthly_cap_usd = Number(monthlyCap);
              try {
                await api("/settings", {
                  method: "PATCH",
                  headers: { "content-type": "application/json" },
                  body: JSON.stringify(body),
                });
                setDoctor(await api<Doctor>("/doctor"));
                setLog("Routing saved.");
              } catch (err) {
                setLog(String(err instanceof Error ? err.message : err));
              }
            }}
          >
            Save routing
          </button>
        </div>
      </div>
    );
  } else if (page === "skills") {
    main = (
      <div className="explore">
        <h2>Skills</h2>
        {skills.map((s) => (
          <div className="hit" key={s.id} data-skill={s.id} onClick={() => {
            setSkillRef(s.id);
            resetGraph(graphFromSkill(s, camera, lens, look, motion, aperture, genre, lighting, palette));
            setSelectedNode(null);
            setView("canvas");
            setPage("canvas");
          }} style={{ cursor: "pointer" }}>
            <strong>{s.id}</strong>
            <div className="muted">{(s.tags || []).join(" · ")}</div>
          </div>
        ))}
      </div>
    );
  } else if (page === "find") {
    main = (
      <div className="keys">
        <h2>Find</h2>
        <label>Query</label>
        <input value={findQ} onChange={(ev) => setFindQ(ev.target.value)} />
        <button
          className="run"
          type="button"
          onClick={async () => {
            const body = await api<{ hits: { uri?: string; transcript?: string }[] }>("/find?q=" + encodeURIComponent(findQ));
            setFindHits(body.hits || []);
          }}
        >
          Search index
        </button>
        {findHits.map((h, i) => (
          <div className="hit" key={i}>
            <div>{h.uri}</div>
            <div className="muted">{(h.transcript || "").slice(0, 160)}</div>
          </div>
        ))}
      </div>
    );
  } else if (page === "cost") {
    main = (
      <div className="keys">
        <h2>Cost report</h2>
        <p className="muted">USD by provider.</p>
        <pre className="log">{costBody || "loading…"}</pre>
      </div>
    );
  }

  function Pills({
    id,
    values,
    current,
    onPick,
  }: {
    id?: string;
    values: string[];
    current: string;
    onPick: (v: string) => void;
  }) {
    return (
      <div className="pills" id={id}>
        {values.map((v) => (
          <button key={v} type="button" className={v === current ? "on" : ""} onClick={() => onPick(v)}>
            {v}
          </button>
        ))}
      </div>
    );
  }

  /**
   * End a node-prompt edit as one undo step. Reads a ref and a stable setter, so a stale closure is safe.
   */
  function settlePrompt() {
    const base = promptBaseRef.current;
    if (!base) return;
    promptBaseRef.current = null;
    setGraphHistory((h) => settle(h, base));
  }

  /** Canvas keys; reassigned each render so it sees current selection. */
  const canvasKeyRef = useRef<(ev: KeyboardEvent) => void>(() => {});
  canvasKeyRef.current = (ev) => {
    const el = ev.target as HTMLElement | null;
    if (el?.closest("input, textarea, select, [contenteditable='true']")) return;
    if (ev.key === " ") {
      if (el?.closest("button")) return; // let a focused toolbar button activate
      ev.preventDefault();
      spaceRef.current = true;
      return;
    }
    const id = shortcutFor(ev);
    if (!id) return;
    ev.preventDefault();
    runShortcut(id);
  };
  useEffect(() => {
    if (page !== "canvas" || view !== "canvas") return;
    const onKey = (ev: KeyboardEvent) => canvasKeyRef.current(ev);
    const onKeyUp = (ev: KeyboardEvent) => {
      if (ev.key === " ") spaceRef.current = false;
    };
    // A held Space loses its keyup when the window blurs or this effect unmounts.
    const releaseSpace = () => {
      spaceRef.current = false;
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", releaseSpace);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", releaseSpace);
      releaseSpace();
    };
  }, [page, view]);

  // Wheel pans; pinch or ⌘/Ctrl+wheel zooms around the cursor. Non-passive so the page does not scroll.
  useEffect(() => {
    const el = boardRef.current;
    if (!el) return;
    function onWheel(ev: WheelEvent) {
      ev.preventDefault();
      const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
      if (ev.ctrlKey || ev.metaKey) {
        const factor = wheelZoomFactor(ev.deltaY, ev.deltaMode, ev.ctrlKey);
        setViewport((v) => zoomAt(v, v.zoom * factor, ev.clientX - r.left, ev.clientY - r.top));
      } else {
        // Some mice report notches in lines (deltaMode 1) or pages (2); pan in pixels.
        const unit = ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? r.height : 1;
        setViewport((v) => ({ ...v, x: v.x - ev.deltaX * unit, y: v.y - ev.deltaY * unit }));
      }
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [page, view]);

  useEffect(() => {
    if (!navOpen) return;
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") setNavOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  return (
    <div className={"shell" + (wantsInsp ? " with-insp" : "")} data-testid="vinci-studio-root">
      {navOpen ? (
        <button type="button" className="rail-scrim" aria-label="Close menu" onClick={() => setNavOpen(false)} />
      ) : null}
      <nav id="studio-rail" className={"rail" + (navOpen ? " open" : "")} aria-label="Studio">
        <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="#34c6c0" />
          <path d="M9 7h5l2 11 2-11h5L18 25h-4L9 7z" fill="#06262a" />
        </svg>
        {railGroups.flatMap((group) => {
          const items = group.items.map((item) => {
            const on =
              item.flyout === "image" ? imageOn : item.flyout === "video" ? videoOn : page === item.id;
            const button = (
              <button
                key={item.id}
                type="button"
                className={on ? "on" : ""}
                title={item.title}
                aria-label={item.title}
                onClick={() => openFlyoutPage(item.id)}
              >
                <RailIcon d={item.d} title={item.title} />
                <span className="rail-label">{item.title}</span>
              </button>
            );
            if (!item.flyout) return button;
            const kind = item.flyout;
            const features: { id: PageId; name: string; blurb: string }[] =
              kind === "image"
                ? [
                    { id: "image", name: "Create Image", blurb: "Stills from a prompt or reference" },
                    { id: "upscale", name: "Upscale Still", blurb: "Increase resolution on a still" },
                    { id: "adapts", name: "Adapts", blurb: "Partner and multi-ratio ad presets" },
                  ]
                : [
                    { id: "video", name: "Create Video", blurb: "Motion from a prompt or still" },
                    { id: "speak", name: "Talking Head", blurb: "Avatar video from a still and a line" },
                  ];
            return (
              <div className="rail-entry" key={item.id}>
                {button}
                <div className="rail-flyout">
                  <div>
                    <p className="rail-flyout-h">Features</p>
                    {features.map((row) => (
                      <button key={row.id} className="flyout-row" type="button" onClick={() => openFlyoutPage(row.id)}>
                        <strong>{row.name}</strong>
                        <span>{row.blurb}</span>
                      </button>
                    ))}
                  </div>
                  <div>
                    <p className="rail-flyout-h">Models</p>
                    {flyoutModels(kind).length ? (
                      flyoutModels(kind).map((row) => (
                        <button
                          key={row.id}
                          className="flyout-row"
                          type="button"
                          onClick={() => pickFlyoutModel(row, kind)}
                        >
                          <strong>{row.display_name || row.id}</strong>
                          <span>{row.provider || "model"}</span>
                        </button>
                      ))
                    ) : (
                      <p className="rail-flyout-empty">No models yet</p>
                    )}
                  </div>
                </div>
              </div>
            );
          });
          return group.label
            ? [<span key={group.label} className="rail-section">{group.label}</span>, ...items]
            : items;
        })}
        <span className="spacer" />
        <button type="button" className={page === "skills" ? "on rail-text" : "rail-text"} title="Skills" aria-label="Skills" onClick={() => openFlyoutPage("skills")}>
          <span className="rail-label">Skills</span>
        </button>
        <button type="button" className={page === "find" ? "on rail-text" : "rail-text"} title="Find" aria-label="Find" onClick={() => openFlyoutPage("find")}>
          <span className="rail-label">Find</span>
        </button>
        <button type="button" className={page === "cost" ? "on rail-text has-mini" : "rail-text has-mini"} title="Cost report" aria-label="Cost report" onClick={() => openFlyoutPage("cost")}>
          <span className="rail-mini" aria-hidden="true">$</span>
          <span className="rail-label">Cost report</span>
        </button>
        <button type="button" className={page === "keys" ? "on rail-text" : "rail-text"} title="Connect" aria-label="Connect" onClick={() => openFlyoutPage("keys")}>
          <span className="rail-label">Connect</span>
        </button>
      </nav>
      <section className="main">
        <div className="top">
          <div className="top-lead">
            <button
              type="button"
              className="rail-menu"
              aria-label={navOpen ? "Close studio menu" : "Open studio menu"}
              aria-expanded={navOpen}
              aria-controls="studio-rail"
              onClick={() => setNavOpen((open) => !open)}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                <path d="M3 5h12M3 9h12M3 13h12" stroke="currentColor" />
              </svg>
            </button>
            <h1>{titles[page]}</h1>
          </div>
          {page === "image" || page === "video" || page === "upscale" || page === "speak" ? (
            <button
              className="ghost"
              type="button"
              onClick={() => {
                setStageReset(true);
                setUploadId(null);
                setFirstFrameId(null);
                setLastFrameId(null);
                setModelsOpen(false);
              }}
            >
              + New
            </button>
          ) : page === "canvas" ? (
            <div className="views">
              <button type="button" className={view === "canvas" ? "on" : ""} onClick={() => setView("canvas")}>
                Canvas
              </button>
              <button type="button" className={view === "timeline" ? "on" : ""} onClick={() => setView("timeline")}>
                Timeline
              </button>
            </div>
          ) : (
            <span />
          )}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="muted">≈ {money(spent)}</span>
            <button className="chip" type="button" onClick={() => setPage("keys")}>
              {live.length
                ? live.map(([id, row]) => row.display_name || id).join(" · ") + (doctor.live_spend ? "" : " · spend off")
                : "Local"}
            </button>
          </div>
        </div>
        <div className="page">{main}</div>
      </section>
      {wantsInsp ? (
        <aside className="insp">
          <div className="insp-h">
            <p className="eyebrow">Cinema stack</p>
            <h2>{titles[page]}</h2>
            <p className="muted">
              {page === "upscale"
                ? "Increase resolution on the still. A prompt is not required."
                : "Pick a template or describe a shot. Price sits on Generate."}
            </p>
          </div>
          <div className="fields">
            <div>
              <label htmlFor="model">Model</label>
              <ModelCombo
                inputId="model"
                value={selected?.id || ""}
                models={comboModels(composeModels, true, statusSuffix)}
                onChange={setModelId}
              />
            </div>
            <div className={page === "upscale" && !mode.showMagnific ? "hidden" : ""}>
              <label htmlFor="prompt">{animateStill(selected) ? "Motion" : "Prompt"}</label>
              <textarea
                id="prompt"
                placeholder={
                  page === "upscale"
                    ? "Optional. Leave blank to upscale the still as-is."
                    : animateStill(selected)
                      ? "How the still should move."
                      : "north-light oak cube, 50mm cinema still."
                }
                value={prompt}
                onChange={(ev) => setPrompt(ev.target.value)}
              />
            </div>
            {opticalPage ? (
              <>
            <div>
              <label>Camera</label>
              <Pills
                id="camera-pills"
                values={CAMERAS}
                current={camera}
                onPick={(v) => {
                  setCamera(v);
                  stampSelected({ camera: v });
                }}
              />
            </div>
            <div>
              <label>Lens</label>
              <Pills
                id="lens-pills"
                values={LENSES}
                current={lens}
                onPick={(v) => {
                  setLens(v);
                  stampSelected({ lens: v });
                }}
              />
            </div>
            <div>
              <label>Look</label>
              <Pills
                id="look-pills"
                values={LOOKS}
                current={look}
                onPick={(v) => {
                  setLook(v);
                  stampSelected({ look: v });
                }}
              />
            </div>
            <div>
              <label>Lighting</label>
              <Pills
                id="lighting-pills"
                values={LIGHTING}
                current={lighting}
                onPick={(v) => {
                  setLighting(v);
                  stampSelected({ lighting: v });
                }}
              />
            </div>
            <div>
              <label>Color palette</label>
              <Pills
                id="palette-pills"
                values={PALETTES}
                current={palette}
                onPick={(v) => {
                  setPalette(v);
                  stampSelected({ palette: v });
                }}
              />
            </div>
            <div>
              <label>Aperture</label>
              <Pills
                id="aperture-pills"
                values={APERTURES}
                current={aperture}
                onPick={(v) => {
                  setAperture(v);
                  stampSelected({ aperture: v });
                }}
              />
            </div>
            <div>
              <label>Genre</label>
              <Pills
                id="genre-pills"
                values={GENRES}
                current={genre}
                onPick={(v) => {
                  setGenre(v);
                  stampSelected({ genre: v });
                }}
              />
            </div>
            {videoish && opticalPage ? (
              <div>
                <label>Camera motion</label>
                <Pills
                  id="motion-pills"
                  values={MOTIONS}
                  current={motion}
                  onPick={(v) => {
                    setMotion(v);
                    stampSelected({ motion: v });
                  }}
                />
              </div>
            ) : null}
              </>
            ) : null}
            {ratios.length ? (
              <div>
                <label>Aspect</label>
                <Pills
                  id="aspect-pills"
                  values={ratios}
                  current={aspectRatio || ratios[0]}
                  onPick={(v) => {
                    setAspectRatio(v);
                    stampSelected({ aspect_ratio: v });
                  }}
                />
              </div>
            ) : null}
            {page !== "upscale" && mode.showMotion && durs.length ? (
              <div>
                <label>Duration</label>
                <Pills
                  id="duration-pills"
                  values={durs.map(String)}
                  current={duration || String(durs.includes(5) ? 5 : durs[0])}
                  onPick={(v) => {
                    setDuration(v);
                    stampSelected({ duration: Number(v) });
                  }}
                />
              </div>
            ) : null}
            {(selected?.constraints?.resolutions || []).length ? (
              <div>
                <label>Quality</label>
                <Pills
                  id="resolution-pills"
                  values={selected?.constraints?.resolutions || []}
                  current={resolution || selected?.constraints?.resolutions?.[0] || ""}
                  onPick={(v) => {
                    setResolution(v);
                    stampSelected({ resolution: v });
                  }}
                />
              </div>
            ) : null}
            {mode.showScale ? (
              <div>
                <label>Scale</label>
                <Pills id="scale-pills" values={["2x", "4x", "8x", "16x"]} current={scale} onPick={setScale} />
              </div>
            ) : null}
            {mode.showScene ? (
              <div id="scene-field">
                <label>Speak scene</label>
                <Pills id="scene-pills" values={SCENES} current={scene} onPick={setScene} />
              </div>
            ) : null}
            {mode.showMagnific ? (
              <div id="magnific-field">
                <p className="muted" style={{ margin: 0 }}>
                  Magnific Creative. Precision ignores these.
                </p>
                <MagRange id="creativity" label="Creativity" value={creativity} onChange={setCreativity} />
                <MagRange id="resemblance" label="Resemblance" value={resemblance} onChange={setResemblance} />
                <MagRange id="hdr" label="HDR" value={hdr} onChange={setHdr} />
                <MagRange id="fractality" label="Fractality" value={fractality} onChange={setFractality} />
                <label>Optimized for</label>
                <Pills id="optimized-pills" values={MAG_STYLES} current={optimizedFor} onPick={setOptimizedFor} />
                <label>Engine</label>
                <Pills id="engine-pills" values={MAG_ENGINES} current={engine} onPick={setEngine} />
              </div>
            ) : null}
            {mode.showStill ? (
            <div id="still-field">
              <label htmlFor="insp-still">{mode.stillLabel}</label>
              <input
                id="insp-still"
                type="file"
                accept={mode.stillAccept}
                onChange={async (ev) => {
                  const file = ev.target.files?.[0];
                  if (!file) return;
                  try {
                    const asset = await ingest(file);
                    setUploadId(asset.id);
                    setStageReset(false);
                    setLog("Input loaded. vinci://assets/" + asset.id);
                  } catch (err) {
                    setLog(String(err instanceof Error ? err.message : err));
                  }
                }}
              />
              <span className="muted">{uploadId ? "vinci://assets/" + uploadId : mode.stillHint}</span>
            </div>
            ) : null}
            {mode.showFrames ? (
              <div id="frames-field">
                <label>First / last frame</label>
                <div className="insp-frames">
                  <div>
                    <label htmlFor="first-frame">First</label>
                    <input
                      id="first-frame"
                      type="file"
                      accept="image/*"
                      onChange={async (ev) => {
                        const file = ev.target.files?.[0];
                        if (!file) return;
                        const asset = await ingest(file);
                        setFirstFrameId(asset.id);
                        setLog("First frame " + asset.id);
                      }}
                    />
                  </div>
                  <div>
                    <label htmlFor="last-frame">Last</label>
                    <input
                      id="last-frame"
                      type="file"
                      accept="image/*"
                      onChange={async (ev) => {
                        const file = ev.target.files?.[0];
                        if (!file) return;
                        const asset = await ingest(file);
                        setLastFrameId(asset.id);
                        setLog("Last frame " + asset.id);
                      }}
                    />
                  </div>
                </div>
              </div>
            ) : null}
            {mode.showCast ? (
              <div id="cast-field">
                <label>Elements</label>
                <p className="muted" style={{ margin: "0 0 6px" }}>
                  Local named stills for characters, locations, and props. Not a scraped community feed.
                </p>
                <Pills
                  id="element-kind-pills"
                  values={[...ELEMENT_KINDS]}
                  current={elementKind}
                  onPick={(v) => setElementKind(v as (typeof ELEMENT_KINDS)[number])}
                />
                <div className="pills" id="cast-pills">
                  {cast.length === 0 ? <span className="muted">None yet</span> : null}
                  {cast.map((c) => (
                    <button
                      key={c.name}
                      type="button"
                      className={prompt.includes("@" + c.name) ? "on" : ""}
                      data-cast={c.name}
                      onClick={() => {
                        const tag = "@" + c.name;
                        setPrompt((p) => (p.includes(tag) ? p : (p.trim() + " " + tag).trim()));
                        setUploadId(c.assetId);
                        setFirstFrameId(c.assetId);
                      }}
                    >
                      @{c.name}
                      {c.kind && c.kind !== "character" ? " · " + c.kind : ""}
                    </button>
                  ))}
                </div>
                <div className="file-row">
                  <input id="cast-file" ref={castFileRef} type="file" accept="image/*" />
                  <input
                    id="cast-name"
                    type="text"
                    placeholder="Name"
                    value={castName}
                    onChange={(ev) => setCastName(ev.target.value)}
                  />
                  <button
                    className="ghost"
                    id="cast-add"
                    type="button"
                    onClick={async () => {
                      const file = castFileRef.current?.files?.[0];
                      const name = castName.trim() || file?.name.replace(/\.[^.]+$/, "") || "Cast";
                      if (!file) {
                        setLog("Pick a still, then Add to cast.");
                        return;
                      }
                      const asset = await ingest(file);
                      setCast((rows) => [
                        ...rows.filter((c) => c.name !== name),
                        { name, assetId: asset.id, kind: elementKind },
                      ]);
                      setCastName("");
                      setLog("Cast @" + name);
                    }}
                  >
                    Add to cast
                  </button>
                </div>
              </div>
            ) : null}
            {page === "upscale" && uploadId && lastDigest ? (
              <div className="split" id="split-view">
                <div>
                  <span className="muted">Before</span>
                  <img className="split-before" src={`${API}/assets/${uploadId}/file`} alt="" />
                </div>
                <div>
                  <span className="muted">After</span>
                  <img className="split-after" src={`${API}/assets/${lastDigest}/file`} alt="" />
                </div>
              </div>
            ) : null}
            <div className="file-row">
              <button className="ghost" type="button" onClick={() => addNode("t2i")}>+ Image node</button>
              <button
                className="ghost"
                type="button"
                onClick={() => {
                  const caps = selected?.capabilities || [];
                  addNode(caps.includes("i2v") && !caps.includes("t2v") ? "i2v" : "t2v");
                }}
              >
                + Video node
              </button>
              <button
                className="ghost"
                type="button"
                onClick={() => {
                  const caps = selected?.capabilities || [];
                  const videoJob = caps.includes("t2v") || caps.includes("i2v");
                  addNode(caps.includes("upscale") && !caps.includes("i2i") && !videoJob ? "upscale" : "i2i");
                }}
              >
                + Upscale node
              </button>
              <button className="ghost" id="add-shot" type="button" onClick={() => addShot()}>+ Shot</button>
            </div>
            <p className="log">{log}</p>
          </div>
          <div className="foot">
            <button className="run" type="button" disabled={busy || !selected} onClick={() => void generate()}>
              <span>{busy ? "Generating…" : "Generate"}</span>
              <span>{money(selected?.pricing?.amount)}</span>
            </button>
            {lastDigest ? (
              <a
                className="ghost"
                data-testid="studio-export-last"
                download={`vinci-${lastDigest.slice(0, 12)}`}
                href={`${API}/assets/${lastDigest}/file`}
                style={{ display: "inline-block", marginTop: 8 }}
              >
                Export last output
              </a>
            ) : null}
            <p className="muted" style={{ margin: "8px 0 0" }}>
              Estimates appear on Generate.
            </p>
          </div>
        </aside>
      ) : null}
      {onboardOpen ? (
        <div id="onboard" data-onboard data-step={String(onboardStep)}>
          <div className="onboard-scrim" />
          <div className="onboard-card">
            <p className="eyebrow">Vinci</p>
            <p className="muted">{ONBOARD_STEPS[onboardStep].kicker}</p>
            <h2>
              {onboardStep === 0 ? (
                <>
                  {"Your Brand's "}
                  <em className="serif">Superagency</em>
                </>
              ) : (
                ONBOARD_STEPS[onboardStep].title
              )}
            </h2>
            <p className="onboard-copy">{ONBOARD_STEPS[onboardStep].copy}</p>
            <div className="onboard-actions">
              <button
                className="run"
                type="button"
                id="onboard-next"
                onClick={() => {
                  if (onboardStep === 1) {
                    setOnboardStep(2);
                    return;
                  }
                  if (onboardStep >= ONBOARD_STEPS.length - 1) {
                    try {
                      localStorage.setItem(ONBOARD_KEY, "done");
                    } catch {
                      /* ignore */
                    }
                    setOnboardOpen(false);
                    setPage("image");
                    return;
                  }
                  setOnboardStep(onboardStep + 1);
                }}
              >
                {ONBOARD_STEPS[onboardStep].next}
              </button>
              {ONBOARD_STEPS[onboardStep].alt ? (
                <button
                  className="ghost"
                  type="button"
                  id="onboard-alt"
                  onClick={() => {
                    try {
                      localStorage.setItem(ONBOARD_KEY, "done");
                    } catch {
                      /* ignore */
                    }
                    setOnboardOpen(false);
                    setPage("keys");
                  }}
                >
                  {ONBOARD_STEPS[onboardStep].alt}
                </button>
              ) : null}
              <button
                className="ghost"
                type="button"
                id="onboard-skip"
                onClick={() => {
                  try {
                    localStorage.setItem(ONBOARD_KEY, "done");
                  } catch {
                    /* ignore */
                  }
                  setOnboardOpen(false);
                }}
              >
                Skip for now
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
