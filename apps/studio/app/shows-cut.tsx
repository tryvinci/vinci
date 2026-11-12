"use client";

import { type MouseEvent, useEffect, useRef, useState } from "react";
import {
  type OlfClip,
  type OlfCueRow,
  type OlfCut,
  type OlfExport,
  type OlfPlan,
  type OlfShow,
  clipAt,
  clipLabel,
  clockText,
  cueAt,
  dialogueLabel,
  fadeAt,
  fileUrl,
  price,
  silentClips,
  spendText,
  takeName,
  timelineTicks,
} from "../lib/shows";
import { message, olf, send } from "./shows-api";
import { Confirm, Field, OlfOnly, StalePill } from "./shows-parts";

type ClipFields = Record<string, string | number | null>;

/**
 * Cut and export (Claude Design, screen 4): the 16:9 preview and its 9:16 crop, the timeline,
 * the selected clip and the export. Playback runs in the browser over the take files (a clock
 * that walks the clips), so nothing renders until Export. Full width: the top bar holds the tabs.
 * A clip plays its take's own sound, or (`audio: separate`) the shot's chosen dialogue take from
 * the start of the clip, as the export does. "Add music cue" renders a music or SFX cue (price
 * first) and places it at the playhead; the cues play over the preview at their volume.
 */
