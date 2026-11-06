/**
 * Canvas pages, comments, minimap, and run-receipt history.
 *
 * Pure data. The project file is what collab snapshots and localStorage store.
 * No React. Tests load this file on its own (tests/test_canvas_board.py).
 */

import { EMPTY_GRAPH, NODE_H, NODE_W, type Graph, type Viewport } from "./canvas-graph";

export const PROJECT_STORAGE_KEY = "vinci-canvas-project-v1";
export const MINIMAP_W = 168;
export const MINIMAP_H = 104;

export type BoardComment = { id: string; x: number; y: number; text: string };
export type BoardPage = {
  id: string;
  name: string;
  graph: Graph;
  comments: BoardComment[];
  viewport?: Viewport;
};
export type ProjectFile = {
  version: 1;
  pages: BoardPage[];
  active: string;
  edgeStyle: "rounded" | "curve" | "straight";
};

export type RunReceipt = {
  id: string;
  state?: string;
  created_at?: string;
  estimate?: { total?: number };
  outputs?: string[];
  nodes?: Record<string, { output?: string; outputs?: string[] }>;
};

export type WorldBox = { x: number; y: number; w: number; h: number };

/** A one-page project. Callers replace the active page as the user edits. */
export function emptyProject(): ProjectFile {
  return {
    version: 1,
    pages: [{ id: "page-1", name: "Page 1", graph: EMPTY_GRAPH, comments: [] }],
    active: "page-1",
    edgeStyle: "rounded",
  };
}

function isGraph(value: unknown): value is Graph {
  if (!value || typeof value !== "object") return false;
  const row = value as Graph;
  return Array.isArray(row.nodes) && Array.isArray(row.edges);
}

function isComment(value: unknown): value is BoardComment {
  if (!value || typeof value !== "object") return false;
  const row = value as BoardComment;
  return typeof row.id === "string" && typeof row.x === "number" && typeof row.y === "number" && typeof row.text === "string";
}

function isPage(value: unknown): value is BoardPage {
  if (!value || typeof value !== "object") return false;
  const row = value as BoardPage;
  return typeof row.id === "string" && typeof row.name === "string" && isGraph(row.graph);
}

/**
 * Parse a project file. Returns null when the JSON is not a version-1 project
 * with at least one page. Unknown active ids fall back to the first page.
 */
export function readProjectFile(raw: string): ProjectFile | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object") return null;
  const rec = data as Partial<ProjectFile>;
  if (rec.version !== 1 || !Array.isArray(rec.pages)) return null;
  const pages: BoardPage[] = [];
  for (const row of rec.pages) {
    if (!isPage(row)) continue;
    const comments = Array.isArray(row.comments) ? row.comments.filter(isComment) : [];
    const viewport = row.viewport && typeof row.viewport.zoom === "number" ? row.viewport : undefined;
    pages.push({ id: row.id, name: row.name, graph: row.graph, comments, viewport });
  }
  if (!pages.length) return null;
  const active = pages.some((p) => p.id === rec.active) ? (rec.active as string) : pages[0].id;
  const edgeStyle = rec.edgeStyle === "curve" || rec.edgeStyle === "straight" ? rec.edgeStyle : "rounded";
  return { version: 1, pages, active, edgeStyle };
}

/** Write the live board into the active page. Other pages stay as they were. */
export function writeActive(
  project: ProjectFile,
  graph: Graph,
  comments: readonly BoardComment[],
  viewport: Viewport,
): ProjectFile {
  let changed = false;
  const pages = project.pages.map((page) => {
    if (page.id !== project.active) return page;
    if (page.graph === graph && page.comments === comments && page.viewport === viewport) return page;
    changed = true;
    return { ...page, graph, comments: [...comments], viewport };
  });
  return changed ? { ...project, pages } : project;
}

/** Append an empty page and make it active. The caller saves the previous page first. */
export function addBoardPage(project: ProjectFile, id: string, name?: string): ProjectFile {
  const page: BoardPage = {
    id,
    name: name || `Page ${project.pages.length + 1}`,
    graph: { nodes: [], edges: [] },
    comments: [],
  };
  return { ...project, pages: [...project.pages, page], active: id };
}

/** Rename one page. Blank names are ignored. */
export function renameBoardPage(project: ProjectFile, id: string, name: string): ProjectFile {
  const next = name.trim();
  if (!next) return project;
  let changed = false;
  const pages = project.pages.map((page) => {
    if (page.id !== id || page.name === next) return page;
    changed = true;
    return { ...page, name: next };
  });
  return changed ? { ...project, pages } : project;
}

