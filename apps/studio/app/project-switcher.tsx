"use client";

import { useEffect, useRef, useState } from "react";

import { filterProjects, projectHref, type Project } from "../lib/projects";
import { topWindow } from "./url-part";

const API = "/vinci-api";

type Props = {
  projects: readonly Project[];
  active: Project;
  /** Shows a reason in the top bar (a refused rename, a failed create). */
  onError: (message: string) => void;
};

/** The project's own URL: the visible URL with `?project=<id>` (the hash, the page, stays). */
function hrefOf(id: string): string {
  return projectHref(topWindow().location.href, id);
}

/** Open a project in this tab: the Studio reloads there, so nothing of this project carries over. */
function openProject(id: string): void {
  console.info("[projects] open", { id });
  topWindow().location.assign(hrefOf(id));
}

async function send(path: string, method: string, body: object): Promise<Project> {
  const res = await fetch(`${API}${path}`, { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const data = (await res.json().catch(() => ({}))) as Project & { detail?: string };
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

/**
 * The project switcher in the top bar (COREPRODUC-702): the tab's project, a search, the open
 * projects (a link each, so Cmd-click opens a new tab), New project, Rename and Archive.
 */
export function ProjectSwitcher({ projects, active, onError }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  /** "new" or "rename": the name field is open for that action. */
  const [naming, setNaming] = useState<"new" | "rename" | null>(null);
  const [name, setName] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (ev: Event) => {
      if (ev instanceof KeyboardEvent ? ev.key === "Escape" : !boxRef.current?.contains(ev.target as Node)) {
        setOpen(false);
        setNaming(null);
      }
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", close);
    };
  }, [open]);

  async function submitName() {
    const words = name.trim();
    if (!words) return;
    try {
      if (naming === "new") {
        openProject((await send("/projects", "POST", { name: words })).id);
      } else {
        await send(`/projects/${encodeURIComponent(active.id)}`, "PATCH", { name: words });
        openProject(active.id); // the new name everywhere: tab title, menus
      }
    } catch (err) {
      onError(`Project not saved: ${(err as Error).message}`);
    }
  }

  async function archive() {
    try {
      await send(`/projects/${encodeURIComponent(active.id)}`, "PATCH", { archived: true });
      openProject(projects.find((p) => p.default)?.id || "");
    } catch (err) {
      onError(`Project not archived: ${(err as Error).message}`);
    }
  }

  const rows = filterProjects(projects, query);
  return (
    <div className="project-switch" ref={boxRef}>
      <button
        type="button"
        className="project-switch-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Switch project"
        data-testid="project-switch"
        onClick={() => setOpen((now) => !now)}
      >
        <span className="project-switch-name">{active.name}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 4l3 3 3-3" fill="none" stroke="currentColor" />
        </svg>
      </button>
      {open ? (
        <div className="project-menu" role="menu" aria-label="Projects">
          {naming ? (
            <form
              onSubmit={(ev) => {
                ev.preventDefault();
                void submitName();
              }}
            >
              <input
                autoFocus
                value={name}
                maxLength={120}
                aria-label={naming === "new" ? "New project name" : "Project name"}
                placeholder="Project name"
                onChange={(ev) => setName(ev.target.value)}
              />
              <button type="submit" className="run" disabled={!name.trim()}>
                {naming === "new" ? "Create" : "Rename"}
              </button>
            </form>
          ) : (
            <>
              {projects.length > 6 ? (
                <input autoFocus value={query} aria-label="Search projects" placeholder="Search projects" onChange={(ev) => setQuery(ev.target.value)} />
              ) : null}
              <div className="project-menu-list">
                {rows.map((p) => (
                  // A link: a click opens it here, Cmd-click or a middle click in a new tab.
                  <a key={p.id} role="menuitem" href={hrefOf(p.id)} target="_top" className={p.id === active.id ? "on" : ""} aria-current={p.id === active.id ? "true" : undefined}>
                    {p.name}
                  </a>
                ))}
                {rows.length === 0 ? <p className="muted">No project has that name.</p> : null}
              </div>
              <div className="project-menu-actions">
                <button type="button" role="menuitem" onClick={() => { setName(""); setNaming("new"); }}>
                  New project
                </button>
                <button type="button" role="menuitem" onClick={() => { setName(active.name); setNaming("rename"); }}>
                  Rename
                </button>
                {active.default ? null : (
                  <button type="button" role="menuitem" onClick={() => void archive()}>
                    Archive
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
