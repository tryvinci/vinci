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

export type MediaKind = "image" | "video" | "audio";
export type GraphNode = {
  id: string;
  type: string;
  capability?: string;
  model_id?: string;
  params?: Record<string, unknown>;
  x?: number;
  y?: number;
};
export type GraphEdge = { src: string; dst: string; input_key?: string };
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
  t2i: { inputs: [], output: "image" },
  i2i: { inputs: [{ key: "media", kind: "image" }], output: "image" },
  upscale: { inputs: [{ key: "media", kind: "image" }], output: "image" },
  t2v: { inputs: [], output: "video" },
  i2v: { inputs: [{ key: "image", kind: "image" }], output: "video" },
  tts: { inputs: [], output: "audio" },
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
};
const NO_PORTS: NodePorts = { inputs: [], output: null };

/** Ports for a node. Unknown capabilities get none, so they cannot be wired by hand. */
export function portsFor(node: GraphNode | undefined): NodePorts {
  return (node && PORTS[node.capability || ""]) || NO_PORTS;
}

/** What a capability produces, or null when it has no declared ports. */
export function outputOf(capability: string): MediaKind | null {
  return PORTS[capability]?.output || null;
}

/** Nodes the add menu offers, in menu order. Every capability here has ports above. */
export type CatalogEntry = { capability: string; label: string; blurb: string };
export const NODE_CATALOG: CatalogEntry[] = [
  { capability: "t2i", label: "Image", blurb: "Generate an image from a prompt" },
  { capability: "i2i", label: "Image edit", blurb: "Restyle or edit an image with a prompt" },
  { capability: "upscale", label: "Upscale", blurb: "Enlarge and sharpen an image" },
  { capability: "t2v", label: "Video", blurb: "Generate a video from a prompt" },
  { capability: "i2v", label: "Animate image", blurb: "Turn a still into a clip" },
  { capability: "lipsync", label: "Lip sync", blurb: "Sync a video to an audio track" },
  { capability: "tts", label: "Voice", blurb: "Speak a prompt as audio" },
];

/**
 * Add-menu rows matching `query`, best first. With `takes`, only nodes with an input of that kind
 * (the add-from-port case). Label prefix beats a word prefix beats a substring anywhere.
 */