export function CutView({
  show,
  cut,
  busy,
  result,
  onUseApproved,
  onClip,
  onExport,
  onCueAdded,
}: {
  show: OlfShow;
  cut: OlfCut | null;
  busy: string;
  result: OlfExport | null;
  onUseApproved: () => void;
  onClip: (index: number, fields: ClipFields) => void;
  onExport: (aspects: string[], subtitles: boolean, c2pa: boolean, otio: boolean, sound: boolean) => void;
  /** A cue was rendered and placed: reload the cut. */
  onCueAdded: (text: string) => void;
}) {
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState(0);
  const [aspects, setAspects] = useState<string[]>(["16:9", "9:16"]);
  const [subtitles, setSubtitles] = useState(true);
  const [adding, setAdding] = useState(false); // the Add music cue form is open
  const [signed, setSigned] = useState(true); // C2PA provenance, when the daemon can sign
  const [otio, setOtio] = useState(false); // also OpenTimelineIO and stems
  const [sound, setSound] = useState(true); // off: no audio stream, the lines are only subtitles
  const duration = cut?.duration || 0;

  // The clock: advance while playing; stop at the end of the cut.
  useEffect(() => {
    if (!playing || !duration) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const step = (now - last) / 1000;
      last = now;
      setTime((at) => Math.min(at + step, duration));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, duration]);
  useEffect(() => {
    if (playing && time >= duration) setPlaying(false);
  }, [playing, time, duration]);

  if (!cut) return <p className="muted">Loading the cut…</p>;
  if (!cut.clips.length) {
    return (
      <section className="olf-cut-empty" data-testid="cut-empty">
        <h1>No cut yet</h1>
        <p className="muted">
          The cut lists takes in play order. Start from the approved video of each shot, or its approved keyframe as a
          still.
        </p>
        <button type="button" className="run" disabled={Boolean(busy)} onClick={onUseApproved} data-testid="cut-use-approved">
          {busy === "approved" ? "Building the cut…" : "Use approved takes"}
        </button>
      </section>
    );
  }
  const at = clipAt(cut, time);
  const fade = fadeAt(cut, time); // the previews draw it as the export does
  const cue = subtitles ? cueAt(cut, time) : "";
  const sel = cut.clips[selected] || cut.clips[0];
  const pct = (seconds: number) => `${(seconds / (duration || 1)) * 100}%`;
  const [width, height] = cut.format.resolution.split("x");
  const speech = sel.dialogue_take;
  const silent = sound ? silentClips(cut) : []; // with no sound, a missing dialogue take stops nothing
  const seek = (event: MouseEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    setTime(Math.min(Math.max(((event.clientX - box.left) / box.width) * duration, 0), duration));
  };
  const commit = (key: "in" | "out", text: string) => {
    const value = Number.parseFloat(text);
    if (Number.isFinite(value) && value >= 0 && value !== sel[key]) onClip(sel.index, { [key]: value });
  };

  return (
    <section className="olf-cut" data-testid="cut-page">
      <div className="olf-cut-main">
        <div className="olf-cut-previews">
          {/* Only the wide preview plays the take's own sound, so it is heard once. */}
          <Preview show={show} at={at} fade={fade} playing={playing} cue={cue} sound className="olf-cut-wide" testId="cut-preview" />
          <Preview show={show} at={at} fade={fade} playing={playing} cue={cue} className="olf-cut-tall" testId="cut-preview-tall" />
          <DialogueSound show={show} at={at} playing={playing} />
          {cut.audio.map((row) => (
            <CueSound key={row.take} show={show} row={row} time={time} playing={playing} />
          ))}
        </div>
        <div className="olf-cut-transport">
          <button
            type="button"
            className="olf-play"
            aria-label={playing ? "Pause" : "Play"}
            onClick={() => {
              if (!playing && time >= duration) setTime(0);
              setPlaying(!playing);
            }}
            data-testid="cut-play"
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <code data-testid="cut-time">
            {clockText(time)} / {clockText(duration)}
          </code>
          <span className="olf-grow" />
          <button type="button" className="ghost" disabled={Boolean(busy)} onClick={onUseApproved} data-testid="cut-use-approved">
            {busy === "approved" ? "Building the cut…" : "Use approved takes"}
          </button>
          <OlfOnly path="/olf/cue">
            <button type="button" className="ghost" aria-pressed={adding} onClick={() => setAdding(!adding)} data-testid="cut-add-cue">
              Add music cue
            </button>
          </OlfOnly>
        </div>
        {adding ? (
          <AddCue
            path={show.path}
            episode={cut.episode}
            start={time}
            onDone={(text) => {
              setAdding(false);
              onCueAdded(text);
            }}
          />
        ) : null}
        <div className="olf-timeline" data-testid="cut-timeline">
          <span className="olf-track-label" />
          <div className="olf-ruler" onClick={seek}>
            {timelineTicks(duration).map((mark) => (
              <span key={mark} style={{ left: pct(mark) }}>
                {clockText(mark).replace(/\.0$/, "")}
              </span>
            ))}
          </div>
          <span className="olf-track-label">Video</span>
          <div className="olf-lane olf-lane-video" onClick={seek}>
            {cut.clips.map((clip) => {
              const label = clipLabel(clip);
              return (
                <button
                  key={clip.index}
                  type="button"
                  className={`olf-clip${clip.index === sel.index ? " on" : ""}${clip.stale ? " is-stale" : ""}${clip.missing ? " is-missing" : ""}`}
                  style={{ left: pct(clip.start), width: pct(clip.length) }}
                  title={`${clip.take} · ${clip.length.toFixed(1)} s`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelected(clip.index);
                    setTime(clip.start);
                  }}
                  data-testid="cut-clip"
                >
                  <code>{label.shot}</code>
                  <span>{label.take}</span>
                </button>
              );
            })}
          </div>
          <span className="olf-track-label">Dialogue</span>
          <div className="olf-lane">
            {/* A separate dialogue take starts with its clip; its block is as long as the speech. */}
            {cut.clips
              .filter((clip) => clip.audio === "separate")
              .map((clip) => (
                <span
                  key={clip.index}
                  className={`olf-cue-block${clip.dialogue_take?.file ? "" : " is-missing"}${clip.dialogue_take?.stale ? " is-stale" : ""}`}
                  style={{
                    left: pct(clip.start),
                    width: pct(Math.min(clip.dialogue_take?.length || clip.length, clip.length)),
                  }}
                  title={clip.dialogue_take ? `${clip.dialogue_take.take} · ${clip.dialogue_take.length.toFixed(1)} s` : ""}
                  data-testid="cut-dialogue"
                >
                  {dialogueLabel(show, clip)}
                </span>
              ))}
            {cut.clips.some((clip) => clip.audio === "separate") ? null : (
              <span className="olf-lane-note">No separate dialogue in this cut. Choose it for a clip under Audio.</span>
            )}
          </div>
          <span className="olf-track-label">Music · SFX</span>
          <div className="olf-lane">
            {cut.audio.length ? (
              cut.audio.map((row) => (
                <span
                  key={row.take}
                  className={`olf-cue-block is-music${row.missing ? " is-missing" : ""}${row.stale ? " is-stale" : ""}`}
                  style={{ left: pct(row.start), width: pct(Math.min(row.length || 1, Math.max(duration - row.start, 0.5))) }}
                  title={`${row.take} · ${row.length.toFixed(1)} s from ${clockText(row.start)} · volume ${row.volume}${row.duck ? " · ducked under dialogue" : ""}`}
                  data-testid="cut-cue"
                >
                  {row.label} · {takeName(row.take)} · vol {row.volume}
                  {row.duck ? " · ducked" : ""}
                  {row.stale ? " · stale" : ""}
                </span>
              ))
            ) : (
              <span className="olf-lane-note">No music cues yet</span>
            )}
          </div>
          <div className="olf-playhead-lane" aria-hidden>
            <span className="olf-playhead" style={{ left: pct(time) }} />
          </div>
        </div>
      </div>

      <aside className="olf-cut-side">
        <section className="olf-cut-block" data-testid="cut-clip-panel">
          <header>
            <h3>Selected clip</h3>
            {sel.stale ? <StalePill /> : null}
          </header>
          <code className="olf-cut-take">{sel.take}</code>
          <div className="olf-grid2">
            <Field label="In">
              <input
                key={`in-${sel.take}-${sel.in}`}
                className="olf-input"
                type="number"
                min={0}
                step={0.1}
                defaultValue={sel.in}
                onBlur={(event) => commit("in", event.currentTarget.value)}
                onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
                aria-label="In (seconds)"
                data-testid="cut-in"
              />
            </Field>
            <Field label="Out">
              <input
                key={`out-${sel.take}-${sel.out}`}
                className="olf-input"
                type="number"
                min={0}
                step={0.1}
                defaultValue={sel.out}
                onBlur={(event) => commit("out", event.currentTarget.value)}
                onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
                aria-label="Out (seconds)"
                data-testid="cut-out"
              />
            </Field>
          </div>
          <Field label="Transition in">
            <div className="olf-choice">
              {(["cut", "fade"] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={sel.transition === kind}
                  disabled={Boolean(busy) || (kind === "fade" && sel.index === 0)}
                  onClick={() => onClip(sel.index, { transition: kind === "cut" ? null : "fade" })}
                  data-testid={`cut-transition-${kind}`}
                >
                  {kind === "cut" ? "Cut" : "Fade"}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Audio">
            <select
              className="olf-input"
              value={sel.audio}
              disabled={Boolean(busy)}
              onChange={(event) => onClip(sel.index, { audio: event.target.value === "own" ? null : "separate" })}
              data-testid="cut-audio"
            >
              <option value="own">The take's own sound</option>
              <option value="separate" disabled={!speech && sel.audio !== "separate"}>
                Separate dialogue take{speech ? ` (${takeName(speech.take)})` : " (none chosen)"}
              </option>
            </select>
          </Field>
        </section>

        <section className="olf-cut-block" data-testid="cut-export">
          <header>
            <h3>Export</h3>
          </header>
          <label className="olf-check">
            <input
              type="checkbox"
              checked={aspects.includes("16:9")}
              onChange={() => setAspects((rows) => (rows.includes("16:9") ? rows.filter((a) => a !== "16:9") : ["16:9", ...rows]))}
            />
            16:9 · {width}×{height}
          </label>
          <label className="olf-check">
            <input
              type="checkbox"
              checked={aspects.includes("9:16")}
              onChange={() => setAspects((rows) => (rows.includes("9:16") ? rows.filter((a) => a !== "9:16") : [...rows, "9:16"]))}
            />
            9:16 · 1080×1920 for X
          </label>
          <label className="olf-check">
            <input type="checkbox" checked={subtitles} onChange={() => setSubtitles(!subtitles)} />
            Burn-in subtitles
          </label>
          <label className="olf-check" title="Off: the files have no audio stream. The lines are only subtitles, and each names its speaker.">
            <input type="checkbox" checked={sound} onChange={() => setSound(!sound)} data-testid="cut-sound" />
            Sound
          </label>
          <label
            className={`olf-check${cut.c2pa ? "" : " is-off"}`}
            title={cut.c2pa ? "Sign each file with a C2PA manifest of its takes (a local signing key)" : "Install c2pa-python (vinci-olf[c2pa]) to sign exports"}
          >
            <input type="checkbox" checked={!!cut.c2pa && signed} disabled={!cut.c2pa} onChange={() => setSigned(!signed)} data-testid="cut-c2pa" />
            C2PA provenance
          </label>
          <label className="olf-check" title="An OpenTimelineIO file of the cut, and WAV stems: dialogue, music and SFX">
            <input type="checkbox" checked={otio} onChange={() => setOtio(!otio)} data-testid="cut-otio" />
            Also export OTIO and stems
          </label>
          {cut.stale ? (
            <p className="olf-impact is-stale" data-testid="cut-stale">
              {cut.stale === 1 ? "1 clip in this cut is stale" : `${cut.stale} clips in this cut are stale`}. Re-render
              {cut.stale === 1 ? " it" : " them"}, or export as {cut.stale === 1 ? "it is" : "they are"}.
            </p>
          ) : null}
          {cut.missing ? <p className="olf-error">A take in the cut has no file. Re-render it, or take it out of the cut.</p> : null}
          {silent.length ? (
            <p className="olf-error" data-testid="cut-silent">
              {silent.map((clip) => clipLabel(clip).shot).join(", ")}: the audio is separate, but the shot has no chosen
              dialogue take. Render and approve dialogue on the shot page, or use the take's own sound.
            </p>
          ) : null}
          <button
            type="button"
            className="run olf-cut-export"
            disabled={Boolean(busy) || !aspects.length || cut.missing > 0 || silent.length > 0}
            onClick={() => onExport(aspects, subtitles, !!cut.c2pa && signed, otio, sound)}
            data-testid="cut-export-button"
          >
            {busy === "export" ? "Exporting…" : "Export episode"}
          </button>
          {result ? (
            <ul className="olf-export-files" data-testid="cut-export-files">
              {result.files.map((file) => (
                <li key={file}>
                  {/\.(mp4|wav)$/.test(file) ? (
                    <a href={fileUrl(show.path, file)} target="_blank" rel="noreferrer">
                      {file}
                    </a>
                  ) : (
                    <code>{file}</code>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      </aside>
    </section>
  );
}

/**
 * The separate dialogue of the clip under the playhead, on the clock: it starts with its clip
 * (as in the export) and stops at its end.
 */
function DialogueSound({ show, at, playing }: { show: OlfShow; at: { clip: OlfClip; offset: number } | null; playing: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  const take = at?.clip.audio === "separate" ? at.clip.dialogue_take : null;
  useEffect(() => {
    const audio = ref.current;
    if (!audio || !at || !take) return;
    const offset = at.offset - at.clip.in; // seconds since the clip started
    const live = playing && offset < take.length;
    if (Math.abs(audio.currentTime - offset) > 0.3 && offset < take.length) audio.currentTime = offset;
    if (live && audio.paused) void audio.play().catch(() => undefined);
    if (!live && !audio.paused) audio.pause();
  });
  return take?.file ? (
    <audio key={take.take} ref={ref} src={fileUrl(show.path, take.file)} preload="auto" data-testid="cut-dialogue-audio" />
  ) : null;
}

/** A music or SFX cue on the clock: it plays from its start for its length, at its volume. */
function CueSound({ show, row, time, playing }: { show: OlfShow; row: OlfCueRow; time: number; playing: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const audio = ref.current;
    if (!audio) return;
    const offset = time - row.start;
    const live = playing && offset >= 0 && offset < row.length;
    audio.volume = Math.min(Math.max(row.volume, 0), 1); // the browser caps volume at 1
    if (live && Math.abs(audio.currentTime - offset) > 0.3) audio.currentTime = offset;
    if (live && audio.paused) void audio.play().catch(() => undefined);
    if (!live && !audio.paused) audio.pause();
  });
  return row.file ? <audio ref={ref} src={fileUrl(show.path, row.file)} preload="auto" data-testid="cut-cue-audio" /> : null;
}

/**
 * "Add music cue": a music or SFX cue from a description and a length, rendered with the price
 * first (`POST /olf/cue`) and placed at the playhead with a volume and ducking under dialogue.
 */
function AddCue({ path, episode, start, onDone }: { path: string; episode: string; start: number; onDone: (text: string) => void }) {
  const [kind, setKind] = useState<"music" | "sfx">("music");
  const [description, setDescription] = useState("");
  const [seconds, setSeconds] = useState("10");
  const [volume, setVolume] = useState("0.6");
  const [duck, setDuck] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [ask, setAsk] = useState<OlfPlan | null>(null); // a paid cue waits here for Confirm
  const body = { path, episode, kind, description, duration: Number(seconds), start, volume: Number(volume), duck };

  async function go(confirmed?: OlfPlan) {
    setError("");
    try {
      if (!confirmed) {
        setBusy("Checking the price…");
        const plan = await olf<OlfPlan>("/cue", send("POST", { ...body, dry_run: true }));
        if (plan.total || plan.unpriced?.length) {
          setAsk(plan);
          return;
        }
        confirmed = plan;
      }
      setBusy(kind === "music" ? "Composing the music…" : "Making the sound…");
      const out = await olf<OlfPlan & { cue: string }>("/cue", send("POST", { ...body, yes: true, max_total: confirmed.total || 0 }));
      console.info("[shows] cue", { cue: out.cue, takes: out.takes, total: out.total });
      onDone(`Added ${out.cue} at ${clockText(start)} · ${out.plan?.[0]?.model} · ${price(out.total)}`);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy("");
    }
  }

  const top = kind === "music" ? 60 : 30; // the engine's limits (vinci_olf.cues.MAX_SECONDS)
  return (
    <form
      className="olf-cut-block olf-add-cue"
      onSubmit={(event) => {
        event.preventDefault();
        void go();
      }}
      data-testid="cut-cue-form"
    >
      <div className="olf-tabs" role="radiogroup" aria-label="Cue kind">
        {(["music", "sfx"] as const).map((k) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={kind === k}
            aria-selected={kind === k}
            onClick={() => {
              setKind(k);
              setSeconds(k === "music" ? "10" : "2");
              setVolume(k === "music" ? "0.6" : "1");
              setDuck(k === "music");
            }}
          >
            {k === "music" ? "Music" : "SFX"}
          </button>
        ))}
      </div>
      <input className="olf-input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder={kind === "music" ? "Slow piano, distant waves" : "An old door creaks open"} aria-label="Cue description" autoFocus />
      <div className="olf-row">
        <label className="olf-field">
          <span className="olf-label">Length (s, up to {top})</span>
          <input className="olf-input" type="number" min={0.5} max={top} step={0.5} value={seconds} onChange={(e) => setSeconds(e.target.value)} aria-label="Cue length" />
        </label>
        <label className="olf-field">
          <span className="olf-label">Volume</span>
          <input className="olf-input" type="number" min={0} max={2} step={0.1} value={volume} onChange={(e) => setVolume(e.target.value)} aria-label="Cue volume" />
        </label>
        <label className="olf-check">
          <input type="checkbox" checked={duck} onChange={(e) => setDuck(e.target.checked)} /> Duck under dialogue
        </label>
      </div>
      {ask ? (
        <Confirm
          text={spendText(ask.total, ask.unpriced, `a ${kind} cue from ${ask.plan?.[0]?.model || "a model"}`)}
          onYes={() => {
            const plan = ask;
            setAsk(null);
            void go(plan);
          }}
          onNo={() => setAsk(null)}
        />
      ) : (
        <button type="submit" className="run" disabled={!description.trim() || !!busy || !(Number(seconds) >= 0.5 && Number(seconds) <= top)} data-testid="cut-cue-add">
          {busy || `Add at ${clockText(start)}`}
        </button>
      )}
      {error ? <p className="olf-error olf-small-text">{error}</p> : null}
    </form>
  );
}

type At = { clip: OlfClip; offset: number };

/**
 * One preview: the clip under the playhead (video, or a keyframe still) with the subtitle line.
 * In a fade, the clip that fades in covers the clip before it, more each frame (as in export).
 */
function Preview({
  show,
  at,
  fade,
  playing,
  cue,
  sound = false,
  className,
  testId,
}: {
  show: OlfShow;
  at: At | null;
  fade: { from: At; to: At; mix: number } | null;
  playing: boolean;
  cue: string;
  /** Play the take's own sound (only when the clip does not play separate dialogue). */
  sound?: boolean;
  className: string;
  testId: string;
}) {
  return (
    <div className={className} data-testid={testId} data-fade={fade ? fade.mix.toFixed(2) : undefined}>
      {fade ? (
        <>
          <Layer show={show} at={fade.from} playing={playing} sound={false} />
          <Layer show={show} at={fade.to} playing={playing} sound={sound} opacity={fade.mix} />
        </>
      ) : (
        <Layer show={show} at={at} playing={playing} sound={sound} />
      )}
      {cue ? <span className="olf-cue">{cue}</span> : null}
    </div>
  );
}

/** One clip in a preview, kept on the clock: seek when it drifts, play and pause with the transport. */
function Layer({ show, at, playing, sound, opacity }: { show: OlfShow; at: At | null; playing: boolean; sound: boolean; opacity?: number }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const video = ref.current;
    if (!video || !at) return;
    if (Math.abs(video.currentTime - at.offset) > 0.3) video.currentTime = at.offset;
    if (playing && video.paused) void video.play().catch(() => undefined);
    if (!playing && !video.paused) video.pause();
  });
  const clip = at?.clip;
  const style = opacity === undefined ? undefined : { opacity };
  if (clip?.file && clip.kind === "video") {
    return (
      <video
        key={clip.take}
        ref={ref}
        className="olf-cut-layer"
        style={style}
        src={fileUrl(show.path, clip.file)}
        muted={!sound || clip.audio === "separate"}
        playsInline
        preload="auto"
        onLoadedMetadata={(event) => {
          event.currentTarget.currentTime = at?.offset || 0;
        }}
      />
    );
  }
  if (clip?.file) return <img className="olf-cut-layer" style={style} src={fileUrl(show.path, clip.file)} alt="" />;
  return <span className="olf-cut-ph">{clip ? `No file for ${clip.take}` : "No clip"}</span>;
}
