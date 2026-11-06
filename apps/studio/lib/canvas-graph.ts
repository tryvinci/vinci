/**
 * Studio canvas graph model.
 *
 * Pure functions over `{ nodes, edges }`. No React, DOM, or imports: tests load
 * this file on its own (tests/test_canvas_graph.py).
 *
 * Data contract with the runtime: the engine ignores `GraphEdge.input_key` and
 * only orders nodes by edges. Data moves through params templates, so a wire
 * from `a` into port `media` of `b` must set `b.params.media` to
 * `{{nodes.a.output}}` (see vinci_runtime.engine, `interpolate(node.params, context)`).
 */

/** Magnific port kinds. Text is a first-class wire, same as image / video / audio. */
export type MediaKind = "text" | "image" | "video" | "audio";
export type GraphNode = {
  id: string;
  type: string;
  capability?: string;
  model_id?: string;
  params?: Record<string, unknown>;
  x?: number;
  y?: number;
  /** Set when this card is a linked copy of another node. Canvas-only; stripped before /runs. */
  instanceOf?: string;
};
/** How a wire is drawn. `rounded` is the default orthogonal wire and is omitted on the edge. */
export type EdgeStyle = "rounded" | "curve" | "straight";
export const EDGE_STYLES: { id: EdgeStyle; label: string }[] = [
  { id: "rounded", label: "Rounded" },
  { id: "curve", label: "Curve" },
  { id: "straight", label: "Straight" },
];
export type GraphEdge = { src: string; dst: string; input_key?: string; style?: EdgeStyle };
/** A canvas-only frame around nodes. Never sent to the runtime. */
export const GROUP_COLORS = ["teal", "amber", "violet", "slate"] as const;
export type GroupColor = (typeof GROUP_COLORS)[number];
export type GraphGroup = { id: string; name: string; color: GroupColor; nodeIds: string[] };
export type Graph = { nodes: GraphNode[]; edges: GraphEdge[]; groups?: GraphGroup[] };
export type InPort = { key: string; kind: MediaKind };
export type NodePorts = { inputs: InPort[]; output: MediaKind | null };
export type GraphResult = { ok: true; graph: Graph } | { ok: false; error: string };

export const EMPTY_GRAPH: Graph = { nodes: [], edges: [] };

/** Typed ports per capability. Keys are the param names providers read. */
const PORTS: Record<string, NodePorts> = {
  t2i: { inputs: [{ key: "prompt", kind: "text" }], output: "image" },
  i2i: {
    inputs: [
      { key: "media", kind: "image" },
      { key: "prompt", kind: "text" },
    ],
    output: "image",
  },
  upscale: { inputs: [{ key: "media", kind: "image" }], output: "image" },
  t2v: { inputs: [{ key: "prompt", kind: "text" }], output: "video" },
  i2v: {
    inputs: [
      { key: "image", kind: "image" },
      { key: "prompt", kind: "text" },
    ],
    output: "video",
  },
  tts: { inputs: [{ key: "prompt", kind: "text" }], output: "audio" },
  voice_clone: { inputs: [{ key: "reference", kind: "audio" }], output: "audio" },
  lipsync: {
    inputs: [
      { key: "video", kind: "video" },
      { key: "audio", kind: "audio" },
    ],
    output: "video",
  },
  reframe: { inputs: [{ key: "media", kind: "video" }], output: "video" },
  caption: { inputs: [{ key: "media", kind: "video" }], output: "video" },
  media: { inputs: [], output: "image" },
  text: { inputs: [], output: "text" },
  list: { inputs: [], output: "text" },
  assistant: { inputs: [{ key: "prompt", kind: "text" }], output: "text" },
  note: { inputs: [], output: null },
};
const NO_PORTS: NodePorts = { inputs: [], output: null };

/** Image / video / audio / text from an upload mime or an explicit kind. */
export function kindFromMime(value: unknown): MediaKind {
  const s = String(value || "").toLowerCase();
  if (s.includes("video")) return "video";
  if (s.includes("audio")) return "audio";
  if (s === "text" || s.includes("text/") || s.includes("json")) return "text";
  return "image";
}

/** Ports for a node. Unknown capabilities get none, so they cannot be wired by hand. */
export function portsFor(node: GraphNode | undefined): NodePorts {
  if (!node) return NO_PORTS;
  const cap = node.capability || "";
  if (cap === "media") return { inputs: [], output: kindFromMime(node.params?.kind || node.params?.mime) };
  return PORTS[cap] || NO_PORTS;
}

/** What a capability produces, or null when it has no declared ports. */
export function outputOf(capability: string): MediaKind | null {
  return PORTS[capability]?.output || null;
}

/** Magnific add-popover chips. 3D / Library stay empty until those surfaces exist. */
export const ADD_CHIPS = [
  { id: "image", label: "Image" },
  { id: "video", label: "Video" },
  { id: "audio", label: "Audio" },
  { id: "3d", label: "3D" },
  { id: "utilities", label: "Utilities" },
  { id: "flows", label: "Flows" },
  { id: "templates", label: "Templates" },
  { id: "library", label: "Library" },
] as const;
export type AddChipId = (typeof ADD_CHIPS)[number]["id"];
export type AddSectionId = "media" | "nodes" | "providers" | "flows";
export type CatalogNodeType = "generate" | "media" | "transform";

/** Nodes the add menu offers, in Magnific section order. */
export type CatalogEntry = {
  capability: string;
  label: string;
  blurb: string;
  section: AddSectionId;
  chips: AddChipId[];
  nodeType: CatalogNodeType;
};
export const NODE_CATALOG: CatalogEntry[] = [
  { capability: "media", label: "Media", blurb: "Upload an image, video, or audio file", section: "media", chips: ["image", "video", "audio", "utilities"], nodeType: "media" },
  { capability: "t2i", label: "Image Gen", blurb: "Generate an image from a prompt", section: "nodes", chips: ["image"], nodeType: "generate" },
  { capability: "t2v", label: "Video Gen", blurb: "Generate a video from a prompt", section: "nodes", chips: ["video"], nodeType: "generate" },
  { capability: "upscale", label: "Upscaler", blurb: "Enlarge and sharpen an image", section: "nodes", chips: ["image"], nodeType: "generate" },
  { capability: "i2i", label: "Image Editor", blurb: "Restyle or edit an image with a prompt", section: "nodes", chips: ["image"], nodeType: "generate" },
  { capability: "tts", label: "Voiceover", blurb: "Speak a prompt as audio", section: "nodes", chips: ["audio"], nodeType: "generate" },
  { capability: "i2v", label: "Animate image", blurb: "Turn a still into a clip", section: "nodes", chips: ["image", "video"], nodeType: "generate" },
  { capability: "lipsync", label: "Lip sync", blurb: "Sync a video to an audio track", section: "nodes", chips: ["video", "audio"], nodeType: "generate" },
  { capability: "text", label: "Text", blurb: "A text block you can wire into prompts", section: "nodes", chips: ["utilities"], nodeType: "transform" },
  { capability: "list", label: "List", blurb: "A list of lines you can wire into prompts", section: "nodes", chips: ["utilities"], nodeType: "transform" },
  { capability: "assistant", label: "Assistant", blurb: "An LLM that writes text", section: "nodes", chips: ["utilities"], nodeType: "transform" },
  { capability: "note", label: "Note", blurb: "A note on the board", section: "nodes", chips: ["utilities"], nodeType: "transform" },
];

