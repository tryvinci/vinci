"use client";

import { type FormEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { daemonPaths } from "../lib/daemon-routes";
import {
  RECENT_KEY,
  type OlfBatch,
  type OlfCut,
  type OlfData,
  type OlfExport,
  type OlfPlan,
  type OlfPrevis,
  type OlfShotDetail,
  type OlfShow,
  type OlfShowRow,
  type OlfStaleCause,
  type OlfTake,
  type RenderKind,
  andList,
  episodeGroups,
  findEntry,
  folderName,
  issueCounts,
  matchShows,
  parseRecent,
  price,
  partRoute,
  pushRecent,
  routePart,
  showSlug,
  slugKey,
  showKey,
  readyJobs,
  runtimeText,
  takeName,
  updatedText,
} from "../lib/shows";
import { type ExportJob, ExportUnreachable, OlfRoutes, message, olf, polling, runJobs, send, waitExport, waitRun } from "./shows-api";
import { setUrlPart, topWindow, urlParts } from "./url-part";
import { BibleView, IssuesView } from "./shows-bible";
import { CutView } from "./shows-cut";
import { type Route, ShowNav, ShowTop, routeEpisode } from "./shows-nav";
import { NewShow } from "./shows-setup";
import { ShotView } from "./shows-shot";
import { ShotsTable, StoryboardView } from "./shows-storyboard";
import { EmptyState } from "./ui/empty-state";
import "./shows.css";

type Batches = { episode: string; stale: OlfBatch; animate: OlfBatch };

/** Where a show opens: the storyboard of its first episode, else the issues page. */
function firstRoute(show: OlfShow): Route {
  const episode = episodeGroups(show)[0]?.episodes[0]?.id;
  return episode ? { view: "storyboard", episode } : { view: "issues" };
}

/** The place a link names, if the show has it (an episode or shot that is gone opens the first place). */
function knownRoute(show: OlfShow, route: Route | null): Route | null {
  if (!route) return null;
  if (route.view === "shot") return show.shots[route.shot] ? route : null;
  if (route.view === "bible") return route.entry === "style" || findEntry(show, route.entry) ? route : null;
  if (route.view === "storyboard" || route.view === "shots" || route.view === "cut") {
    return episodeGroups(show).some((group) => group.episodes.some((ep) => ep.id === route.episode)) ? route : null;
  }
  return route;
}

/** The show slug and the place in it that the URL names (`#shows/lamp-oil-b1b8cc8b/cut/e01`). */
function urlShow(): { slug: string; part: string } {
  const [page, rest] = urlParts();
  const [slug, ...part] = page === "shows" ? rest.split("/") : [""];
  return { slug: slug || "", part: part.join("/") };
}

/**
 * Shows: the OLF movie engine in the Studio, laid out as the Claude Design editor. The bible locks
 * the look, the storyboard reviews keyframes (cheap stills), and the shot page approves takes and
 * renders video from the chosen keyframe.
 *
 * Args:
 *   topSlot: The Studio top-bar element that shows the show's header (crumb, spec, actions).
 *   hosted: A host serves the shows (Vinci Platform): they live in its storage, so there is no
 *     folder to open and the open screen lists the host's shows only.
 */
/** An export a Cut follows: the attempt that owns it, its step and start (ms), then its files. */
type ExportView = { attempt: number; stage: string; since: number; result: OlfExport | null };

/** Session key of the running exports of this tab (`<show path>\n<episode>` → export id): a reload goes on waiting. */
const EXPORT_KEY = "vinci-shows-exports-v1";

/**
 * The running export of a show's episode in this tab: read it (`id` left out), keep it (an id) or
 * forget it (`null`).
 *
 * Returns:
 *   The kept export id, or "".
 */
function keptExport(key: string, id?: string | null): string {
  try {
    const rows = JSON.parse(sessionStorage.getItem(EXPORT_KEY) || "{}") as Record<string, string>;
    if (id === undefined) return rows[key] || "";
    if (id) rows[key] = id;
    else delete rows[key];
    sessionStorage.setItem(EXPORT_KEY, JSON.stringify(rows));
    return id || "";
  } catch {
    return ""; // no session storage (a private window): the export still runs, a reload only loses its progress
  }
}

export function ShowsPage({ topSlot, hosted = false }: { topSlot?: HTMLElement | null; hosted?: boolean }) {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [routes, setRoutes] = useState<Set<string> | null>(null); // the OLF routes this daemon serves
  const [shows, setShows] = useState<OlfShowRow[]>([]); // GET /olf/shows, for the open screen
  const [recent, setRecent] = useState<string[]>([]);
  const [show, setShow] = useState<OlfShow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [route, setRoute] = useState<Route>({ view: "issues" });
  // The detail remembers its shot, so a reload keeps the old one on screen and a new shot never shows it.
  const [detail, setDetail] = useState<{ shot: string; body: OlfShotDetail } | null>(null);
  const [busy, setBusy] = useState<Record<string, RenderKind>>({});
  // The Cut screen: the cut of one episode, what it is doing ("approved", "clip", "export"), the last export.
  const [cut, setCut] = useState<OlfCut | null>(null);
  const [cutBusy, setCutBusy] = useState("");
  // The exports this page follows, one view per show and episode (`key` = "<path>\n<episode>"): the step
  // and start (ms) while it runs ("Rendering… 2:41"), then the files. Each Cut shows only its own, and
  // clip edits (`cutBusy`) never hide it. Bug fixed (first occurrence, 2026-11-18, 1 report,
  // COREPRODUC-693): a 4-minute export showed only "Exporting…", and a reload lost it.
  const [exportViews, setExportViews] = useState<Record<string, ExportView>>({}); // per Cut key: each Cut its own
  const exportViewsRef = useRef(exportViews);
  useEffect(() => {
    exportViewsRef.current = exportViews;
  }, [exportViews]);
  const attempts = useRef(0); // each export a page follows has its own number: an older one never writes a newer view
  const following = useRef(new Set<string>()); // export ids this page polls: one poller per job
  const openCut = useRef(""); // the key of the open Cut, set by an effect
  const alive = useRef(true); // false once the person left Shows: a kept export then waits for their return
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // The one previs slot: `key` names its show and episode; the newest request owns it.
  const [previs, setPrevis] = useState<{ key: string; result: OlfPrevis | null; busy: string }>({ key: "", result: null, busy: "" });
  const previsRun = useRef(0);
  const [notice, setNotice] = useState("");
  // The storyboard's batch buttons: dry runs of both batches (jobs and price) for its episode.
  const [batches, setBatches] = useState<Batches | null>(null);
  const [creating, setCreating] = useState(false); // the New show wizard is open
  const [library, setLibrary] = useState<OlfData[]>([]); // the camerawork library of the engine
  const mainRef = useRef<HTMLElement>(null);
  const shotId = route.view === "shot" ? route.shot : null;
  const cutEpisode = route.view === "cut" ? route.episode : null;
  const boardEpisode = route.view === "storyboard" ? route.episode : null;

  // The newest load wins. Bug fixed (first occurrence, 2026-11-13 production crawl, COREPRODUC-642): a
  // new episode showed only after Reload; an older /project answer (a render poll) could land last.
  // A reload (`keepView`) is for the show on screen only: it never replaces a show being opened.
  const openRun = useRef(0);
  const shownPath = useRef<string | null>(null);
  const opening = useRef(false);
  useEffect(() => {
    shownPath.current = show?.path ?? null;
  }, [show]);
  /** Load a show; returns true when its answer was shown. `start` is the place a link names. */
  const open = useCallback(async (path: string, keepView = false, start: Route | null = null): Promise<boolean> => {
    if (keepView && (opening.current || path !== shownPath.current)) {
      console.info("[shows] reload skipped: another show is on screen or opening", { path });
      return false;
    }
    const run = ++openRun.current;
    if (!keepView) opening.current = true;
    setLoading(true);
    setError("");
    try {
      const body = await olf<OlfShow>(`/project?path=${encodeURIComponent(path)}`);
      if (run !== openRun.current) {
        console.info("[shows] older load dropped", { path, run });
        return false;
      }
      setShow(body);
      setRecent((rows) => pushRecent(rows, body.path));
      if (!keepView) {
        const known = knownRoute(body, start);
        if (start && !known) setNotice("That place is not in this show. It opens at its start.");
        setRoute(known || firstRoute(body));
      }
      console.info("[shows] opened", {
        path: body.path,
        shots: Object.keys(body.shots).length,
        takes: Object.keys(body.takes).length,
        issues: body.issues.length,
      });
      return true;
    } catch (err) {
      if (run !== openRun.current) return false; // a newer load owns the page
      // With a show open, the open screen (which shows `error`) is hidden, so a reload uses the notice.
      if (keepView) setNotice(message(err));
      else {
        setError(message(err));
        setShow(null);
      }
      return false;
    } finally {
      if (run === openRun.current) {
        setLoading(false);
        opening.current = false;
      }
    }
  }, []);

  useEffect(() => {
    if (recent.length) window.localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
  }, [recent]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 7000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    // Block body: in new Chromium scrollTo() returns a Promise, and an effect may return only a cleanup.
    mainRef.current?.scrollTo({ top: 0 });
  }, [route]);

  useEffect(() => {
    let live = true;
    void daemonPaths("/vinci-api").then((paths) => {
      if (!live) return;
      setRoutes(paths);
      setAvailable(paths.has("/olf/project"));
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    // The open screen lists the shows; it loads again each time a show closes.
    if (!available || show || !routes?.has("/olf/shows")) return;
    let live = true;
    olf<{ shows: OlfShowRow[] }>("/shows")
      .then((body) => live && setShows(body.shows || []))
      .catch((err) => console.warn("[shows] list failed", message(err)));
    return () => {
      live = false;
    };
  }, [available, show, routes]);

  useEffect(() => {
    // A host runs renders after its answer: poll the ones that are still running (after a reload
    // too). A render this page started is polled already (`polling`).
    if (!show) return;
    for (const row of show.renders || []) {
      if (polling.has(row.run_id)) continue;
      setBusy((rows) => ({ ...rows, [row.shot]: row.kind }));
      console.info("[shows] polling a render", row);
      void waitRun(row.run_id)
        .then((done) => setNotice(`Rendered ${andList(done.takes.map(takeName))} for ${row.shot} · ${price(done.total)}`))
        .catch((err) => setNotice(message(err)))
        .finally(() => {
          setBusy(({ [row.shot]: _done, ...rest }) => rest);
          void open(show.path, true);
        });
    }
  }, [show, open]);

  useEffect(() => {
    if (!available) return;
    // The camerawork library ships with the engine, so one read serves each show. An older
    // daemon has no such route: the menu then lists the show's own templates only.
    void olf<{ library: OlfData[] }>("/camerawork")
      .then((body) => setLibrary(body.library || []))
      .catch(() => undefined);
  }, [available]);

  /**
   * Open the show a URL slug names, at the place the URL names: from the show list (a host, or a daemon
   * that lists shows), else from the recent shows. An unknown show leaves the open screen with a notice.
   */
  const linking = useRef(0); // the lookup that is finding a URL's show (0: none); the URL keeps naming it meanwhile
  const lookups = useRef(0);
  const quiet = useRef(false); // the page opened a show by itself: its place replaces the bare `#shows`
  const restoring = useRef(false); // Back or Forward set the place: a place fixed up replaces its entry
  const held = useRef(false); // the show list failed: the URL keeps the link, so a reload can try again
  const openSlug = useCallback(
    async (slug: string, part: string, recentRows: string[]) => {
      const lookup = ++lookups.current;
      const run = openRun.current; // a later Back or open moves it on, and this lookup then stops
      linking.current = lookup;
      let failed = false;
      const listed = routes?.has("/olf/shows")
        ? await olf<{ shows: OlfShowRow[] }>("/shows").then((body) => body.shows || []).catch((err) => {
            failed = true;
            console.warn("[shows] list failed for a link", message(err));
            return [] as OlfShowRow[];
          })
        : [];
      const path = [...listed.map((row) => row.path), ...recentRows].find((row) => showKey(row) === slugKey(slug));
      console.info("[shows] url show", { slug, part, found: Boolean(path), failed, stale: run !== openRun.current });
      if (run === openRun.current) {
        if (path) await open(path, false, partRoute(part));
        else {
          setShow(null); // the open screen says why
          restoring.current = false;
          held.current = failed;
          setError(failed ? "Could not load your shows, so this link did not open. Reload the page to try again." : "That show is not in your Studio.");
          if (!failed) setUrlPart("shows", "", true);
        }
      }
      if (linking.current === lookup) linking.current = 0;
    },
    [routes, open],
  );

  useEffect(() => {
    if (!available || !routes) return;
    const rows = parseRecent(window.localStorage.getItem(RECENT_KEY));
    setRecent(rows);
    const { slug, part } = urlShow();
    if (slug) void openSlug(slug, part, rows); // a link or a reload names the show
    else if (rows[0]) {
      quiet.current = true;
      void open(rows[0]).then((shown) => {
        if (!shown) quiet.current = false; // only this automatic open replaces the bare entry
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, when the engine and its routes are known
  }, [available, routes]);

  // The open show and its place are in the URL: `#shows/lamp-oil-b1b8cc8b/cut/e01` (COREPRODUC-698).
  // Opening a show from its bare link (`#shows/<slug>`), by itself, or by Back fills in the place in place.
  useEffect(() => {
    if (loading || !available) return;
    const { slug, part } = urlShow();
    if (!show) {
      if (!linking.current && !held.current) setUrlPart("shows", ""); // closed, or never opened
      return;
    }
    held.current = false;
    const mine = showSlug(show.path, show.title || folderName(show.path));
    const bare = (slugKey(slug) === showKey(show.path) && !part) || (quiet.current && !slug) || restoring.current;
    quiet.current = false;
    restoring.current = false;
    setUrlPart("shows", `${mine}/${routePart(route)}`, bare);
  }, [show, route, loading, available, error]);

  // Back and Forward: open the show and place the URL names, or the open screen.
  const showRef = useRef(show);
  useEffect(() => {
    showRef.current = show;
  }, [show]);
  useEffect(() => {
    const onPop = () => {
      if (urlParts()[0] !== "shows") return;
      const { slug, part } = urlShow();
      const now = showRef.current;
      held.current = false;
      if (now && slug && showKey(now.path) === slugKey(slug)) {
        const known = knownRoute(now, partRoute(part));
        if (part && !known) setNotice("That place is not in this show. It opens at its start.");
        restoring.current = true;
        return setRoute(known || firstRoute(now));
      }
      openRun.current += 1; // a pending lookup or load is stale now
      linking.current = 0;
      if (!slug) return setShow(null);
      restoring.current = true;
      void openSlug(slug, part, parseRecent(window.localStorage.getItem(RECENT_KEY)));
    };
    const w = topWindow();
    w.addEventListener("popstate", onPop);
    return () => w.removeEventListener("popstate", onPop);
  }, [openSlug]);

  // Another show or episode: its Cut never shows the previous one's cut while its own loads.
  useEffect(() => {
    setCut(null);
  }, [show?.path, cutEpisode]);

  useEffect(() => {
    // A shot that cannot resolve has no plan; its page shows the engine's reason instead.
    if (!show || !shotId || !show.shots[shotId] || show.shots[shotId].error) return;
    let live = true;
    olf<OlfShotDetail>(`/shot?path=${encodeURIComponent(show.path)}&shot=${encodeURIComponent(shotId)}`)
      .then((body) => live && setDetail({ shot: shotId, body }))
      .catch((err) => live && setNotice(message(err)));
    return () => {
      live = false;
    };
  }, [show, shotId]);

  useEffect(() => {
    if (!show || !cutEpisode) return;
    let live = true;
    olf<OlfCut>(`/cut?path=${encodeURIComponent(show.path)}&episode=${encodeURIComponent(cutEpisode)}`)
      .then((body) => live && setCut(body))
      .catch((err) => live && setNotice(message(err)));
    return () => {
      live = false;
    };
  }, [show, cutEpisode]);

  useEffect(() => {
    // A show with errors renders nothing, so it gets no batch plans (they would only repeat the errors).
    if (!show || !boardEpisode || issueCounts(show.issues).errors) return;
    let live = true;
    const plan = (mode: string) =>
      olf<OlfBatch>("/batch", send("POST", { path: show.path, episode: boardEpisode, mode, dry_run: true }));
    Promise.all([plan("stale"), plan("animate")])
      .then(([stale, animate]) => live && setBatches({ episode: boardEpisode, stale, animate }))
      .catch((err) => live && setNotice(message(err)));
    return () => {
      live = false;
    };
  }, [show, boardEpisode]);

  /** Change the cut (use approved takes, or one clip's fields); the route answers with the new cut. */
  async function editCut(job: string, body: Record<string, unknown>) {
    if (!show || !cutEpisode) return;
    setCutBusy(job);
    try {
      setCut(await olf<OlfCut>("/cut", send("PATCH", { path: show.path, episode: cutEpisode, ...body })));
      console.info("[shows] cut", { episode: cutEpisode, ...body });
    } catch (err) {
      setNotice(message(err));
    } finally {
      setCutBusy("");
    }
  }

  /** Make the e-conte sheet, the animatic or the mock render of the open episode ($0). Only the
   * newest request writes the previs slot, and the slot names its show and episode. */
  async function makePrevis(kind: "sheet" | "animatic" | "mock") {
    if (!show || !episode) return;
    const [id, key, run] = [episode.id, `${show.path}\n${episode.id}`, ++previsRun.current];
    /** An older run must not clear a newer one, for this or another episode or show (CodeRabbit, #530). */
    const settle = (result: OlfPrevis | null) => {
      if (previsRun.current === run) setPrevis({ key, result, busy: "" });
    };
    setPrevis({ key, result: null, busy: kind });
    try {
      const body = { path: show.path, episode: id, sheet: kind === "sheet", animatic: kind === "animatic", mock: kind === "mock" };
      const result = await olf<OlfPrevis>("/previs", send("POST", body));
      settle(result);
      const what = { sheet: "E-conte sheet", animatic: "Animatic", mock: "Mock render" }[kind];
      setNotice(`${what} for ${body.episode}: ${result.cuts} cuts · ${runtimeText(result.runtime)} · $0`);
      console.info("[shows] previs", { kind, episode: body.episode, ...result });
    } catch (err) {
      settle(null);
      setNotice(message(err));
    }
  }

  /**
   * Follow a host's export of one show and episode: its step while it runs, then its files. The job
   * id is kept for the tab once, when the host accepts the job, so a reload or another page goes on
   * waiting; it is forgotten only when its result is shown on its own Cut.
   *
   * Args:
   *   key: "<show path>\n<episode>".
   *   start: Starts the export (or waits for a kept one); it reports each answer of the job.
   */
  async function followExport(key: string, start: (onJob: (job: ExportJob) => void) => Promise<unknown>) {
    const episode = key.split("\n")[1];
    const since = Date.now();
    const attempt = ++attempts.current;
    let id = "";
    let reachable = true;
    /** Change this Cut's view only while it is still this attempt's. */
    const mine = (next: (view: ExportView) => ExportView | null) =>
      setExportViews((views) => {
        const view = views[key];
        if (!view || view.attempt !== attempt) return views;
        const { [key]: _old, ...rest } = views;
        const changed = next(view);
        return changed ? { ...rest, [key]: changed } : rest;
      });
    const before = exportViewsRef.current[key]; // a rejected click leaves the view it found
    setExportViews((views) => ({ ...views, [key]: { attempt, stage: "", since, result: null } }));
    try {
      const result = (await start((job) => {
        if (!id) {
          id = job.id; // the first answer: the host accepted the job (later answers never write the id back)
          keptExport(key, id);
          following.current.add(id);
        }
        if (!alive.current) throw new Error("left Shows"); // stop polling; Cut resumes the kept export
        mine((view) => ({ ...view, stage: job.stage || "", since: job.created_at ? Date.parse(job.created_at) : since }));
      })) as OlfExport;
      mine((view) => ({ ...view, result }));
      setNotice(`Exported ${result.files.length} files for ${episode} · ${result.duration.toFixed(1)} s`);
      console.info("[shows] exported", { episode, ...result });
    } catch (err) {
      reachable = !(err instanceof ExportUnreachable);
      if (alive.current) setNotice(message(err));
      mine(() => (id ? null : before || null)); // a rejected click (no job) gives the Cut back its view
    } finally {
      following.current.delete(id);
      // Forget the id only for this job's own outcome, shown on its own Cut; a later visit shows any other.
      if (id && alive.current && reachable && openCut.current === key && keptExport(key) === id) keptExport(key, null);
    }
  }

  /** Export the cut of the open episode: one MP4 for each aspect, with the subtitles, sound, C2PA and OTIO that the user picks. */
  function exportEpisode(aspects: string[], subtitles: boolean, c2pa: boolean, otio: boolean, sound: boolean) {
    if (!show || !cutEpisode) return;
    const body = { path: show.path, episode: cutEpisode, aspects, subtitles, c2pa, otio, sound };
    void followExport(`${show.path}\n${cutEpisode}`, (onJob) => olf<OlfExport>("/export", send("POST", body), onJob));
  }

  // Cut opens on an episode whose export this tab kept (a reload, another page): wait for it again.
  const cutKey = show && cutEpisode ? `${show.path}\n${cutEpisode}` : "";
  const cutView = cutKey ? exportViews[cutKey] : undefined;
  useEffect(() => {
    openCut.current = cutKey;
    const id = cutKey ? keptExport(cutKey) : "";
    if (!id || following.current.has(id)) return;
    console.info("[shows] export resumed", { key: cutKey, id });
    void followExport(cutKey, (onJob) => waitExport(id, onJob));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new show or episode resumes
  }, [cutKey]);

  async function openSample() {
    setLoading(true);
    try {
      const { path } = await olf<{ path: string }>("/sample", send("POST", {}));
      await open(path);
    } catch (err) {
      setError(message(err));
      setLoading(false);
    }
  }

  /** Render one shot; `model` is a person's pick (else routing); `total` is the price they saw. */
  async function render(id: string, kind: RenderKind, yes = false, count = 1, model?: string, total?: number) {
    if (!show) return;
    setBusy((rows) => ({ ...rows, [id]: kind }));
    setNotice("");
    try {
      // A confirmed render sends the price the person saw; the engine stops if the plan costs more.
      const body = { path: show.path, shot: id, kind, yes, count, model, max_total: yes ? total || 0 : undefined };
      const result = await olf<OlfPlan>("/render", send("POST", body));
      const made = andList((result.takes || []).map(takeName));
      setNotice(`Rendered ${made} for ${id} · ${price(result.total)}`);
      console.info("[shows] rendered", { shot: id, kind, count, takes: result.takes, total: result.total });
      await open(show.path, true);
    } catch (err) {
      const text = message(err);
      // A paid render stops before it runs; the shot page shows the price and asks first.
      const paid = text.includes("--yes");
      if (paid) setRoute({ view: "shot", shot: id });
      setNotice(paid ? "This render costs money. Check the price on the shot page, then confirm." : text);
    } finally {
      setBusy(({ [id]: _done, ...rest }) => rest);
    }
  }

  /**
   * Run a batch for the storyboard's episode: one request per job, each bounded by its planned
   * price (their sum is the confirmed total), and the board reloads after each job.
   */
  async function runBatch(mode: "stale" | "animate", yes = false) {
    if (!show || !boardEpisode) return;
    const jobs = readyJobs(batches?.[mode]);
    const path = show.path;
    setNotice("");
    const result = await runJobs(path, jobs, yes, async (done, job) => {
      if (done) await open(path, true); // the finished job shows at once
      setBusy((rows) => {
        const rest = Object.fromEntries(Object.entries(rows).filter(([id]) => !jobs.some((row) => row.shot === id)));
        return job ? { ...rest, [job.shot]: job.kind || "keyframe" } : rest;
      });
      if (job) setNotice(`Rendering ${done + 1} of ${jobs.length}: ${job.shot} · ${job.kind || "keyframe"}…`);
    });
    const made = result.takes.length ? andList(result.takes.map(takeName)) : "nothing";
    setNotice(
      `Rendered ${made} for ${boardEpisode} · ${price(result.total)}` +
        (result.failed.length ? ` · ${result.failed.length} failed: ${result.failed[0].error}` : ""),
    );
    console.info("[shows] batch", { episode: boardEpisode, mode, takes: result.takes, total: result.total, failed: result.failed });
  }

  /**
   * Author the show (vinci_olf.author): edit a shot, add a shot, scene or episode, replace a sheet,
   * add a form. Reloads after the edit and returns the route's answer (null on an error notice).
   */
  async function author<T>(method: "POST" | "PATCH" | "PUT", route: string, body: Record<string, unknown>, done?: (out: T) => string) {
    if (!show) return null;
    try {
      const out = await olf<T>(route, send(method, { path: show.path, ...body }));
      console.info("[shows] authored", method, route, Object.keys(body)); // keys only: images are base64
      // After the reload: the notice and the new item show together. A failed reload keeps its own notice.
      if ((await open(show.path, true)) && done) setNotice(done(out));
      return out;
    } catch (err) {
      setNotice(message(err));
      return null;
    }
  }

  /** Apply line-level edits to the show files (review a take, choose a take), then reload. */
  async function patch(calls: [string, Record<string, unknown>][]) {
    if (!show) return;
    try {
      for (const [path, body] of calls) await olf(path, send("PATCH", { path: show.path, ...body }));
      console.info("[shows] edited", calls);
      await open(show.path, true);
    } catch (err) {
      setNotice(message(err));
    }
  }

  /**
   * Approve a take and choose it (the design outlines approved takes as selected): `select.keyframe`,
   * `select.video` or `select.audio` (the dialogue a cut clip plays as separate sound). Again: draft.
   */
  function approve(take: OlfTake) {
    const shot = take.id.slice(0, take.id.lastIndexOf("/"));
    const on = take.status !== "approved";
    void patch([
      ["/take", { take: take.id, status: on ? "approved" : "draft" }],
      ...(on ? [["/select", { shot, choices: { [take.kind]: takeName(take.id) } }] as [string, Record<string, unknown>]] : []),
    ]);
  }

  // The show's header goes into the Studio top bar (as Canvas puts its view switch there).
  const has = (path: string) => !routes || routes.has(path);
  const top = (node: ReactNode) => (
    <OlfRoutes.Provider value={has}>
      {topSlot
        ? createPortal(
            <ShowTop
              show={show}
              route={route}
              onRoute={setRoute}
              onReload={() => show && void open(show.path, true)}
              onClose={() => setShow(null)}
            />,
            topSlot,
          )
        : null}
      {node}
    </OlfRoutes.Provider>
  );

  if (available === false) {
    return top(
      <div className="shows-page shows-solo" data-testid="shows-off">
        <EmptyState
          eyebrow="Movie engine"
          title="Shows are off in this daemon"
          copy="The movie engine (vinci-olf) is not installed. Run make install, then restart the daemon."
        />
      </div>,
    );
  }
  if (!show && creating) {
    return top(
      <NewShow
        onCancel={() => setCreating(false)}
        onOpen={async (path, text) => {
          setCreating(false);
          await open(path);
          setNotice(text);
        }}
      />,
    );
  }
  if (!show) {
    return top(
      <OpenShow
        busy={loading}
        ready={available !== null}
        error={error}
        recent={hosted ? [] : recent.filter((path) => !shows.some((row) => row.path === path))}
        shows={shows}
        folders={!hosted}
        onOpen={(path) => void open(path)}
        onSample={() => void openSample()}
        onNew={() => setCreating(true)}
      />,
    );
  }
  const { errors } = issueCounts(show.issues);
  const episodeId = routeEpisode(show, route);
  const episode = show.episodes.find((ep) => ep.id === episodeId);
  const openShot = (id: string) => setRoute({ view: "shot", shot: id });
  const openEntry = (id: string) => setRoute({ view: "bible", entry: id });
  // A shot that left the show (its file was edited away) falls back to its storyboard.
  const view = route.view === "shot" && !show.shots[route.shot] ? "storyboard" : route.view;
  const full = view === "shot" || view === "cut"; // the design gives these pages the full width
  return top(
    // The shot page and the Cut screen have no left panel and use the full width, as in the design.
    <div className={`shows-page${full ? " is-full" : ""}`} data-testid="shows-page">
      {full ? null : (
        <ShowNav
          show={show}
          route={route}
          onRoute={setRoute}
          onNewEpisode={async (title, season) => {
            const out = await author<{ episode: string }>("POST", "/episode", { title, season }, (o) => `Added episode ${o.episode.toUpperCase()} · ${title}`);
            if (out) setRoute({ view: "storyboard", episode: out.episode });
          }}
        />
      )}
      <main className="shows-main" ref={mainRef}>
        {notice ? (
          <div className="shows-notice" role="status" data-testid="shows-notice">
            <span>{notice}</span>
            <button type="button" className="olf-x" aria-label="Dismiss" onClick={() => setNotice("")}>
              ×
            </button>
          </div>
        ) : null}
        {errors && view !== "issues" ? (
          <div className="shows-banner" role="alert" data-testid="shows-banner">
            <span>
              This show has {errors} {errors === 1 ? "error" : "errors"}. Render stays off until you fix the files.
            </span>
            <button type="button" className="ghost" onClick={() => setRoute({ view: "issues" })}>
              Show issues
            </button>
          </div>
        ) : null}
        {view === "cut" && episode ? (
          <CutView
            show={show}
            cut={cut?.episode === episode.id ? cut : null}
            busy={cutView && !cutView.result ? "export" : cutBusy}
            job={cutView && !cutView.result ? cutView : null}
            result={cutView?.result || null}
            onUseApproved={() => void editCut("approved", { use_approved: true })}
            onClip={(clip, fields) => void editCut("clip", { clip, fields })}
            onExport={(aspects, subtitles, c2pa, otio, sound) => void exportEpisode(aspects, subtitles, c2pa, otio, sound)}
            onCueAdded={(text) => {
              setNotice(text);
              void open(show.path, true); // reloads the show, then the cut
            }}
          />
        ) : null}
        {(view === "storyboard" || view === "shots" || view === "cut") && !episode ? (
          <p className="muted">This show has no episodes yet. Add episodes/e01/episode.yaml, then reload.</p>
        ) : null}
        {view === "storyboard" && episode ? (
          <StoryboardView
            show={show}
            episode={episode}
            busy={busy}
            batches={batches?.episode === episode.id ? batches : null}
            locked={errors > 0}
            onBatch={(mode, yes) => void runBatch(mode, yes)}
            onOpenShot={openShot}
            onAddShot={(scene, fields) =>
              void author<{ shot: string }>("POST", "/shot", { scene, ...fields }, (o) => `Added ${takeName(o.shot)} to ${scene}`)
            }
            onAddScene={(heading) =>
              void author<{ scene: string }>("POST", "/scene", { episode: episode.id, heading }, (o) => `Added scene ${o.scene}`)
            }
            previs={previs.key === `${show.path}\n${episode.id}` ? previs : { result: null, busy: "" }}
            onPrevis={(kind) => void makePrevis(kind)}
            onImportScript={async (script) => {
              type Added = { scenes: string[]; locations: string[]; characters: string[] };
              const out = await author<Added>("POST", "/script", { episode: episode.id, script }, (o) =>
                [`Added ${andList(o.scenes)} to ${episode.id.toUpperCase()}`, ...(o.characters.length ? [`add a sheet for ${andList(o.characters)}`] : [])].join(" · "),
              );
              return !!out;
            }}
          />
        ) : null}
        {view === "shots" && episode ? <ShotsTable show={show} episode={episode} onOpenShot={openShot} /> : null}
        {view === "shot" && shotId ? (
          <ShotView
            key={shotId}
            show={show}
            id={shotId}
            detail={detail?.shot === shotId ? detail.body : null}
            busy={busy[shotId]}
            locked={errors > 0}
            onRender={(kind, yes, count, model, total) => void render(shotId, kind, yes, count, model, total)}
            onApprove={approve}
            onReject={(take) =>
              void patch([["/take", { take: take.id, status: take.status === "rejected" ? "draft" : "rejected" }]])
            }
            onOpenEntry={openEntry}
            library={library}
            onEdit={(fields) => void author("PATCH", "/shot", { shot: shotId, fields })}
            onCamerawork={(template) => void author("POST", "/camerawork", { shot: shotId, template })}
            onExplain={(take) => olf<OlfStaleCause>(`/stale?path=${encodeURIComponent(show.path)}&take=${encodeURIComponent(take)}`)}
            onKeep={(take) => void author("POST", "/keep", { take }, () => `Kept ${takeName(take)}: it is fresh until an input changes again`)}
            onStoryboard={(draw) =>
              draw().then(
                (data) => author("POST", "/storyboard", { shot: shotId, data }, () => "Saved the 3D pill frame: the next keyframe of this shot gets it as its layout"),
                (err) => {
                  console.error("[shows] pill frame not drawn", err); // e.g. no WebGL, or three.js did not load
                  setNotice(`Could not draw the 3D pill frame: ${message(err)}. Try again.`);
                },
              )
            }
          />
        ) : null}
        {route.view === "bible" ? (
          <BibleView
            key={route.entry}
            show={show}
            id={route.entry}
            library={library}
            onOpenEntry={openEntry}
            onAddSheet={async (data) =>
              (await author<{ sheet: string }>("POST", "/sheet", { entry: route.entry, data, add: true }, (o) => `Added ${o.sheet}`))?.sheet || null
            }
            onReplaceSheet={(data, sheet) =>
              void author<{ file: string }>("POST", "/sheet", { entry: route.entry, data, sheet }, (o) =>
                `Replaced ${o.file.split("/").pop()}. Takes that used the old sheet are stale.`,
              )
            }
            onCloneVoice={async (name, sample) =>
              !!(await author<{ voice: string }>("POST", "/voice/clone", { character: route.entry, name, sample, consent: true }, () => `Cloned ${name}. It is the voice now; dialogue takes in the old voice are stale.`))
            }
            onSetVoice={(voice_id, name) =>
              void author<{ voice: string }>("POST", "/voice", { character: route.entry, voice_id, name }, () => `${name} is the voice now. Dialogue takes in the old voice are stale.`)
            }
            onAddForm={(fields) =>
              void author<{ form: string }>("POST", "/form", { entry: route.entry, ...fields }, (o) => `Added form ${o.form}`)
            }
            onEdit={(method, path, body, notice) => void author<Record<string, unknown>>(method, path, body, notice)}
            onSaveSource={async (text) => !!(await author<{ file: string }>("PUT", "/source", { entry: route.entry, text }, (o) => `Saved ${o.file}`))}
          />
        ) : null}
        {view === "issues" ? <IssuesView show={show} /> : null}
      </main>
    </div>
  );
}

function OpenShow({
  busy,
  ready,
  error,
  recent,
  shows,
  folders,
  onOpen,
  onSample,
  onNew,
}: {
  busy: boolean;
  ready: boolean;
  error: string;
  recent: readonly string[];
  /** `GET /olf/shows`. */
  shows: readonly OlfShowRow[];
  /** Shows are folders on this computer (a local daemon), so a path opens one. */
  folders: boolean;
  onOpen: (path: string) => void;
  onSample: () => void;
  onNew: () => void;
}) {
  const [path, setPath] = useState("");
  const [query, setQuery] = useState("");
  function submit(ev: FormEvent) {
    ev.preventDefault();
    if (path.trim()) onOpen(path.trim());
  }
  // One grid: recent folders outside the shows folder first (local only), then `GET /olf/shows`, last changed first.
  const cards = [
    ...recent.map((row) => ({ path: row, title: folderName(row), note: row })),
    ...shows.map((row) => ({ path: row.path, title: row.title, note: updatedText(row.updated_at) })),
  ];
  const shown = matchShows(cards, query);
  const buttons = (
    <>
      <button className="run" type="button" disabled={busy || !ready} onClick={onNew} data-testid="shows-new">
        New show
      </button>
      <button className="ghost" type="button" disabled={busy || !ready} onClick={onSample} data-testid="shows-open-sample">
        {busy ? "Opening…" : "Open the sample show"}
      </button>
    </>
  );
  const folderForm = folders ? (
    <form className="shows-path" onSubmit={submit}>
      <input
        value={path}
        onChange={(ev) => setPath(ev.target.value)}
        placeholder="/path/to/my-show"
        aria-label="Show folder"
        data-testid="shows-path"
      />
      <button className="ghost" type="submit" disabled={busy || !ready || !path.trim()}>
        Open folder
      </button>
    </form>
  ) : null;
  return (
    <div className={`shows-page shows-solo${cards.length ? " shows-home" : ""}`} data-testid="shows-open">
      {cards.length ? (
        // A person with shows sees them first; 100 shows fit as a grid, with a search past 8.
        <>
          <header className="olf-head">
            <div>
              <p className="eyebrow">Shows</p>
              <h1>Your shows · {cards.length}</h1>
            </div>
            <div className="olf-head-actions">{buttons}</div>
          </header>
          {cards.length > 8 || folders ? (
            <div className="shows-home-tools">
              {cards.length > 8 ? (
                <input
                  type="search"
                  value={query}
                  onChange={(ev) => setQuery(ev.target.value)}
                  placeholder={`Search ${cards.length} shows…`}
                  aria-label="Search shows"
                  data-testid="shows-search"
                />
              ) : null}
              {folderForm}
            </div>
          ) : null}
          <div className="shows-grid" data-testid="shows-grid">
            {shown.map((row) => (
              <button key={row.path} type="button" className="show-card" title={row.title} disabled={busy} onClick={() => onOpen(row.path)}>
                <strong>{row.title}</strong>
                <span>{row.note}</span>
              </button>
            ))}
          </div>
          {!shown.length ? (
            <p className="muted" data-testid="shows-no-match">
              No show matches &ldquo;{query.trim()}&rdquo;.
            </p>
          ) : null}
        </>
      ) : (
        <EmptyState
          eyebrow="Shows"
          title="Build the world once. Render every episode."
          copy="Write the show bible once: characters, places, props and style. Vinci renders every shot from it on any model, and shows you which takes are out of date when the bible changes."
          actions={
            <div className="shows-open-actions">
              {buttons}
              {folderForm}
            </div>
          }
          hint={
            folders
              ? "A show is a folder in the Open Lore Format, with project.yaml at the top. The sample is a short anime show called Tidewatch."
              : // A host keeps the shows in its storage, not in folders on this computer.
                "A show keeps its bible, episodes and shots together. The sample is Lamp Oil: one finished scene with its keyframes, clips and subtitles."
          }
        />
      )}
      {error ? (
        <p className="shows-error" role="alert" data-testid="shows-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}
