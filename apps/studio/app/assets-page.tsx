"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { importToPhotos, isMacNativeShell, revealInFinder } from "../lib/mac-native";
import {
  LIBRARY_API,
  groupLibraryItems,
  libraryFileUrl,
  type LibraryFacets,
  type LibraryItem,
  type LibraryResponse,
  type LibraryStatus,
} from "./library-types";
import { plainError } from "./ui/plain-text";
import { DockIcon, DOCK_ICON } from "./ui/icons";

export type { LibraryItem, LibraryResponse, LibraryStatus } from "./library-types";

const DATE_PRESETS = [
  { id: "all", label: "Any date" },
  { id: "today", label: "Today" },
  { id: "7d", label: "Last 7 days" },
  { id: "30d", label: "Last 30 days" },
];

const SECTIONS = [
  { id: "assets", label: "Assets" },
  { id: "projects", label: "Projects" },
  { id: "favorites", label: "Favorites" },
  { id: "elements", label: "Elements" },
  { id: "trash", label: "Trash" },
] as const;

const TYPES = [
  { id: "", label: "All" },
  { id: "image", label: "Images" },
  { id: "video", label: "Video" },
  { id: "audio", label: "Audio" },
  { id: "enhanced", label: "Enhanced" },
] as const;

export type CastElement = { name: string; assetId: string; kind?: string };

function kindLabel(kind: string): string {
  if (kind === "image") return "Image";
  if (kind === "video") return "Video";
  if (kind === "audio") return "Audio";
  return "File";
}

function savedWhere(kind: string): string {
  if (kind === "local") return "Saved to a folder";
  if (kind === "photos") return "Saved to Photos";
  if (kind === "r2") return "Saved to a bucket";
  return "Saved in the app";
}