export function nodeTypeOf(capability: string): CatalogNodeType {
  return NODE_CATALOG.find((row) => row.capability === capability)?.nodeType || "generate";
}

function catalogScore(label: string, capability: string, blurb: string, query: string): number {
  const q = query.trim().toLowerCase();
  if (!q) return 0;
  const name = label.toLowerCase();
  if (name.startsWith(q)) return 0;
  if (name.split(/\s+/).some((w) => w.startsWith(q))) return 1;
  return `${name} ${capability} ${blurb.toLowerCase()}`.includes(q) ? 2 : -1;
}

/**
 * Add-menu node rows matching `query`, best first. With `takes`, only nodes with an input of that kind
 * (the add-from-port case). Label prefix beats a word prefix beats a substring anywhere.
 */
export function searchCatalog(query: string, takes?: MediaKind | null, chip?: AddChipId | null): CatalogEntry[] {
  const rows = NODE_CATALOG.filter((e) => {
    if (takes && !(PORTS[e.capability]?.inputs || []).some((p) => p.kind === takes)) return false;
    if (chip && !e.chips.includes(chip)) return false;
    return true;
  });
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows
    .map((e, i) => ({ e, i, s: catalogScore(e.label, e.capability, e.blurb, q) }))
    .filter((r) => r.s >= 0)
    .sort((a, b) => a.s - b.s || a.i - b.i)
    .map((r) => r.e);
}

export type AddModel = { id: string; display_name: string; provider: string; capabilities: string[] };
export type AddTemplate = { id: string; title: string; blurb: string };
export type AddPick =
  | { kind: "node"; capability: string }
  | { kind: "model"; capability: string; modelId: string }
  | { kind: "flow"; templateId: string };
export type AddMenuRow = {
  id: string;
  pick: AddPick;
  section: AddSectionId;
  vendor?: string;
  vendorCount?: number;
  label: string;
  blurb: string;
  output: MediaKind | null;
};
export type AddMenuSection = { id: AddSectionId; label: string; rows: AddMenuRow[] };

const SECTION_LABEL: Record<AddSectionId, string> = {
  media: "Media",
  nodes: "Nodes",
  providers: "Models",
  flows: "Flows",
};

const MODEL_CHIPS: Record<Exclude<AddChipId, "3d" | "utilities" | "flows" | "templates" | "library">, string[]> = {
  image: ["t2i", "i2i", "upscale"],
  video: ["t2v", "i2v", "lipsync"],
  audio: ["tts", "voice_clone"],
};

/** First generate capability on a model that can take `takes` (click-output-to-add). */
export function capabilityForModel(capabilities: string[], takes?: MediaKind | null): string | null {
  for (const row of NODE_CATALOG) {
    if (row.nodeType !== "generate" || !capabilities.includes(row.capability)) continue;
    if (takes && !(PORTS[row.capability]?.inputs || []).some((p) => p.kind === takes)) continue;
    return row.capability;
  }
  return null;
}

function modelMatchesChip(model: AddModel, chip?: AddChipId | null): boolean {
  if (!chip) return true;
  if (chip === "3d" || chip === "utilities" || chip === "flows" || chip === "templates" || chip === "library") return false;
  return (model.capabilities || []).some((cap) => MODEL_CHIPS[chip].includes(cap));
}

/**
 * Magnific add popover: Media / Nodes / Models (grouped by vendor, with counts) / Flows.
 * `takes` is the click-output filter. Flows stay out of that list — only compatible nodes and models.
 */
export function buildAddMenu(
  query: string,
  opts?: { chip?: AddChipId | null; takes?: MediaKind | null; models?: AddModel[]; templates?: AddTemplate[] },
): AddMenuSection[] {
  const chip = opts?.chip || null;
  const takes = opts?.takes || null;
  const q = query.trim().toLowerCase();
  const sections: AddMenuSection[] = [];

  const nodes = searchCatalog(query, takes, chip === "flows" || chip === "templates" || chip === "library" || chip === "3d" ? null : chip);
  const media = nodes.filter((row) => row.section === "media");
  const rest = nodes.filter((row) => row.section === "nodes");
  if (chip !== "flows" && chip !== "templates" && chip !== "library" && chip !== "3d") {
    if (media.length) {
      sections.push({
        id: "media",
        label: SECTION_LABEL.media,
        rows: media.map((row) => ({
          id: "node:" + row.capability,
          pick: { kind: "node", capability: row.capability },
          section: "media",
          label: row.label,
          blurb: row.blurb,
          output: outputOf(row.capability),
        })),
      });
    }
    if (rest.length) {
      sections.push({
        id: "nodes",
        label: SECTION_LABEL.nodes,
        rows: rest.map((row) => ({
          id: "node:" + row.capability,
          pick: { kind: "node", capability: row.capability },
          section: "nodes",
          label: row.label,
          blurb: row.blurb,
          output: outputOf(row.capability),
        })),
      });
    }
  }

  if (chip !== "utilities" && chip !== "3d" && chip !== "library" && chip !== "flows" && chip !== "templates") {
    const models = (opts?.models || []).filter((m) => {
      if (!modelMatchesChip(m, chip)) return false;
      const cap = capabilityForModel(m.capabilities || [], takes);
      if (!cap) return false;
      if (!q) return true;
      return catalogScore(m.display_name || m.id, m.id, m.provider, q) >= 0;
    });
    const grouped = new Map<string, AddModel[]>();
    for (const model of models) {
      const vendor = model.provider || "other";
      const list = grouped.get(vendor) || [];
      list.push(model);
      grouped.set(vendor, list);
    }
    const rows: AddMenuRow[] = [];
    for (const [vendor, list] of grouped) {
      for (const model of list) {
        const cap = capabilityForModel(model.capabilities || [], takes);
        if (!cap) continue;
        rows.push({
          id: "model:" + model.id,
          pick: { kind: "model", capability: cap, modelId: model.id },
          section: "providers",
          vendor,
          vendorCount: list.length,
          label: model.display_name || model.id,
          blurb: vendor,
          output: outputOf(cap),
        });
      }
    }
    if (rows.length) sections.push({ id: "providers", label: SECTION_LABEL.providers, rows });
  }

  if (!takes && (chip === "flows" || chip === "templates" || !chip)) {
    const templates = (opts?.templates || []).filter((t) => {
      if (!q) return true;
      return catalogScore(t.title, t.id, t.blurb, q) >= 0;
    });
    if (templates.length) {
      sections.push({
        id: "flows",
        label: SECTION_LABEL.flows,
        rows: templates.map((t) => ({
          id: "flow:" + t.id,
          pick: { kind: "flow", templateId: t.id },
          section: "flows",
          label: t.title,
          blurb: t.blurb,
          output: null,
        })),
      });
    }
  }

  return sections;
}