export function searchCatalog(query: string, takes?: MediaKind | null): CatalogEntry[] {
  const q = query.trim().toLowerCase();
  const rows = NODE_CATALOG.filter((e) => !takes || (PORTS[e.capability]?.inputs || []).some((p) => p.kind === takes));
  if (!q) return rows;
  const score = (e: CatalogEntry): number => {
    const label = e.label.toLowerCase();
    if (label.startsWith(q)) return 0;
    if (label.split(/\s+/).some((w) => w.startsWith(q))) return 1;
    return `${label} ${e.capability} ${e.blurb.toLowerCase()}`.includes(q) ? 2 : -1;
  };
  return rows
    .map((e, i) => ({ e, i, s: score(e) }))
    .filter((r) => r.s >= 0)
    .sort((a, b) => a.s - b.s || a.i - b.i)
    .map((r) => r.e);
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
};
export const NODE_DEFAULTS: Record<string, NodeDefaults> = {
  t2i: { prompt: "required", placeholder: "Describe the image you want", aspect_ratio: "16:9" },
  i2i: { prompt: "required", placeholder: "Describe the change to make" },
  upscale: { prompt: "none" },
  t2v: { prompt: "required", placeholder: "Describe the shot and its motion", aspect_ratio: "16:9", duration: 5 },
  i2v: { prompt: "optional", placeholder: "Describe how the still should move", duration: 5 },
  lipsync: { prompt: "none" },
  tts: { prompt: "required", placeholder: "What should the voice say?" },
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
  page: { prompt?: string; aspect_ratio?: string; duration?: string | number },
): Record<string, unknown> {
  const d = defaultsFor(capability);
  const out: Record<string, unknown> = { ...inputDefaults(capability) };
  if (d.prompt !== "none") out.prompt = (page.prompt || "").trim();
  if (d.aspect_ratio) out.aspect_ratio = page.aspect_ratio || d.aspect_ratio;
  if (d.duration != null) out.duration = Number(page.duration) || d.duration;
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
  if (defaultsFor(node.capability).prompt === "required" && !filled("prompt")) return "Add a prompt.";
  for (const port of portsFor(node).inputs) {
    if (!filled(port.key)) return `Connect ${/^[aeiou]/.test(port.kind) ? "an" : "a"} ${port.kind} input.`;
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
export function connect(graph: Graph, src: string, dst: string, key?: string): GraphResult {
  const a = graph.nodes.find((n) => n.id === src);
  const b = graph.nodes.find((n) => n.id === dst);
  if (!a || !b) return { ok: false, error: "Node not found." };
  if (src === dst) return { ok: false, error: "A node cannot connect to itself." };
  const out = portsFor(a).output;
  if (!out) return { ok: false, error: `${a.id} has no output to connect.` };
  const fits = portsFor(b).inputs.filter((p) => p.kind === out && (!key || p.key === key));
  if (!fits.length) return { ok: false, error: `${b.id} has no ${out} input.` };
  const taken = new Set(graph.edges.filter((e) => e.dst === dst).map((e) => e.input_key));
  const port = fits.find((p) => !taken.has(p.key)) || fits[0];
  const wired = graph.edges.some((e) => e.src === src && e.dst === dst && e.input_key === port.key);
  // Same wire again: a no-op, unless an older save left the param pointing at page inputs.
  if (wired && b.params?.[port.key] === nodeRef(src)) return { ok: true, graph };
  if (reaches(graph, dst, src)) return { ok: false, error: "That wire would make a loop." };
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
    graph: setNodeParam({ ...graph, edges: [...edges, { src, dst, input_key: port.key }] }, dst, port.key, nodeRef(src)),
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
function readsFrom(node: GraphNode | undefined, src: string, except?: string): boolean {
  const ref = refPattern(src);
  return Object.entries(node?.params || {}).some(
    ([key, value]) => key !== except && ref.test(typeof value === "string" ? value : JSON.stringify(value ?? null)),
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
export function groupNodes(graph: Graph, ids: string[], id: string, name = "Untitled group"): Graph {
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

/** Append `node`; when `linkFrom` is set and the types fit, wire it in. */
export function addNode(graph: Graph, node: GraphNode, linkFrom?: string): Graph {
  const next = { ...graph, nodes: [...graph.nodes, node] };
  if (!linkFrom) return next;
  const wired = connect(next, linkFrom, node.id);
  return wired.ok ? wired.graph : next;
}

/** Shallow-merge `patch` into a node. */
export function updateNode(graph: Graph, id: string, patch: Partial<GraphNode>): Graph {
  return { ...graph, nodes: graph.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)) };
}

/** Shallow-merge `patch` into a node's params. */
export function setParams(graph: Graph, id: string, patch: Record<string, unknown>): Graph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) => (n.id === id ? { ...n, params: { ...(n.params || {}), ...patch } } : n)),
  };
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

/** Copy a node beside the original. Wires are not copied, so wired inputs fall back to page inputs. */
export function duplicateNode(graph: Graph, id: string, newId: string): Graph {
  const src = graph.nodes.find((n) => n.id === id);
  if (!src) return graph;
  const params = { ...(src.params || {}) };
  for (const port of portsFor(src).inputs) {
    if (String(params[port.key] || "").startsWith("{{nodes.")) params[port.key] = inputRef(port.key);
  }
  const copy = { ...src, id: newId, params, x: (src.x || 0) + 24, y: (src.y || 0) + 24 };
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

/** What a run reads from the canvas. Layout (positions, groups) is left out. */
function runtimeOf(graph: Graph): string {
  return JSON.stringify({ nodes: toWorkflowNodes(graph.nodes), edges: graph.edges });
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
): { nodes: number; total: number; unpriced: number } {
  let total = 0;
  let unpriced = 0;
  let nodes = 0;
  for (const id of withAncestors(graph, ids)) {
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
  return nodes.map(({ x, y, ...n }) => {
    void x;
    void y;
    const params = { ...(n.params || {}) };
    const video = n.capability === "t2v" || n.capability === "i2v";
    for (const key of SHOT_KEYS) if (!params[key]) params[key] = inputRef(key);
    if (video && params.duration == null) params.duration = inputRef("duration");
    if (video && !params.motion) params.motion = inputRef("motion");
    return { ...n, params };
  });
}

/* ---------- View: node geometry, pan and zoom ---------- */

/** Node card size in graph units. Width matches `.node` in globals.css; height is the idle card (labels grow it). */
export const NODE_W = 196;
export const NODE_H = 172;
const PORT_Y = 44;
const PORT_GAP = 26;

/** Port centre offset from the node top: output and first input at PORT_Y, more inputs below. */
export function portY(index: number): number {
  return PORT_Y + index * PORT_GAP;
}

/** Bezier between two graph points, leaving and entering horizontally. */
export function curve(x1: number, y1: number, x2: number, y2: number): string {
  return `M${x1} ${y1} C${x1 + 40} ${y1}, ${x2 - 40} ${y2}, ${x2} ${y2}`;
}

/** Bezier from `a`'s output port into `b`'s input `key` (first input when unknown). */
export function wirePath(a: GraphNode, b: GraphNode, key?: string): string {
  const index = Math.max(0, portsFor(b).inputs.findIndex((p) => p.key === key));
  return curve((a.x || 0) + NODE_W, (a.y || 0) + PORT_Y, b.x || 0, (b.y || 0) + portY(index));
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
