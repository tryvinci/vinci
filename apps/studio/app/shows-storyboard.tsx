"use client";

import { type FormEvent, useState } from "react";
import {
  FRAMINGS,
  type OlfBatch,
  type OlfEpisode,
  type OlfPrevis,
  type OlfScene,
  type OlfScriptPreview,
  type OlfShow,
  busyText,
  entryName,
  episodeStats,
  fileUrl,
  findEntry,
  framingShort,
  price,
  readyJobs,
  runtimeText,
  frames,
  shotState,
  shownKeyframe,
  spendText,
  takeName,
  takesSummary,
} from "../lib/shows";
import { Confirm, OlfOnly, Pick, PillFrame, StalePill, StatusPill } from "./shows-parts";
import { ScriptStep } from "./shows-setup";

type Mode = "stale" | "animate";
export type ShotFields = { description: string; duration: string; framing: string };

/** `loc/lighthouse · night · Mira Sol (winter, night outfit)`. */
function sceneLine(show: OlfShow, scene: OlfScene): string {
  const cast = (scene.characters || []).map((id) => {
    const look = scene.looks?.[id];
    const parts = [look?.form, look?.outfit && look.outfit !== "default" ? `${look.outfit} outfit` : null].filter(Boolean);
    return `${entryName(findEntry(show, id), id)}${parts.length ? ` (${parts.join(", ")})` : ""}`;
  });
  return [scene.location, scene.variant, ...cast].filter(Boolean).join(" · ");
}

/** `kf1 is stale (e02/s03/sh014 keyframe)`, one line per job: the button's tooltip. */
function jobList(batch: OlfBatch | undefined): string {
  return readyJobs(batch)
    .map((job) => `${job.shot} ${job.kind}: ${job.why}`)
    .join("\n");
}

/**
 * Storyboard (Claude Design, screen 1): every scene of an episode with its shots. The cards are for
 * review, as in the design: a card opens the shot page, which draws keyframes, approves takes and
 * renders video. The header runs batches for the episode, as in the design: re-render what is stale,
 * and animate the approved keyframes, each after one price check. "Shot list from script" turns a
 * pasted script into new scenes and shots (rules first; a text model on request).
 */