export function flattenAddMenu(sections: AddMenuSection[]): AddMenuRow[] {
  return sections.flatMap((section) => section.rows);
}

/** Unwired inputs read page inputs, e.g. `{ media: "{{inputs.media}}" }` for an upscale. */
export function inputDefaults(capability: string): Record<string, string> {
  return Object.fromEntries((PORTS[capability]?.inputs || []).map((p) => [p.key, inputRef(p.key)]));
}

/** Per-capability defaults for new nodes. `prompt` says whether the node needs its own text. */
export type NodeDefaults = {
  prompt: "required" | "optional" | "none";
  placeholder?: string;
  aspect_ratio?: string;
  duration?: number;
  resolution?: string;
  count?: number;
};
export const NODE_DEFAULTS: Record<string, NodeDefaults> = {
  t2i: { prompt: "required", placeholder: "Describe the image you want", aspect_ratio: "16:9", resolution: "1K", count: 1 },
  i2i: { prompt: "required", placeholder: "Describe the change to make", resolution: "1K", count: 1 },
  upscale: { prompt: "none" },
  t2v: { prompt: "required", placeholder: "Describe the shot and its motion", aspect_ratio: "16:9", duration: 5, count: 1 },
  i2v: { prompt: "optional", placeholder: "Describe how the still should move", duration: 5, count: 1 },
  lipsync: { prompt: "none" },
  tts: { prompt: "required", placeholder: "What should the voice say?" },
  media: { prompt: "none" },
  text: { prompt: "required", placeholder: "Write the text" },
  list: { prompt: "optional", placeholder: "One item per line" },
  assistant: { prompt: "optional", placeholder: "Ask the assistant" },
  note: { prompt: "optional", placeholder: "A note on the board" },
};
const PROMPT_ONLY: NodeDefaults = { prompt: "optional" };

export function defaultsFor(capability?: string): NodeDefaults {
  return NODE_DEFAULTS[capability || ""] || PROMPT_ONLY;
}

/**
 * Params a new node starts with: its own prompt (seeded from the page), aspect and duration
 * from the page or the capability default, and unwired inputs reading page inputs.
 */
export function startParams(
  capability: string,
  page: { prompt?: string; aspect_ratio?: string; duration?: string | number; resolution?: string },
): Record<string, unknown> {
  const d = defaultsFor(capability);
  const out: Record<string, unknown> = { ...inputDefaults(capability) };
  if (d.prompt !== "none") out.prompt = (page.prompt || "").trim();
  if (d.aspect_ratio) out.aspect_ratio = page.aspect_ratio || d.aspect_ratio;
  if (d.duration != null) out.duration = Number(page.duration) || d.duration;
  if (d.resolution) out.resolution = page.resolution || d.resolution;
  if (d.count != null) {
    out.count = d.count;
    out.num_images = d.count;
  }
  return out;
}

/**
 * Why `node` cannot run yet, or null when it can. `page` lists page inputs that have a value
 * (an unwired input reading `{{inputs.media}}` is fine when the page has an uploaded still).
 */
export function blockedReason(node: GraphNode, page: Record<string, boolean>): string | null {
  const params = node.params || {};
  const filled = (key: string): boolean => {
    const v = params[key];
    if (typeof v !== "string") return v != null && v !== "";
    const ref = /^\{\{\s*inputs\.([\w.]+)\s*\}\}$/.exec(v.trim());
    return ref ? Boolean(page[ref[1]]) : v.trim() !== "";
  };
  const promptNeed = defaultsFor(node.capability).prompt;
  if (promptNeed === "required" && !filled("prompt")) return "Add a prompt, then run.";
  for (const port of portsFor(node).inputs) {
    if (port.key === "prompt" && promptNeed !== "required") continue;
    if (!filled(port.key)) return `Connect ${port.kind} first.`;
  }
  return null;
}

/** Template that feeds node `id`'s first output into a param. */
export function nodeRef(id: string): string {
  return `{{nodes.${id}.output}}`;
}

function inputRef(key: string): string {
  return `{{inputs.${key}}}`;
}

/** True when `from` can reach `to` along edges. */
function reaches(graph: Graph, from: string, to: string): boolean {
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const id = stack.pop() as string;
    if (id === to) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const e of graph.edges) if (e.src === id) stack.push(e.dst);
  }
  return false;
}

function setNodeParam(graph: Graph, id: string, key: string, value: string): Graph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) => (n.id === id ? { ...n, params: { ...(n.params || {}), [key]: value } } : n)),
  };
}

/**
 * Wire `src`'s output into an input of `dst`.
 *
 * Picks `key` when given, else the first free input whose kind matches. An input
 * takes one source, so an existing wire into the same input is replaced.
 */
