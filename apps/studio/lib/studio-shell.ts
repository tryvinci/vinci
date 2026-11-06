/**
 * Studio shell navigation. One format-grouped rail, plus All tools and Ctrl+K.
 *
 * The rail is the format groups (Explore, Image, Video, Canvas, Library) with
 * Features|Models flyouts and the Skills / Find / Cost / Connect footer.
 * All tools and Ctrl+K index those same entries. They are not a second menu.
 * Home, Assets, Edit, Supercomputer, 3D, and Collab have no rail slot; they
 * stay in that same index so the pages remain reachable.
 *
 * Pure functions. No React, DOM, or imports: tests load this file on its own
 * (tests/test_studio_shell.py). Page renderers stay in studio-client.tsx.
 */

export type PageId =
  | "home"
  | "explore"
  | "image"
  | "adapts"
  | "video"
  | "speak"
  | "upscale"
  | "edit"
  | "canvas"
  | "library"
  | "assets"
  | "agent"
  | "space"
  | "collab"
  | "skills"
  | "find"
  | "cost"
  | "keys"
  | "settings";

export type ToolCategory = "image" | "video" | "audio" | "edit" | "canvas" | "library" | "templates" | "utilities";

export type Tool = {
  id: string;
  title: string;
  blurb: string;
  page: PageId;
  category: ToolCategory;
  pinable: boolean;
};

export type FlyoutKind = "image" | "video";

export type CommandHit = {
  kind: "tool" | "asset" | "project" | "model";
  id: string;
  title: string;
  blurb: string;
  page?: PageId;
  /** Set on model hits so a pick opens the same page as the format flyout. */
  flyout?: FlyoutKind;
};

export type CommandAsset = { id: string; kind?: string; uri?: string; mime?: string };
export type CommandProject = { id: string; title: string; blurb?: string; page?: PageId };
/** A model row from the Image or Video flyout. Ctrl+K lists these same rows. */
export type CommandModel = { id: string; title: string; blurb?: string; page: PageId; flyout: FlyoutKind };

export type RailItem = {
  id: PageId;
  title: string;
  icon: string;
  flyout?: FlyoutKind;
};

export type RailGroup = { label?: string; items: RailItem[] };

export type FlyoutFeature = { id: PageId; title: string; blurb: string };

/** Pages that existed on the 15-item rail. Each must stay reachable. */
export const LEGACY_PAGES: PageId[] = [
  "explore",
  "image",
  "adapts",
  "video",
  "speak",
  "upscale",
  "canvas",
  "library",
  "agent",
  "space",
  "collab",
  "skills",
  "find",
  "cost",
  "keys",
];

export const PIN_STORAGE_KEY = "vinci-pinned-tools-v1";
export const COLLAPSE_STORAGE_KEY = "vinci-sidebar-collapsed-v1";

/** Magnific All-tools tabs. Empty categories stay hidden in the popover. */
export const TOOL_CATEGORIES: ("all" | ToolCategory)[] = [
  "all",
  "image",
  "video",
  "audio",
  "edit",
  "canvas",
  "library",
  "templates",
  "utilities",
];

export const TAB_LABEL: Record<string, string> = {
  all: "All",
  image: "Image",
  video: "Video",
  audio: "Audio",
  edit: "Edit",
  canvas: "Canvas",
  library: "Library",
  templates: "Templates",
  utilities: "Utilities",
  motion: "Motion",
  upscale: "Upscale",
  cinema: "Cinema",
  ads: "Ads",
  clips: "Clips",
  elements: "Elements",
  shots: "Shots",
};

export function tabLabel(id: string): string {
  return TAB_LABEL[id] || id.slice(0, 1).toUpperCase() + id.slice(1);
}

/**
 * The only Studio rail. Image and Video open Features|Models flyouts.
 * Labels show on hover; below 960px the same list is the menu drawer.
 */
export const RAIL_GROUPS: RailGroup[] = [
  {
    items: [{ id: "explore", title: "Explore", icon: "M9 2a7 7 0 1 1 0 14A7 7 0 0 1 9 2zm0 2v5l3 2" }],
  },
  {
    label: "Formats",
    items: [
      { id: "image", title: "Image", icon: "M3 4h12v10H3zM3 12l3-3 2 2 2-2 4 4", flyout: "image" },
      { id: "video", title: "Video", icon: "M2.5 5h9v8h-9zM11.5 8l4-2v6l-4-2z", flyout: "video" },
    ],
  },
  {
    label: "Workflows",
    items: [
      { id: "canvas", title: "Canvas", icon: "M3 4h5v4H3zM10 10h5v4h-5zM8 6h3v4" },
      { id: "library", title: "Library", icon: "M3 4h4v11H3zM8 4h3v11H8zM12.5 4.5L15 15" },
    ],
  },
];

