"use client";

import { useState } from "react";
import {
  BIBLE_KINDS,
  OLF_API,
  type OlfEntry,
  type OlfShow,
  entryName,
  episodeGroups,
  episodeOf,
  findEntry,
  issueCounts,
  neighbors,
  seasonLabel,
  shownKeyframe,
  takesOf,
} from "../lib/shows";
import { StalePill, StatusPill } from "./shows-parts";

/** Where the Shows page is. Storyboard and Shots belong to an episode; a shot opens its own page. */
export type Route =
  | { view: "storyboard" | "shots" | "cut"; episode: string }
  | { view: "shot"; shot: string }
  | { view: "bible"; entry: string }
  | { view: "issues" };

/** The episode a route belongs to (bible and issues fall back to the first episode). */
export function routeEpisode(show: OlfShow, route: Route): string | undefined {
  if (route.view === "storyboard" || route.view === "shots" || route.view === "cut") return route.episode;
  // A shot ID starts with its episode ID (`e02/s03/sh014`), even after the shot leaves the show.
  if (route.view === "shot") return route.shot.split("/")[0];
  return episodeGroups(show)[0]?.episodes[0]?.id;
}

/**
 * Bible groups as in the design: characters, locations, then props and voices together. Camerawork
 * (the show's camera templates) comes last; an older daemon sends no such list.
 */
function bibleGroups(show: OlfShow): { label: string; rows: OlfEntry[] }[] {
  return [
    { label: "Characters", rows: show.bible.character },
    { label: "Locations", rows: show.bible.location },
    { label: "Props · Voices", rows: [...show.bible.prop, ...show.bible.voice] },
    { label: "Camerawork", rows: show.bible.camerawork || [] },
  ].filter((group) => group.rows.length);
}

/** The sections of a show, in the design's order. Cut opens full width with tabs in the top bar. */
function sections(show: OlfShow, route: Route, episode: string) {
  return [
    { id: "bible", label: "Bible", on: route.view === "bible", go: { view: "bible", entry: show.bible.character[0]?.id || "style" } },
    { id: "storyboard", label: "Storyboard", on: route.view === "storyboard", go: { view: "storyboard", episode } },
    { id: "shots", label: "Shots", on: route.view === "shots", go: { view: "shots", episode } },
    { id: "cut", label: "Cut", on: route.view === "cut", go: { view: "cut", episode } },
  ] as const;
}

/**
 * Left panel (Claude Design editor): the sections as a list (Bible, Storyboard, Shots, Cut), then
 * the episodes by season, or the bible entries while the Bible is open. The shot page and the Cut
 * screen have no panel.
 */
export function ShowNav({
  show,
  route,
  onRoute,
  onNewEpisode,
}: {
  show: OlfShow;
  route: Route;
  onRoute: (route: Route) => void;
  /** Design "+ New episode": the title, and the season of the last group (if any). */
  onNewEpisode: (title: string, season: string | null) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const groups = episodeGroups(show);
  const episode = routeEpisode(show, route) || "";
  const inBible = route.view === "bible";
  const entryOn = (id: string) => (route.view === "bible" && route.entry === id ? "on" : "");
  return (
    <aside className="shows-nav" data-testid="shows-nav">
      <nav className="shows-sections" aria-label="Show sections">
        {sections(show, route, episode).map((row) => (
          <button
            key={row.id}
            type="button"
            className={row.on ? "on" : ""}
            disabled={row.id !== "bible" && !episode}
            onClick={() => onRoute(row.go as Route)}
            data-testid={`shows-section-${row.id}`}
          >
            {row.label}
          </button>
        ))}
      </nav>
      {inBible ? (
        <div className="shows-list" data-testid="shows-bible-list">
          <p className="eyebrow">Style</p>
          <button type="button" className={entryOn("style")} onClick={() => onRoute({ view: "bible", entry: "style" })}>
            {String(show.style?.data.look?.medium || "Style")} · {String(show.style?.data.id || "main").replace("style/", "")}
          </button>
          {bibleGroups(show).map((group) => (
            <div key={group.label} className="shows-list-group">
              <p className="eyebrow">{group.label}</p>
              {group.rows.map((row) => (
                <button key={row.id} type="button" className={entryOn(row.id)} onClick={() => onRoute({ view: "bible", entry: row.id })}>
                  {entryName(row)}
                </button>
              ))}
            </div>
          ))}
        </div>
      ) : (
        <div className="shows-list" data-testid="shows-episode-list">
          {groups.map((group) => (
            <div key={group.season?.id || "episodes"} className="shows-list-group" data-testid="shows-season">
              <p className="eyebrow" title={group.season?.synopsis || ""}>
                {group.season ? seasonLabel(group.season) : "Episodes"}
              </p>
              {group.episodes.map((ep) => (
                <button
                  key={ep.id}
                  type="button"
                  className={ep.id === episode ? "on" : ""}
                  onClick={() => onRoute({ view: route.view === "shots" ? "shots" : "storyboard", episode: ep.id })}
                >
                  {ep.id.toUpperCase()} · {ep.title || "Episode"}
                </button>
              ))}
            </div>
          ))}
          {adding ? (
            <form
              className="shows-list-new"
              onSubmit={(event) => {
                event.preventDefault();
                if (title.trim()) onNewEpisode(title.trim(), groups[groups.length - 1]?.season?.id || null);
                setTitle("");
                setAdding(false);
              }}
            >
              <input className="olf-input" value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => !title.trim() && setAdding(false)} placeholder="Episode title" aria-label="Episode title" autoFocus />
            </form>
          ) : (
            <button type="button" className="shows-list-add" onClick={() => setAdding(true)} data-testid="new-episode">
              + New episode
            </button>
          )}
        </div>
      )}
    </aside>
  );
}