export function connect(graph: Graph, src: string, dst: string, key?: string, style?: EdgeStyle): GraphResult {
  const a = graph.nodes.find((n) => n.id === src);
  const b = graph.nodes.find((n) => n.id === dst);
  if (!a || !b) return { ok: false, error: "That step is missing. Add it again." };
  if (src === dst) return { ok: false, error: "Connect this to a different step." };
  const out = portsFor(a).output;
  if (!out) return { ok: false, error: "This step has nothing to connect." };
  const fits = portsFor(b).inputs.filter((p) => p.kind === out && (!key || p.key === key));
  if (!fits.length) return { ok: false, error: `This step cannot take ${out}.` };
  const taken = new Set(graph.edges.filter((e) => e.dst === dst).map((e) => e.input_key));
  const port = fits.find((p) => !taken.has(p.key)) || fits[0];
  const wired = graph.edges.some((e) => e.src === src && e.dst === dst && e.input_key === port.key);
  // Same wire again: a no-op, unless an older save left the param pointing at page inputs.
  if (wired && b.params?.[port.key] === nodeRef(src)) return { ok: true, graph };
  if (reaches(graph, dst, src)) return { ok: false, error: "That connection loops. Pick a different step." };
  // The input's old source: a keyed edge, or an unkeyed one (templates, old saves) feeding this param.
  const replaced = graph.edges.filter(
    (e) => e.dst === dst && (e.input_key === port.key || (e.input_key == null && b.params?.[port.key] === nodeRef(e.src))),
  );
  const edges = graph.edges.filter((e) => !replaced.includes(e));
  // Keep ordering on an old source that another param of `dst` still reads (e.g. first_frame_url).
  for (const e of replaced) {
    const dependency = e.src !== src && readsFrom(b, e.src, port.key);
    if (dependency && !edges.some((x) => x.src === e.src && x.dst === dst)) edges.push({ src: e.src, dst });
  }
  return {
    ok: true,
    graph: setNodeParam(
      { ...graph, edges: [...edges, { src, dst, input_key: port.key, ...(style && style !== "rounded" ? { style } : {}) }] },
      dst,
      port.key,
      nodeRef(src),
    ),
  };
}

/** A whole `{{ nodes.<src>... }}` template, matching the runtime's `interpolate` grammar. */
function refPattern(src: string, flags = ""): RegExp {
  const id = src.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`\\{\\{\\s*nodes\\.${id}(?:\\.[^}]*)?\\s*\\}\\}`, flags);
}

/**
 * Drop every reference to `src` from a param value: a string that is only a reference becomes
 * `fallback`, list items that are only a reference are removed, and embedded ones are cut out.
 */
function scrubRefs(value: unknown, src: string, fallback: unknown): unknown {
  const only = (v: unknown) => typeof v === "string" && refPattern(src).test(v) && v.replace(refPattern(src, "g"), "").trim() === "";
  if (only(value)) return fallback;
  if (typeof value === "string") return value.replace(refPattern(src, "g"), "");
  if (Array.isArray(value)) return value.filter((v) => !only(v)).map((v) => scrubRefs(v, src, ""));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, scrubRefs(v, src, "")]));
  }
  return value;
}

/**
 * True when a param of `node` (other than `except`) still reads anything of `src` (`output`,
 * `outputs`, `data`...), even inside a list or object. Same grammar as the runtime's
 * `interpolate`: whitespace is allowed inside the braces.
 */
/** Every string inside a param value (lists and objects included). JSON would escape `\t` in `{{ }}`. */
function stringsIn(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(stringsIn);
  if (value && typeof value === "object") return Object.values(value).flatMap(stringsIn);
  return [];
}

function readsFrom(node: GraphNode | undefined, src: string, except?: string): boolean {
  const ref = refPattern(src);
  return Object.entries(node?.params || {}).some(
    ([key, value]) => key !== except && stringsIn(value).some((s) => ref.test(s)),
  );
}

/**
 * Remove the wire `src -> dst`. Every param of `dst` that read `src`'s output points back at page
 * inputs; an edge stays only if a param still embeds the reference (in a longer template, a list, or
 * an object), so the runtime still runs `src` first.
 */
export function disconnect(graph: Graph, src: string, dst: string): Graph {
  if (!graph.edges.some((e) => e.src === src && e.dst === dst)) return graph;
  let next: Graph = { ...graph, edges: graph.edges.filter((e) => !(e.src === src && e.dst === dst)) };
  const node = next.nodes.find((n) => n.id === dst);
  for (const [key, value] of Object.entries(node?.params || {})) {
    if (value === nodeRef(src)) next = setNodeParam(next, dst, key, inputRef(key));
  }
  if (readsFrom(next.nodes.find((n) => n.id === dst), src)) next = { ...next, edges: [...next.edges, { src, dst }] };
  return next;
}

/** Remove nodes and every wire touching them; downstream inputs fall back to page inputs. */
export function removeNodes(graph: Graph, ids: Iterable<string>): Graph {
  const gone = new Set(ids);
  if (!graph.nodes.some((n) => gone.has(n.id))) return graph;
  let next = graph;
  for (const e of graph.edges) if (gone.has(e.src) || gone.has(e.dst)) next = disconnect(next, e.src, e.dst);
  // Survivors may still name a deleted node (nested or embedded); the runtime would raise KeyError.
  const nodes = next.nodes
    .filter((n) => !gone.has(n.id))
    .map((n) => {
      if (![...gone].some((id) => readsFrom(n, id))) return n;
      const params: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(n.params || {})) {
        params[key] = [...gone].reduce((v, id) => scrubRefs(v, id, inputRef(key)), value);
      }
      return { ...n, params };
    })
    .map((n) => {
      if (!n.instanceOf || !gone.has(n.instanceOf)) return n;
      const { instanceOf: _drop, ...rest } = n;
      return rest;
    });
  const edges = next.edges.filter((e) => !gone.has(e.src) && !gone.has(e.dst));
  const groups = (next.groups || [])
    .map((grp) => ({ ...grp, nodeIds: grp.nodeIds.filter((id) => !gone.has(id)) }))
    .filter((grp) => grp.nodeIds.length);
  return { ...next, nodes, edges, groups };
}

/** Move `ids` by (dx, dy) from their `starts` positions (graph units). */
export function moveNodes(graph: Graph, starts: Record<string, { x: number; y: number }>, dx: number, dy: number): Graph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) =>
      starts[n.id] ? { ...n, x: Math.round(starts[n.id].x + dx), y: Math.round(starts[n.id].y + dy) } : n,
    ),
  };
}