/** Text buttons under the format groups. Same pages as the daemon rail. */
export const RAIL_FOOTER: { id: PageId; title: string }[] = [
  { id: "skills", title: "Skills" },
  { id: "find", title: "Find" },
  { id: "cost", title: "Cost report" },
  { id: "keys", title: "Connect" },
];

/** Feature column of the Image and Video flyouts. All tools lists these rows. */
export const FLYOUT_FEATURES: Record<FlyoutKind, FlyoutFeature[]> = {
  image: [
    { id: "image", title: "Create Image", blurb: "Make a still from a prompt or a reference" },
    { id: "upscale", title: "Upscale Still", blurb: "Make a still sharper" },
    { id: "adapts", title: "Adapts", blurb: "Resize one still into ad sizes" },
  ],
  video: [
    { id: "video", title: "Create Video", blurb: "Make a clip from a prompt or a still" },
    { id: "speak", title: "Talking Head", blurb: "A still that speaks a line" },
  ],
};

/** True when this rail row is the current page, including its flyout features. */
export function railItemOn(item: RailItem, page: PageId): boolean {
  if (item.flyout === "image") return page === "image" || page === "upscale" || page === "adapts";
  if (item.flyout === "video") return page === "video" || page === "speak";
  return page === item.id;
}

/**
 * Index rows for the format rail and its flyouts. All tools and Ctrl+K
 * search this list. Pin stays inside All tools; it does not add a rail icon.
 */
const RAIL_INDEX: Tool[] = [
  { id: "explore", title: "Explore", blurb: "Starter templates on this computer", page: "explore", category: "templates", pinable: true },
  { id: "image", title: "Create Image", blurb: "Make a still from a prompt or a reference", page: "image", category: "image", pinable: false },
  { id: "upscale", title: "Upscale Still", blurb: "Make a still sharper", page: "upscale", category: "edit", pinable: true },
  { id: "adapts", title: "Adapts", blurb: "Resize one still into ad sizes", page: "adapts", category: "edit", pinable: true },
  { id: "video", title: "Create Video", blurb: "Make a clip from a prompt or a still", page: "video", category: "video", pinable: false },
  { id: "speak", title: "Talking Head", blurb: "A still that speaks a line", page: "speak", category: "audio", pinable: false },
  { id: "canvas", title: "Canvas", blurb: "Chain steps on the board", page: "canvas", category: "canvas", pinable: false },
  { id: "library", title: "Library", blurb: "People, places, props, and styles to @mention", page: "library", category: "library", pinable: false },
  { id: "skills", title: "Skills", blurb: "Workflows installed on this computer", page: "skills", category: "templates", pinable: true },
  { id: "find", title: "Find", blurb: "Search files on this computer", page: "find", category: "utilities", pinable: true },
  { id: "cost", title: "Cost report", blurb: "What you have spent, by provider", page: "cost", category: "utilities", pinable: true },
  { id: "keys", title: "Connect", blurb: "Add a provider key", page: "keys", category: "utilities", pinable: true },
];

/**
 * Pages with no format-rail slot. They share the All tools / Ctrl+K index
 * and are not drawn as a second rail.
 */
export const OFF_RAIL_TOOLS: Tool[] = [
  { id: "home", title: "Home", blurb: "Templates on this computer", page: "home", category: "templates", pinable: true },
  { id: "edit", title: "Edit", blurb: "Tools that start from a file you upload", page: "edit", category: "edit", pinable: false },
  { id: "assets", title: "Assets", blurb: "Everything you have made", page: "assets", category: "library", pinable: false },
  { id: "agent", title: "Supercomputer", blurb: "Describe a job. Get steps you can run.", page: "agent", category: "utilities", pinable: true },
  { id: "space", title: "3D", blurb: "Turn the last still and make a new angle", page: "space", category: "utilities", pinable: true },
  { id: "collab", title: "Collab", blurb: "Share a session on this computer", page: "collab", category: "utilities", pinable: true },
];