/**
 * The show's header in the Studio top bar (the Claude Design header): a crumb on the left; the
 * spec (or the entry's file), health and actions on the right. On the shot page: back to the
 * storyboard, the shot's status, and the previous and next shot.
 */
export function ShowTop({
  show,
  route,
  onRoute,
  onReload,
  onClose,
}: {
  show: OlfShow | null;
  route: Route;
  onRoute: (route: Route) => void;
  onReload: () => void;
  onClose: () => void;
}) {
  if (!show) return <span className="top-crumb">Shows</span>;
  if (route.view === "shot" && show.shots[route.shot]) {
    const id = route.shot;
    const { prev, next } = neighbors(episodeOf(show, id), id);
    const shown = shownKeyframe(show, id);
    return (
      <>
        <span className="top-crumb">
          <button type="button" className="olf-back" onClick={() => onRoute({ view: "storyboard", episode: id.split("/")[0] })}>
            ‹ Storyboard
          </button>
          <span className="muted">/</span>
          <code>{id}</code>
          {shown ? <StatusPill status={shown.status} /> : null}
          {takesOf(show, id).some((take) => take.stale) ? <StalePill /> : null}
        </span>
        <span className="top-actions">
          <button type="button" className="olf-x" disabled={!prev} onClick={() => prev && onRoute({ view: "shot", shot: prev })} aria-label="Previous shot">
            ‹
          </button>
          <button type="button" className="olf-x" disabled={!next} onClick={() => next && onRoute({ view: "shot", shot: next })} aria-label="Next shot">
            ›
          </button>
        </span>
      </>
    );
  }
  const { errors, warnings } = issueCounts(show.issues);
  const episodeId = routeEpisode(show, route) || "";
  const ep = show.episodes.find((row) => row.id === episodeId);
  const entry = route.view === "bible" ? (route.entry === "style" ? show.style : findEntry(show, route.entry)) : null;
  const kind = entry && BIBLE_KINDS.find((row) => show.bible[row.id]?.includes(entry));
  const context =
    route.view === "issues"
      ? "Issues"
      : route.view === "bible"
        ? ["Bible", route.entry === "style" ? "Style" : kind?.label, entry && route.entry !== "style" ? entryName(entry) : null]
            .filter(Boolean)
            .join(" · ")
        : ep
          ? `${ep.id.toUpperCase()} · ${route.view === "cut" ? "Cut" : ep.title || "Episode"}`
          : "";
  return (
    <>
      <span className="top-crumb" title={show.path}>
        <b>{show.title}</b>
        {context ? (
          <>
            <span className="muted">/</span>
            <span className="top-context">{context}</span>
          </>
        ) : null}
      </span>
      {route.view === "cut" ? (
        // The design's Cut screen moves the sections into tabs, so the timeline gets the full width.
        <nav className="top-tabs" aria-label="Show sections">
          {sections(show, route, episodeId).map((row) => (
            <button
              key={row.id}
              type="button"
              className={row.on ? "on" : ""}
              onClick={() => onRoute(row.go as Route)}
              data-testid={`shows-tab-${row.id}`}
            >
              {row.label}
            </button>
          ))}
        </nav>
      ) : null}
      <span className="top-actions">
        <code className="top-file">{route.view === "cut" && ep?.file ? `${ep.file} · cut` : entry?.file || `spec: ${show.spec}`}</code>
        <button
          type="button"
          className={`shows-health ${errors ? "bad" : "ok"}`}
          onClick={() => onRoute({ view: "issues" })}
          data-testid="shows-health"
        >
          {errors ? `${errors} ${errors === 1 ? "error" : "errors"}` : "Valid OLF v0.1"}
          {warnings ? ` · ${warnings} ${warnings === 1 ? "warning" : "warnings"}` : ""}
        </button>
        <button type="button" className="olf-x" title="Reload from disk" aria-label="Reload" onClick={onReload}>
          ↻
        </button>
        {/* Design "Share": the show folder as one .olf.zip of plain OLF files (exports left out). */}
        <a className="ghost olf-small olf-share" href={`${OLF_API}/share?path=${encodeURIComponent(show.path)}`} download data-testid="share">
          Share
        </a>
        <button type="button" className="ghost olf-small" onClick={onClose}>
          Close show
        </button>
      </span>
    </>
  );
}