/** Group `ids` (two or more existing nodes). A node lives in one group, so it leaves any other. */
export function groupNodes(graph: Graph, ids: string[], id: string, name = "Group"): Graph {
  const members = ids.filter((m) => graph.nodes.some((n) => n.id === m));
  // Regrouping an existing group would reset its name and colour.
  if (members.length < 2 || groupOf(graph, members)) return graph;
  const others = (graph.groups || [])
    .map((grp) => ({ ...grp, nodeIds: grp.nodeIds.filter((m) => !members.includes(m)) }))
    .filter((grp) => grp.nodeIds.length);
  const color = GROUP_COLORS[(graph.groups || []).length % GROUP_COLORS.length];
  return { ...graph, groups: [...others, { id, name, color, nodeIds: members }] };
}

/** Remove the groups that contain any of `ids`; the nodes stay. */
export function ungroupNodes(graph: Graph, ids: string[]): Graph {
  const before = graph.groups || [];
  const groups = before.filter((grp) => !grp.nodeIds.some((m) => ids.includes(m)));
  return groups.length === before.length ? graph : { ...graph, groups };
}

export function updateGroup(graph: Graph, id: string, patch: Partial<Omit<GraphGroup, "id">>): Graph {
  return { ...graph, groups: (graph.groups || []).map((grp) => (grp.id === id ? { ...grp, ...patch } : grp)) };
}

/** The group whose members are exactly `ids`, if any (clicking a frame selects its members). */
export function groupOf(graph: Graph, ids: string[]): GraphGroup | undefined {
  return (graph.groups || []).find(
    (grp) => grp.nodeIds.length === ids.length && grp.nodeIds.every((m) => ids.includes(m)),
  );
}

/** Append `node`; when `linkFrom` is set and the types fit, wire it in. `style` is the new wire's draw style. */
export function addNode(graph: Graph, node: GraphNode, linkFrom?: string, style?: EdgeStyle): Graph {
  const next = { ...graph, nodes: [...graph.nodes, node] };
  if (!linkFrom) return next;
  const wired = connect(next, linkFrom, node.id, undefined, style);
  return wired.ok ? wired.graph : next;
}

/** Shallow-merge `patch` into a node. Linked instances follow model, type, and params. */
export function updateNode(graph: Graph, id: string, patch: Partial<GraphNode>): Graph {
  const next = { ...graph, nodes: graph.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) };
  return syncInstances(next, id);
}

/** Shallow-merge `patch` into a node's params. Linked instances stay on the same params. */
export function setParams(graph: Graph, id: string, patch: Record<string, unknown>): Graph {
  const next = {
    ...graph,
    nodes: graph.nodes.map((n) => (n.id === id ? { ...n, params: { ...(n.params || {}), ...patch } } : n)),
  };
  return syncInstances(next, id);
}

/**
 * Copy params, model, and capability from a linked source onto its instances.
 * Editing an instance writes through to the source first. A missing source detaches the copy.
 * Returns the same graph when nothing is linked.
 */
export function syncInstances(graph: Graph, editedId?: string): Graph {
  if (!graph.nodes.some((n) => n.instanceOf)) return graph;
  let nodes = graph.nodes;
  const edited = editedId ? nodes.find((n) => n.id === editedId) : undefined;
  if (edited?.instanceOf) {
    const srcId = edited.instanceOf;
    nodes = nodes.map((n) =>
      n.id === srcId
        ? { ...n, params: edited.params, model_id: edited.model_id, capability: edited.capability, type: edited.type }
        : n,
    );
  }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  let changed = edited?.instanceOf ? true : false;
  const next = nodes.map((n) => {
    if (!n.instanceOf) return n;
    const src = byId.get(n.instanceOf);
    if (!src) {
      changed = true;
      const { instanceOf: _drop, ...rest } = n;
      return rest;
    }
    if (n.params === src.params && n.model_id === src.model_id && n.capability === src.capability && n.type === src.type) return n;
    changed = true;
    return { ...n, params: src.params, model_id: src.model_id, capability: src.capability, type: src.type };
  });
  return changed ? { ...graph, nodes: next } : graph;
}

/** Linked copies of `ids`. Each copy follows its source (or that source's own source). */
export function instanceNodes(graph: Graph, ids: readonly string[], newIds: readonly string[]): Graph {
  let next = graph;
  ids.forEach((id, i) => {
    const src = next.nodes.find((n) => n.id === id);
    const newId = newIds[i];
    if (!src || !newId) return;
    const sourceId = src.instanceOf || id;
    const origin = next.nodes.find((n) => n.id === sourceId) || src;
    next = {
      ...next,
      nodes: [
        ...next.nodes,
        { ...origin, id: newId, instanceOf: sourceId, x: (src.x || 0) + 36, y: (src.y || 0) + 36 },
      ],
    };
  });
  return next;
}

/** Draw style for the wires that touch the selection, or the selected wire. */
export function edgesForStyle(
  graph: Graph,
  ids: readonly string[],
  edge: { src: string; dst: string } | null,
): { src: string; dst: string }[] {
  if (edge) return graph.edges.filter((e) => e.src === edge.src && e.dst === edge.dst).map((e) => ({ src: e.src, dst: e.dst }));
  return graph.edges.filter((e) => ids.includes(e.src) || ids.includes(e.dst)).map((e) => ({ src: e.src, dst: e.dst }));
}

/** The shared style of `pairs`, or null when they disagree or there are none. */
export function commonEdgeStyle(graph: Graph, pairs: readonly { src: string; dst: string }[]): EdgeStyle | null {
  if (!pairs.length) return null;
  const styles = pairs.map((p) => graph.edges.find((e) => e.src === p.src && e.dst === p.dst)?.style || "rounded");
  return styles.every((s) => s === styles[0]) ? styles[0] : null;
}

/** Set the draw style of `pairs`. `rounded` drops the field so old saves stay unchanged. */
export function setEdgeStyle(graph: Graph, pairs: readonly { src: string; dst: string }[], style: EdgeStyle): Graph {
  const want = new Set(pairs.map((p) => `${p.src}->${p.dst}`));
  if (!want.size) return graph;
  let changed = false;
  const edges = graph.edges.map((e) => {
    if (!want.has(`${e.src}->${e.dst}`)) return e;
    if ((e.style || "rounded") === style) return e;
    changed = true;
    if (style === "rounded") {
      const { style: _drop, ...rest } = e;
      return rest;
    }
    return { ...e, style };
  });
  return changed ? { ...graph, edges } : graph;
}