export function StoryboardView({
  show,
  episode,
  busy,
  batches,
  locked,
  onBatch,
  onOpenShot,
  onAddShot,
  onAddScene,
  onImportScript,
  previs,
  onPrevis,
}: {
  show: OlfShow;
  episode: OlfEpisode;
  busy: Record<string, string>;
  batches: { stale: OlfBatch; animate: OlfBatch } | null;
  locked: boolean;
  onBatch: (mode: Mode, yes: boolean) => void;
  onOpenShot: (id: string) => void;
  onAddShot: (scene: string, fields: ShotFields) => void;
  onAddScene: (heading: string) => void;
  /** Add a script's scenes and shots to the episode; true when they were written. */
  onImportScript: (script: string) => Promise<boolean>;
  /** The last previs files of this episode, and "sheet" or "animatic" while one is made. */
  previs: { result: OlfPrevis | null; busy: string };
  /** Make the e-conte sheet, the animatic or the mock render ($0: no model runs). */
  onPrevis: (kind: "sheet" | "animatic" | "mock") => void;
}) {
  const stats = episodeStats(show, episode);
  const [confirm, setConfirm] = useState<Mode | null>(null);
  const [script, setScript] = useState<string | null>(null); // null: the script panel is closed
  const [view, setView] = useState<OlfScriptPreview | null>(null);
  const blocked = locked || !batches || Object.keys(busy).length > 0;
  const stale = readyJobs(batches?.stale).length;
  const animate = readyJobs(batches?.animate).length;
  /** Start a batch. A paid batch, or one with a model that has no flat price, asks once for the whole batch. */
  const run = (mode: Mode) => (batches?.[mode].total || batches?.[mode].unpriced.length ? setConfirm(mode) : onBatch(mode, false));
  return (
    <section data-testid="shows-storyboard">
      <header className="olf-head">
        <div>
          <h1>Storyboard</h1>
          <p className="muted">Approve a keyframe for each shot before you animate. Stills are cheap to redo.</p>
        </div>
        <div className="olf-head-actions" data-testid="batch-actions">
          {confirm && batches ? (
            <Confirm
              text={spendText(batches[confirm].total, batches[confirm].unpriced, `${readyJobs(batches[confirm]).length} renders`)}
              onYes={() => {
                onBatch(confirm, true);
                setConfirm(null);
              }}
              onNo={() => setConfirm(null)}
            />
          ) : (
            <>
              <button
                type="button"
                className="ghost"
                disabled={locked}
                aria-pressed={script !== null}
                onClick={() => setScript(script === null ? "" : null)}
                data-testid="script-open"
              >
                Shot list from script
              </button>
              <OlfOnly path="/olf/previs">
                <button
                  type="button"
                  className="ghost"
                  disabled={Boolean(previs.busy) || !stats.shots}
                  title="A PDF with 5 cuts a page: picture, action, dialogue and time. $0."
                  onClick={() => onPrevis("sheet")}
                  data-testid="previs-sheet"
                >
                  {previs.busy === "sheet" ? "Drawing…" : "E-conte sheet"}
                </button>
                <button
                  type="button"
                  className="ghost"
                  disabled={Boolean(previs.busy) || !stats.shots}
                  title="One MP4 of the episode from the best picture of each shot: video, keyframe, else pills. $0."
                  onClick={() => onPrevis("animatic")}
                  data-testid="previs-animatic"
                >
                  {previs.busy === "animatic" ? "Making…" : "Animatic"}
                </button>
                <button
                  type="button"
                  className="ghost"
                  disabled={Boolean(previs.busy) || !stats.shots}
                  title="One MP4 of the episode with one look: every shot from its pills, no sound, the lines as subtitles. $0."
                  onClick={() => onPrevis("mock")}
                  data-testid="previs-mock"
                >
                  {previs.busy === "mock" ? "Rendering…" : "Mock render"}
                </button>
              </OlfOnly>
              <button
                type="button"
                className="ghost olf-stale-btn"
                disabled={blocked || !stale}
                title={jobList(batches?.stale) || "Nothing is stale with a fresh input to render from."}
                onClick={() => run("stale")}
                data-testid="batch-stale"
              >
                Re-render {stale} stale
              </button>
              <button
                type="button"
                className="run"
                disabled={blocked || !animate}
                title={jobList(batches?.animate) || "Approve a keyframe first: the batch animates approved keyframes."}
                onClick={() => run("animate")}
                data-testid="batch-animate"
              >
                Animate approved · est. {price(batches?.animate.total)}
              </button>
            </>
          )}
        </div>
      </header>
      {previs.result ? (
        <ul className="olf-export-files olf-previs" data-testid="previs-files">
          {previs.result.files.map((file) => (
            <li key={file}>
              <a href={fileUrl(show.path, file)} target="_blank" rel="noreferrer">
                {file}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
      {script !== null ? (
        <section className="script-import" data-testid="script-import">
          <ScriptStep script={script} onScript={setScript} path={show.path} onView={setView} />
          <footer className="setup-foot">
            <button type="button" className="ghost" onClick={() => setScript(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="run"
              disabled={!view?.shots}
              onClick={async () => {
                if (await onImportScript(script)) setScript(null);
              }}
              data-testid="script-add"
            >
              Add {view?.scenes.length || 0} {view?.scenes.length === 1 ? "scene" : "scenes"} · {view?.shots || 0} {view?.shots === 1 ? "shot" : "shots"} to {episode.id.toUpperCase()}
            </button>
          </footer>
        </section>
      ) : null}
      <div className="olf-stats" data-testid="shows-stats">
        <div className="olf-stat">
          <span>Shots</span>
          <b>{stats.shots}</b>
        </div>
        <div className="olf-stat">
          <span>Keyframes approved</span>
          <b className="tone-ok">
            {stats.approved} / {stats.shots}
          </b>
        </div>
        <div className="olf-stat">
          <span>Stale takes</span>
          <b className={stats.stale ? "tone-stale" : ""}>{stats.stale}</b>
        </div>
        <div className="olf-stat">
          <span>Runtime</span>
          <b>{runtimeText(stats.runtime)}</b>
        </div>
      </div>
      {episode.scenes.map((scene) => (
        <section key={scene.id} className="olf-scene" data-testid="shows-scene" data-scene={scene.id}>
          <header>
            <h2>{scene.heading || scene.id}</h2>
            <code>{scene.id}</code>
            <span className="muted">{sceneLine(show, scene)}</span>
          </header>
          <div className="olf-board">
            {scene.shots.map((id) => (
              <ShotCard key={id} show={show} id={id} busy={busy[id]} onOpen={() => onOpenShot(id)} />
            ))}
            <AddShot locked={locked} onAdd={(fields) => onAddShot(scene.id, fields)} />
          </div>
        </section>
      ))}
      <AddScene locked={locked} first={!episode.scenes.length} onAdd={onAddScene} />
    </section>
  );
}

/** Design "+ Add shot": a dashed card that opens a short form (what happens, length, framing). */
function AddShot({ locked, onAdd }: { locked: boolean; onAdd: (fields: ShotFields) => void }) {
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [seconds, setSeconds] = useState("3");
  const [framing, setFraming] = useState("medium");
  if (!open) {
    return (
      <button type="button" className="olf-card olf-add" disabled={locked} onClick={() => setOpen(true)} data-testid="add-shot">
        + Add shot
      </button>
    );
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    onAdd({ description: description.trim(), duration: `${seconds}s`, framing });
    setOpen(false);
    setDescription("");
  }
  return (
    <form className="olf-card olf-add-form" onSubmit={submit} data-testid="add-shot-form">
      <textarea className="olf-input olf-textarea" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What happens in the shot" aria-label="Shot description" autoFocus />
      <div className="olf-row">
        <input className="olf-input" type="number" min={0.5} step={0.5} value={seconds} onChange={(e) => setSeconds(e.target.value)} aria-label="Length in seconds" />
        <Pick value={framing} options={FRAMINGS} onPick={(v) => v && setFraming(v)} />
      </div>
      <div className="olf-row">
        <button type="submit" className="run olf-small olf-grow" disabled={!description.trim() || !(Number(seconds) > 0)}>
          Add shot
        </button>
        <button type="button" className="ghost olf-small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** A new scene: its heading (INT. LAMP ROOM - NIGHT). An episode with no scenes asks for one. */
function AddScene({ locked, first, onAdd }: { locked: boolean; first: boolean; onAdd: (heading: string) => void }) {
  const [open, setOpen] = useState(false);
  const [heading, setHeading] = useState("");
  if (!open && !first) {
    return (
      <button type="button" className="ghost olf-small olf-add-scene" disabled={locked} onClick={() => setOpen(true)} data-testid="add-scene">
        + Add scene
      </button>
    );
  }
  return (
    <form
      className="olf-add-scene-form"
      onSubmit={(event) => {
        event.preventDefault();
        onAdd(heading.trim());
        setHeading("");
        setOpen(false);
      }}
      data-testid="add-scene-form"
    >
      {first ? <p className="muted">This episode has no scenes yet. Add the first scene, then its shots.</p> : null}
      <div className="olf-row">
        <input className="olf-input olf-grow" value={heading} onChange={(e) => setHeading(e.target.value)} placeholder="INT. LAMP ROOM - NIGHT" aria-label="Scene heading" autoFocus={!first} />
        <button type="submit" className="run olf-small" disabled={locked || !heading.trim()}>
          Add scene
        </button>
        {first ? null : (
          <button type="button" className="ghost olf-small" onClick={() => setOpen(false)}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

/** One shot on the storyboard: its keyframe (else its framing), its state and its tags. A click opens it. */
function ShotCard({ show, id, busy, onOpen }: { show: OlfShow; id: string; busy?: string; onOpen: () => void }) {
  const shot = show.shots[id];
  const state = shotState(show, id);
  const keyframe = shownKeyframe(show, id);
  return (
    <button
      type="button"
      className={`olf-card${state === "stale" ? " is-stale" : ""}`}
      onClick={onOpen}
      aria-label={`Open shot ${id}`}
      data-testid="shot-card"
      data-shot={id}
      data-state={state}
    >
      <span className="olf-card-thumb">
        {keyframe?.file ? (
          <img src={fileUrl(show.path, keyframe.file)} alt="" />
        ) : shot.pills?.start.length ? (
          <>
            <PillFrame pills={shot.pills} />
            <span className="olf-pills-tag">{framingShort(shot.camera)}</span>
          </>
        ) : (
          <span className="olf-card-ph">{framingShort(shot.camera)}</span>
        )}
        <span className="olf-card-tags">
          {state === "error" ? (
            <span className="olf-pill status-rejected">error</span>
          ) : keyframe ? (
            <StatusPill status={keyframe.status} />
          ) : (
            <span className="olf-pill">no takes</span>
          )}
        </span>
        {state === "stale" ? (
          <span className="olf-card-stale">
            <StalePill />
          </span>
        ) : null}
        {busy ? <span className="olf-busy">{busyText(busy)}</span> : null}
      </span>
      <span className="olf-card-body">
        <span className="olf-card-line">
          <code>{takeName(id)}</code>
          <span>{frames(shot.duration)}</span>
        </span>
        <span className="olf-card-desc">{shot.error || shot.description}</span>
        <span className="olf-card-meta">{takesSummary(show, id)}</span>
      </span>
    </button>
  );
}

/** Shots: one table row per shot of the episode. */
export function ShotsTable({
  show,
  episode,
  onOpenShot,
}: {
  show: OlfShow;
  episode: OlfEpisode;
  onOpenShot: (id: string) => void;
}) {
  return (
    <section data-testid="shows-shots">
      <header className="olf-head">
        <div>
          <h1>Shots</h1>
          <p className="muted">Every shot of the episode, in play order.</p>
        </div>
      </header>
      <table className="olf-table">
        <thead>
          <tr>
            <th>Shot</th>
            <th>Scene</th>
            <th>Camera</th>
            <th>What happens</th>
            <th>Length</th>
            <th>Keyframe</th>
            <th>Takes</th>
          </tr>
        </thead>
        <tbody>
          {episode.scenes.flatMap((scene) =>
            scene.shots.map((id) => {
              const shot = show.shots[id];
              const keyframe = shownKeyframe(show, id);
              return (
                <tr key={id} onClick={() => onOpenShot(id)} data-testid="shots-row">
                  <td>
                    {/* A button for the keyboard; its click reaches the row's handler. */}
                    <button type="button" className="olf-link" aria-label={`Open shot ${id}`}>
                      <code>{takeName(id)}</code>
                    </button>
                  </td>
                  <td>{scene.heading || scene.id}</td>
                  <td>
                    <code>{framingShort(shot.camera)}</code>
                  </td>
                  <td className="olf-table-desc">{shot.error || shot.description}</td>
                  <td>{frames(shot.duration)}</td>
                  <td>{keyframe ? <StatusPill status={keyframe.status} /> : <span className="muted">none</span>}</td>
                  <td>
                    {takesSummary(show, id)} {shotState(show, id) === "stale" ? <StalePill /> : null}
                  </td>
                </tr>
              );
            }),
          )}
        </tbody>
      </table>
    </section>
  );
}
