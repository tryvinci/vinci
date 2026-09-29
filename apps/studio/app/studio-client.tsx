"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";

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
type GraphNode = {
  id: string;
  type: string;
  capability?: string;
  model_id?: string;
  params?: Record<string, unknown>;
  x?: number;
  y?: number;
};
type GraphEdge = { src: string; dst: string; input_key?: string };
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

function wirePath(a: GraphNode, b: GraphNode): string {
  const x1 = (a.x || 0) + 196;
  const y1 = (a.y || 0) + 44;
  const x2 = b.x || 0;
  const y2 = (b.y || 0) + 44;
  return `M${x1} ${y1} C${x1 + 40} ${y1}, ${x2 - 40} ${y2}, ${x2} ${y2}`;
}

function modelIdForNode(node: GraphNode, fallbackId: string, catalog: Model[]): string {
  const cap = node.capability;
  for (const id of [node.model_id, fallbackId]) {
    if (!id) continue;
    const row = catalog.find((m) => m.id === id);
    if (row && (!cap || row.capabilities.includes(cap))) return id;
  }
  const mock = catalog.find((m) => m.provider === "mock" && (!cap || m.capabilities.includes(cap)));
  return mock?.id || fallbackId;
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
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({ nodes: [], edges: [] });
  const [graphEdited, setGraphEdited] = useState(false);
  const [skillRef, setSkillRef] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
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
  const [pref, setPref] = useState("cheapest");
  const [maxCost, setMaxCost] = useState("");
  const [monthlyCap, setMonthlyCap] = useState("");
  const [resolution, setResolution] = useState("");
  const [firstFrameId, setFirstFrameId] = useState<string | null>(null);
  const [lastFrameId, setLastFrameId] = useState<string | null>(null);
  const [cast, setCast] = useState<CastRow[]>([]);
  const [castName, setCastName] = useState("");
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const dragRef = useRef<{ id: string; dx: number; dy: number; x: number; y: number; moved: boolean } | null>(null);
  const linkFromRef = useRef<string | null>(null);
  const castFileRef = useRef<HTMLInputElement>(null);
  const composeStillRef = useRef<HTMLInputElement>(null);

  const composeModels = useMemo(() => {
    const list = models.filter((m) => {
      const caps = m.capabilities || [];
      if (page === "image") return caps.includes("t2i");
      if (page === "video") return caps.includes("t2v") || caps.includes("i2v");
      if (page === "upscale") return caps.includes("upscale") || caps.includes("i2i");
      if (page === "speak") return caps.includes("tts") || caps.includes("lipsync") || caps.includes("i2v");
      return caps.includes("t2i") || caps.includes("t2v") || caps.includes("i2i");
    });
    const rows = (list.length ? list : models).slice();
    rows.sort((a, b) => {
      if (a.provider === "mock" && b.provider !== "mock") return -1;
      if (b.provider === "mock" && a.provider !== "mock") return 1;
      if (page === "upscale") {
        const stillA = (a.capabilities || []).includes("i2i") ? 0 : 1;
        const stillB = (b.capabilities || []).includes("i2i") ? 0 : 1;
        if (stillA !== stillB) return stillA - stillB;
      }
      return (a.display_name || "").localeCompare(b.display_name || "");
    });
    return rows;
  }, [models, page]);

  useEffect(() => {
    if (!composeModels.length) return;
    const current = composeModels.find((m) => m.id === modelId);
    if (page === "upscale") {
      const still =
        composeModels.find((m) => m.provider === "mock" && (m.capabilities || []).includes("i2i")) ||
        composeModels.find((m) => (m.capabilities || []).includes("i2i"));
      if (still && (!current || !(current.capabilities || []).includes("i2i"))) {
        setModelId(still.id);
        return;
      }
    }
    if (current) return;
    const mock = composeModels.find((m) => m.provider === "mock") || composeModels[0];
    if (mock) setModelId(mock.id);
  }, [composeModels, modelId, page]);

  const selected =
    composeModels.find((m) => m.id === modelId) ||
    composeModels.find((m) => m.provider === "mock") ||
    composeModels[0];
  const opticalPage = ["image", "video", "speak", "canvas"].includes(page);
  const videoish = Boolean(
    selected?.capabilities?.includes("t2v") ||
      selected?.capabilities?.includes("i2v") ||
      page === "video" ||
      graph.nodes.some((n) => n.capability === "t2v" || n.capability === "i2v"),
  );

  const loadMedia = useCallback(async () => {
    const [runBody, assetBody] = await Promise.all([
      api<{ runs: Run[] }>("/runs"),
      api<{ assets: Asset[] }>("/assets"),
    ]);
    setRuns(runBody.runs || []);
    setAssets(assetBody.assets || []);
  }, []);

  const boot = useCallback(async () => {
    try {
      await api("/init", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ demo: true }),
      });
      const [doc, modelBody, skillBody, tplBody] = await Promise.all([
        api<Doctor>("/doctor"),
        api<{ models: Model[] }>("/models"),
        api<{ skills: Skill[] }>("/skills"),
        api<{ templates: Template[] }>("/templates"),
      ]);
      setDoctor(doc);
      setPref(doc.preference || "cheapest");
      setMonthlyCap(doc.budget?.monthly_cap_usd != null ? String(doc.budget.monthly_cap_usd) : "");
      setModels(modelBody.models || []);
      setSkills(skillBody.skills || []);
      setTemplates(tplBody.templates || []);
      const mock = (modelBody.models || []).find((m) => m.provider === "mock");
      setModelId((prev) => prev || mock?.id || modelBody.models?.[0]?.id || "");
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
      const drag = dragRef.current;
      if (!drag) return;
      if (!drag.moved && Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y) < 4) return;
      drag.moved = true;
      const x = Math.max(8, ev.clientX - drag.dx);
      const y = Math.max(8, ev.clientY - drag.dy);
      setGraph((g) => ({
        ...g,
        nodes: g.nodes.map((n) => (n.id === drag.id ? { ...n, x, y } : n)),
      }));
    }
    function up() {
      const drag = dragRef.current;
      if (drag && !drag.moved) setSelectedNode(drag.id);
      else if (drag) setGraphEdited(true);
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

  function skillFor(model?: Model): string {
    if (page === "upscale") return "@tryvinci/image-upscale";
    if (page === "speak") return "@tryvinci/still-to-talk";
    if (page === "video") return "@tryvinci/video-generate";
    if (page === "image") return "@tryvinci/image-generate";
    if (skillRef && !graphEdited) return skillRef;
    const caps = model?.capabilities || [];
    if (caps.includes("t2v") || caps.includes("i2v")) return "@tryvinci/video-generate";
    return "@tryvinci/image-generate";
  }

  function shotInputs(base: Record<string, unknown>) {
    const inputs = { ...base };
    if (aspectRatio) inputs.aspect_ratio = aspectRatio;
    if (duration && videoish) inputs.duration = Number(duration);
    if (resolution) inputs.resolution = resolution;
    if (scale && page === "upscale") inputs.scale = scale;
    if (camera) inputs.camera = camera;
    if (lens) inputs.lens = lens;
    if (look) inputs.look = look;
    if (lighting) inputs.lighting = lighting;
    if (palette) inputs.palette = palette;
    if (motion && videoish) inputs.motion = motion;
    if (aperture) inputs.aperture = aperture;
    if (genre) inputs.genre = genre;
    if (scene && (page === "speak" || scene !== "general")) inputs.scene = scene;
    if (page === "upscale") {
      inputs.creativity = creativity;
      inputs.resemblance = resemblance;
      inputs.hdr = hdr;
      inputs.fractality = fractality;
      inputs.optimized_for = optimizedFor;
      inputs.engine = engine;
    }
    if (firstFrameId) {
      inputs.first_frame_url = firstFrameId;
      inputs.start_image_url = firstFrameId;
      inputs.image = firstFrameId;
    }
    if (lastFrameId) {
      inputs.last_frame_url = lastFrameId;
      inputs.tail_image_url = lastFrameId;
    }
    if (uploadId) {
      inputs.media = uploadId;
      if (!inputs.image) inputs.image = uploadId;
    }
    if (page !== "upscale") {
      const urls: string[] = [];
      if (typeof inputs.image === "string" && inputs.image) urls.push(inputs.image);
      for (const row of cast) {
        if (row.assetId && !urls.includes(row.assetId)) urls.push(row.assetId);
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
    setGraph((g) => ({
      ...g,
      nodes: g.nodes.map((n) =>
        n.id !== selectedNode ? n : { ...n, params: { ...(n.params || {}), ...patch } },
      ),
    }));
    setGraphEdited(true);
  }

  async function ingest(file: File): Promise<Asset> {
    const data = new FormData();
    data.append("file", file);
    const res = await fetch(API + "/assets", { method: "POST", body: data });
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()) as Asset;
  }

  function nodeDigest(id: string): string | null {
    for (const run of [...projectRuns].reverse()) {
      const row = run.nodes?.[id];
      if (row?.output) return row.output;
      if (row?.outputs?.[0]) return row.outputs[0];
    }
    return null;
  }

  function withShotParams(nodes: GraphNode[]): GraphNode[] {
    return nodes.map((n) => {
      const params = { ...(n.params || {}) };
      if (!params.aspect_ratio) params.aspect_ratio = "{{inputs.aspect_ratio}}";
      if ((n.capability === "t2v" || n.capability === "i2v") && params.duration == null) {
        params.duration = "{{inputs.duration}}";
      }
      if (!params.camera) params.camera = "{{inputs.camera}}";
      if (!params.lens) params.lens = "{{inputs.lens}}";
      if (!params.look) params.look = "{{inputs.look}}";
      if (!params.aperture) params.aperture = "{{inputs.aperture}}";
      if (!params.genre) params.genre = "{{inputs.genre}}";
      if (!params.lighting) params.lighting = "{{inputs.lighting}}";
      if (!params.palette) params.palette = "{{inputs.palette}}";
      if ((n.capability === "t2v" || n.capability === "i2v") && !params.motion) {
        params.motion = "{{inputs.motion}}";
      }
      const { x, y, ...rest } = n;
      void x;
      void y;
      return { ...rest, params };
    });
  }

  async function generate(opts?: { nodeId?: string; graph?: boolean }) {
    if (busy) return;
    const model = selected;
    const text = prompt.trim() || "north-light oak cube, 50mm cinema still.";
    if (!model) {
      setLog("Studio is still loading models.");
      return;
    }
    if (model.provider !== "mock" && !usable(model)) {
      setPage("keys");
      setLog("Paste a key under Connect, or keep using local models.");
      return;
    }
    const skill = skillFor(model);
    const inputs = shotInputs({ prompt: text });
    if ((skill.includes("upscale") || page === "upscale") && !uploadId && !lastDigest) {
      setLog("Generate or drop a still first, then upscale.");
      return;
    }
    setBusy(true);
    setStageReset(false);
    setModelsOpen(false);
    setLog("Generating… " + (skillRef || skill));
    try {
      const payload: Record<string, unknown> = { inputs, preference: pref };
      const cap = Number(maxCost);
      if (maxCost !== "" && !Number.isNaN(cap)) payload.max_cost = cap;
      const generateNodes = graph.nodes.filter((n) => n.type === "generate");
      const skillNodes = (skills.find((s) => s.id === skill)?.workflow?.nodes || []).filter((n) => n.type === "generate");
      const onlyId = opts?.nodeId;
      if (onlyId) {
        const keep = new Set([onlyId]);
        let added = true;
        while (added) {
          added = false;
          for (const e of graph.edges) {
            if (keep.has(e.dst) && !keep.has(e.src)) {
              keep.add(e.src);
              added = true;
            }
          }
        }
        payload.workflow = {
          id: "canvas-node",
          version: "1.0.0",
          preference: pref,
          nodes: withShotParams(graph.nodes.filter((n) => keep.has(n.id))).map((n) =>
            n.id === onlyId ? { ...n, model_id: modelIdForNode(n, model.id, models) } : n,
          ),
          edges: graph.edges.filter((e) => keep.has(e.src) && keep.has(e.dst)),
        };
      } else if ((graphEdited || opts?.graph) && generateNodes.length) {
        payload.workflow = {
          id: "canvas",
          version: "1.0.0",
          preference: pref,
          nodes: withShotParams(graph.nodes),
          edges: graph.edges,
        };
      } else {
        payload.skill = skill;
        if (skillNodes.length <= 1) payload.model_id = model.id;
      }
      const body = await api<Run>("/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      setRunIds((ids) => [...ids, body.id]);
      await loadMedia();
      const digest = body.outputs?.[0];
      setLog(
        body.state === "completed"
          ? "Shot landed on the canvas." + (digest ? " vinci://assets/" + digest : "")
          : JSON.stringify(body.error || body),
      );
    } catch (err) {
      setLog(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
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
    setGraph(
      skill
        ? graphFromSkill(skill, nextCamera, nextLens, nextLook, nextMotion, nextAperture, nextGenre, nextLighting, nextPalette)
        : { nodes: [], edges: [] },
    );
    setGraphEdited(false);
    setSelectedNode(null);
    if (nextPage === "canvas") setView("canvas");
    setPage(nextPage);
  }

  function addNode(capability: string) {
    const id = capability + "-" + Math.random().toString(16).slice(2, 6);
    const n: GraphNode = {
      id,
      type: "generate",
      capability,
      params: {
        prompt: "{{inputs.prompt}}",
        aspect_ratio: "{{inputs.aspect_ratio}}",
        camera,
        lens,
        look,
        lighting,
        palette,
        aperture,
        genre,
      },
      x: 60 + (graph.nodes.length % 3) * 210,
      y: 80,
    };
    if (capability === "i2i" || capability === "i2v") {
      n.params = { ...n.params, media: "{{inputs.media}}" };
    }
    if (capability === "t2v" || capability === "i2v") {
      n.params = { ...n.params, duration: "{{inputs.duration}}", motion };
    }
    if (capability === "i2v") {
      n.params = { ...n.params, image: "{{inputs.image}}" };
    }
    const prev = graph.nodes.at(-1);
    const edges = prev
      ? [...graph.edges, { src: prev.id, dst: id, input_key: capability === "i2v" ? "image" : "media" }]
      : graph.edges;
    setGraph({ nodes: [...graph.nodes, n], edges });
    setGraphEdited(true);
    setSkillRef(null);
    setView("canvas");
    setPage("canvas");
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
      if (body.authorize_url) window.open(body.authorize_url, "_blank", "noopener,noreferrer");
      setLog(body.hint || (body.mode === "key" ? "This connector uses a pasted API key." : "Paste a token."));
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
      if (snap.graph) setGraph(snap.graph);
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
  const rail: { id: PageId; title: string; d: string }[] = [
    { id: "explore", title: "Explore", d: "M9 2a7 7 0 1 1 0 14A7 7 0 0 1 9 2zm0 2v5l3 2" },
    { id: "image", title: "Image", d: "M3 4h12v10H3zM3 12l3-3 2 2 2-2 4 4" },
    { id: "video", title: "Video", d: "M2.5 5h9v8h-9zM11.5 8l4-2v6l-4-2z" },
    { id: "speak", title: "Speak", d: "M4 8v2c0 2.8 2.2 5 5 5s5-2.2 5-5V8M7 3h4v8H7z" },
    { id: "upscale", title: "Upscale still", d: "M3 7h6v6H3zM8 3h7v7H8z" },
    { id: "canvas", title: "Canvas", d: "M3 4h5v4H3zM10 10h5v4h-5zM8 6h3v4" },
    { id: "library", title: "Library", d: "M3 4h4v11H3zM8 4h3v11H8zM12.5 4.5L15 15" },
    { id: "agent", title: "Supercomputer", d: "M4 5h10v8H4zM7 14h4M6 3v2M12 3v2" },
    { id: "space", title: "3D", d: "M9 2l7 4v8l-7 4-7-4V6zM9 10V18M2 6l7 4 7-4" },
    { id: "collab", title: "Collab", d: "M6 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zm6 0a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM3 16c0-2 2-3.5 3.5-3.5S10 14 10 16M8 16c0-2 2-3.5 4-3.5s4 1.5 4 3.5" },
  ];

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
        copy: "Talking photo from an image and a spoken line.",
        primary: "Upload a still",
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
                    if (page === "upscale" || page === "speak") composeStillRef.current?.click();
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
          <div className="compose-gallery">
            {composeModels.map((m) => (
              <button
                key={m.id}
                className={"model-card" + (m.id === selected?.id ? " on" : "")}
                type="button"
                onClick={() => setModelId(m.id)}
              >
                <span className="who">{m.provider === "magnific" ? "Magnific / Freepik" : m.provider === "mock" ? "Local" : m.provider}</span>
                <strong>{m.display_name}</strong>
                <span className="meta">
                  {usable(m) || m.provider === "mock" ? money(m.pricing?.amount) : "needs key"} · {(m.capabilities || []).slice(0, 3).join(" · ")}
                </span>
              </button>
            ))}
          </div>
        </details>
      </div>
    );
  } else if (page === "canvas") {
    const selectedRow = graph.nodes.find((n) => n.id === selectedNode);
    main = (
      <div className="stage">
        <main className="board">
          {graph.nodes.length === 0 && view === "canvas" ? (
            <div className="empty">
              <div>
                <h2>Empty canvas.</h2>
                <p>Open a template, or add image / video / upscale nodes.</p>
              </div>
            </div>
          ) : null}
          {view === "canvas" ? (
            <div className="graph">
              <svg className="wires" aria-hidden="true">
                {graph.edges.map((e) => {
                  const a = graph.nodes.find((n) => n.id === e.src);
                  const b = graph.nodes.find((n) => n.id === e.dst);
                  if (!a || !b) return null;
                  return (
                    <path
                      key={e.src + "->" + e.dst}
                      d={wirePath(a, b)}
                      fill="none"
                      stroke="#3f3f46"
                      strokeWidth="1.4"
                    />
                  );
                })}
              </svg>
              {graph.nodes.map((n) => {
                const digest = nodeDigest(n.id);
                const cap = n.capability || n.type;
                const asset = assets.find((a) => a.id === digest);
                const stack = opticalLabel(n, camera, lens, look, motion, aperture, genre, lighting, palette);
                return (
                  <div
                    key={n.id}
                    data-id={n.id}
                    className={"node" + (selectedNode === n.id ? " on" : "")}
                    style={{ left: n.x || 40, top: n.y || 40 }}
                    onPointerDown={(ev) => {
                      if ((ev.target as HTMLElement).classList.contains("port")) return;
                      dragRef.current = {
                        id: n.id,
                        dx: ev.clientX - (n.x || 40),
                        dy: ev.clientY - (n.y || 40),
                        x: ev.clientX,
                        y: ev.clientY,
                        moved: false,
                      };
                    }}
                  >
                    <div
                      className="port in"
                      data-port="in"
                      data-id={n.id}
                      onPointerDown={(ev) => ev.stopPropagation()}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        const from = linkFromRef.current;
                        if (!from || from === n.id) return;
                        setGraph((g) => {
                          if (g.edges.some((edge) => edge.src === from && edge.dst === n.id)) return g;
                          return { ...g, edges: [...g.edges, { src: from, dst: n.id, input_key: "media" }] };
                        });
                        setGraphEdited(true);
                        linkFromRef.current = null;
                        setLinkFrom(null);
                      }}
                    />
                    <div
                      className={"port out" + (linkFrom === n.id ? " on" : "")}
                      data-port="out"
                      data-id={n.id}
                      onPointerDown={(ev) => ev.stopPropagation()}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        linkFromRef.current = n.id;
                        setLinkFrom(n.id);
                        setLog("Click an input port to connect.");
                      }}
                    />
                    <div className="thumb">
                      {digest && asset?.mime?.startsWith("video/") ? (
                        <video src={`${API}/assets/${digest}/file`} muted />
                      ) : digest ? (
                        <img alt="" src={`${API}/assets/${digest}/file`} />
                      ) : null}
                    </div>
                    <div className="meta">
                      <div className="k">{cap}{stack ? " · " + stack : ""}</div>
                      <strong>{n.id}</strong>
                    </div>
                  </div>
                );
              })}
              <div className={"results" + (view === "canvas" ? "" : " hidden")} id="results">
                {graph.nodes.map((n) => {
                  const digest = nodeDigest(n.id);
                  if (!digest) return null;
                  const asset = assets.find((a) => a.id === digest);
                  return (
                    <button key={n.id} className="shot" type="button" onClick={() => setSelectedNode(n.id)}>
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
          <div className="canvas-tools">
            <button className="ghost" type="button" onClick={() => void generate({ graph: true })}>
              Generate graph
            </button>
            <button className="ghost" type="button" id="tl-play" onClick={() => void playTimeline()}>
              Play timeline
            </button>
          </div>
          {selectedRow ? (
            <aside className="drawer">
              <h3>{selectedRow.id}</h3>
              <p className="muted">{opticalLabel(selectedRow, camera, lens, look, motion, aperture, genre, lighting, palette) || "Set camera, lens, and look in the stack."}</p>
              {nodeDigest(selectedRow.id) ? (
                <img alt="" src={`${API}/assets/${nodeDigest(selectedRow.id)}/file`} />
              ) : (
                <p className="muted">No output on this node yet.</p>
              )}
              <label htmlFor="node-model">Node model</label>
              <select
                id="node-model"
                value={selectedRow.model_id || ""}
                onChange={(ev) => {
                  const value = ev.target.value;
                  setGraph((g) => ({
                    ...g,
                    nodes: g.nodes.map((n) => (n.id === selectedRow.id ? { ...n, model_id: value || undefined } : n)),
                  }));
                  setGraphEdited(true);
                }}
              >
                <option value="">inherit skill default</option>
                {models
                  .filter((m) => (m.capabilities || []).includes(selectedRow.capability || "t2i"))
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.display_name} · {m.provider}
                    </option>
                  ))}
              </select>
              <div className="file-row" style={{ marginTop: 10 }}>
                <button className="run" type="button" onClick={() => void generate({ nodeId: selectedRow.id })}>
                  Generate this node
                </button>
                <button className="ghost" type="button" onClick={() => setSelectedNode(null)}>
                  Close
                </button>
              </div>
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
                Start OAuth
              </button>
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
            setGraph(graphFromSkill(s, camera, lens, look, motion, aperture, genre, lighting, palette));
            setGraphEdited(false);
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

  return (
    <div className={"shell" + (wantsInsp ? " with-insp" : "")}>
      <nav className="rail" aria-label="Studio">
        <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="#34c6c0" />
          <path d="M9 7h5l2 11 2-11h5L18 25h-4L9 7z" fill="#06262a" />
        </svg>
        {rail.map((item) => (
          <button
            key={item.id}
            type="button"
            className={page === item.id ? "on" : ""}
            title={item.title}
            aria-label={item.title}
            onClick={() => setPage(item.id)}
          >
            <RailIcon d={item.d} title={item.title} />
          </button>
        ))}
        <span className="spacer" />
        <button type="button" className={page === "skills" ? "on" : ""} title="Skills" onClick={() => setPage("skills")}>
          Skills
        </button>
        <button type="button" className={page === "find" ? "on" : ""} title="Find" onClick={() => setPage("find")}>
          Find
        </button>
        <button type="button" className={page === "cost" ? "on" : ""} title="Cost report" onClick={() => setPage("cost")}>
          $
        </button>
        <button type="button" className={page === "keys" ? "on" : ""} title="Connect" onClick={() => setPage("keys")}>
          Connect
        </button>
      </nav>
      <section className="main">
        <div className="top">
          <h1>{titles[page]}</h1>
          {page === "image" || page === "video" || page === "upscale" || page === "speak" ? (
            <button
              className="ghost"
              type="button"
              onClick={() => {
                setStageReset(true);
                setUploadId(null);
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
              {live.length ? live.map(([id, row]) => row.display_name || id).join(" · ") : "Local"}
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
            <p className="muted">Pick a template or describe a shot. Price sits on Generate.</p>
          </div>
          <div className="fields">
            <div>
              <label htmlFor="model">Model</label>
              <select id="model" value={selected?.id || ""} onChange={(ev) => setModelId(ev.target.value)}>
                {composeModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name} · {m.provider === "mock" ? "Local" : m.provider} · {money(m.pricing?.amount)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="prompt">Prompt</label>
              <textarea
                id="prompt"
                placeholder="north-light oak cube, 50mm cinema still."
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
            {videoish ? (
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
            {page !== "upscale" && videoish && durs.length ? (
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
            {page === "upscale" ? (
              <div>
                <label>Scale</label>
                <Pills id="scale-pills" values={["2x", "4x", "8x", "16x"]} current={scale} onPick={setScale} />
              </div>
            ) : null}
            {page === "speak" ? (
              <div id="scene-field">
                <label>Speak scene</label>
                <Pills id="scene-pills" values={SCENES} current={scene} onPick={setScene} />
              </div>
            ) : null}
            {page === "upscale" ? (
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
            <div>
              <label>Still or clip</label>
              <input
                id="insp-still"
                type="file"
                accept="image/*,video/*,audio/*"
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
            </div>
            {page !== "upscale" && (wantsFrames(selected) || videoish) ? (
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
            {["image", "video", "speak", "canvas"].includes(page) ? (
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
              <button className="ghost" type="button" onClick={() => addNode("t2v")}>+ Video node</button>
              <button className="ghost" type="button" onClick={() => addNode("i2i")}>+ Upscale node</button>
              <button className="ghost" id="add-shot" type="button" onClick={() => addShot()}>+ Shot</button>
            </div>
            <p className="log">{log}</p>
          </div>
          <div className="foot">
            <button className="run" type="button" disabled={busy || !selected} onClick={() => void generate()}>
              <span>{busy ? "Generating…" : "Generate"}</span>
              <span>{money(selected?.pricing?.amount)}</span>
            </button>
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