/**
 * Nodes a Run click should send.
 * Card, inspector, and group Run omit `solo`, so they include ancestors.
 * `solo` is the context-menu item "Run this node only".
 */
export function runSet(graph: Graph, ids: Iterable<string>, solo = false): Set<string> {
  return solo ? new Set(ids) : withAncestors(graph, ids);
}

/** `ids` plus every node upstream of them. */
export function withAncestors(graph: Graph, ids: Iterable<string>): Set<string> {
  const keep = new Set(ids);
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
  return keep;
}

/** Selection-toolbar run scope. Card Run stays on ancestors; these scopes do not replace it. */
export type RunScope = "node" | "upstream" | "page";
export const RUN_SCOPES: { id: RunScope; label: string }[] = [
  { id: "node", label: "This node only" },
  { id: "upstream", label: "Up to here" },
  { id: "page", label: "Whole page" },
];

/**
 * Nodes a selection-toolbar scope runs.
 * `upstream` ("up to here") is the selection and what feeds it, never nodes downstream of it.
 * `node` is the selection alone. `page` is every node on the current page.
 */
export function scopeNodes(graph: Graph, ids: Iterable<string>, scope: RunScope): string[] {
  if (scope === "page") return graph.nodes.map((n) => n.id);
  const picked = [...ids].filter((id, i, all) => all.indexOf(id) === i && graph.nodes.some((n) => n.id === id));
  if (scope === "node") return picked;
  return [...withAncestors(graph, picked)];
}

/**
 * Price of a toolbar scope. The id list is already closed, so ancestors are not added again.
 * Downstream nodes stay out of an "up to here" total.
 */
export function estimateScope(
  graph: Graph,
  ids: Iterable<string>,
  priceOf: (node: GraphNode) => number | null | undefined,
  scope: RunScope,
): { nodes: number; total: number; unpriced: number } {
  return estimateRun(graph, scopeNodes(graph, ids, scope), priceOf, true);
}

/** Copy a node beside the original. Wires are not copied, so every node reference falls back to page inputs. */
export function duplicateNode(graph: Graph, id: string, newId: string): Graph {
  const src = graph.nodes.find((n) => n.id === id);
  if (!src) return graph;
  // A space before `.` is part of the id (`{{nodes.a .output}}` is node "a ").
  // A space before `}}` is not (`{{ nodes.still }}` is node "still").
  const named = (s: string) =>
    [...s.matchAll(/\{\{\s*nodes\.([^}]+)\}\}/g)].map((m) => {
      const body = m[1];
      const dot = body.indexOf(".");
      return dot < 0 ? body.trimEnd() : body.slice(0, dot);
    });
  const refs = stringsIn(src.params).flatMap(named);
  const params: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(src.params || {})) {
    params[key] = [...new Set(refs)].reduce((v, id) => scrubRefs(v, id, inputRef(key)), value);
  }
  const { instanceOf: _linked, ...bare } = src;
  const copy = { ...bare, id: newId, params, x: (src.x || 0) + 24, y: (src.y || 0) + 24 };
  return { ...graph, nodes: [...graph.nodes, copy] };
}

/** Undo/redo stacks around the current graph. `base` is the graph that was loaded. */
export type GraphHistory = { past: Graph[]; present: Graph; future: Graph[]; base: Graph };
export const HISTORY_LIMIT = 100;

export function startHistory(graph: Graph): GraphHistory {
  return { past: [], present: graph, future: [], base: graph };
}

/** Record `next` as one undoable step. Unchanged graphs are not recorded. */
function record(h: GraphHistory, step: Graph, present: Graph): GraphHistory {
  return { ...h, past: [...h.past, step].slice(-HISTORY_LIMIT), present, future: [] };
}

export function commit(h: GraphHistory, next: Graph): GraphHistory {
  if (next === h.present) return h;
  return record(h, h.present, next);
}

/** Show `next` without recording it (drag frames). Pair with `settle`. */
export function preview(h: GraphHistory, next: Graph): GraphHistory {
  return { ...h, present: next };
}

/** Record everything since `base` (the graph before the drag) as one step. */
export function settle(h: GraphHistory, base: Graph): GraphHistory {
  if (h.present === base) return h;
  // Dragged back to where it started: keep redo and the original graph object.
  if (JSON.stringify(h.present) === JSON.stringify(base)) return { ...h, present: base };
  return record(h, base, h.present);
}

/** Generate nodes and the wires between them. Canvas-only types stay off the runtime. */
export function runtimeGraph(graph: Graph): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes = toWorkflowNodes(graph.nodes);
  const ids = new Set(nodes.map((n) => n.id));
  return {
    nodes,
    edges: graph.edges
      .filter((e) => ids.has(e.src) && ids.has(e.dst))
      .map(({ style: _style, ...e }) => e),
  };
}

/** What a run reads from the canvas. Layout (positions, groups) is left out. */
function runtimeOf(graph: Graph): string {
  return JSON.stringify(runtimeGraph(graph));
}

/**
 * True when a run would read something other than what was loaded. Moving or grouping nodes does
 * not count, so a loaded template keeps running as its skill (with the skill's manifest defaults).
 */
export function isEdited(h: GraphHistory): boolean {
  return h.present !== h.base && runtimeOf(h.present) !== runtimeOf(h.base);
}

export function undo(h: GraphHistory): GraphHistory {
  const prev = h.past.at(-1);
  if (!prev) return h;
  return { ...h, past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future] };
}

export function redo(h: GraphHistory): GraphHistory {
  const [next, ...rest] = h.future;
  if (!next) return h;
  return { ...h, past: [...h.past, h.present], present: next, future: rest };
}

/**
 * Upper bound for a run of `ids` plus what feeds them: the sum of known model prices.
 * Unchanged upstream jobs hit the runtime cache at $0, so the real cost can be lower.
 */
export function estimateRun(
  graph: Graph,
  ids: Iterable<string>,
  priceOf: (node: GraphNode) => number | null | undefined,
  solo = false,
): { nodes: number; total: number; unpriced: number } {
  let total = 0;
  let unpriced = 0;
  let nodes = 0;
  for (const id of runSet(graph, ids, solo)) {
    const node = graph.nodes.find((n) => n.id === id);
    if (!node || node.type !== "generate") continue;
    nodes += 1;
    const price = priceOf(node);
    if (price == null) unpriced += 1;
    else total += price;
  }
  return { nodes, total, unpriced };
}