/** Drop a page. The last page cannot be removed. If the active page goes, the first one opens. */
export function removeBoardPage(project: ProjectFile, id: string): ProjectFile {
  if (project.pages.length < 2 || !project.pages.some((page) => page.id === id)) return project;
  const pages = project.pages.filter((page) => page.id !== id);
  const active = project.active === id ? pages[0].id : project.active;
  return { ...project, pages, active };
}

export function activePage(project: ProjectFile): BoardPage {
  return project.pages.find((page) => page.id === project.active) || project.pages[0];
}

/** Cost rows from run receipts, in the order the runs were given. Dollars come from `estimate.total`. */
export function receiptCosts(runs: readonly RunReceipt[]): { id: string; state: string; dollars: number; when: string }[] {
  return runs.map((run) => ({
    id: run.id,
    state: run.state || "",
    dollars: Number(run.estimate?.total || 0),
    when: run.created_at || "",
  }));
}

/** Sum of receipt cost rows. */
export function receiptTotal(runs: readonly RunReceipt[]): number {
  return receiptCosts(runs).reduce((sum, row) => sum + row.dollars, 0);
}

/** Asset ids a receipt produced, run outputs first, then node outputs not already listed. */
export function receiptAssets(runs: readonly RunReceipt[]): { runId: string; assetId: string }[] {
  const rows: { runId: string; assetId: string }[] = [];
  for (const run of runs) {
    const seen = new Set<string>();
    for (const id of run.outputs || []) {
      if (!id || seen.has(id)) continue;
      seen.add(id);
      rows.push({ runId: run.id, assetId: id });
    }
    for (const node of Object.values(run.nodes || {})) {
      const ids = node.output ? [node.output] : node.outputs || [];
      for (const id of ids) {
        if (!id || seen.has(id)) continue;
        seen.add(id);
        rows.push({ runId: run.id, assetId: id });
      }
    }
  }
  return rows;
}

/** One row per node that a receipt recorded. */
export function receiptNodes(runs: readonly RunReceipt[]): { runId: string; nodeId: string; assetId: string }[] {
  const rows: { runId: string; nodeId: string; assetId: string }[] = [];
  for (const run of runs) {
    for (const [nodeId, node] of Object.entries(run.nodes || {})) {
      rows.push({ runId: run.id, nodeId, assetId: node.output || node.outputs?.[0] || "" });
    }
  }
  return rows;
}

/**
 * World rectangle that contains every node and the visible board.
 * The viewport is included so an empty page still has a minimap.
 */
export function minimapWorld(
  nodes: readonly { x?: number; y?: number }[],
  view: Viewport,
  boardW: number,
  boardH: number,
): WorldBox {
  const vx = -view.x / view.zoom;
  const vy = -view.y / view.zoom;
  const vw = boardW / view.zoom;
  const vh = boardH / view.zoom;
  let left = vx;
  let top = vy;
  let right = vx + vw;
  let bottom = vy + vh;
  for (const node of nodes) {
    left = Math.min(left, node.x || 0);
    top = Math.min(top, node.y || 0);
    right = Math.max(right, (node.x || 0) + NODE_W);
    bottom = Math.max(bottom, (node.y || 0) + NODE_H);
  }
  const pad = 40;
  return { x: left - pad, y: top - pad, w: Math.max(1, right - left + pad * 2), h: Math.max(1, bottom - top + pad * 2) };
}

/** Graph point to minimap pixels. */
export function minimapPoint(world: WorldBox, mapW: number, mapH: number, gx: number, gy: number): { x: number; y: number } {
  return { x: ((gx - world.x) / world.w) * mapW, y: ((gy - world.y) / world.h) * mapH };
}

/**
 * Pan so the graph point under minimap pixel (mx, my) sits at the board centre.
 * Zoom is unchanged.
 */
export function viewportFromMinimap(
  world: WorldBox,
  mapW: number,
  mapH: number,
  mx: number,
  my: number,
  boardW: number,
  boardH: number,
  zoom: number,
): Viewport {
  const gx = world.x + (mx / mapW) * world.w;
  const gy = world.y + (my / mapH) * world.h;
  return { x: boardW / 2 - gx * zoom, y: boardH / 2 - gy * zoom, zoom };
}