export function AssetsPage({
  elements,
  focusId,
  onRerun,
  onOpenConnect,
}: {
  elements: CastElement[];
  /** Ctrl+K asset hit. Marks that card when the index includes it. */
  focusId?: string | null;
  onRerun: (item: LibraryItem) => void;
  onOpenConnect: () => void;
}) {
  const [section, setSection] = useState<(typeof SECTIONS)[number]["id"]>("assets");
  const [tool, setTool] = useState("");
  const [date, setDate] = useState("all");
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [facets, setFacets] = useState<LibraryFacets>({ kinds: [], models: [], providers: [] });
  const [status, setStatus] = useState<LibraryStatus | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const mac = isMacNativeShell();

  const load = useCallback(async (next?: { q?: string }) => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    params.set("section", section);
    if (tool) params.set("tool", tool);
    if (date !== "all") params.set("date", date);
    const q = next?.q ?? query;
    if (q.trim()) params.set("q", q.trim());
    try {
      const res = await fetch(`${LIBRARY_API}/library?${params.toString()}`);
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
      const body = (await res.json()) as LibraryResponse;
      setItems(body.items || []);
      setFacets(body.facets || { kinds: [], models: [], providers: [] });
      setStatus(body.status);
      setSelected(new Set());
      setOpenId(null);
    } catch (err) {
      setError(plainError(err));
    } finally {
      setLoading(false);
    }
  }, [date, query, section, tool]);

  useEffect(() => {
    void load();
  }, [load]);

  const groups = useMemo(() => groupLibraryItems(items), [items]);
  const openItem = items.find((row) => row.id === openId) || null;

  async function copyPrompt(item: LibraryItem) {
    try {
      await navigator.clipboard.writeText(item.prompt || "");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  async function favorite(item: LibraryItem) {
    setBusyId(item.id);
    try {
      const res = await fetch(`${LIBRARY_API}/library/items/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ favorite: !item.favorite }),
      });
      if (!res.ok) throw new Error(res.statusText);
      await load();
    } catch (err) {
      setError(plainError(err));
    } finally {
      setBusyId(null);
    }
  }

  async function trash(ids: string[]) {
    setBusyId(ids[0] || null);
    try {
      for (const id of ids) {
        const res = await fetch(`${LIBRARY_API}/library/items/${encodeURIComponent(id)}`, { method: "DELETE" });
        if (!res.ok) throw new Error(res.statusText);
      }
      await load();
    } catch (err) {
      setError(plainError(err));
    } finally {
      setBusyId(null);
    }
  }

  async function restore(ids: string[]) {
    setBusyId(ids[0] || null);
    try {
      for (const id of ids) {
        const res = await fetch(`${LIBRARY_API}/library/items/${encodeURIComponent(id)}/restore`, { method: "POST" });
        if (!res.ok) throw new Error(res.statusText);
      }
      await load();
    } catch (err) {
      setError(plainError(err));
    } finally {
      setBusyId(null);
    }
  }

  function toggle(id: string) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleGroup(ids: string[]) {
    setSelected((cur) => {
      const next = new Set(cur);
      const allOn = ids.every((id) => next.has(id));
      for (const id of ids) {
        if (allOn) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }

  const reason = status?.reason || (loading ? "loading" : "ready");
  const noRows = !loading && !error && items.length === 0 && section !== "elements";
  const freshEmpty = noRows && section === "assets" && reason === "empty";
  const showGrid = !loading && !error && items.length > 0 && section !== "elements";

  return (
    <div className="assets-page" data-testid="assets-page">
      <aside className="assets-nav" data-testid="assets-nav">
        <p className="eyebrow">Library</p>
        {SECTIONS.map((row) => (
          <button
            key={row.id}
            type="button"
            className={section === row.id ? "on" : ""}
            data-testid={`assets-section-${row.id}`}
            onClick={() => setSection(row.id)}
          >
            {row.label}
          </button>
        ))}
        <p className="eyebrow">Type</p>
        {TYPES.map((row) => (
          <button
            key={row.id || "all"}
            type="button"
            className={tool === row.id ? "on" : ""}
            data-testid={`assets-type-${row.id || "all"}`}
            onClick={() => setTool(row.id)}
          >
            {row.label}
          </button>
        ))}
      </aside>
      <div className="assets-main">
        <header className="assets-head">
          <h2>{SECTIONS.find((row) => row.id === section)?.label || "Assets"}</h2>
          <form
            className="assets-toolbar"
            onSubmit={(ev) => {
              ev.preventDefault();
              setQuery(draft);
            }}
          >
            <label className="assets-search">
              Search
              <input
                data-testid="assets-search"
                value={draft}
                onChange={(ev) => setDraft(ev.target.value)}
                placeholder="Search by prompt"
              />
            </label>
            <label>
              Date
              <select data-testid="assets-date" value={date} onChange={(ev) => setDate(ev.target.value)}>
                {DATE_PRESETS.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="ghost" type="submit">
              Search
            </button>
          </form>
        </header>

        {loading ? <p className="muted" data-testid="assets-loading">Loading…</p> : null}
        {error ? (
          <div className="assets-empty" data-testid="assets-error">
            <h3>Could not load your files</h3>
            <p className="muted">{error}</p>
            <button className="run" type="button" onClick={() => void load()}>
              Try again
            </button>
          </div>
        ) : null}

        {!loading && !error && section === "projects" && items.length > 0 ? (
          <div className="assets-project" data-testid="assets-project">
            <strong>This Studio</strong>
            <span className="muted">{status?.total || items.length} files on this computer</span>
          </div>
        ) : null}

        {!loading && !error && section === "elements" ? (
          <div className="assets-elements" data-testid="assets-elements">
            {elements.length === 0 ? (
              <div className="assets-empty">
                <h3>No people, places, or props yet</h3>
                <p className="muted">Add a person, place, or prop from Image or the canvas.</p>
              </div>
            ) : (
              <div className="assets-masonry">
                {elements.map((row) => (
                  <article key={row.assetId + row.name} className="assets-card">
                    <img src={`${LIBRARY_API}/assets/${row.assetId}/file`} alt="" />
                    <strong>{row.name}</strong>
                    <span className="muted">{row.kind || "Item"}</span>
                  </article>
                ))}
              </div>
            )}
          </div>
        ) : null}

        {freshEmpty ? (
          <div className="assets-empty" data-testid="assets-empty">
            <h3>Nothing here yet</h3>
            <p className="muted">
              Make a still or a clip. Finished work shows up here.
            </p>
            <button className="run" type="button" onClick={onOpenConnect}>
              Open Connect
            </button>
          </div>
        ) : null}
        {noRows && !freshEmpty ? (
          <div className="assets-empty" data-testid="assets-filtered-empty">
            <h3>{section === "trash" ? "Trash is empty" : "Nothing matches"}</h3>
            <p className="muted">
              {section === "favorites"
                ? "Mark a file as a favorite. Hover it and press the heart."
                : "Clear the search, or widen the type and date."}
            </p>
          </div>
        ) : null}

        {showGrid ? (
          <div className="assets-groups" data-testid="assets-grid">
            {groups.map((group) => {
              const ids = group.items.map((row) => row.id);
              const allOn = ids.every((id) => selected.has(id));
              return (
                <section key={group.key} className="assets-group" data-testid="assets-group">
                  <header className="assets-group-head">
                    <label>
                      <input
                        type="checkbox"
                        data-testid="assets-select-all"
                        checked={allOn}
                        onChange={() => toggleGroup(ids)}
                      />
                      Select all
                    </label>
                    <strong>{group.label}</strong>
                    <span className="muted">{group.items.length}</span>
                  </header>
                  <div className="assets-masonry">
                    {group.items.map((item) => (
                      <article
                        key={item.id}
                        className={"assets-card" + (selected.has(item.id) || item.id === focusId ? " on" : "")}
                        data-asset={item.id}
                      >
                        <label className="assets-check">
                          <input
                            type="checkbox"
                            checked={selected.has(item.id)}
                            onChange={() => toggle(item.id)}
                          />
                        </label>
                        <button type="button" className="assets-thumb" onClick={() => setOpenId(item.id)}>
                          {item.media_missing ? (
                            <span className="assets-ph">{kindLabel(item.media_kind)}</span>
                          ) : item.media_kind === "video" ? (
                            <video src={libraryFileUrl(item.id)} muted playsInline />
                          ) : item.media_kind === "audio" ? (
                            <span className="assets-ph">Audio</span>
                          ) : (
                            <img src={libraryFileUrl(item.id)} alt="" />
                          )}
                        </button>
                        <div className="assets-hover">
                          <button type="button" aria-label="Favorite" onClick={() => void favorite(item)}>
                            {item.favorite ? "♥" : "♡"}
                          </button>
                          <a
                            href={libraryFileUrl(item.id)}
                            download={`vinci-${item.asset_id.slice(0, 12) || item.id}`}
                            aria-label="Download"
                          >
                            ↓
                          </a>
                          <button type="button" className="icon-btn" aria-label="Copy prompt" onClick={() => void copyPrompt(item)}>
                            <DockIcon d={DOCK_ICON.copy} />
                            <span className="dock-tip">Copy prompt</span>
                          </button>
                          <button
                            type="button"
                            className="icon-btn"
                            data-testid="assets-more"
                            aria-label="More actions"
                            onClick={() => setMenuId(menuId === item.id ? null : item.id)}
                          >
                            <DockIcon d={DOCK_ICON.more} />
                            <span className="dock-tip">More actions</span>
                          </button>
                          {menuId === item.id ? (
                            <div className="assets-more" data-testid="assets-hover-menu">
                              {mac && item.local && !item.media_missing ? (
                                <>
                                  <button
                                    type="button"
                                    data-testid="assets-reveal-finder"
                                    onClick={() => revealInFinder(item.media_path)}
                                  >
                                    Reveal in Finder
                                  </button>
                                  <button
                                    type="button"
                                    data-testid="assets-save-photos"
                                    onClick={() => importToPhotos(item.media_path, item.photos_album || "Vinci")}
                                  >
                                    Save to Photos
                                  </button>
                                </>
                              ) : null}
                              <button type="button" onClick={() => onRerun(item)}>
                                Re-run
                              </button>
                              {section === "trash" ? (
                                <button type="button" onClick={() => void restore([item.id])}>
                                  Restore
                                </button>
                              ) : (
                                <button type="button" onClick={() => void trash([item.id])}>
                                  Delete
                                </button>
                              )}
                            </div>
                          ) : null}
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        ) : null}

        {selected.size > 0 ? (
          <div className="assets-selection" data-testid="assets-selection">
            <span>{selected.size} selected</span>
            {section === "trash" ? (
              <button className="run" type="button" disabled={!!busyId} onClick={() => void restore([...selected])}>
                Restore
              </button>
            ) : (
              <button className="ghost" type="button" disabled={!!busyId} onClick={() => void trash([...selected])}>
                Delete
              </button>
            )}
          </div>
        ) : null}

        {openItem ? (
          <div className="assets-overlay" data-testid="assets-overlay" onClick={() => setOpenId(null)}>
            <div className="assets-overlay-card" onClick={(ev) => ev.stopPropagation()}>
              {openItem.media_kind === "video" ? (
                <video src={libraryFileUrl(openItem.id)} controls />
              ) : openItem.media_kind === "audio" ? (
                <audio src={libraryFileUrl(openItem.id)} controls />
              ) : (
                <img src={libraryFileUrl(openItem.id)} alt="" />
              )}
              <p>{openItem.prompt || "Untitled"}</p>
              <p className="muted">
                {savedWhere(openItem.destination_kind)}
              </p>
              <div className="file-row">
                <button className="run" type="button" onClick={() => onRerun(openItem)}>
                  Re-run
                </button>
                <button className="ghost" type="button" onClick={() => void copyPrompt(openItem)}>
                  Copy prompt
                </button>
                <button className="ghost" type="button" onClick={() => setOpenId(null)}>
                  Close
                </button>
              </div>
            </div>
          </div>
        ) : null}
        <p className="muted assets-hint">{facets.kinds.length ? facets.kinds.join(" · ") : ""}</p>
      </div>
    </div>
  );
}
