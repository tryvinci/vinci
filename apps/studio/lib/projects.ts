/**
 * Studio projects (COREPRODUC-702): a project groups a person's Image, Video and Canvas work, so
 * several projects can run side by side without mixing.
 *
 * The project lives in the visible URL (`/studio?project=<id>#image`), not in a global "current
 * project", so each tab or window keeps its own. Changing project reloads the Studio at the new URL:
 * no board, feed or draft carries over. The daemon and the host answer `/projects` (see
 * docs/VINCI_OSS_RUNTIME.md, section 7); a backend without it leaves projects off and the Studio
 * works as before.
 */

export type Project = {
  id: string;
  name: string;
  default: boolean;
  board_rev: number;
  archived_at: string | null;
  updated_at: string;
};

/** The project this tab opened last, for a new tab with no `?project=`. A convenience only. */
export const LAST_PROJECT_KEY = "vinci-last-project-v1";

let current: string | null = null;
let named = false; // the tab's project is not the default one

/** The tab's project id, or null while projects are off (or not picked yet). */
export function currentProject(): string | null {
  return current;
}

export function setCurrentProject(id: string | null, isDefault = false): void {
  current = id;
  named = Boolean(id) && !isDefault;
}

/** A browser storage key for the tab's project. My work keeps the plain key, so what it kept before projects stays. */
export function projectKey(key: string): string {
  return named ? `${key}:${current}` : key;
}

/** The `?project=` of a URL search string ("" when none). */
export function projectFromSearch(search: string): string {
  return new URLSearchParams(search).get("project") || "";
}

/**
 * The project a tab opens: the URL's, else the one opened last, else the default one. An archived
 * or unknown id falls through to the next choice.
 *
 * Args:
 *   projects: `GET /projects`.
 *   asked: The URL's `?project=`.
 *   last: The id kept under `LAST_PROJECT_KEY`.
 */
export function pickProject(projects: readonly Project[], asked: string, last: string): Project | null {
  const open = projects.filter((p) => !p.archived_at);
  return open.find((p) => p.id === asked) || open.find((p) => p.id === last) || open.find((p) => p.default) || open[0] || null;
}

/**
 * A URL with `?project=<id>`, keeping its other query values and its hash.
 *
 * Args:
 *   href: The current URL.
 *   id: The project to open.
 */
export function projectHref(href: string, id: string): string {
  const url = new URL(href);
  url.searchParams.set("project", id);
  return url.toString();
}

/** A GET path with the tab's project added (`/runs` → `/runs?project=…`); unchanged while projects are off. */
export function withProject(path: string): string {
  if (!current) return path;
  return `${path}${path.includes("?") ? "&" : "?"}project=${encodeURIComponent(current)}`;
}

/** A POST /runs body with the tab's project, so the run stays in it. */
export function runBody<T extends object>(payload: T): T & { project_id?: string } {
  return current ? { ...payload, project_id: current } : payload;
}

/** An upload form with the tab's project. */
export function uploadForm(file: Blob, name?: string): FormData {
  const data = new FormData();
  if (name) data.append("file", file, name);
  else data.append("file", file);
  if (current) data.append("project_id", current);
  return data;
}

/** Projects for the switcher: open ones, last changed first, that match the search words. */
export function filterProjects(projects: readonly Project[], query: string): Project[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return projects
    .filter((p) => !p.archived_at && words.every((w) => p.name.toLowerCase().includes(w)))
    .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
}

/** A saved board and its revision; `board` is null before the first save. */
export type SavedBoard = { board: unknown; board_rev: number };

/**
 * Save a project's board. Resolves to the new revision, or null when another window saved first
 * (HTTP 409): the caller then stops saving and asks for a reload.
 *
 * Args:
 *   base: The API base (`/vinci-api`).
 *   id: The project.
 *   board: The `ProjectFile` (pages, comments, viewports).
 *   rev: The revision this board was loaded or last saved at.
 */
export async function saveBoard(base: string, id: string, board: unknown, rev: number): Promise<number | null> {
  const res = await fetch(`${base}/projects/${encodeURIComponent(id)}/board`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ board, board_rev: rev }),
  });
  if (res.status === 409) {
    console.warn("[projects] board save refused: another window saved first", { id, rev });
    return null;
  }
  if (!res.ok) throw new Error(`The board was not saved (HTTP ${res.status}).`);
  const saved = (await res.json()) as { board_rev: number };
  console.info("[projects] board saved", { id, board_rev: saved.board_rev });
  return saved.board_rev;
}