/** All tools and Ctrl+K. Rail entries first, then pages that have no rail slot. */
export const TOOLS: Tool[] = [...RAIL_INDEX, ...OFF_RAIL_TOOLS];

/** Keys / Cost / moved rail pages. Magnific avatar menu. */
export const AVATAR_MENU: { id: string; title: string; page: PageId }[] = [
  { id: "keys", title: "Connect", page: "keys" },
  { id: "settings", title: "Settings", page: "settings" },
  { id: "cost", title: "Cost report", page: "cost" },
  { id: "agent", title: "Supercomputer", page: "agent" },
  { id: "space", title: "3D", page: "space" },
  { id: "collab", title: "Collab", page: "collab" },
  { id: "find", title: "Find", page: "find" },
];

/** Score a haystack. Prefix beats a word prefix beats a substring. Miss is -1. */
function hitScore(haystack: string, query: string): number {
  const h = haystack.toLowerCase();
  if (h.startsWith(query)) return 0;
  if (h.split(/[^a-z0-9]+/).some((word) => word.startsWith(query))) return 1;
  return h.includes(query) ? 2 : -1;
}

/**
 * All-tools rows for `query` and `category`. Empty query keeps catalog order.
 * Typing filters the active tab the way Magnific filters as you type.
 */
export function filterTools(query: string, category: string = "all", tools: readonly Tool[] = TOOLS): Tool[] {
  const tab = category.trim().toLowerCase() || "all";
  const rows = tab === "all" ? tools.slice() : tools.filter((tool) => tool.category === tab);
  const q = query.trim().toLowerCase();
  if (!q) return rows;
  return rows
    .map((tool, index) => ({
      tool,
      index,
      score: Math.min(
        ...[tool.title, tool.blurb, tool.category, tool.page].map((part) => hitScore(part, q)).filter((n) => n >= 0),
        99,
      ),
    }))
    .filter((row) => row.score < 99)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map((row) => row.tool);
}

/** Tabs that still have a row after the current query. */
export function visibleCategories(query: string, tools: readonly Tool[] = TOOLS): ("all" | ToolCategory)[] {
  return TOOL_CATEGORIES.filter((tab) => tab === "all" || filterTools(query, tab, tools).length > 0);
}

/**
 * Pin a pinable tool. Core sidebar tools are ignored. Order is pin order.
 */
export function pinTool(pinned: readonly string[], id: string, tools: readonly Tool[] = TOOLS): string[] {
  const tool = tools.find((row) => row.id === id);
  if (!tool || !tool.pinable) return pinned.slice();
  if (pinned.includes(id)) return pinned.slice();
  return [...pinned, id];
}

/** Drop a pinned id. Unknown ids are ignored. */
export function unpinTool(pinned: readonly string[], id: string): string[] {
  return pinned.filter((row) => row !== id);
}

/** Toggle pin. Returns the next list. */
export function togglePin(pinned: readonly string[], id: string, tools: readonly Tool[] = TOOLS): string[] {
  return pinned.includes(id) ? unpinTool(pinned, id) : pinTool(pinned, id, tools);
}

/** Pinned tools that still exist, in pin order, for the sidebar strip. */
export function sidebarPins(pinned: readonly string[], tools: readonly Tool[] = TOOLS): Tool[] {
  const known = new Map(tools.map((tool) => [tool.id, tool]));
  const rows: Tool[] = [];
  for (const id of pinned) {
    const tool = known.get(id);
    if (tool && tool.pinable) rows.push(tool);
  }
  return rows;
}

export function parsePinned(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((id): id is string => typeof id === "string" && id.length > 0);
  } catch {
    return [];
  }
}

export function serializePinned(ids: readonly string[]): string {
  return JSON.stringify(sidebarPins(ids).map((tool) => tool.id));
}

export function parseCollapsed(raw: string | null | undefined): boolean {
  return raw === "1" || raw === "true";
}

/** Pages drawn on the format rail (groups, flyout features, and the footer). */
export function railPageIds(): PageId[] {
  const ids: PageId[] = [];
  const push = (id: PageId) => {
    if (!ids.includes(id)) ids.push(id);
  };
  for (const group of RAIL_GROUPS) for (const item of group.items) push(item.id);
  for (const kind of ["image", "video"] as const) for (const row of FLYOUT_FEATURES[kind]) push(row.id);
  for (const row of RAIL_FOOTER) push(row.id);
  return ids;
}

