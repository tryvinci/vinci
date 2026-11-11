"use client";

import { type FormEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { daemonHasPath } from "../lib/daemon-routes";
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
  type OlfStaleCause,
  type OlfTake,
  type RenderKind,
  andList,
  episodeGroups,
  folderName,
  issueCounts,
  parseRecent,
  price,
  pushRecent,
  readyJobs,
  runtimeText,
  takeName,
} from "../lib/shows";
import { message, olf, runJobs, send } from "./shows-api";
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

/**
 * Shows: the OLF movie engine in the Studio, laid out as the Claude Design editor. The bible locks
 * the look, the storyboard reviews keyframes (cheap stills), and the shot page approves takes and
 * renders video from the chosen keyframe.
 *
 * Args:
 *   topSlot: The Studio top-bar element that shows the show's header (crumb, spec, actions).
 */
export function ShowsPage({ topSlot }: { topSlot?: HTMLElement | null }) {
  const [available, setAvailable] = useState<boolean | null>(null);
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
  const [exported, setExported] = useState<OlfExport | null>(null);
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

  const open = useCallback(async (path: string, keepView = false) => {
    setLoading(true);
    setError("");
    try {
      const body = await olf<OlfShow>(`/project?path=${encodeURIComponent(path)}`);
      setShow(body);
      setRecent((rows) => pushRecent(rows, body.path));
      if (!keepView) setRoute(firstRoute(body));
      console.info("[shows] opened", {
        path: body.path,
        shots: Object.keys(body.shots).length,
        takes: Object.keys(body.takes).length,
        issues: body.issues.length,
      });
    } catch (err) {
      // With a show open, the open screen (which shows `error`) is hidden, so a reload uses the notice.
      if (keepView) setNotice(message(err));
      else {
        setError(message(err));
        setShow(null);
      }
    } finally {
      setLoading(false);
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
    void daemonHasPath("/vinci-api", "/olf/project").then((ok) => live && setAvailable(ok));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!available) return;
    // The camerawork library ships with the engine, so one read serves each show. An older
    // daemon has no such route: the menu then lists the show's own templates only.
    void olf<{ library: OlfData[] }>("/camerawork")
      .then((body) => setLibrary(body.library || []))
      .catch(() => undefined);
  }, [available]);

  useEffect(() => {
    if (!available) return;
    const rows = parseRecent(window.localStorage.getItem(RECENT_KEY));
    setRecent(rows);
    if (rows[0]) void open(rows[0]);
  }, [available, open]);

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

  /** Export the cut of the open episode: one MP4 for each aspect, with the subtitles, sound, C2PA and OTIO that the user picks. */
  async function exportEpisode(aspects: string[], subtitles: boolean, c2pa: boolean, otio: boolean, sound: boolean) {
    if (!show || !cutEpisode) return;
    setCutBusy("export");
    setExported(null);
    try {
      const body = { path: show.path, episode: cutEpisode, aspects, subtitles, c2pa, otio, sound };
      const result = await olf<OlfExport>("/export", send("POST", body));
      setExported(result);
      setNotice(`Exported ${result.files.length} files for ${cutEpisode} · ${result.duration.toFixed(1)} s`);
      console.info("[shows] exported", { episode: cutEpisode, ...result });
    } catch (err) {
      setNotice(message(err));
    } finally {
      setCutBusy("");
    }
  }

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
  async function author<T>(method: "POST" | "PATCH", route: string, body: Record<string, unknown>, done?: (out: T) => string) {
    if (!show) return null;
    try {
      const out = await olf<T>(route, send(method, { path: show.path, ...body }));
      console.info("[shows] authored", method, route, Object.keys(body)); // keys only: images are base64
      if (done) setNotice(done(out));
      await open(show.path, true);
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
  const top = (node: ReactNode) => (
    <>
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
    </>
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
        recent={recent}
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
            busy={cutBusy}
            result={exported}
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
  onOpen,
  onSample,
  onNew,
}: {
  busy: boolean;
  ready: boolean;
  error: string;
  recent: readonly string[];
  onOpen: (path: string) => void;
  onSample: () => void;
  onNew: () => void;
}) {
  const [path, setPath] = useState("");
  function submit(ev: FormEvent) {
    ev.preventDefault();
    if (path.trim()) onOpen(path.trim());
  }
  return (
    <div className="shows-page shows-solo" data-testid="shows-open">
      <EmptyState
        eyebrow="Movie engine · OLF v0.1"
        title="Build the world once. Render every episode."
        copy="Write the show bible once: characters, places, props and style. Vinci renders every shot from it on any model, and shows you which takes are out of date when the bible changes."
        actions={
          <div className="shows-open-actions">
            <button className="run" type="button" disabled={busy || !ready} onClick={onNew} data-testid="shows-new">
              New show
            </button>
            <button className="ghost" type="button" disabled={busy || !ready} onClick={onSample} data-testid="shows-open-sample">
              {busy ? "Opening…" : "Open the sample show"}
            </button>
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
          </div>
        }
        hint={
          recent.length ? (
            <span className="shows-recent">
              Recent:{" "}
              {recent.map((row) => (
                <button key={row} type="button" title={row} onClick={() => onOpen(row)}>
                  {folderName(row)}
                </button>
              ))}
            </span>
          ) : (
            "A show is a folder in the Open Lore Format, with project.yaml at the top. The sample is a short anime show called Tidewatch."
          )
        }
      />
      {error ? (
        <p className="shows-error" role="alert" data-testid="shows-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}