const SHOT_KEYS = ["aspect_ratio", "camera", "lens", "look", "aperture", "genre", "lighting", "palette"];

/** Runtime nodes: fill unset shot params from page inputs and drop canvas-only fields. */
export function toWorkflowNodes(nodes: GraphNode[]): GraphNode[] {
  return nodes.filter((n) => n.type === "generate").map(({ x, y, instanceOf, ...n }) => {
    void x;
    void y;
    void instanceOf;
    const params = { ...(n.params || {}) };
    const video = n.capability === "t2v" || n.capability === "i2v";
    for (const key of SHOT_KEYS) if (!params[key]) params[key] = inputRef(key);
    if (video && params.duration == null) params.duration = inputRef("duration");
    if (video && !params.motion) params.motion = inputRef("motion");
    return { ...n, params };
  });
}

/* ---------- View: node geometry, pan and zoom ---------- */

/** Node card size in graph units. Width matches `.node` in globals.css; height is the idle Magnific card. */
export const NODE_W = 320;
export const NODE_H = 300;
const PORT_Y = 44;
const PORT_GAP = 26;

/** Port centre offset from the node top: output and first input at PORT_Y, more inputs below. */
export function portY(index: number): number {
  return PORT_Y + index * PORT_GAP;
}

/** Orthogonal rounded wire (Magnific Spaces). Leaves and enters horizontally. */
export function curve(x1: number, y1: number, x2: number, y2: number): string {
  const dy = y2 - y1;
  if (Math.abs(dy) < 0.5) return `M${x1} ${y1} L${x2} ${y2}`;
  const dir = dy > 0 ? 1 : -1;
  if (x2 >= x1 + 24) {
    const mid = x1 + Math.max(32, (x2 - x1) / 2);
    const r = Math.min(12, Math.abs(mid - x1) / 2, Math.abs(x2 - mid) / 2, Math.abs(dy) / 2);
    return `M${x1} ${y1} L${mid - r} ${y1} Q${mid} ${y1} ${mid} ${y1 + dir * r} L${mid} ${y2 - dir * r} Q${mid} ${y2} ${mid + r} ${y2} L${x2} ${y2}`;
  }
  const outX = x1 + 40;
  const inX = x2 - 40;
  const midY = y1 + dy / 2;
  const r = Math.min(12, 20, Math.abs(dy) / 4);
  return `M${x1} ${y1} L${outX - r} ${y1} Q${outX} ${y1} ${outX} ${y1 + dir * r} L${outX} ${midY - dir * r} Q${outX} ${midY} ${outX - r} ${midY} L${inX + r} ${midY} Q${inX} ${midY} ${inX} ${midY + dir * r} L${inX} ${y2 - dir * r} Q${inX} ${y2} ${inX + r} ${y2} L${x2} ${y2}`;
}

/** Wire from `a`'s output into `b`'s input `key` (first input when unknown). Default is the rounded orthogonal wire. */
export function wirePath(a: GraphNode, b: GraphNode, key?: string, style?: EdgeStyle): string {
  const index = Math.max(0, portsFor(b).inputs.findIndex((p) => p.key === key));
  const x1 = (a.x || 0) + NODE_W;
  const y1 = (a.y || 0) + PORT_Y;
  const x2 = b.x || 0;
  const y2 = (b.y || 0) + portY(index);
  if (style === "straight") return `M${x1} ${y1} L${x2} ${y2}`;
  if (style === "curve") {
    const c = Math.max(48, Math.abs(x2 - x1) / 2);
    return `M${x1} ${y1} C${x1 + c} ${y1} ${x2 - c} ${y2} ${x2} ${y2}`;
  }
  return curve(x1, y1, x2, y2);
}

/**
 * First spot at or after (x, y) where a node card fits without overlapping another. Scans in growing
 * rings of card-sized steps, right before down, so inserts land beside what is already there.
 * Always ends: a card blocks at most a 2x2 block of grid cells, and each ring adds new cells.
 */
export function freeSpot(graph: Graph, x: number, y: number): { x: number; y: number } {
  const clear = (px: number, py: number) =>
    !graph.nodes.some((n) => Math.abs((n.x || 0) - px) < NODE_W + 16 && Math.abs((n.y || 0) - py) < NODE_H + 16);
  for (let ring = 0; ; ring++) {
    for (let row = 0; row <= ring; row++) {
      for (let col = 0; col <= ring; col++) {
        if (Math.max(row, col) !== ring) continue;
        const at = { x: Math.round(x + col * (NODE_W + 40)), y: Math.round(y + row * (NODE_H + 40)) };
        if (clear(at.x, at.y)) return at;
      }
    }
  }
}

/** Frame around a group's members, with room for the title bar above. Null when it has no members. */
export function groupBounds(graph: Graph, group: GraphGroup, pad = 20): { x: number; y: number; w: number; h: number } | null {
  const cards = graph.nodes.filter((n) => group.nodeIds.includes(n.id));
  if (!cards.length) return null;
  const left = Math.min(...cards.map((n) => n.x || 0)) - pad;
  const top = Math.min(...cards.map((n) => n.y || 0)) - pad - 28;
  const right = Math.max(...cards.map((n) => (n.x || 0) + NODE_W)) + pad;
  const bottom = Math.max(...cards.map((n) => (n.y || 0) + NODE_H)) + pad;
  return { x: left, y: top, w: right - left, h: bottom - top };
}

/** Ids of cards that overlap a graph-space rectangle (marquee select). */
export function nodesInRect(graph: Graph, r: { x: number; y: number; w: number; h: number }): string[] {
  const x2 = r.x + r.w;
  const y2 = r.y + r.h;
  return graph.nodes
    .filter((n) => {
      const nx = n.x || 0;
      const ny = n.y || 0;
      return nx < x2 && nx + NODE_W > r.x && ny < y2 && ny + NODE_H > r.y;
    })
    .map((n) => n.id);
}

/** Screen = graph * zoom + (x, y). */
export type Viewport = { x: number; y: number; zoom: number };
export const HOME_VIEW: Viewport = { x: 0, y: 0, zoom: 1 };
export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 2.5;

export function clampZoom(zoom: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom));
}