/** Visible label for a command asset row. The id and uri stay searchable, not shown. */
function assetLabel(asset: CommandAsset): string {
  const kind = (asset.kind || asset.mime?.split("/")[0] || "file").toLowerCase();
  if (kind === "image") return "Image";
  if (kind === "video") return "Video";
  if (kind === "audio") return "Audio";
  return "File";
}

/**
 * Ctrl+K rows. Empty query lists tools and, when passed, the flyout models.
 * A typed query also matches assets and projects (templates / collab sessions).
 */
export function commandSearch(
  query: string,
  extras: {
    assets?: readonly CommandAsset[];
    projects?: readonly CommandProject[];
    /** Same model rows the Image and Video flyouts show. */
    models?: readonly CommandModel[];
  } = {},
  tools: readonly Tool[] = TOOLS,
): CommandHit[] {
  const q = query.trim().toLowerCase();
  const toolHits: CommandHit[] = filterTools(query, "all", tools).map((tool) => ({
    kind: "tool" as const,
    id: tool.id,
    title: tool.title,
    blurb: tool.blurb,
    page: tool.page,
  }));
  const modelHits: CommandHit[] = (extras.models || [])
    .map((model, index) => {
      const blurb = model.blurb || "model";
      const score = q
        ? Math.min(...[model.id, model.title, blurb, model.flyout].map((part) => hitScore(part, q)).filter((n) => n >= 0), 99)
        : 0;
      return { model, index, score, blurb };
    })
    .filter((row) => row.score < 99)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map((row) => ({
      kind: "model" as const,
      id: row.model.id,
      title: row.model.title,
      blurb: row.blurb,
      page: row.model.page,
      flyout: row.model.flyout,
    }));
  if (!q) return [...toolHits, ...modelHits];
  const assetHits: CommandHit[] = (extras.assets || [])
    .map((asset, index) => {
      const score = Math.min(
        ...[asset.id, asset.uri, asset.kind, asset.mime]
          .filter((part): part is string => typeof part === "string")
          .map((part) => hitScore(part, q))
          .filter((n) => n >= 0),
        99,
      );
      return { asset, index, score };
    })
    .filter((row) => row.score < 99)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map((row) => ({
      kind: "asset" as const,
      id: row.asset.id,
      title: assetLabel(row.asset),
      blurb: "In your library",
      page: "assets" as PageId,
    }));
  const projectHits: CommandHit[] = (extras.projects || [])
    .map((project, index) => {
      const blurb = project.blurb || "project";
      const score = Math.min(
        ...[project.title, blurb, project.id].map((part) => hitScore(part, q)).filter((n) => n >= 0),
        99,
      );
      return { project, index, score, blurb };
    })
    .filter((row) => row.score < 99)
    .sort((a, b) => a.score - b.score || a.index - b.index)
    .map((row) => ({
      kind: "project" as const,
      id: row.project.id,
      title: row.project.title,
      blurb: row.blurb,
      page: row.project.page,
    }));
  return [...toolHits, ...modelHits, ...assetHits, ...projectHits];
}

/** Wrap the highlighted command row. */
export function moveCommandIndex(index: number, delta: number, count: number): number {
  if (count <= 0) return 0;
  return (((index + delta) % count) + count) % count;
}

export function pickCommandHit(hits: readonly CommandHit[], index: number): CommandHit | null {
  if (!hits.length) return null;
  return hits[moveCommandIndex(index, 0, hits.length)] || null;
}

/** True when this key opens the Magnific command box. */
export function isCommandHotkey(ev: { key: string; metaKey?: boolean; ctrlKey?: boolean }): boolean {
  return (Boolean(ev.metaKey) || Boolean(ev.ctrlKey)) && ev.key.toLowerCase() === "k";
}

/** Union of the All tools index and the avatar menu. Used to prove no page is lost. */
export function reachablePages(
  tools: readonly Tool[] = TOOLS,
  menu: readonly { page: PageId }[] = AVATAR_MENU,
): PageId[] {
  const pages = new Set<PageId>();
  for (const tool of tools) pages.add(tool.page);
  for (const item of menu) pages.add(item.page);
  return [...pages];
}

/** Higgsfield Edit index: upload-first tools only. */
export function editTools(tools: readonly Tool[] = TOOLS): Tool[] {
  return tools.filter((tool) => tool.category === "edit" && tool.id !== "edit");
}
