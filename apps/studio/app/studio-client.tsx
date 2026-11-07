"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { AdaptFlowCanvas } from "./adapt-flow-canvas";
import { AdaptsPanel, EMPTY_PRESET_DRAFT, type PresetDraft } from "./adapts-panel";
import { EffectShell } from "./effect-shell";
import { OutputSettingsPanel } from "./output-settings-panel";
import { defaultAppIdForPage, getApp } from "../lib/apps-catalog";
import { AssetsPage, type LibraryItem as AssetItem } from "./assets-page";
import { type LibraryResponse } from "./library-types";
import { daemonHasPath } from "../lib/daemon-routes";
import type { AdaptPresetRow, AdaptTarget, BatchStatus } from "./adapt-ui-shared";
import { CanvasAddMenu } from "./canvas-add-menu";
import { CanvasEmpty } from "./canvas-empty";
import { CanvasInspector } from "./canvas-inspector";
import { CanvasNodeCard } from "./canvas-node-card";
import { ImagePage } from "./image-page";
import { LibraryPage } from "./library-page";
import { VideoPage } from "./video-page";
import { type ComboModel } from "./model-combo";
import { VinciLogo } from "./ui/logo";
import { DockIcon, DOCK_ICON } from "./ui/icons";
import { plainError } from "./ui/plain-text";
import { availabilityRank, modelAvailability, rankModels } from "../lib/model-search";
import {
  classifyModel,
  connectedProviderIds,
  modelsFor,
  modelsForNodeTypes,
  surfaceForPage,
  tieBreakAvailability,
  withoutMockWhenConnected,
  type Surface,
} from "../lib/model-capabilities";
import {
  addRef,
  ASPECTS,
  countPatch,
  countValue,
  listedOr,
  MOTIONS,
  nextRefRole,
  OPTICAL_NEUTRAL,
  pickListed,
  promptValue,
  REF_LIMIT,
  refsOf,
  removeRef,
  RESOLUTIONS,
  type RefRole,
} from "../lib/canvas-node";
import {
  autoImportPhotosExports,
  type ExportedOutputRow,
} from "../lib/mac-native";
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
  commonEdgeStyle,
  duplicateNode,
  edgesForStyle,
  estimateRun,
  fitView,
  GROUP_COLORS,
  groupBounds,
  groupNodes,
  groupOf,
  instanceNodes,
  moveNodes,
  nodesInRect,
  nodeTypeOf,
  freeSpot,
  portY,
  portsFor,
  isEdited,
  preview,
  redo,
  removeNodes,
  runSet,
  RUN_SCOPES,
  runtimeGraph,
  setEdgeStyle,
  setParams,
  settle,
  shortcutFor,
  startHistory,
  startParams,
  undo,
  ungroupNodes,
  updateGroup,
  updateNode,
  wheelZoomFactor,
  wirePath,
  withKeys,
  zoomAt,
  type AddChipId,
  type AddPick,
  type EdgeStyle,
  type Graph,
  type GraphEdge,
  type GraphNode,
  type MediaKind,
  type RunScope,
  type ShortcutId,
  type Viewport,
} from "../lib/canvas-graph";
import { EdgeTools, HistoryPanel, MinimapZoom, PageBar, SelectionBar } from "./canvas-chrome";
import {
  PROJECT_STORAGE_KEY,
  activePage,
  addBoardPage,
  emptyProject,
  MINIMAP_H,
  MINIMAP_W,
  minimapWorld,
  readProjectFile,
  removeBoardPage,
  renameBoardPage,
  viewportFromMinimap,
  writeActive,
  type BoardComment,
  type ProjectFile,
} from "../lib/canvas-board";
import {
  AVATAR_MENU,
  FLYOUT_FEATURES,
  RAIL_FOOTER,
  RAIL_GROUPS,
  commandSearch,
  editTools,
  filterTools,
  isCommandHotkey,
  moveCommandIndex,
  parsePinned,
  pickCommandHit,
  railItemOn,
  serializePinned,
  tabLabel,
  togglePin,
  visibleCategories,
  PIN_STORAGE_KEY,
  type CommandHit,
  type CommandModel,
  type FlyoutKind,
  type PageId,
} from "../lib/studio-shell";
import {
  LIBRARY_STORAGE_KEY,
  asCastRow,
  asLibraryItem,
  mentionRole,
  mentionableItems,
  mentionedItems,
  parseLibraryStore,
  providerMentionInputs,
  serializeLibraryStore,
  upsertLibraryItem,
  type LibraryItem,
  type LibraryTab,
} from "../lib/library";

const API = "/vinci-api";

/** Visible label for a command row kind. The raw `hit.kind` stays for routing and scoring. */
function kindWord(kind: CommandHit["kind"]): string {
  if (kind === "tool") return "Tool";
  if (kind === "asset") return "File";
  if (kind === "project") return "Project";
  return "Model";
}