/** Zoom to `zoom` keeping the screen point (px, py) over the same graph point. */
export function zoomAt(view: Viewport, zoom: number, px: number, py: number): Viewport {
  const z = clampZoom(zoom);
  const gx = (px - view.x) / view.zoom;
  const gy = (py - view.y) / view.zoom;
  return { x: px - gx * z, y: py - gy * z, zoom: z };
}

/**
 * Zoom multiplier for one wheel event. Pixel deltas scale by 0.002 and line deltas by 0.05.
 * Trackpad pinch arrives as ctrlKey with small pixel deltas, so only those get x10; a Ctrl + mouse
 * wheel notch (~100px) keeps the normal ~15% step.
 */
export function wheelZoomFactor(deltaY: number, deltaMode: number, pinch: boolean): number {
  const step = deltaMode === 1 ? 0.05 : deltaMode ? 1 : 0.002;
  const boost = pinch && deltaMode === 0 && Math.abs(deltaY) < 50 ? 10 : 1;
  return 2 ** (-deltaY * step * boost);
}

/**
 * Fit `nodes` inside a `w` x `h` view. Never zooms past 100%, so a lone node is not blown up.
 * `heights` holds rendered card heights by node id; missing ids fall back to NODE_H.
 */
export function fitView(
  nodes: GraphNode[],
  w: number,
  h: number,
  pad = 48,
  heights: ReadonlyMap<string, number> = new Map(),
): Viewport {
  if (!nodes.length || w <= 0 || h <= 0) return HOME_VIEW;
  const xs = nodes.map((n) => n.x || 0);
  const ys = nodes.map((n) => n.y || 0);
  const left = Math.min(...xs);
  const top = Math.min(...ys);
  const bw = Math.max(...xs) + NODE_W - left;
  const bh = Math.max(...nodes.map((n) => (n.y || 0) + (heights.get(n.id) || NODE_H))) - top;
  const zoom = clampZoom(Math.min((w - pad * 2) / bw, (h - pad * 2) / bh, 1));
  return { x: (w - bw * zoom) / 2 - left * zoom, y: (h - bh * zoom) / 2 - top * zoom, zoom };
}

/* ---------- Keyboard shortcuts (single source for handler, tooltips, and the sheet) ---------- */

export type ShortcutId =
  | "addNode"
  | "selectAll"
  | "runSelection"
  | "runAll"
  | "group"
  | "ungroup"
  | "undo"
  | "redo"
  | "delete"
  | "clear"
  | "duplicate"
  | "fit"
  | "fitSelection"
  | "resetView"
  | "zoomIn"
  | "zoomOut"
  | "panMode"
  | "selectMode"
  | "comment"
  | "help";
type KeySpec = { key: string; mod?: boolean; shift?: boolean };
export type Shortcut = { id: ShortcutId; label: string; keys: string; group: "Edit" | "View"; match: KeySpec[] };

export const SHORTCUTS: Shortcut[] = [
  { id: "addNode", label: "Add node", keys: "N", group: "Edit", match: [{ key: "n" }] },
  { id: "undo", label: "Undo", keys: "⌘Z", group: "Edit", match: [{ key: "z", mod: true }] },
  { id: "redo", label: "Redo", keys: "⌘⇧Z", group: "Edit", match: [{ key: "z", mod: true, shift: true }] },
  { id: "duplicate", label: "Duplicate selection", keys: "⌘D", group: "Edit", match: [{ key: "d", mod: true }] },
  { id: "selectAll", label: "Select all", keys: "⌘A", group: "Edit", match: [{ key: "a", mod: true }] },
  { id: "runSelection", label: "Run selection", keys: "⌘↵", group: "Edit", match: [{ key: "enter", mod: true }] },
  { id: "runAll", label: "Run all", keys: "⌘⇧↵", group: "Edit", match: [{ key: "enter", mod: true, shift: true }] },
  { id: "group", label: "Group selection", keys: "⌘G", group: "Edit", match: [{ key: "g", mod: true }] },
  { id: "ungroup", label: "Ungroup", keys: "⌘⇧G", group: "Edit", match: [{ key: "g", mod: true, shift: true }] },
  {
    id: "delete",
    label: "Delete selection",
    keys: "⌫",
    group: "Edit",
    match: [{ key: "backspace" }, { key: "delete" }],
  },
  { id: "clear", label: "Clear selection", keys: "Esc", group: "Edit", match: [{ key: "escape" }] },
  { id: "fit", label: "Zoom to fit", keys: "D", group: "View", match: [{ key: "d" }] },
  { id: "fitSelection", label: "Zoom to selection", keys: "F", group: "View", match: [{ key: "f" }] },
  { id: "resetView", label: "Reset view (100%)", keys: "⌘0", group: "View", match: [{ key: "0", mod: true }] },
  { id: "zoomIn", label: "Zoom in", keys: "⌘=", group: "View", match: [{ key: "=", mod: true }] },
  { id: "zoomOut", label: "Zoom out", keys: "⌘−", group: "View", match: [{ key: "-", mod: true }] },
  { id: "panMode", label: "Pan tool (or hold Space)", keys: "H", group: "View", match: [{ key: "h" }] },
  { id: "selectMode", label: "Select tool", keys: "V", group: "View", match: [{ key: "v" }] },
  { id: "comment", label: "Comment", keys: "C", group: "Edit", match: [{ key: "c" }] },
  { id: "help", label: "Show shortcuts", keys: "?", group: "View", match: [{ key: "?", shift: true }] },
];

/** Map a key event to a shortcut. ⌘ and Ctrl both count as `mod`; Alt combos never match. */
export function shortcutFor(ev: {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}): ShortcutId | null {
  if (ev.altKey) return null;
  const key = ev.key === "+" ? "=" : ev.key.toLowerCase();
  const mod = Boolean(ev.metaKey || ev.ctrlKey);
  const shift = Boolean(ev.shiftKey);
  // "+" needs Shift on most layouts; treat ⌘+ and ⌘= alike.
  const shiftMatters = ev.key !== "+";
  for (const s of SHORTCUTS) {
    for (const m of s.match) {
      if (m.key === key && Boolean(m.mod) === mod && (!shiftMatters || Boolean(m.shift) === shift)) return s.id;
    }
  }
  return null;
}

/** Tooltip text for a toolbar control, e.g. "Undo (⌘Z)". */
export function withKeys(id: ShortcutId): string {
  const s = SHORTCUTS.find((row) => row.id === id);
  return s ? `${s.label} (${s.keys})` : "";
}