/** Hide internal asset URIs and hashes in Find results. */
function findHitUri(uri?: string): string {
  const value = (uri || "").trim();
  if (!value) return "File";
  if (/vinci:\/\//i.test(value) || /\b[0-9a-f]{32,}\b/i.test(value)) return "File";
  return value;
}
const CATS = ["all", "image", "motion", "upscale", "cinema", "ads", "clips", "audio"];
const KEY_ORDER = ["higgsfield", "magnific", "wavespeed", "google", "fal", "elevenlabs", "cloudflare", "mcp"];
const CONNECTOR_ORDER = ["mock", ...KEY_ORDER];
const ONBOARD_KEY = "vinci-onboard-v1";
const ONBOARD_STEPS = [
  {
    kicker: "1 / 3",
    title: "Make images and video here",
    copy: "Stills, video, and campaigns in one place. Connect a provider when you want live models.",
    next: "Continue",
    alt: "",
  },
  {
    kicker: "2 / 3",
    title: "Connect when you need live models",
    copy: "Work on this computer now. When you want live models, open Connect and paste a key.",
    next: "Start generating",
    alt: "Connect a key",
  },
  {
    kicker: "3 / 3",
    title: "Make a still",
    copy: "Open Image, pick a model, then Generate. The price is on the button.",
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
  pricing?: { amount?: number; unit?: string };
  constraints?: { aspect_ratios?: string[]; max_duration?: number; resolutions?: string[]; max_input_images?: number | null };
  quality_tier?: string;
};
type Skill = { id: string; tags?: string[]; workflow?: { nodes?: GraphNode[]; edges?: GraphEdge[] } };
type Run = {
  id: string;
  state?: string;
  skill?: string;
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
  exported_outputs?: ExportedOutputRow[];
  estimate?: { total?: number };
  nodes?: Record<string, { output?: string; outputs?: string[]; job_id?: string }>;
  error?: unknown;
  workflow?: { nodes?: { model_id?: string; capability?: string }[] };
};
type Asset = { id: string; mime?: string; kind?: string; uri?: string; width?: number; height?: number };
type PlanStep = { id: string; title: string; skill: string; blurb?: string; note?: string };
type CastRow = { id?: string; name: string; assetId: string; kind?: string; refs?: string[]; soulId?: string };
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

/**
 * modelsFor order, then hide mock when a real provider is connected,
 * then availabilityRank only inside an equal modelsFor rank.
 */
function rankSurface<T extends Model>(
  surface: Surface,
  rows: readonly T[],
  connectedProviders: readonly string[],
  doctor: { providers?: Record<string, { configured?: boolean; available?: boolean } | undefined>; live_spend?: boolean },
): T[] {
  const listed = withoutMockWhenConnected(rows, connectedProviders);
  return tieBreakAvailability(surface, listed, (row) =>
    availabilityRank(modelAvailability(row, doctor.providers?.[row.provider], !!doctor.live_spend)),
  );
}

function modelIdForNode(
  node: GraphNode,
  fallbackId: string,
  catalog: Model[],
  connected?: readonly string[],
): string {
  const cap = node.capability;
  const providers =
    connected && connected.length
      ? connected
      : [...new Set(catalog.map((row) => row.provider).filter(Boolean))];
  const matched = cap ? modelsFor("canvas", providers, catalog, { capability: cap }) : catalog;
  const rows = withoutMockWhenConnected(matched, providers);
  for (const id of [node.model_id, fallbackId]) {
    if (id && rows.some((row) => row.id === id)) return id;
  }
  return rows[0]?.id || fallbackId;
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
      x: 40 + (i % 3) * (NODE_W + 40),
      y: 36 + Math.floor(i / 3) * (NODE_H + 40),
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
  const [page, setPage] = useState<PageId>("home");
  const [effectAppId, setEffectAppId] = useState(() => defaultAppIdForPage("speak"));
  const [navOpen, setNavOpen] = useState(false);
  const [pinnedIds, setPinnedIds] = useState<string[]>([]);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [toolsQuery, setToolsQuery] = useState("");
  const [toolsCategory, setToolsCategory] = useState("all");
  const [commandOpen, setCommandOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [commandIndex, setCommandIndex] = useState(0);
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [focusAssetId, setFocusAssetId] = useState<string | null>(null);
  const [view, setView] = useState<"canvas" | "timeline">("canvas");
  const [showGrid, setShowGrid] = useState(true);
  const [dockMenu, setDockMenu] = useState<null | "zoom" | "more">(null);
  const [category, setCategory] = useState("all");
  const [models, setModels] = useState<Model[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [doctor, setDoctor] = useState<Doctor>({});
  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState("");
  const [camera, setCamera] = useState(OPTICAL_NEUTRAL.camera);
  const [lens, setLens] = useState(OPTICAL_NEUTRAL.lens);
  const [look, setLook] = useState(OPTICAL_NEUTRAL.look);
  const [lighting, setLighting] = useState(OPTICAL_NEUTRAL.lighting);
  const [palette, setPalette] = useState(OPTICAL_NEUTRAL.palette);
  const [motion, setMotion] = useState(OPTICAL_NEUTRAL.motion);
  const [aperture, setAperture] = useState(OPTICAL_NEUTRAL.aperture);
  const [genre, setGenre] = useState(OPTICAL_NEUTRAL.genre);
  const [scene, setScene] = useState("general");
  const [creativity, setCreativity] = useState(0);
  const [resemblance, setResemblance] = useState(0);
  const [hdr, setHdr] = useState(0);
  const [fractality, setFractality] = useState(0);
  const [optimizedFor, setOptimizedFor] = useState("standard");
  const [engine, setEngine] = useState("automatic");
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
  const [canvasTool, setCanvasTool] = useState<"select" | "pan" | "note" | "comment">("select");
  const [runScope, setRunScope] = useState<RunScope>("upstream");
  const [project, setProject] = useState<ProjectFile>(() => emptyProject());
  const [comments, setComments] = useState<BoardComment[]>([]);
  const [editingComment, setEditingComment] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [menuEpoch, setMenuEpoch] = useState(0);
  const [projectReady, setProjectReady] = useState(false);
  const [panning, setPanning] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  /** Add menu at board coords; `from` set when opened from a node's output port. */
  const [addMenu, setAddMenu] = useState<{ x: number; y: number; from?: string; kind?: MediaKind | null } | null>(null);
  const [addChip, setAddChip] = useState<AddChipId | null>(null);
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
  /** Pointer that started the current pan, marquee, or drag. Other pointers must not end it. */
  const gesturePointerRef = useRef<number | null>(null);
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
  /** Gear on a Magnific card opens the right inspector for that node. */
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const nodeRefInput = useRef<HTMLInputElement>(null);
  const nodeRefRole = useRef<RefRole>("style");
  const nodeRefTarget = useRef<string | null>(null);
  /** Bumped per loaded graph, so a run that finishes after a reset cannot badge the new graph's nodes. */
  const graphEpochRef = useRef(0);
  /** Loading a template, skill, or collab snapshot starts a fresh history and drops stale selection or drags. */
  const resetGraph = useCallback((next: Graph) => {
    setGraphHistory(startHistory(next));
    setViewport(HOME_VIEW);
    setSelection([]);
    setSelectedEdge(null);
    setNodeRuns({}); // states are keyed by node id; a new graph may reuse ids
    setInspectorOpen(false);
    graphEpochRef.current += 1;
    dragRef.current = null;
    if (!panRef.current && !marqueeRef.current) gesturePointerRef.current = null;
  }, []);
  const applyProject = useCallback((file: ProjectFile) => {
    const page = activePage(file);
    setProject(page.id === file.active ? file : { ...file, active: page.id });
    resetGraph(page.graph);
    setComments(page.comments || []);
    setViewport(page.viewport || HOME_VIEW);
  }, [resetGraph]);
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
  const [libTab, setLibTab] = useState<LibraryTab>("characters");
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
  const [outputDestKind, setOutputDestKind] = useState("none");
  const [outputLocalDir, setOutputLocalDir] = useState("");
  const [outputPhotosAlbum, setOutputPhotosAlbum] = useState("Vinci");
  const [outputR2Prefix, setOutputR2Prefix] = useState("vinci/outputs/");
  const [outputR2Configured, setOutputR2Configured] = useState(false);
  const [resolution, setResolution] = useState("");
  const [quality, setQuality] = useState("");
  const [batchCount, setBatchCount] = useState(1);
  const [firstFrameId, setFirstFrameId] = useState<string | null>(null);
  const [lastFrameId, setLastFrameId] = useState<string | null>(null);
  const [extendMode, setExtendMode] = useState(false);
  const [extendClipId, setExtendClipId] = useState<string | null>(null);
  const [audioId, setAudioId] = useState<string | null>(null);
  const [videoExtraIds, setVideoExtraIds] = useState<string[]>([]);
  const [audioOn, setAudioOn] = useState(false);
  const [seed, setSeed] = useState("");
  const [steps, setSteps] = useState("");
  const [cast, setCast] = useState<CastRow[]>([]);
  const libraryItems = useMemo(() => cast.map(asLibraryItem), [cast]);
  const mentionItems = useMemo(() => mentionableItems(libraryItems), [libraryItems]);
  const [libraryReady, setLibraryReady] = useState(false);
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

  const connected = useMemo(() => connectedProviderIds(doctor.providers), [doctor]);
  const connectedKey = connected.join("\0");
  /** True after the user picks a model. Auto-defaults stay false so a new key can replace mock. */
  const modelTouched = useRef(false);
  const seenConnected = useRef(connectedKey);

  const composeModels = useMemo(() => {
    const surface = surfaceForPage(page);
    if (page === "image") {
      const seen = new Set<string>();
      const rows: Model[] = [];
      for (const part of ["image", "image_edit"] as const) {
        for (const row of modelsFor(part, connected, models)) {
          if (seen.has(row.id)) continue;
          seen.add(row.id);
          rows.push(row);
        }
      }
      return rankSurface("image", rows, connected, doctor);
    }
    return rankSurface(surface, modelsFor(surface, connected, models), connected, doctor);
  }, [models, page, connected, doctor]);


  function statusSuffix(row: Model): string {
    const status = modelAvailability(row, doctor.providers?.[row.provider], !!doctor.live_spend);
    if (status === "spend_off") return " · paid runs off";
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
    if (page === "speak" || page === "upscale" || page === "adapts") {
      setEffectAppId(defaultAppIdForPage(page));
    }
  }, [page]);

  useEffect(() => {
    if (seenConnected.current !== connectedKey) {
      const held = models.find((m) => m.id === modelId);
      if (!held || held.provider === "mock") modelTouched.current = false;
      seenConnected.current = connectedKey;
    }
    if (!composeModels.length) return;
    const current = composeModels.find((m) => m.id === modelId);
    if (
      page === "upscale" &&
      current &&
      !modelTouched.current &&
      !classifyModel(current).functions.includes("image_upscale")
    ) {
      const still = composeModels.find((m) => classifyModel(m).functions.includes("image_upscale"));
      if (still && still.id !== modelId) {
        setModelId(still.id);
        return;
      }
    }
    const hasLive = composeModels.some((m) => m.provider !== "mock");
    if (current && (modelTouched.current || current.provider !== "mock" || !hasLive)) return;
    const next = composeModels.find((m) => m.provider !== "mock") || composeModels[0];
    if (next && next.id !== modelId) {
      modelTouched.current = false;
      setModelId(next.id);
    }
  }, [composeModels, modelId, page, connectedKey, models]);

  const selected = composeModels.find((m) => m.id === modelId) || composeModels[0];
  const mode = panelFor(selected, page);

  const loadMedia = useCallback(async () => {
    const [runBody, assetBody] = await Promise.all([
      api<{ runs: Run[] }>("/runs"),
      api<{ assets: Asset[] }>("/assets"),
    ]);
    setRuns(runBody.runs || []);
    setAssets(assetBody.assets || []);
  }, []);

  const [toolFeed, setToolFeed] = useState<AssetItem[]>([]);
  const loadToolFeed = useCallback(async (tool?: "image" | "video") => {
    const next = tool || (page === "video" ? "video" : page === "image" ? "image" : null);
    if (!next) return;
    try {
      if (!(await daemonHasPath(API, "/library"))) {
        setToolFeed([]);
        return;
      }
      const body = await api<LibraryResponse>(`/library?tool=${next}&limit=80`);
      setToolFeed(body.items || []);
    } catch {
      setToolFeed([]);
    }
  }, [page]);

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
      setLog("Source added.");
    },
    [loadMedia],
  );

  const estimateAdapt = useCallback(async () => {
    if (!adaptSourceId) {
      setLog("Upload a still first.");
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
    setLog(`Estimate ${money(body.total)} for ${adaptTargets.length} sizes.`);
  }, [adaptLayout, adaptSourceId, adaptTargets]);

  const runAdapt = useCallback(async () => {
    if (!adaptSourceId) {
      setLog("Upload a still first.");
      return;
    }
    const presetIds = adaptTargets.map((row) => row.preset_id).filter((id): id is string => Boolean(id));
    if (!presetIds.length) {
      setLog("Pick at least one size.");
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
          ? `${failed} sizes failed. Check the results.`
          : `Done. ${outputs.length} sizes ready.`,
      );
    } catch (err) {
      setLog(plainError(err));
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
      setLog("Preset saved.");
    } catch (err) {
      setLog(plainError(err));
    }
  }, [presetDraft, reloadPresets]);

  const deletePreset = useCallback(
    async (id: string) => {
      try {
        await api(`/presets/${id}`, { method: "DELETE" });
        await reloadPresets();
        setLog("Preset deleted.");
      } catch (err) {
        setLog(plainError(err));
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
      const [doc, modelBody, skillBody, tplBody, presetBody, settingsBody] = await Promise.all([
        api<Doctor>("/doctor"),
        api<{ models: Model[] }>("/models"),
        api<{ skills: Skill[] }>("/skills"),
        api<{ templates: Template[] }>("/templates"),
        api<{ presets: AdaptPresetRow[] }>("/presets"),
        api<{
          output_destination: {
            kind: string;
            local_dir?: string;
            photos_album?: string;
            r2_prefix?: string;
            r2_configured?: boolean;
          };
        }>("/settings"),
      ]);
      setDoctor(doc);
      setPref(doc.preference || "cheapest");
      setMonthlyCap(doc.budget?.monthly_cap_usd != null ? String(doc.budget.monthly_cap_usd) : "");
      const od = settingsBody.output_destination || { kind: "none" };
      setOutputDestKind(od.kind || "none");
      setOutputLocalDir(od.local_dir || "");
      setOutputPhotosAlbum(od.photos_album || "Vinci");
      setOutputR2Prefix(od.r2_prefix || "vinci/outputs/");
      setOutputR2Configured(Boolean(od.r2_configured));
      setModels(modelBody.models || []);
      setSkills(skillBody.skills || []);
      setTemplates(tplBody.templates || []);
      setAdaptPresets(presetBody.presets || []);
      await loadMedia();
    } catch (err) {
      setLog(plainError(err));
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
    try {
      const stored = parseLibraryStore(localStorage.getItem(LIBRARY_STORAGE_KEY));
      if (stored.length) {
        setCast(stored.map(asCastRow));
        console.info("[library] loaded", { count: stored.length });
      }
    } catch {
      /* ignore */
    }
    setLibraryReady(true);
  }, []);

  useEffect(() => {
    if (!libraryReady) return;
    try {
      localStorage.setItem(LIBRARY_STORAGE_KEY, serializeLibraryStore(libraryItems));
    } catch {
      /* ignore */
    }
  }, [libraryItems, libraryReady]);

  useEffect(() => {
    setModelsOpen(false);
  }, [page]);

  useEffect(() => {
    if (page === "image" || page === "video") void loadToolFeed(page);
  }, [loadToolFeed, page]);

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
      .catch((err) => setLog(plainError(err)));
  }, [page]);

  useEffect(() => {
    function fromGesture(ev: PointerEvent) {
      const id = gesturePointerRef.current;
      return id === null || ev.pointerId === id;
    }
    function end() {
      gesturePointerRef.current = null;
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
    function move(ev: PointerEvent) {
      if (!fromGesture(ev)) return;
      // No button held: the pointerup was missed (released outside the window), so end the gesture.
      if (ev.buttons === 0 && (panRef.current || marqueeRef.current || dragRef.current)) return end();
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
    function up(ev: PointerEvent) {
      if (!fromGesture(ev)) return;
      end();
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    window.addEventListener("blur", end);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      window.removeEventListener("blur", end);
    };
  }, []);

  const usable = (model?: Model) => {
    if (!model) return false;
    if (model.provider === "mock") return true;
    return !!model.available && !!doctor.live_spend;
  };
  const modelRank = useCallback(
    (row: { provider?: string }) =>
      availabilityRank(modelAvailability(row as Model, doctor.providers?.[row.provider || ""], !!doctor.live_spend)),
    [doctor],
  );

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
  const canvasSelected = page === "canvas" ? graph.nodes.find((n) => n.id === selectedNode) : undefined;
  const wantsInsp = page === "canvas" && inspectorOpen && Boolean(canvasSelected);
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

  function shownResolution(): string {
    const valid = selected?.constraints?.resolutions ?? [];
    return valid.includes(resolution) ? resolution : valid[0] || "";
  }

  function modelListsResolution(modelId: string | undefined, value: unknown): boolean {
    const allowed = models.find((m) => m.id === modelId)?.constraints?.resolutions;
    return Boolean(allowed?.includes(String(value ?? "")));
  }

  function shotInputs(base: Record<string, unknown>) {
    const inputs = { ...base };
    if (aspectRatio && ratios.length) inputs.aspect_ratio = aspectRatio;
    if (duration && mode.showMotion) inputs.duration = Number(duration);
    // Send the resolution the pills show. A value from another model is not on this list.
    const shown = shownResolution();
    if (shown) inputs.resolution = shown;
    if (page === "image" && quality) inputs.quality = quality;
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
    if ((mode.showFrames || page === "video") && firstFrameId) {
      inputs.first_frame_url = firstFrameId;
      inputs.start_image_url = firstFrameId;
      inputs.image = firstFrameId;
      inputs.media = firstFrameId;
    }
    if ((mode.showFrames || page === "video") && lastFrameId) {
      inputs.last_frame_url = lastFrameId;
      inputs.tail_image_url = lastFrameId;
    }
    if (page === "video") {
      if (seed.trim()) inputs.seed = Number(seed) || seed;
      if (steps.trim()) inputs.steps = Number(steps);
      if (audioId) inputs.audio = audioId;
      if (extendClipId) inputs.video = extendClipId;
    }
    if (mode.showStill && uploadId && page !== "video") {
      inputs.media = uploadId;
      if (!inputs.image) inputs.image = uploadId;
    }
    if (mode.showCast || mode.showStill || (page === "video" && videoExtraIds.length)) {
      const urls: string[] = [];
      if (typeof inputs.image === "string" && inputs.image) urls.push(inputs.image);
      if (page === "video") {
        for (const id of videoExtraIds) {
          if (id && !urls.includes(id)) urls.push(id);
        }
      }
      const mapped = providerMentionInputs(String(inputs.prompt || prompt), libraryItems, selected, urls);
      if (mapped.image_urls.length) {
        inputs.image_urls = mapped.image_urls;
        if (!inputs.image) inputs.image = mapped.image_urls[0];
      }
      if (mapped.soul_id) inputs.soul_id = mapped.soul_id;
    }
    return inputs;
  }

  /**
   * Attach @mentioned Library refs onto each generate node before /runs.
   *
   * Typed `@Name` (no popover click) still sends that character's stills.
   */
  function withMentionRefs(g: Graph, model?: Model): Graph {
    let next = g;
    for (const n of g.nodes) {
      const text = promptValue(n.params) || prompt;
      const chosen = mentionedItems(text, libraryItems);
      if (!chosen.length) continue;
      let params = n.params || {};
      for (const item of chosen) {
        for (const id of item.refs) params = addRef(params, mentionRole(item.kind), id);
      }
      const mapped = providerMentionInputs(
        text,
        libraryItems,
        model,
        refsOf(params).map((row) => row.assetId),
      );
      if (mapped.soul_id) params = { ...params, soul_id: mapped.soul_id };
      next = setParams(next, n.id, params);
    }
    return next;
  }

  function applyLibraryMention(nodeId: string, item: LibraryItem) {
    setGraph((g) => {
      let params = g.nodes.find((n) => n.id === nodeId)?.params || {};
      for (const id of item.refs) params = addRef(params, mentionRole(item.kind), id);
      console.info("[library] canvas mention", { nodeId, name: item.name, refs: item.refs.length });
      return setParams(g, nodeId, params);
    });
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
        setInspectorOpen(false);
        setCanvasTool("select");
        setHistoryOpen(false);
        setMenuEpoch((n) => n + 1);
        return;
      case "comment":
        setCanvasTool((tool) => (tool === "comment" ? "select" : "comment"));
        return;
      case "duplicate": {
        if (!selection.length) return;
        const copies = selection.map((id) => {
          const src = graph.nodes.find((n) => n.id === id);
          return [id, (src?.capability || "node") + "-" + Math.random().toString(16).slice(2, 6)] as const;
        });
        setGraph((g) => copies.reduce((acc, [id, copyId]) => duplicateNode(acc, id, copyId), g));
        setSelection(copies.map(([, copyId]) => copyId));
        setLog(copies.length === 1 ? "Duplicated." : `Duplicated ${copies.length} steps.`);
        return;
      }
      case "selectAll":
        setSelection(graph.nodes.map((n) => n.id));
        setSelectedEdge(null);
        return;
      case "runSelection":
        return runNodes(selection);
      case "runAll": {
        const blocker = graph.nodes.length ? runBlocker(graph.nodes.map((n) => n.id)) : "Add a step first. Press N, or pick a card.";
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
        // A selected wire is the selection (Delete removes it first), so fit its two ends.
        const ids = selectedEdge ? [selectedEdge.src, selectedEdge.dst] : selection;
        const rows = graph.nodes.filter((n) => ids.includes(n.id));
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
      setLog("Select two or more steps to group. Shift-click, or drag a box.");
      return;
    }
    if (groupOf(graph, selection)) {
      setLog("Already a group. Double-click the title to rename.");
      return;
    }
    const id = "group-" + Math.random().toString(16).slice(2, 6);
    setGraph((g) => groupNodes(g, selection, id));
    setLog(`Grouped ${selection.length} steps. Double-click the title to rename.`);
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

  /** Save the live board onto the active page, then open `id`. */
  function showPage(id: string) {
    if (id === project.active) return;
    const saved = writeActive(project, graph, comments, viewport);
    const page = saved.pages.find((row) => row.id === id);
    if (!page) return;
    setProject({ ...saved, active: id });
    resetGraph(page.graph);
    setComments(page.comments || []);
    setViewport(page.viewport || HOME_VIEW);
    setSelection([]);
    setSelectedEdge(null);
  }

  function createPage() {
    const id = "page-" + Math.random().toString(16).slice(2, 6);
    const saved = writeActive(project, graph, comments, viewport);
    const next = addBoardPage(saved, id);
    setProject(next);
    resetGraph({ nodes: [], edges: [] });
    setComments([]);
    setViewport(HOME_VIEW);
    setSelection([]);
    setSelectedEdge(null);
  }

  function deletePage(id: string) {
    const saved = writeActive(project, graph, comments, viewport);
    const next = removeBoardPage(saved, id);
    if (next === saved) return;
    setProject(next);
    if (next.active !== project.active) {
      const page = activePage(next);
      resetGraph(page.graph);
      setComments(page.comments || []);
      setViewport(page.viewport || HOME_VIEW);
      setSelection([]);
      setSelectedEdge(null);
    }
  }

  function scopeCost(scope: RunScope, ids: string[]) {
    if (scope === "page") return runCost(graph.nodes.map((n) => n.id), new Set(graph.nodes.map((n) => n.id)), true);
    if (scope === "node") return runCost(ids, new Set(ids), true);
    return runCost(ids);
  }

  function scopeBlocker(scope: RunScope, ids: string[]) {
    if (scope === "page") return runBlocker(graph.nodes.map((n) => n.id), true);
    if (scope === "node") return runBlocker(ids, true);
    return runBlocker(ids, false);
  }

  /** Selection-toolbar run. Card Run and "Run this node only" stay on `runNodes`. */
  function runScoped(scope: RunScope) {
    if (scope === "page") runNodes(graph.nodes.map((n) => n.id), true);
    else if (scope === "node") runNodes(selection, true);
    else runNodes(selection, false);
  }

  function applyEdgeStyle(style: EdgeStyle) {
    setProject((current) => ({ ...current, edgeStyle: style }));
    const pairs = edgesForStyle(graph, selection, selectedEdge);
    if (pairs.length) setGraph((g) => setEdgeStyle(g, pairs, style));
  }

  function instanceSelection() {
    if (!selection.length) return;
    const copies = selection.map((id) => {
      const src = graph.nodes.find((n) => n.id === id);
      return [id, (src?.capability || "node") + "-" + Math.random().toString(16).slice(2, 6)] as const;
    });
    setGraph((g) => instanceNodes(g, copies.map(([id]) => id), copies.map(([, copyId]) => copyId)));
    setSelection(copies.map(([, copyId]) => copyId));
    setLog(copies.length === 1 ? `Instanced ${copies[0][0]}.` : `Instanced ${copies.length} nodes.`);
  }

  function selectionAnchor(): { x: number; y: number; below: boolean } | null {
    const nodes = graph.nodes.filter((n) => selection.includes(n.id));
    let left = Infinity;
    let right = -Infinity;
    let top = Infinity;
    let bottom = -Infinity;
    if (nodes.length) {
      for (const n of nodes) {
        left = Math.min(left, n.x || 0);
        right = Math.max(right, (n.x || 0) + NODE_W);
        top = Math.min(top, n.y || 0);
        bottom = Math.max(bottom, (n.y || 0) + NODE_H);
      }
    } else if (selectedEdge) {
      const a = graph.nodes.find((n) => n.id === selectedEdge.src);
      const b = graph.nodes.find((n) => n.id === selectedEdge.dst);
      if (!a || !b) return null;
      const x1 = (a.x || 0) + NODE_W;
      const y1 = (a.y || 0) + portY(0);
      const x2 = b.x || 0;
      const y2 = (b.y || 0) + portY(0);
      left = Math.min(x1, x2);
      right = Math.max(x1, x2);
      top = Math.min(y1, y2);
      bottom = Math.max(y1, y2);
    } else return null;
    const screenTop = top * viewport.zoom + viewport.y;
    const screenBottom = bottom * viewport.zoom + viewport.y;
    const below = screenTop < 56;
    return { x: ((left + right) / 2) * viewport.zoom + viewport.x, y: below ? screenBottom : screenTop, below };
  }

  /** True when a different pointer already owns the pan, marquee, or drag. */
  function gestureTaken(pointerId: number): boolean {
    const owner = gesturePointerRef.current;
    return owner !== null && owner !== pointerId;
  }

  /** Start a drag of `ids` (a node, a selection, or a frame's members); a plain click selects `click`. */
  function startDrag(ev: { clientX: number; clientY: number; pointerId: number }, ids: string[], click: string[]) {
    if (gestureTaken(ev.pointerId)) return;
    gesturePointerRef.current = ev.pointerId;
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
    setCtxMenu({ x: Math.min(ev.clientX - r.left, r.width - 260), y: Math.min(ev.clientY - r.top, r.height - 280) });
  }

  /** Delete the selected wire, or else the selected nodes and their wires. */
  function deleteSelection() {
    if (selectedEdge) {
      setGraph((g) => disconnect(g, selectedEdge.src, selectedEdge.dst));
      setLog("Connection removed.");
      setSelectedEdge(null);
    } else if (selection.length) {
      const gone = selection;
      setGraph((g) => removeNodes(g, gone));
      setLog(gone.length === 1 ? "Deleted. Undo with ⌘Z." : `Deleted ${gone.length} steps. Undo with ⌘Z.`);
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
    const node = graph.nodes.find((n) => n.id === id);
    const asset = node?.params?.asset;
    if (typeof asset === "string" && asset && !asset.startsWith("{{")) return asset;
    return null;
  }

  async function generate(opts?: { nodeIds?: string[]; graph?: boolean; solo?: boolean }) {
    if (busy) return;
    const epoch = graphEpochRef.current;
    const model = selected;
    // Generate graph and node runs always send the canvas; animating a still is a page run.
    const animating = animateStill(model) && mode.showStill && !opts?.nodeIds?.length && !opts?.graph;
    const skill = skillFor(model);
    if (!model) {
      setLog("Models are still loading. Wait a moment and try again.");
      return;
    }
    const generateNodes = graph.nodes.filter((n) => n.type === "generate");
    // A canvas run can get its image from an upstream node, so only page runs need one up front.
    const canvasRun = !animating && (!!opts?.nodeIds?.length || ((graphEdited || !!opts?.graph) && generateNodes.length > 0));
    // Canvas nodes run on their pinned model or one the runtime picks: only page runs, targets that fall
    // back to the page model, and nodes pinned to it need it to be usable.
    const targets = new Set(opts?.nodeIds || []);
    const sent = targets.size ? graph.nodes.filter((n) => runSet(graph, targets, Boolean(opts?.solo)).has(n.id)) : generateNodes;
    const pageModelUsed =
      !canvasRun ||
      sent.some((n) => (targets.has(n.id) ? modelIdForNode(n, model.id, models, connected) : n.model_id) === model.id);
    if (pageModelUsed && model.provider !== "mock" && !usable(model)) {
      const status = modelAvailability(model, doctor.providers?.[model.provider], !!doctor.live_spend);
      if (status === "spend_off") {
        setLog("This model has a key, but paid runs are off. Turn on live spend, then try again.");
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
    setLog("Generating…");
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
        const keep = runSet(graph, targets, Boolean(opts?.solo));
        tracked = [...keep];
        const slice = {
          ...graph,
          nodes: graph.nodes.filter((n) => keep.has(n.id)),
          edges: graph.edges.filter((e) => keep.has(e.src) && keep.has(e.dst)),
        };
        const runtime = runtimeGraph(withMentionRefs(slice, model));
        payload.workflow = {
          id: "canvas-node",
          version: "1.0.0",
          preference: pref,
          nodes: runtime.nodes.map((n) =>
            targets.has(n.id) ? { ...n, model_id: modelIdForNode(n, model.id, models, connected) } : n,
          ),
          edges: runtime.edges,
        };
      } else if (!payload.workflow && (graphEdited || opts?.graph) && generateNodes.length) {
        tracked = generateNodes.map((n) => n.id);
        const runtime = runtimeGraph(withMentionRefs(graph, model));
        payload.workflow = {
          id: "canvas",
          version: "1.0.0",
          preference: pref,
          nodes: runtime.nodes,
          edges: runtime.edges,
        };
      } else if (!payload.workflow) {
        payload.skill = skill;
        const only = skillNodes.length === 1 ? skillNodes[0] : undefined;
        const pageCanRun = Boolean(
          only?.capability && (model.capabilities || []).includes(only.capability),
        );
        if (skillNodes.length > 1) {
          // These nodes are routed later. The page resolution may not be in that model's list.
          delete inputs.resolution;
        } else if (only?.model_id && only.model_id !== model.id) {
          // The skill pins its own model. Keep the page resolution only if that model lists it.
          if (!modelListsResolution(only.model_id, inputs.resolution)) delete inputs.resolution;
        } else if (only && !pageCanRun) {
          delete inputs.resolution;
        }
        if (skillNodes.length <= 1 && (!only || pageCanRun)) payload.model_id = model.id;
      }
      trackedRef.current = tracked;
      if (tracked.length) setNodeRuns((prev) => ({ ...prev, ...Object.fromEntries(tracked.map((id) => [id, { state: "running" as const }])) }));
      const times = !canvasRun && page === "image" ? (batchCount === 4 ? 4 : 1) : 1;
      let body: Run | null = null;
      for (let i = 0; i < times; i += 1) {
        body = await api<Run>("/runs", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(payload),
        });
        setRunIds((ids) => [...ids, body!.id]);
      }
      if (!body) throw new Error("Generate did not start a run.");
      if (tracked.length) {
        const results = await nodeRunStates(body, tracked);
        if (epoch === graphEpochRef.current) setNodeRuns((prev) => ({ ...prev, ...results }));
        // Recorded: a later failure (media refresh) is logged but must not mark these nodes as errors.
        trackedRef.current = [];
      }
      await loadMedia();
      await loadToolFeed(page === "video" ? "video" : "image");
      if (body.exported_outputs?.length) {
        autoImportPhotosExports(body.exported_outputs);
      }
      setLog(
        body.state === "completed"
          ? page === "image"
            ? "Your still is in the feed."
            : page === "video"
              ? "Your clip is in History."
              : "Done. It is on the board."
          : plainError(typeof body.error === "string" ? body.error : ""),
      );
    } catch (err) {
      const message = plainError(err);
      setLog(message);
      const failed = trackedRef.current;
      if (failed.length && epoch === graphEpochRef.current) setNodeRuns((prev) => ({ ...prev, ...Object.fromEntries(failed.map((id) => [id, { state: "error" as const, error: message }])) }));
    } finally {
      trackedRef.current = [];
      setBusy(false);
    }
  }

  function applyLibraryParams(params: Record<string, unknown>) {
    const asString = (key: string) => (typeof params[key] === "string" ? params[key] : "");
    const asNumber = (key: string) => (typeof params[key] === "number" ? params[key] : null);
    if (asString("aspect_ratio")) setAspectRatio(asString("aspect_ratio"));
    if (params.duration != null) setDuration(String(params.duration));
    if (asString("resolution")) setResolution(asString("resolution"));
    if (asString("camera")) setCamera(asString("camera"));
    if (asString("lens")) setLens(asString("lens"));
    if (asString("look")) setLook(asString("look"));
    if (asString("lighting")) setLighting(asString("lighting"));
    if (asString("palette")) setPalette(asString("palette"));
    if (asString("motion")) setMotion(asString("motion"));
    if (asString("aperture")) setAperture(asString("aperture"));
    if (asString("genre")) setGenre(asString("genre"));
    if (asString("scene")) setScene(asString("scene"));
    if (asString("optimized_for")) setOptimizedFor(asString("optimized_for"));
    if (asString("engine")) setEngine(asString("engine"));
    if (asString("scale")) setScale(asString("scale"));
    const creativityN = asNumber("creativity");
    if (creativityN != null) setCreativity(creativityN);
    const resemblanceN = asNumber("resemblance");
    if (resemblanceN != null) setResemblance(resemblanceN);
    const hdrN = asNumber("hdr");
    if (hdrN != null) setHdr(hdrN);
    const fractalityN = asNumber("fractality");
    if (fractalityN != null) setFractality(fractalityN);
  }

  /** Re-run an Assets item with the sidecar params, then open the matching compose page. */
  async function rerunFromLibrary(item: AssetItem) {
    const nextPage = (item.rerun_page as PageId) || "image";
    const params = item.params || {};
    const promptText = item.prompt || (typeof params.prompt === "string" ? params.prompt : "");
    setPrompt(promptText);
    if (item.model_id) setModelId(item.model_id);
    applyLibraryParams(params);
    setPage(nextPage);
    setStageReset(false);
    setBusy(true);
    setLog("Running it again…");
    try {
      const body = await api<Run>("/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          skill: item.rerun_skill,
          model_id: item.model_id || undefined,
          inputs: { ...params, prompt: promptText },
          preference: pref,
        }),
      });
      setRunIds((ids) => [...ids, body.id]);
      await loadMedia();
      await loadToolFeed(item.rerun_page === "video" ? "video" : "image");
      if (body.exported_outputs?.length) {
        autoImportPhotosExports(body.exported_outputs);
      }
      setLog(
        body.state === "completed"
          ? "Done. Your new file is ready."
          : plainError(typeof body.error === "string" ? body.error : ""),
      );
    } catch (err) {
      setLog(plainError(err));
    } finally {
      setBusy(false);
    }
  }

  /** Per-node states after a run: output present (cached when the job hit the runtime cache) or error. */
  async function nodeRunStates(body: Run, ids: string[]) {
    const next: typeof nodeRuns = {};
    const error = body.state === "completed" ? "" : plainError(typeof body.error === "string" ? body.error : "");
    await Promise.all(
      ids.map(async (id) => {
        const row = body.nodes?.[id];
        if (!row?.output && !row?.outputs?.length) {
          next[id] = { state: "error", error: error || "No output. Try again." };
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
    const id = modelIdForNode(n, selected?.id || "", models, connected);
    return models.find((m) => m.id === id)?.pricing?.amount ?? null;
  }

  /** Short pre-run cost of `ids` and what feeds them; `pinned` are the nodes the run pins to a model. */
  function runCost(ids: string[], pinned = new Set(ids), solo = false): { nodes: number; text: string } {
    const e = estimateRun(graph, ids, (n) => nodePrice(n, pinned), solo);
    const parts = [e.nodes > e.unpriced ? `up to ${money(e.total)}` : "", e.unpriced ? `${e.unpriced} not estimated` : ""];
    return { nodes: e.nodes, text: parts.filter(Boolean).join(" + ") };
  }

  function runLabel(ids: string[], pinned?: Set<string>): string {
    const { nodes, text } = runCost(ids, pinned);
    return `Run ${nodes} step${nodes === 1 ? "" : "s"}. ${text}`;
  }

  /** Run `ids` plus what feeds them. `solo` is the context-menu item "Run this node only". */
  function runNodes(ids: string[], solo = false) {
    if (!ids.length) {
      setLog("Select a step to run.");
      return;
    }
    const blocker = runBlocker(ids, solo);
    if (blocker) {
      setLog(blocker);
      return;
    }
    void generate({ nodeIds: ids, solo });
  }

  function openTemplate(t: Template) {
    const skill = skills.find((s) => s.id === t.skill);
    const defaults = t.defaults || {};
    const nextPrompt = prompt.trim() || String(defaults.prompt || "") || "north-light oak cube tumbling";
    const nextCamera = String(defaults.camera || OPTICAL_NEUTRAL.camera);
    const nextLens = String(defaults.lens || OPTICAL_NEUTRAL.lens);
    const nextLook = String(defaults.look || OPTICAL_NEUTRAL.look);
    const nextLighting = String(defaults.lighting || OPTICAL_NEUTRAL.lighting);
    const nextPalette = String(defaults.palette || OPTICAL_NEUTRAL.palette);
    const nextMotion = String(defaults.motion || OPTICAL_NEUTRAL.motion);
    const nextAperture = String(defaults.aperture || OPTICAL_NEUTRAL.aperture);
    const nextGenre = String(defaults.genre || OPTICAL_NEUTRAL.genre);
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

  /** A fresh node: generate nodes get the cinema stack; Media / Text / Note stay canvas-only. */
  function buildNode(capability: string, x: number, y: number, modelId?: string): GraphNode {
    const nodeType = nodeTypeOf(capability);
    const video = capability === "t2v" || capability === "i2v";
    const started = startParams(capability, { prompt, aspect_ratio: aspectRatio, duration, resolution });
    const params =
      nodeType === "generate"
        ? {
            camera,
            lens,
            look,
            lighting,
            palette,
            aperture,
            genre,
            ...(video ? { motion } : {}),
            ...started,
          }
        : started;
    return {
      id: capability + "-" + Math.random().toString(16).slice(2, 6),
      type: nodeType,
      capability,
      ...(modelId && nodeType === "generate" ? { model_id: modelId } : {}),
      params,
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

  /** First reason the given nodes (and what feeds them, unless `solo`) cannot run, or null. */
  function runBlocker(ids: Iterable<string>, solo = false): string | null {
    const page = pageInputFlags();
    for (const id of runSet(graph, ids, solo)) {
      const node = graph.nodes.find((n) => n.id === id);
      const reason = node && node.type === "generate" ? blockedReason(node, page) : null;
      if (reason) return reason;
    }
    return null;
  }

  /** Insert a node: beside `from` (and wired to it when the types fit), else at the board centre. */
  function insertNode(capability: string, from?: string, modelId?: string) {
    const src = from ? graph.nodes.find((n) => n.id === from) : undefined;
    const { w, h } = boardSize();
    const want = src
      ? { x: (src.x || 0) + NODE_W + 80, y: src.y || 0 }
      : w
        ? { x: (w / 2 - viewport.x) / viewport.zoom - NODE_W / 2, y: (h / 2 - viewport.y) / viewport.zoom - 80 }
        : { x: 60 + (graph.nodes.length % 3) * (NODE_W + 40), y: 80 }; // board not mounted (inspector on another page)
    const at = freeSpot(graph, want.x, want.y);
    const n = buildNode(capability, at.x, at.y, modelId);
    const next = addGraphNode(graph, n, src?.id, project.edgeStyle);
    setGraph(next);
    setSelectedNode(n.id);
    setSelectedEdge(null);
    const wired = next.edges.length > graph.edges.length;
    setLog(wired ? "Connected." : "Added.");
    return n.id;
  }

  function applyAddPick(pick: AddPick, from?: string) {
    if (pick.kind === "flow") {
      const template = templates.find((row) => row.id === pick.templateId);
      if (template) openTemplate(template);
      closeAddMenu();
      return;
    }
    insertNode(pick.capability, from, pick.kind === "model" ? pick.modelId : undefined);
    closeAddMenu();
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
      x: Math.max(8, Math.min(x, w - 372)),
      y: Math.max(56, Math.min(y, h - 300)),
      from: src?.id,
      kind: src ? portsFor(src).output : null,
    });
    setAddQuery("");
    setAddIndex(0);
    setAddChip(null);
  }

  function closeAddMenu() {
    setAddMenu(null);
    linkFromRef.current = null;
    setLinkFrom(null);
    setAddChip(null);
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
      setLog("Add a step first. Press N, or pick a card.");
      return;
    }
    for (const n of ordered) {
      const digest = nodeDigest(n.id);
      setTlStatus("Playing…");
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
          ? `${id} is on.` + (doctor.live_spend ? "" : " Paid runs are off.")
          : `${id} is saved. Add a key in Connect if it is still off.`,
      );
      setPage("keys");
    } catch (err) {
      setLog(plainError(err));
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
      setLog(plainError(err));
    }
  }

  async function oauthStart(id: string) {
    try {
      const body = await api<{ hint?: string; authorize_url?: string; mode?: string }>(
        `/providers/${encodeURIComponent(id)}/oauth`,
        { method: "POST" },
      );
      if (body.mode === "key") {
        setLog(body.hint || "Paste a key for this provider.");
        return;
      }
      if (body.authorize_url) window.open(body.authorize_url, "_blank", "noopener,noreferrer");
      if (body.mode !== "oauth") {
        setLog(body.hint || "Paste an access token.");
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
          setLog(`${id} needs you to sign in again.`);
          return;
        }
        if (row?.auth_state === "connected") {
          await boot();
          setLog(`${id} is connected.`);
          return;
        }
      }
      if (attempt === oauthAttemptRef.current) setLog("Still waiting for sign-in. Finish it in the browser, then come back.");
    } catch (err) {
      setLog(plainError(err));
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
      setLog((body.steps || []).length ? "Plan ready. Press Run plan." : "No templates match. Try a shorter brief.");
    } catch (err) {
      setLog(plainError(err));
    }
  }

  async function runPlan() {
    if (!plan.length || busy) return;
    setBusy(true);
    try {
      for (const step of plan) {
        const inputs = shotInputs({ prompt: brief.trim() || step.blurb || step.title });
        const planned = (skills.find((s) => s.id === step.skill)?.workflow?.nodes || []).filter(
          (n) => n.type === "generate",
        );
        const only = planned.length === 1 ? planned[0] : undefined;
        const pinnedElsewhere = Boolean(only?.model_id && only.model_id !== selected?.id);
        const pinnable = Boolean(
          only?.capability &&
            usable(selected) &&
            !pinnedElsewhere &&
            (selected?.capabilities || []).includes(only.capability),
        );
        if (pinnedElsewhere) {
          if (!modelListsResolution(only?.model_id, inputs.resolution)) delete inputs.resolution;
        } else if (!pinnable) {
          // A lip-sync or audio step must not inherit a still model's resolution.
          delete inputs.resolution;
        }
        const body = await api<Run>("/runs", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            skill: step.skill,
            inputs,
            model_id: pinnable ? selected?.id : undefined,
            preference: pref,
            max_cost: 0,
          }),
        });
        setRunIds((ids) => [...ids, body.id]);
      }
      await loadMedia();
      setLog("Plan complete.");
    } catch (err) {
      setLog(plainError(err));
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
      setLog(body.state === "completed" ? "Your new angle is ready." : plainError(typeof body.error === "string" ? body.error : ""));
    } catch (err) {
      setLog(plainError(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadSessions() {
    try {
      const body = await api<{ sessions: { id: string; name: string }[] }>("/collab/sessions");
      setSessions(body.sessions || []);
    } catch (err) {
      setLog(plainError(err));
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
      setLog(plainError(err));
    }
  }

  async function joinCollab(sid: string) {
    try {
      const body = await api<{
        id: string;
        name?: string;
        snapshot?: {
          prompt?: string;
          graph?: { nodes: GraphNode[]; edges: GraphEdge[] };
          cast?: CastRow[];
          page?: PageId;
          project?: ProjectFile;
        };
      }>(`/collab/sessions/${encodeURIComponent(sid)}`);
      setCollabId(body.id);
      if (body.name) setCollabName(body.name);
      const snap = body.snapshot || {};
      if (snap.prompt) setPrompt(snap.prompt);
      const opened = snap.project ? readProjectFile(JSON.stringify(snap.project)) : null;
      if (opened) applyProject(opened);
      else if (snap.graph) resetGraph(snap.graph);
      if (snap.cast) setCast(snap.cast);
      if (snap.page) setPage(String(snap.page) === "history" ? "assets" : snap.page);
      setLog("Session opened.");
    } catch (err) {
      setLog(plainError(err));
    }
  }

  async function pushCollab(sid: string) {
    try {
      await api(`/collab/sessions/${encodeURIComponent(sid)}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: collabName || "Session",
          snapshot: { prompt, graph, cast, page, project: writeActive(project, graph, comments, viewport) },
        }),
      });
      setCollabId(sid);
      setLog("Session updated.");
      await loadSessions();
    } catch (err) {
      setLog(plainError(err));
    }
  }

  const titles: Record<PageId, string> = {
    home: "Home",
    explore: "Templates",
    image: "Image",
    adapts: "Adapts",
    video: "Video",
    speak: "Speak",
    upscale: "Upscale still",
    edit: "Edit",
    canvas: "Canvas",
    library: "Library",
    assets: "Assets",
    agent: "Supercomputer",
    space: "3D",
    collab: "Collab",
    keys: "Connect",
    settings: "Settings",
    skills: "Skills",
    find: "Find",
    cost: "Cost report",
  };

  const live = Object.entries(doctor.providers || {}).filter(([id, row]) => id !== "mock" && row && row.available);
  const spent = projectRuns.reduce((sum, r) => sum + Number(r.estimate?.total || 0), 0);
  const popoverTools = filterTools(toolsQuery, toolsCategory);
  const popoverTabs = visibleCategories(toolsQuery);

  const saveOutputDestination = useCallback(async () => {
    await api("/settings", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        output_destination_kind: outputDestKind,
        output_local_dir: outputLocalDir,
        output_photos_album: outputPhotosAlbum,
        output_r2_prefix: outputR2Prefix,
      }),
    });
    setLog("Save location updated.");
  }, [outputDestKind, outputLocalDir, outputPhotosAlbum, outputR2Prefix]);
  const liveSpend = !!doctor.live_spend;
  /** Models in an Image or Video flyout. Membership and order come from modelsFor. */
  function flyoutModels(kind: FlyoutKind) {
    const groups: Model[][] =
      kind === "image"
        ? [
            rankSurface("image", modelsFor("image", connected, models), connected, doctor),
            rankSurface("image_edit", modelsFor("image_edit", connected, models), connected, doctor),
            rankSurface("upscale", modelsFor("upscale", connected, models), connected, doctor),
          ]
        : [
            rankSurface("video", modelsFor("video", connected, models), connected, doctor),
            rankSurface("audio", modelsFor("audio", connected, models), connected, doctor),
            rankSurface(
              "canvas",
              modelsFor("canvas", connected, models, { capability: "lipsync" }),
              connected,
              doctor,
            ),
          ];
    const seen = new Set<string>();
    const rows: Model[] = [];
    for (const group of groups) {
      for (const row of group) {
        if (seen.has(row.id)) continue;
        seen.add(row.id);
        rows.push(row);
      }
    }
    return rows.slice(0, 8);
  }

  /** Per-node pill list. Capability membership is modelsFor, not a raw includes check. */
  function nodeModels(capability: string): Model[] {
    const cap = capability || "t2i";
    return rankSurface("canvas", modelsFor("canvas", connected, models, { capability: cap }), connected, doctor);
  }
  function modelFlyoutPage(row: Model, kind: FlyoutKind): PageId {
    const caps = row.capabilities || [];
    if (kind === "image") return caps.includes("t2i") ? "image" : "upscale";
    const talk = (caps.includes("lipsync") || caps.includes("tts")) && !caps.includes("t2v") && !caps.includes("i2v");
    return talk ? "speak" : "video";
  }
  const shellModels: CommandModel[] = (["image", "video"] as const).flatMap((kind) =>
    flyoutModels(kind).map((row) => ({
      id: row.id,
      title: row.display_name || row.id,
      blurb: row.provider || "Model",
      page: modelFlyoutPage(row, kind),
      flyout: kind,
    })),
  );
  const modelQuery = toolsQuery.trim().toLowerCase();
  const popoverModels = shellModels.filter((row) => {
    if (toolsCategory === "image" && row.flyout !== "image") return false;
    if (toolsCategory === "video" && row.flyout !== "video") return false;
    if (toolsCategory !== "all" && toolsCategory !== "image" && toolsCategory !== "video") return false;
    if (!modelQuery) return true;
    return (row.title + " " + row.blurb + " " + row.id).toLowerCase().includes(modelQuery);
  });
  const commandHits = commandSearch(commandQuery, {
    assets,
    models: shellModels,
    projects: [
      ...templates.map((row) => ({ id: row.id, title: row.title, blurb: row.blurb, page: (row.page || "canvas") as PageId })),
      ...sessions.map((row) => ({ id: row.id, title: row.name, blurb: "Collab session", page: "collab" as const })),
    ],
  });
  /** Close All tools, Ctrl+K, the avatar menu, and the mobile drawer. */
  function closeShellOverlays() {
    setToolsOpen(false);
    setCommandOpen(false);
    setAvatarOpen(false);
    setNavOpen(false);
    if (typeof document !== "undefined") {
      (document.activeElement as HTMLElement | null)?.blur();
    }
  }
  /** Open a Studio page and drop every shell overlay. */
  function openPage(next: PageId) {
    setPage(next);
    setModelsOpen(false);
    closeShellOverlays();
  }
  function persistPins(next: string[]) {
    setPinnedIds(next);
    try {
      localStorage.setItem(PIN_STORAGE_KEY, serializePinned(next));
    } catch {
      /* ignore */
    }
  }
  /** Same page a flyout model pick opens. */
  function pickFlyoutModel(row: Model, kind: FlyoutKind) {
    modelTouched.current = true;
    setModelId(row.id);
    openPage(modelFlyoutPage(row, kind));
  }
  /** Enter on a Ctrl+K row: tool page, flyout model, asset, template, or collab session. */
  function openCommandHit(hit: CommandHit) {
    if (hit.kind === "model" && hit.flyout) {
      const row = models.find((model) => model.id === hit.id);
      if (row) {
        pickFlyoutModel(row, hit.flyout);
        return;
      }
    }
    if (hit.kind === "asset") {
      setFocusAssetId(hit.id);
      openPage("assets");
      return;
    }
    if (hit.kind === "project") {
      const template = templates.find((row) => row.id === hit.id);
      if (template) {
        closeShellOverlays();
        openTemplate(template);
        return;
      }
      if (hit.page === "collab") {
        closeShellOverlays();
        void joinCollab(hit.id);
        return;
      }
    }
    if (hit.page) openPage(hit.page);
  }

  let main: ReactNode = null;
  if (page === "home" || page === "explore") {
    const items = templates.filter((t) => category === "all" || t.category === category);
    main = (
      <div className="explore">
        <h2>{page === "home" ? "Home" : "Templates"}</h2>
        <p className="muted">Templates on this computer. Talking scenes open Video. Everything else opens the canvas.</p>
        <div className="cats">
          {CATS.map((c) => (
            <button key={c} type="button" className={category === c ? "on" : ""} onClick={() => setCategory(c)}>
              {tabLabel(c)}
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
  } else if (page === "image") {
    main = (
      <ImagePage
        models={models}
        connected={connected}
        availability={modelRank}
        selected={selected}
        modelId={selected?.id || modelId}
        onModelId={setModelId}
        prompt={prompt}
        onPrompt={setPrompt}
        aspect={aspectRatio || ratios[0] || ""}
        onAspect={(v) => {
          setAspectRatio(v);
          stampSelected({ aspect_ratio: v });
        }}
        resolution={shownResolution()}
        onResolution={setResolution}
        quality={quality}
        onQuality={setQuality}
        batch={batchCount}
        onBatch={setBatchCount}
        refs={uploadId ? [uploadId] : []}
        onAddRef={(file) => {
          void ingest(file)
            .then((asset) => {
              setUploadId(asset.id);
              setLog("Reference added.");
            })
            .catch((err) => setLog(plainError(err)));
        }}
        onRemoveRef={() => setUploadId(null)}
        cast={mentionItems.map(asCastRow)}
        busy={busy}
        pendingCount={batchCount === 4 ? 4 : 1}
        runs={runs}
        assets={assets}
        ready={(row) => usable({ ...row, capabilities: row.capabilities || [] })}
        onGenerate={() => void generate()}
        onReference={(id) => {
          setUploadId(id);
          setLog("Using this still as the reference.");
        }}
        onAnimate={(id) => {
          setUploadId(id);
          setFirstFrameId(id);
          setExtendMode(false);
          setExtendClipId(null);
          setPage("video");
          setLog("Start frame set. You are on Video.");
        }}
        onLog={setLog}
      />
    );
  } else if (page === "video") {
    main = (
      <VideoPage
        models={models}
        connected={connected}
        availability={modelRank}
        selected={selected}
        modelId={selected?.id || modelId}
        onModelId={setModelId}
        prompt={prompt}
        onPrompt={setPrompt}
        aspect={aspectRatio || ratios[0] || ""}
        onAspect={(v) => {
          setAspectRatio(v);
          stampSelected({ aspect_ratio: v });
        }}
        resolution={shownResolution()}
        onResolution={setResolution}
        duration={duration || (durs.includes(5) ? "5" : String(durs[0] || ""))}
        onDuration={(v) => {
          setDuration(v);
          stampSelected({ duration: Number(v) });
        }}
        seed={seed}
        onSeed={setSeed}
        steps={steps}
        onSteps={setSteps}
        extendMode={extendMode}
        onExtendMode={setExtendMode}
        startId={firstFrameId}
        endId={lastFrameId}
        clipId={extendClipId}
        audioId={audioId}
        extraIds={videoExtraIds}
        onStart={setFirstFrameId}
        onEnd={setLastFrameId}
        onClip={setExtendClipId}
        onAudio={setAudioId}
        onExtra={(id) => setVideoExtraIds((rows) => (rows.includes(id) ? rows : [...rows, id]))}
        onRemoveStart={() => setFirstFrameId(null)}
        onRemoveEnd={() => setLastFrameId(null)}
        onRemoveClip={() => setExtendClipId(null)}
        onRemoveAudio={() => setAudioId(null)}
        onRemoveExtra={(id) => setVideoExtraIds((rows) => rows.filter((row) => row !== id))}
        audioOn={audioOn}
        onAudioOn={setAudioOn}
        motion={motion}
        onMotion={(v) => {
          setMotion(v);
          stampSelected({ motion: v });
        }}
        motions={MOTIONS}
        cast={mentionItems.map(asCastRow)}
        busy={busy}
        runs={runs}
        assets={assets}
        ready={(row) => usable({ ...row, capabilities: row.capabilities || [] })}
        onGenerate={() => void generate()}
        onIngest={ingest}
        onLog={setLog}
      />
    );
  } else if (page === "speak" || page === "upscale" || page === "adapts") {
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
    const adaptsPanel =
      page === "adapts" ? (
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
          <AdaptsPanel {...panelProps} />
        </>
      ) : null;
    main =
      page === "adapts" && adaptView === "flow" ? (
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
        </>
      ) : (
        <EffectShell
          page={page}
          appId={effectAppId}
          onAppIdChange={setEffectAppId}
          models={models}
          connected={connected}
          liveSpend={liveSpend}
          runs={projectRuns}
          assets={assets}
          money={money}
          onOpenConnect={() => setPage("keys")}
          onRunComplete={() => void loadMedia()}
          adaptOutputIds={adaptOutputs}
          adaptsPanel={adaptsPanel}
          library={mentionItems}
        />
      );
  } else if (page === "canvas") {
    const pageHas = pageInputFlags();
    main = (
      <div className="stage">
        <main
          className={"board" + (showGrid ? "" : " no-grid")}
          style={
            view === "canvas"
              ? {
                  backgroundPosition: `${viewport.x}px ${viewport.y}px`,
                  backgroundSize: `${20 * viewport.zoom}px ${20 * viewport.zoom}px`,
                }
              : undefined
          }
        >
          {graph.nodes.length === 0 && view === "canvas" ? <CanvasEmpty onPick={(cap) => addNode(cap)} /> : null}
          {view === "canvas" ? (
            <div
              ref={boardRef}
              className={"graph" + (canvasTool === "pan" ? " pan" : "") + (panning ? " panning" : "") + (canvasTool === "note" || canvasTool === "comment" ? " place" : "")}
              onPointerDown={(ev) => {
                if (canvasTool === "pan" || spaceRef.current || ev.button === 1) {
                  ev.preventDefault();
                  if (gestureTaken(ev.pointerId)) return;
                  gesturePointerRef.current = ev.pointerId;
                  panRef.current = { x: ev.clientX, y: ev.clientY, vx: viewport.x, vy: viewport.y };
                  setPanning(true);
                  return;
                }
                setCtxMenu(null);
                setDockMenu(null);
                setMenuEpoch((n) => n + 1);
                if ((canvasTool === "comment" || canvasTool === "note") && ev.target === ev.currentTarget && ev.button === 0) {
                  const rect = ev.currentTarget.getBoundingClientRect();
                  const gx = (ev.clientX - rect.left - viewport.x) / viewport.zoom;
                  const gy = (ev.clientY - rect.top - viewport.y) / viewport.zoom;
                  if (canvasTool === "comment") {
                    const id = "c-" + Math.random().toString(16).slice(2, 6);
                    setComments((list) => [...list, { id, x: gx, y: gy, text: "" }]);
                    setEditingComment(id);
                  } else {
                    const at = freeSpot(graph, gx, gy);
                    const note = buildNode("note", at.x, at.y);
                    setGraph((g) => addGraphNode(g, note));
                    setSelectedNode(note.id);
                  }
                  return;
                }
                if (ev.target !== ev.currentTarget || ev.button !== 0) return;
                if (gestureTaken(ev.pointerId)) return;
                const r = ev.currentTarget.getBoundingClientRect();
                gesturePointerRef.current = ev.pointerId;
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
                        if (gestureTaken(ev.pointerId)) return;
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
                    const d = wirePath(a, b, e.input_key, e.style);
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
                        return <path className="wire ghost" d={curve(x1, y1, bx, by)} />;
                      })()
                    : null}
                </svg>
                {graph.nodes.map((n) => {
                  const digest = nodeDigest(n.id);
                  const cap = n.capability || n.type;
                  const asset = assets.find((a) => a.id === digest);
                  const label = NODE_CATALOG.find((row) => row.capability === n.capability)?.label || cap;
                  const needs = n.type === "generate" ? blockedReason(n, pageHas) : null;
                  return (
                    <div
                      key={n.id}
                      data-id={n.id}
                      className={"node" + (selection.includes(n.id) ? " on" : "") + (nodeRuns[n.id] ? " run-" + nodeRuns[n.id].state : "") + (n.instanceOf ? " is-instance" : "")}
                      style={{ left: n.x ?? 0, top: n.y ?? 0 }}
                      onPointerDown={(ev) => {
                        if ((ev.target as HTMLElement).closest(".port, .node-ui")) return;
                        if (canvasTool === "pan" || spaceRef.current || ev.button !== 0) return;
                        ev.stopPropagation();
                        setCtxMenu(null);
                        if (ev.shiftKey) {
                          setSelection((sel) => (sel.includes(n.id) ? sel.filter((id) => id !== n.id) : [...sel, n.id]));
                          setSelectedEdge(null);
                          return;
                        }
                        if (gestureTaken(ev.pointerId)) return;
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
                      {n.instanceOf ? <span className="node-instance">Instance</span> : null}
                      {portsFor(n).inputs.map((port, i) => (
                        <button
                          type="button"
                          key={port.key}
                          className={"port in kind-" + port.kind}
                          data-port="in"
                          data-id={n.id}
                          data-key={port.key}
                          data-kind={port.kind}
                          style={{ top: portY(i) - 5 }}
                          title={`${port.kind} in`}
                          aria-label={`${port.kind} input`}
                          onPointerDown={(ev) => ev.stopPropagation()}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            const from = linkFromRef.current;
                            if (!from) return;
                            closeAddMenu();
                            const wired = connect(graph, from, n.id, port.key, project.edgeStyle);
                            if (!wired.ok) {
                              setLog(wired.error);
                              return;
                            }
                            setGraph(wired.graph);
                            setLog("Connected.");
                          }}
                        />
                      ))}
                      {portsFor(n).output ? (
                        <button
                          type="button"
                          className={"port out kind-" + portsFor(n).output + (linkFrom === n.id ? " on" : "")}
                          data-port="out"
                          data-id={n.id}
                          data-kind={portsFor(n).output || ""}
                          style={{ top: portY(0) - 5 }}
                          title={`${portsFor(n).output} out. Click to add the next step.`}
                          aria-label={`${portsFor(n).output} output`}
                          onPointerDown={(ev) => ev.stopPropagation()}
                          onClick={(ev) => {
                            ev.stopPropagation();
                            linkFromRef.current = n.id;
                            setLinkFrom(n.id);
                            openAddMenu(n.id);
                            setLog(`Pick a step that takes ${portsFor(n).output}, or click an input.`);
                          }}
                        />
                      ) : null}
                      {(() => {
                        const modelRows = comboModels(nodeModels(n.capability || "t2i"), true, statusSuffix);
                        const model = models.find((m) => m.id === (n.model_id || modelIdForNode(n, selected?.id || "", models, connected)));
                        const aspects = listedOr(model?.constraints?.aspect_ratios, ASPECTS);
                        const resolutions = listedOr(model?.constraints?.resolutions, RESOLUTIONS);
                        const aspectChip = pickListed(n.params?.aspect_ratio, aspects);
                        const resolutionChip = pickListed(n.params?.resolution, resolutions);
                        const runText = runCost([n.id]).text;
                        const runBlock = n.type === "generate" ? runBlocker([n.id]) : null;
                        return (
                          <CanvasNodeCard
                            node={n}
                            label={label}
                            subtitle={NODE_CATALOG.find((row) => row.capability === n.capability)?.blurb}
                            placeholder={defaultsFor(n.capability).placeholder}
                            showPrompt={defaultsFor(n.capability).prompt !== "none"}
                            prompt={promptValue(n.params)}
                            digest={digest}
                            thumbSrc={digest ? `${API}/assets/${digest}/file` : undefined}
                            video={Boolean(asset?.mime?.startsWith("video/"))}
                            runState={nodeRuns[n.id]}
                            needs={needs}
                            models={modelRows}
                            modelId={n.model_id || ""}
                            aspects={aspects}
                            resolutions={resolutions}
                            count={countValue(n.params)}
                            aspect={aspectChip}
                            resolution={resolutionChip}
                            costText={runText}
                            runDisabled={Boolean(runBlock) || busy}
                            runTitle={runBlock || `Run · ${runText || "cost unknown"}`}
                            inspectorOpen={inspectorOpen && selectedNode === n.id}
                            refCount={refsOf(n.params).length}
                            promptRef={selectedNode === n.id ? settleOnUnmount : undefined}
                            onPromptFocus={() => {
                              promptBaseRef.current = graph;
                            }}
                            onPromptChange={(text) => {
                              setGraphHistory((h) => preview(h, setParams(h.present, n.id, { prompt: text })));
                            }}
                            onPromptBlur={settlePrompt}
                            onCount={(value) => setGraph((g) => setParams(g, n.id, countPatch(value)))}
                            onAspect={(v) => setGraph((g) => setParams(g, n.id, { aspect_ratio: v }))}
                            onResolution={(v) => setGraph((g) => setParams(g, n.id, { resolution: v }))}
                            onModel={(value) => setGraph((g) => updateNode(g, n.id, { model_id: value || undefined }))}
                            onGear={() => {
                              if (inspectorOpen && selectedNode === n.id) {
                                setInspectorOpen(false);
                                return;
                              }
                              setSelectedNode(n.id);
                              setSelectedEdge(null);
                              setInspectorOpen(true);
                            }}
                            onRun={() => runNodes([n.id])}
                            library={mentionItems}
                            onMention={(item) => applyLibraryMention(n.id, item)}
                            onAddReference={() => {
                              if (refsOf(n.params).length >= REF_LIMIT) return;
                              nodeRefTarget.current = n.id;
                              nodeRefRole.current = nextRefRole(refsOf(n.params));
                              nodeRefInput.current?.click();
                            }}
                            onUpload={
                              n.capability === "media"
                                ? (file) => {
                                    void ingest(file)
                                      .then((asset) => {
                                        const kind = asset.mime?.startsWith("video/")
                                          ? "video"
                                          : asset.mime?.startsWith("audio/")
                                            ? "audio"
                                            : "image";
                                        setGraph((g) => setParams(g, n.id, { asset: asset.id, mime: asset.mime, kind }));
                                        setLog("File added.");
                                      })
                                      .catch((err) => setLog(plainError(err)));
                                  }
                                : undefined
                            }
                          />
                        );
                      })()}
                    </div>
                  );
                })}
                {comments.map((comment) => (
                  <div
                    key={comment.id}
                    className="board-comment node-ui"
                    data-testid="board-comment"
                    style={{ left: comment.x, top: comment.y }}
                    onPointerDown={(ev) => ev.stopPropagation()}
                  >
                    <button type="button" className="icon-round on" aria-label="Edit comment" onClick={() => setEditingComment(comment.id)}>
                      C
                    </button>
                    {editingComment === comment.id || !comment.text ? (
                      <textarea
                        autoFocus
                        aria-label="Comment text"
                        value={comment.text}
                        onChange={(ev) => setComments((list) => list.map((row) => (row.id === comment.id ? { ...row, text: ev.target.value } : row)))}
                        onBlur={() => {
                          if (comment.text.trim()) setEditingComment(null);
                        }}
                      />
                    ) : (
                      <p>{comment.text}</p>
                    )}
                    <button
                      type="button"
                      className="icon-round"
                      aria-label="Delete comment"
                      onClick={() => setComments((list) => list.filter((row) => row.id !== comment.id))}
                    >
                      ×
                    </button>
                  </div>
                ))}
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
              {(() => {
                const anchor = selectionAnchor();
                if (!anchor) return null;
                const rows = RUN_SCOPES.map((row) => ({ ...row, cost: scopeCost(row.id, selection).text }));
                const pairs = edgesForStyle(graph, selection, selectedEdge);
                const blocker = selection.length ? scopeBlocker(runScope, selection) : null;
                return (
                  <SelectionBar
                    epoch={menuEpoch}
                    x={anchor.x}
                    y={anchor.y}
                    below={anchor.below}
                    scope={runScope}
                    scopes={rows}
                    cost={rows.find((row) => row.id === runScope)?.cost || "$0"}
                    edgeStyle={commonEdgeStyle(graph, pairs) || project.edgeStyle}
                    runDisabled={Boolean(blocker) || busy || !selection.length}
                    runTitle={blocker || rows.find((row) => row.id === runScope)?.cost || "Run"}
                    showRun={selection.length > 0}
                    canDuplicate={selection.length > 0}
                    canInstance={selection.length > 0}
                    canDelete={selection.length > 0 || Boolean(selectedEdge)}
                    canGroup={selection.length > 1}
                    canUngroup={(graph.groups || []).some((grp) => grp.nodeIds.some((id) => selection.includes(id)))}
                    onRun={() => runScoped(runScope)}
                    onScope={setRunScope}
                    onEdgeStyle={applyEdgeStyle}
                    onDuplicate={() => runShortcut("duplicate")}
                    onInstance={instanceSelection}
                    onDelete={deleteSelection}
                    onGroup={groupSelection}
                    onUngroup={ungroupSelection}
                  />
                );
              })()}
              <EdgeTools
                tool={canvasTool}
                canUndo={graphHistory.past.length > 0}
                canRedo={graphHistory.future.length > 0}
                historyOpen={historyOpen}
                addTitle={withKeys("addNode")}
                selectTitle={withKeys("selectMode")}
                panTitle={withKeys("panMode")}
                commentTitle={withKeys("comment")}
                undoTitle={withKeys("undo")}
                redoTitle={withKeys("redo")}
                onAdd={() => openAddMenu()}
                onSelect={() => setCanvasTool("select")}
                onPan={() => setCanvasTool("pan")}
                onNote={() => setCanvasTool((tool) => (tool === "note" ? "select" : "note"))}
                onComment={() => runShortcut("comment")}
                onUndo={() => stepHistory("undo")}
                onRedo={() => stepHistory("redo")}
                onHistory={() => setHistoryOpen((open) => !open)}
              />
              <PageBar
                pages={project.pages}
                active={project.active}
                onOpen={showPage}
                onAdd={createPage}
                onRemove={deletePage}
                onRename={(id, name) => setProject((current) => renameBoardPage(current, id, name))}
              />
              <MinimapZoom
                epoch={menuEpoch}
                nodes={graph.nodes}
                view={viewport}
                boardW={boardSize().w}
                boardH={boardSize().h}
                onPan={(mx, my) => {
                  const { w, h } = boardSize();
                  const world = minimapWorld(graph.nodes, viewport, w, h);
                  setViewport(viewportFromMinimap(world, MINIMAP_W, MINIMAP_H, mx, my, w, h, viewport.zoom));
                }}
                onZoomIn={() => zoomBy(1.2)}
                onZoomOut={() => zoomBy(1 / 1.2)}
                onFit={() => runShortcut("fit")}
                onFitSelection={() => runShortcut("fitSelection")}
                onReset={() => runShortcut("resetView")}
              />
              <HistoryPanel open={historyOpen} runs={projectRuns} money={money} onClose={() => setHistoryOpen(false)} />
            </div>
          ) : (
            <>
              <div className="tl-bar">
                <span className="muted" id="tl-status">{tlStatus}</span>
                <button className="ghost" type="button" id="tl-play" onClick={() => void playTimeline()}>
                  Play timeline
                </button>
              </div>
              <div className="tl-stage" id="tl-stage">
                {tlMedia?.video ? <video src={tlMedia.src} autoPlay muted /> : tlMedia ? <img alt="" src={tlMedia.src} /> : <p className="muted">Nothing to play yet. Press Run, then play.</p>}
              </div>
            </>
          )}
          {view === "canvas" ? (
            <>
              <button
                type="button"
                className={"edge-btn edge-help help" + (sheetOpen ? " on" : "")}
                aria-label="Show shortcuts"
                title={withKeys("help")}
                aria-expanded={sheetOpen}
                onClick={() => setSheetOpen((open) => !open)}
              >
                <DockIcon d={DOCK_ICON.help} />
              </button>
            </>
          ) : null}
          <div className="canvas-bar">
            {view === "canvas" ? (
              <div className="canvas-view" role="toolbar" aria-label="Canvas view">
                <button type="button" className={"dock-btn" + (canvasTool === "select" ? " on" : "")} aria-label="Select" aria-pressed={canvasTool === "select"} title={withKeys("selectMode")} onClick={() => { setCanvasTool("select"); setDockMenu(null); }}>
                  <DockIcon d={DOCK_ICON.select} />
                  <span className="dock-tip">Select <kbd>V</kbd></span>
                </button>
                <button type="button" className={"dock-btn" + (canvasTool === "pan" ? " on" : "")} aria-label="Pan" aria-pressed={canvasTool === "pan"} title={withKeys("panMode")} onClick={() => { setCanvasTool("pan"); setDockMenu(null); }}>
                  <DockIcon d={DOCK_ICON.pan} />
                  <span className="dock-tip">Pan <kbd>H</kbd></span>
                </button>
                <button type="button" className="dock-btn" aria-label="Frame" title={withKeys("group")} disabled={selection.length < 2} onClick={() => { groupSelection(); setDockMenu(null); }}>
                  <DockIcon d={DOCK_ICON.frame} />
                  <span className="dock-tip">Frame <kbd>⌘G</kbd></span>
                </button>
                <button
                  type="button"
                  className="dock-btn"
                  aria-label="Text"
                  title="Edit the selected prompt"
                  onClick={() => {
                    setDockMenu(null);
                    const id = selection[0];
                    const el = id ? document.querySelector(`[data-node-prompt="${id}"]`) : null;
                    if (el instanceof HTMLTextAreaElement) el.focus();
                  }}
                >
                  <DockIcon d={DOCK_ICON.text} />
                  <span className="dock-tip">Text</span>
                </button>
                {/* Pen is a dock slot. It does not change the pointer; Select and Pan still do. */}
                <button type="button" className="dock-btn" aria-label="Pen" title="Pen" onClick={() => setDockMenu(null)}>
                  <DockIcon d={DOCK_ICON.pen} />
                  <span className="dock-tip">Pen</span>
                </button>
                <button type="button" className="dock-btn" aria-label="Grid" aria-pressed={showGrid} title="Dot grid" onClick={() => { setShowGrid((on) => !on); setDockMenu(null); }}>
                  <DockIcon d={DOCK_ICON.grid} />
                  <span className="dock-tip">Grid</span>
                </button>
                <button type="button" className="dock-btn" aria-label="Add node" data-testid="canvas-add" title={withKeys("addNode")} onClick={() => { setDockMenu(null); openAddMenu(); }}>
                  <DockIcon d={DOCK_ICON.add} />
                  <span className="dock-tip">Add <kbd>N</kbd></span>
                </button>
                <span className="dock-slot">
                  <button type="button" className={"dock-btn" + (dockMenu === "zoom" ? " on" : "")} aria-label="Zoom" aria-expanded={dockMenu === "zoom"} title={withKeys("zoomIn")} onClick={() => setDockMenu((m) => (m === "zoom" ? null : "zoom"))}>
                    <DockIcon d={DOCK_ICON.zoom} />
                    <span className="dock-tip">Zoom</span>
                  </button>
                  {dockMenu === "zoom" ? (
                    <div className="dock-pop" role="menu">
                      <button type="button" aria-label="Zoom out" title={withKeys("zoomOut")} onClick={() => zoomBy(1 / 1.2)}>−</button>
                      <button type="button" className="zoom-pct" title={withKeys("resetView")} onClick={() => runShortcut("resetView")}>{Math.round(viewport.zoom * 100)}%</button>
                      <button type="button" aria-label="Zoom in" title={withKeys("zoomIn")} onClick={() => zoomBy(1.2)}>+</button>
                      <button type="button" title={withKeys("fit")} onClick={() => runShortcut("fit")}>Fit</button>
                    </div>
                  ) : null}
                </span>
                <button type="button" className="dock-btn" aria-label="Undo" title={withKeys("undo")} disabled={!graphHistory.past.length} onClick={() => stepHistory("undo")}>
                  <DockIcon d={DOCK_ICON.undo} />
                  <span className="dock-tip">Undo <kbd>⌘Z</kbd></span>
                </button>
                <button type="button" className="dock-btn" aria-label="Redo" title={withKeys("redo")} disabled={!graphHistory.future.length} onClick={() => stepHistory("redo")}>
                  <DockIcon d={DOCK_ICON.redo} />
                  <span className="dock-tip">Redo <kbd>⌘⇧Z</kbd></span>
                </button>
                <span className="dock-slot">
                  <button type="button" className={"dock-btn" + (dockMenu === "more" ? " on" : "")} aria-label="More canvas actions" aria-expanded={dockMenu === "more"} onClick={() => setDockMenu((m) => (m === "more" ? null : "more"))}>
                    <DockIcon d={DOCK_ICON.more} />
                    <span className="dock-tip">More</span>
                  </button>
                  {dockMenu === "more" ? (
                    <div className="dock-pop" role="menu">
                      {selectedEdge || selection.length ? (
                        <button type="button" title={withKeys("delete")} onClick={() => { setDockMenu(null); deleteSelection(); }}>
                          {selectedEdge ? "Delete connection" : selection.length > 1 ? `Delete ${selection.length}` : "Delete"}
                        </button>
                      ) : null}
                      <button type="button" onClick={() => { setDockMenu(null); void playTimeline(); }}>Play timeline</button>
                    </div>
                  ) : null}
                </span>
              </div>
            ) : null}
          </div>
          {addMenu && view === "canvas" ? (
            <CanvasAddMenu
              x={addMenu.x}
              y={addMenu.y}
              query={addQuery}
              index={addIndex}
              chip={addChip}
              takes={addMenu.kind}
              models={rankSurface("canvas", modelsForNodeTypes(connected, models), connected, doctor)}
              templates={templates}
              onQuery={setAddQuery}
              onIndex={setAddIndex}
              onChip={setAddChip}
              onPick={(pick) => applyAddPick(pick, addMenu.from)}
              onClose={closeAddMenu}
            />
          ) : null}
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
                    {(() => {
                      const soloNode =
                        selection.length === 1
                          ? graph.nodes.find((node) => node.id === selection[0] && node.type === "generate")
                          : undefined;
                      const soloOnlyCost = soloNode ? runCost([soloNode.id], new Set([soloNode.id]), true).text : "";
                      return (
                        <button
                          type="button"
                          role="menuitem"
                          disabled={!soloNode || busy}
                          onClick={() => {
                            setCtxMenu(null);
                            if (soloNode) runNodes([soloNode.id], true);
                          }}
                        >
                          <span>Run this node only</span>
                          <kbd>{soloOnlyCost}</kbd>
                        </button>
                      );
                    })()}
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
          <input
            ref={nodeRefInput}
            className="hidden"
            type="file"
            accept="image/*,video/*"
            data-testid="node-ref-file"
            onChange={(ev) => {
              const file = ev.target.files?.[0];
              ev.target.value = "";
              const id = nodeRefTarget.current;
              const role = nodeRefRole.current;
              nodeRefTarget.current = null;
              if (!file || !id) return;
              void ingest(file).then((asset) => {
                setGraph((g) => {
                  const row = g.nodes.find((n) => n.id === id);
                  if (!row || refsOf(row.params).length >= REF_LIMIT) return g;
                  return setParams(g, id, addRef(row.params, role, asset.id));
                });
              });
            }}
          />
        </main>
      </div>
    );
  } else if (page === "edit") {
    main = (
      <div className="explore">
        <h2>Edit</h2>
        <p className="muted">These tools start from a file you upload. Sharpen and resize live under Image.</p>
        <div className="grid">
          {editTools().map((tool) => (
            <button key={tool.id} className="card" type="button" onClick={() => openPage(tool.page)}>
              <div>
                <strong>{tool.title}</strong>
                <div className="muted">{tool.blurb}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    );
  } else if (page === "library") {
    main = (
      <LibraryPage
        items={libraryItems}
        tab={libTab}
        onTab={setLibTab}
        templates={templates}
        onCreate={(item) => {
          setCast((rows) => upsertLibraryItem(rows.map(asLibraryItem), item).map(asCastRow));
          setLog("Library @" + item.name);
        }}
        onOpenTemplate={(id) => {
          const template = templates.find((row) => row.id === id);
          if (template) openTemplate(template);
        }}
        onIngest={ingest}
      />
    );
  } else if (page === "assets") {
    main = (
      <AssetsPage
        elements={cast}
        focusId={focusAssetId}
        onOpenConnect={() => setPage("keys")}
        onRerun={(item) => void rerunFromLibrary(item)}
      />
    );
  } else if (page === "agent") {
    main = (
      <div className="lib-page">
        <h2>Supercomputer</h2>
        <p className="muted">Describe the job. Vinci turns it into steps you can run.</p>
        <label htmlFor="agent-brief">Brief</label>
        <textarea
          id="agent-brief"
          className="prompt"
          value={brief}
          onChange={(ev) => setBrief(ev.target.value)}
          placeholder="A watch on marble at dusk, then a slow turn."
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
          <p className="muted">Describe the job, then press Plan.</p>
        )}
        {log ? <p className="log">{log}</p> : null}
      </div>
    );
  } else if (page === "space") {
    main = (
      <div className="lib-page">
        <h2>3D</h2>
        <p className="muted">Turn the last still. Press the button when you want a new angle.</p>
        <div className="stage-3d">
          <div className="card3d" style={{ transform: `rotateY(${yaw}deg)` }}>
            {lastStill ? (
              <img src={`${API}/assets/${lastStill}/file`} alt="Last still" />
            ) : (
              <span className="muted">Make a still first. Open Image, then come back.</span>
            )}
          </div>
        </div>
        <div className="file-row">
          <button className="ghost" type="button" onClick={() => setYaw((y) => y - 25)}>
            Turn left
          </button>
          <button className="ghost" type="button" onClick={() => setYaw((y) => y + 25)}>
            Turn right
          </button>
          <button className="run" type="button" onClick={() => void generate3d()} disabled={busy}>
            Make a new angle
          </button>
        </div>
        {log ? <p className="log">{log}</p> : null}
      </div>
    );
  } else if (page === "collab") {
    main = (
      <div className="lib-page">
        <h2>Collab</h2>
        <p className="muted">Share a session on this computer. It keeps the board, the prompt, and the cast.</p>
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
        {collabId ? <p className="muted">This session is open.</p> : null}
        <div className="lib" style={{ marginTop: 16 }}>
          {sessions.map((s) => (
            <article key={s.id} className="collab-card">
              <strong>{s.name}</strong>
              <div className="file-row">
                <button className="ghost" type="button" onClick={() => void joinCollab(s.id)}>
                  Open
                </button>
                <button className="ghost" type="button" onClick={() => void pushCollab(s.id)}>
                  Update
                </button>
              </div>
            </article>
          ))}
        </div>
        {!sessions.length ? <p className="muted">No sessions yet. Name one and press New session.</p> : null}
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
        ? "Ready"
        : picked.configured
          ? "Key saved, paid runs off"
          : "Needs a key";
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
          Paste a provider key. Higgsfield, Magnific, and Freepik are built in. Keys stay on this computer in <code>~/.vinci/keys</code>.
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
            <optgroup label="Providers">
              {httpIds.map((id) => (
                <option key={id} value={id}>
                  {rows[id]?.display_name || id}
                </option>
              ))}
            </optgroup>
            <optgroup label="Other servers">
              {mcpExtra.map((id) => (
                <option key={id} value={id}>
                  {rows[id]?.display_name || id}
                </option>
              ))}
              {rows.mcp ? <option value="mcp">Custom server</option> : null}
              <option value="mcp_new">Another server</option>
            </optgroup>
          </select>
        </div>
        {connectId === "mock" ? (
          <div className="connect-sheet" id="connect-sheet">
            <span className="kind">Local</span>
            <strong>Local</strong>
            <p className="muted">On this computer. No key.</p>
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
            <span className="kind">Custom server</span>
            <strong>Another server</strong>
            <p className="muted">
              Add another server next to Custom server. It needs a short name, an address, and an optional sign-in address.
            </p>
            <label>Label</label>
            <input
              id="label-mcp_new"
              value={keyDraft["label-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "label-mcp_new": ev.target.value }))}
              placeholder="ComfyUI"
            />
            <label>Short name</label>
            <input
              id="slug-mcp_new"
              value={keyDraft["slug-mcp_new"] || ""}
              onChange={(ev) =>
                setKeyDraft((d) => ({ ...d, "slug-mcp_new": ev.target.value.replace(/[^a-z0-9_]/gi, "").toLowerCase() }))
              }
              placeholder="comfy"
            />
            <label>Server address</label>
            <input
              id="url-mcp_new"
              value={keyDraft["url-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "url-mcp_new": ev.target.value }))}
              placeholder="http://127.0.0.1:8765/mcp"
            />
            <label>Sign-in address (optional)</label>
            <input
              id="authurl-mcp_new"
              value={keyDraft["authurl-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "authurl-mcp_new": ev.target.value }))}
              placeholder="https://…/sign-in"
            />
            <label>Access token (optional)</label>
            <input
              id="key-mcp_new"
              type="password"
              autoComplete="off"
              value={keyDraft["key-mcp_new"] || ""}
              onChange={(ev) => setKeyDraft((d) => ({ ...d, "key-mcp_new": ev.target.value }))}
            />
            <button className="run" type="button" onClick={() => void addNamedMcp()}>
              Add server
            </button>
          </div>
        ) : picked ? (
          <div className="connect-sheet" id="connect-sheet">
            <span className="kind">{picked.kind === "mcp" ? "Custom server" : "Provider"}</span>
            <strong>{picked.display_name || connectId}</strong>
            <div className="muted">
              {pickedStatus}
            </div>
            {picked.docs ? (
              <p className="muted">
                <a href={picked.docs} target="_blank" rel="noreferrer">Provider docs</a>
              </p>
            ) : null}
            {mcpPicked ? (
              <>
                <label>Server address</label>
                <input
                  value={keyDraft[`url-${connectId}`] ?? picked.url ?? ""}
                  onChange={(ev) => setKeyDraft((d) => ({ ...d, [`url-${connectId}`]: ev.target.value }))}
                  placeholder="http://127.0.0.1:8765/mcp"
                  id={`url-${connectId}`}
                />
                <label>Sign-in address (optional)</label>
                <input
                  value={keyDraft[`authurl-${connectId}`] ?? picked.authorize_url ?? ""}
                  onChange={(ev) => setKeyDraft((d) => ({ ...d, [`authurl-${connectId}`]: ev.target.value }))}
                  placeholder="https://…/sign-in"
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
            <label>Or the name of an environment variable</label>
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
                  placeholder="Account id"
                />
              </>
            ) : null}
            {(picked.extra_secret_names || []).map((name) => (
              <div key={name}>
                <label>Paste the extra key</label>
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
                Sign in
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
                      .catch((err) => setLog(plainError(err)));
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
            <p className="muted">Pick a mark, or choose from the list. Providers take a key. A custom server takes an address.</p>
          </div>
        )}
        <div className="connect-routing">
          <p className="eyebrow">Model choice</p>
          <label>Prefer</label>
          <select value={pref} onChange={(ev) => setPref(ev.target.value)}>
            <option value="cheapest">Lowest price</option>
            <option value="fastest">Fastest</option>
            <option value="quality">Best quality</option>
          </select>
          <label>Max price per run (USD)</label>
          <input id="max-cost" value={maxCost} onChange={(ev) => setMaxCost(ev.target.value)} placeholder="No limit" />
          <label>Monthly limit (USD)</label>
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
                setLog("Model choice saved.");
              } catch (err) {
                setLog(plainError(err));
              }
            }}
          >
            Save model choice
          </button>
        </div>
      </div>
    );
  } else if (page === "settings") {
    main = (
      <div className="keys connect">
        <p className="eyebrow">Vinci</p>
        <h2>Settings</h2>
        <p className="muted lede">Preferences on this computer. Provider keys stay in Connect.</p>
        <OutputSettingsPanel
          outputDestKind={outputDestKind}
          setOutputDestKind={setOutputDestKind}
          outputLocalDir={outputLocalDir}
          setOutputLocalDir={setOutputLocalDir}
          outputPhotosAlbum={outputPhotosAlbum}
          setOutputPhotosAlbum={setOutputPhotosAlbum}
          outputR2Prefix={outputR2Prefix}
          setOutputR2Prefix={setOutputR2Prefix}
          outputR2Configured={outputR2Configured}
          onSave={async () => {
            try {
              await saveOutputDestination();
            } catch (err) {
              setLog(plainError(err));
            }
          }}
        />
        <button className="ghost" type="button" onClick={() => setPage("assets")}>
          View Assets
        </button>
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
        <label>Search</label>
        <input value={findQ} onChange={(ev) => setFindQ(ev.target.value)} />
        <button
          className="run"
          type="button"
          onClick={async () => {
            const body = await api<{ hits: { uri?: string; transcript?: string }[] }>("/find?q=" + encodeURIComponent(findQ));
            setFindHits(body.hits || []);
          }}
        >
          Search
        </button>
        {findHits.map((h, i) => (
          <div className="hit" key={i}>
            <div>{findHitUri(h.uri)}</div>
            <div className="muted">{(h.transcript || "").slice(0, 160)}</div>
          </div>
        ))}
      </div>
    );
  } else if (page === "cost") {
    main = (
      <div className="keys">
        <h2>Cost report</h2>
        <p className="muted">What you have spent, by provider.</p>
        <pre className="log">{costBody || "Loading…"}</pre>
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
    if (commandOpen || toolsOpen || avatarOpen) return;
    if (el?.closest("input, textarea, select, [contenteditable='true'], .node-pill")) return;
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

  useEffect(() => {
    if (!selectedNode) setInspectorOpen(false);
  }, [selectedNode]);

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
    try {
      setPinnedIds(parsePinned(localStorage.getItem(PIN_STORAGE_KEY)));
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(PROJECT_STORAGE_KEY);
      const file = raw ? readProjectFile(raw) : null;
      if (file) applyProject(file);
    } catch {
      /* ignore a blocked or corrupt project file */
    }
    setProjectReady(true);
  }, [applyProject]);

  useEffect(() => {
    if (!projectReady) return;
    try {
      localStorage.setItem(PROJECT_STORAGE_KEY, JSON.stringify(writeActive(project, graph, comments, viewport)));
    } catch {
      /* ignore */
    }
  }, [comments, graph, project, projectReady, viewport]);

  useEffect(() => {
    if (!navOpen) return;
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") setNavOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (isCommandHotkey(ev)) {
        ev.preventDefault();
        setCommandOpen((open) => !open);
        setCommandQuery("");
        setCommandIndex(0);
        setToolsOpen(false);
        setAvatarOpen(false);
        return;
      }
      if (ev.key === "Escape") {
        setCommandOpen(false);
        setToolsOpen(false);
        setAvatarOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      className={"shell" + (wantsInsp ? " with-insp" : "")}
      data-testid="vinci-studio-root"
    >
      {navOpen || toolsOpen || commandOpen || avatarOpen ? (
        <button
          type="button"
          className="rail-scrim"
          aria-label="Close menu"
          onClick={() => {
            setNavOpen(false);
            closeShellOverlays();
          }}
        />
      ) : null}
      <nav
        id="studio-rail"
        className={"rail" + (navOpen ? " open" : "")}
        aria-label="Studio"
        data-testid="studio-sidebar"
      >
        <VinciLogo />
        {RAIL_GROUPS.flatMap((group) => {
          const items = group.items.map((item) => {
            const on = railItemOn(item, page);
            const button = (
              <button
                key={item.id}
                type="button"
                className={on ? "on" : ""}
                title={item.title}
                aria-label={item.title}
                onClick={() => openPage(item.id)}
              >
                <RailIcon d={item.icon} title={item.title} />
                <span className="rail-label">{item.title}</span>
              </button>
            );
            if (!item.flyout) return button;
            const kind = item.flyout;
            return (
              <div className="rail-entry" key={item.id}>
                {button}
                <div className="rail-flyout">
                  <div>
                    <p className="rail-flyout-h">Features</p>
                    {FLYOUT_FEATURES[kind].map((row) => (
                      <button key={row.id} className="flyout-row" type="button" onClick={() => openPage(row.id)}>
                        <strong>{row.title}</strong>
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
                          <span>{row.provider || "Model"}</span>
                        </button>
                      ))
                    ) : (
                      <p className="rail-flyout-empty">No models yet. Open Connect to add a key.</p>
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
        {RAIL_FOOTER.map((item) => (
          <button
            key={item.id}
            type="button"
            className={(page === item.id ? "on rail-text" : "rail-text") + (item.id === "cost" ? " has-mini" : "")}
            title={item.title}
            aria-label={item.title}
            onClick={() => openPage(item.id)}
          >
            {item.id === "cost" ? <span className="rail-mini" aria-hidden="true">$</span> : null}
            <span className="rail-label">{item.title}</span>
          </button>
        ))}
        <div className="rail-avatar">
          <button
            type="button"
            className={avatarOpen || page === "keys" || page === "cost" ? "on" : ""}
            title="Account"
            aria-label="Account menu"
            aria-expanded={avatarOpen}
            onClick={() => {
              setAvatarOpen((open) => !open);
              setToolsOpen(false);
              setCommandOpen(false);
            }}
          >
            <span className="avatar-face" aria-hidden="true">
              {live.length ? (live[0][1].display_name || live[0][0]).slice(0, 1).toUpperCase() : "V"}
            </span>
            <span className="rail-label">{live.length ? live.map(([id, row]) => row.display_name || id).join(" · ") : "Local"}</span>
          </button>
          {avatarOpen ? (
            <div className="avatar-menu" role="menu">
              {AVATAR_MENU.map((item) => (
                <button key={item.id} type="button" role="menuitem" onClick={() => openPage(item.page)}>
                  {item.title}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </nav>
      {toolsOpen ? (
        <div className="all-tools" role="dialog" aria-label="All tools" data-testid="all-tools-popover">
          <input
            autoFocus
            value={toolsQuery}
            onChange={(ev) => setToolsQuery(ev.target.value)}
            placeholder="Search tools"
            aria-label="Search tools"
          />
          <div className="all-tools-tabs">
            {popoverTabs.map((tab) => (
              <button
                key={tab}
                type="button"
                className={toolsCategory === tab ? "on" : ""}
                onClick={() => setToolsCategory(tab)}
              >
                {tabLabel(tab)}
              </button>
            ))}
          </div>
          <div className="all-tools-list">
            {popoverTools.map((tool) => (
              <div key={tool.id} className="all-tools-row">
                <button type="button" className="all-tools-open" onClick={() => openPage(tool.page)}>
                  <strong>{tool.title}</strong>
                  <span>{tool.blurb}</span>
                </button>
                {tool.pinable ? (
                  <button
                    type="button"
                    className={pinnedIds.includes(tool.id) ? "pin on" : "pin"}
                    aria-label={pinnedIds.includes(tool.id) ? `Unpin ${tool.title}` : `Pin ${tool.title}`}
                    onClick={() => persistPins(togglePin(pinnedIds, tool.id))}
                  >
                    {pinnedIds.includes(tool.id) ? "Unpin" : "Pin"}
                  </button>
                ) : null}
              </div>
            ))}
            {popoverModels.length ? <p className="rail-flyout-h">Models</p> : null}
            {popoverModels.map((row) => (
              <div key={row.flyout + row.id} className="all-tools-row">
                <button
                  type="button"
                  className="all-tools-open"
                  onClick={() => {
                    const model = models.find((item) => item.id === row.id);
                    if (model) pickFlyoutModel(model, row.flyout);
                  }}
                >
                  <strong>{row.title}</strong>
                  <span>{row.blurb}</span>
                </button>
              </div>
            ))}
            {popoverTools.length === 0 && popoverModels.length === 0 ? <p className="muted">No tools match. Try another word.</p> : null}
          </div>
        </div>
      ) : null}
      {commandOpen ? (
        <div
          className="command-box"
          role="dialog"
          aria-label="Search"
          data-testid="command-box"
        >
          <input
            autoFocus
            value={commandQuery}
            placeholder="Search tools, assets, projects"
            aria-label="Search tools, assets, projects"
            onChange={(ev) => {
              setCommandQuery(ev.target.value);
              setCommandIndex(0);
            }}
            onKeyDown={(ev) => {
              if (ev.key === "ArrowDown") {
                ev.preventDefault();
                setCommandIndex((i) => moveCommandIndex(i, 1, commandHits.length));
              } else if (ev.key === "ArrowUp") {
                ev.preventDefault();
                setCommandIndex((i) => moveCommandIndex(i, -1, commandHits.length));
              } else if (ev.key === "Enter") {
                ev.preventDefault();
                const hit = pickCommandHit(commandHits, commandIndex);
                if (hit) openCommandHit(hit);
              }
            }}
          />
          <div className="command-list">
            {commandHits.map((hit, i) => (
              <button
                key={hit.kind + (hit.flyout || "") + hit.id}
                type="button"
                className={i === commandIndex ? "on" : ""}
                onMouseEnter={() => setCommandIndex(i)}
                onClick={() => openCommandHit(hit)}
              >
                <strong>{hit.title}</strong>
                <span>
                  {kindWord(hit.kind)} · {hit.blurb}
                </span>
              </button>
            ))}
            {commandHits.length === 0 ? <p className="muted">No matches. Try another word.</p> : null}
          </div>
        </div>
      ) : null}
      <section className="main">
        <div className="top">
          <div className="top-lead">
            <span className="top-logo">
              <VinciLogo variant="mark" />
            </span>
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
            <h1 className={page === "canvas" ? "sr-only" : ""}>
              {page === "speak" || page === "upscale" || page === "adapts"
                ? getApp(effectAppId)?.name || titles[page]
                : titles[page]}
            </h1>
            {page === "canvas" ? (
              <div className="space-switch" role="group" aria-label="Canvas view">
                <button type="button" className={view === "canvas" ? "on" : ""} onClick={() => setView("canvas")}>
                  Canvas
                </button>
                <button type="button" className={view === "timeline" ? "on" : ""} onClick={() => setView("timeline")}>
                  Timeline
                </button>
              </div>
            ) : null}
          </div>
          {page === "video" ? (
            <button
              className="icon-btn"
              type="button"
              aria-label="New"
              title="New"
              onClick={() => {
                setStageReset(true);
                setUploadId(null);
                setFirstFrameId(null);
                setLastFrameId(null);
                setExtendMode(false);
                setExtendClipId(null);
                setAudioId(null);
                setVideoExtraIds([]);
                setModelsOpen(false);
              }}
            >
              <DockIcon d={DOCK_ICON.add} />
            </button>
          ) : page === "speak" || page === "upscale" || page === "adapts" ? (
            <button
              className="icon-btn"
              type="button"
              aria-label="New"
              title="New"
              onClick={() => setEffectAppId(defaultAppIdForPage(page))}
            >
              <DockIcon d={DOCK_ICON.add} />
            </button>
          ) : page === "canvas" ? (
            <span />
          ) : (
            <span />
          )}
          <div className="top-meta">
            {page === "canvas" ? (
              <>
                <button
                  type="button"
                  className="access-pill"
                  aria-label="Local access"
                  aria-expanded={avatarOpen}
                  onClick={() => {
                    setAvatarOpen((open) => !open);
                    setCommandOpen(false);
                    setToolsOpen(false);
                  }}
                >
                  <span className="access-dot" aria-hidden="true" />
                  Local
                </button>
                <button
                  className="run canvas-generate"
                  type="button"
                  disabled={graph.nodes.length === 0 || !!runBlocker(graph.nodes.map((node) => node.id))}
                  title={runBlocker(graph.nodes.map((node) => node.id)) || "Runs this step and the steps that feed it."}
                  onClick={() => void generate({ graph: true })}
                >
                  Run
                </button>
              </>
            ) : (
              <span className="muted">≈ {money(spent)}</span>
            )}
            <button
              className="ghost"
              type="button"
              title="All tools"
              onClick={() => {
                setToolsOpen(true);
                setToolsQuery("");
                setToolsCategory("all");
                setCommandOpen(false);
                setAvatarOpen(false);
              }}
            >
              All tools
            </button>
          </div>
        </div>
        <div className="page">{main}</div>
      </section>
      {wantsInsp && page === "canvas" && canvasSelected ? (
        (() => {
          const n = canvasSelected;
          const modelRows = comboModels(nodeModels(n.capability || "t2i"), true, statusSuffix);
          const model = models.find((m) => m.id === (n.model_id || modelIdForNode(n, selected?.id || "", models, connected)));
          const aspects = listedOr(model?.constraints?.aspect_ratios, ASPECTS);
          const resolutions = listedOr(model?.constraints?.resolutions, RESOLUTIONS);
          const runText = runCost([n.id]).text;
          const runBlock = n.type === "generate" ? runBlocker([n.id]) : null;
          return (
            <CanvasInspector
              node={n}
              label={NODE_CATALOG.find((row) => row.capability === n.capability)?.label || n.capability || n.id}
              placeholder={defaultsFor(n.capability).placeholder}
              prompt={promptValue(n.params)}
              models={modelRows}
              modelId={n.model_id || ""}
              aspects={aspects}
              resolutions={resolutions}
              count={countValue(n.params)}
              aspect={pickListed(n.params?.aspect_ratio, aspects)}
              resolution={pickListed(n.params?.resolution, resolutions)}
              costText={runText}
              runDisabled={Boolean(runBlock) || busy}
              runTitle={runBlock || `Run · ${runText || "cost unknown"}`}
              assets={assets}
              apiBase={API}
              promptRef={settleOnUnmount}
              onPromptFocus={() => {
                promptBaseRef.current = graph;
              }}
              onPromptChange={(text) => {
                setGraphHistory((h) => preview(h, setParams(h.present, n.id, { prompt: text })));
              }}
              onPromptBlur={settlePrompt}
              onCount={(value) => setGraph((g) => setParams(g, n.id, countPatch(value)))}
              onAspect={(v) => setGraph((g) => setParams(g, n.id, { aspect_ratio: v }))}
              onResolution={(v) => setGraph((g) => setParams(g, n.id, { resolution: v }))}
              onModel={(value) => setGraph((g) => updateNode(g, n.id, { model_id: value || undefined }))}
              onSeed={(v) => {
                const seed = v.trim();
                setGraph((g) => setParams(g, n.id, { seed: seed === "" ? "" : Number(seed) || seed }));
              }}
              onShot={(patch) => setGraph((g) => setParams(g, n.id, patch))}
              onRun={() => runNodes([n.id])}
              onClose={() => setInspectorOpen(false)}
              library={mentionItems}
              onMention={(item) => applyLibraryMention(n.id, item)}
              onAddSlot={(role) => {
                if (refsOf(n.params).length >= REF_LIMIT) return;
                nodeRefTarget.current = n.id;
                nodeRefRole.current = role;
                nodeRefInput.current?.click();
              }}
              onRemoveRef={(assetId) => setGraph((g) => setParams(g, n.id, removeRef(g.nodes.find((row) => row.id === n.id)?.params, assetId)))}
            />
          );
        })()
      ) : null}
      {onboardOpen ? (
        <div id="onboard" data-onboard data-step={String(onboardStep)}>
          <div className="onboard-scrim" />
          <div className="onboard-card">
            <p className="eyebrow">Vinci</p>
            <p className="muted">{ONBOARD_STEPS[onboardStep].kicker}</p>
            <h2>{ONBOARD_STEPS[onboardStep].title}</h2>
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
