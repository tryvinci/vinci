"use client";

import { type ChangeEvent, type ReactNode, useEffect, useRef, useState } from "react";
import {
  COPY_PROMPT,
  type OlfModels,
  type OlfPill,
  type OlfPills,
  type OlfShow,
  SLOT_COLORS,
  TEXT_MODEL_KEY,
  autoLabel,
  choiceLabel,
  mediaUrl,
} from "../lib/shows";
import { message, olf, useOlfRoute } from "./shows-api";

/** Its children only when the daemon serves `path`. A host serves fewer OLF routes for now. */
export function OlfOnly({ path, children }: { path: string; children: ReactNode }) {
  return useOlfRoute(path) ? <>{children}</> : null;
}

/**
 * Design: the character's Voice. An ElevenLabs voice from `GET /olf/voices` (a free call); with no
 * ElevenLabs the list is empty, because demo speech has one voice.
 */
export function VoicePick({ value, onPick, testId }: { value: string; onPick: (id: string, name: string) => void; testId: string }) {
  const [voices, setVoices] = useState<{ id: string; name: string }[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    olf<{ voices: { id: string; name: string }[] }>("/voices")
      .then((body) => setVoices(body.voices))
      .catch((err) => {
        setVoices([]);
        setError(message(err));
      });
  }, []);
  if (voices && !voices.length) {
    return (
      <span className="muted olf-small-text" data-testid={testId}>
        {error || "Connect ElevenLabs to pick a voice. Demo speech has one voice."}
      </span>
    );
  }
  const known = !value || !!voices?.some((row) => row.id === value);
  return (
    <select
      className="olf-input"
      value={known ? value : "other"}
      disabled={!voices}
      onChange={(event) => {
        const row = voices?.find((voice) => voice.id === event.target.value);
        if (row) onPick(row.id, row.name);
      }}
      data-testid={testId}
    >
      <option value="" disabled>
        {voices ? "Pick a voice" : "Loading voices…"}
      </option>
      {known ? null : (
        <option value="other" disabled>
          {value} (not in this account)
        </option>
      )}
      {(voices || []).map((row) => (
        <option key={row.id} value={row.id}>
          {row.name}
        </option>
      ))}
    </select>
  );
}

/** A take status (`draft`, `candidate`, `approved`, `rejected`) as a small pill. */
export function StatusPill({ status }: { status?: string | null }) {
  if (!status) return null;
  return <span className={`olf-pill status-${status}`}>{status}</span>;
}

/** The orange mark: an input changed after the render (calculated, never stored). */
export function StalePill() {
  return <span className="olf-pill is-stale">stale</span>;
}

/** The pin video is older than the shot camera: the stage and the keyframe layout box say so. Kept here, not in
 * shows-scenelab.tsx, so the shot page shows it without loading the lazy scene lab. */
export function PinStale({ fields }: { fields: string[] }) {
  return (
    <p className="olf-warn" data-testid="pin-stale">
      Pin video is out of date: {fields.join(", ")} changed. Click Use again to re-record it.
    </p>
  );
}

export function Panel({
  title,
  aside,
  children,
  testId,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section className="olf-panel" data-testid={testId}>
      <header>
        <h3>{title}</h3>
        {aside ? <span className="olf-panel-aside">{aside}</span> : null}
      </header>
      {children}
    </section>
  );
}

/** The design's play bar for a video or an audio take: play, a scrub bar and the time. */
export function PlayBar({ media }: { media: HTMLMediaElement }) {
  const [state, setState] = useState({ playing: false, time: 0, duration: 0 });
  useEffect(() => {
    const sync = () =>
      setState({
        playing: !media.paused,
        time: media.currentTime,
        duration: Number.isFinite(media.duration) ? media.duration : 0,
      });
    const events = ["timeupdate", "loadedmetadata", "durationchange", "play", "pause", "ended"];
    for (const name of events) media.addEventListener(name, sync);
    sync();
    return () => {
      for (const name of events) media.removeEventListener(name, sync);
    };
  }, [media]);
  return (
    <div className="olf-playbar" data-testid="play-bar">
      <button
        type="button"
        className="olf-play"
        aria-label={state.playing ? "Pause" : "Play"}
        onClick={() => (media.paused ? void media.play().catch(() => undefined) : media.pause())}
        data-testid="play-toggle"
      >
        {state.playing ? "❚❚" : "▶"}
      </button>
      <input
        type="range"
        className="olf-scrub"
        min={0}
        max={state.duration || 0}
        step={0.05}
        value={Math.min(state.time, state.duration || 0)}
        onChange={(event) => {
          media.currentTime = Number(event.target.value);
        }}
        aria-label="Seek"
      />
      <code data-testid="play-time">
        {state.time.toFixed(1)} / {state.duration.toFixed(1)}s
      </code>
    </div>
  );
}

/** Read a picked file as a `data:` URL, the way the authoring routes take images. */
export function fileData(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read the file"));
    reader.readAsDataURL(file);
  });
}

/**
 * Props for a select that shows a pick at once. Bug fixed (first report 2026-11-19, prod, COREPRODUC-737): a shot
 * menu was bound to the saved value, so a pick snapped back until the save and the show reload
 * ended (seconds on a host), and the person saw no change.
 *
 * Args:
 *   value: The saved value.
 *   onPick: Saves a pick (`null` for ""); its promise ends after the save and the reload.
 *   scope: What the menu edits (a Cut clip); a pick shows only while the menu edits the same thing.
 *
 * Returns:
 *   `value`, `onChange` and `aria-busy` for a `<select>`: the pick shows (busy) until `onPick`
 *   ends, then the saved value shows again, so a failed save shows the old value. Only the
 *   newest pick ends the busy state, so an older save cannot hide a newer pick (CodeRabbit, #715).
 */
export function usePick(value: string | undefined, onPick: (value: string | null) => unknown, scope = "") {
  const [pending, setPending] = useState<{ value: string; scope: string } | null>(null);
  const newest = useRef(0);
  const shown = pending?.scope === scope ? pending.value : null;
  return {
    value: shown ?? value ?? "",
    "aria-busy": shown !== null,
    onChange: (event: ChangeEvent<HTMLSelectElement>) => {
      const next = event.target.value;
      const run = ++newest.current;
      setPending({ value: next, scope });
      void Promise.resolve(onPick(next || null)).finally(() => run === newest.current && setPending(null));
    },
  };
}

/** A select for one shot field; `blank` adds a "—" option that removes an optional field. */
export function Pick({
  value,
  options,
  blank = false,
  disabled = false,
  onPick,
  testId,
}: {
  value?: string;
  options: readonly string[];
  blank?: boolean;
  disabled?: boolean;
  onPick: (value: string | null) => unknown;
  testId?: string;
}) {
  const list = value && !options.includes(value) ? [value, ...options] : options;
  return (
    <select className="olf-input" disabled={disabled} data-testid={testId} {...usePick(value, onPick)}>
      {blank || !value ? <option value="">—</option> : null}
      {list.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}

/**
 * The text model menu (`GET /olf/models?capability=t2t`) and the person's pick, kept for the next
 * visit and shared by the script panel and the scene lab: "" is Auto (routing), `COPY_PROMPT`
 * copies the prompt for their own agent. An agent CLI is only ever a person's pick.
 *
 * @param step "scene" asks for the scene lab's prices: the hosted scene build is free, so Vinci's
 *   row there says 0 credits, not the 1 credit of a script step (COREPRODUC-738).
 * @returns The menu (null until it loads), the pick, and a setter that keeps it.
 */
export function useTextModel(step?: "scene"): [OlfModels | null, string, (id: string) => void] {
  const [models, setModels] = useState<OlfModels | null>(null);
  const [pick, setPick] = useState("");
  useEffect(() => {
    olf<OlfModels>(`/models?capability=t2t${step ? `&step=${step}` : ""}`)
      .then((body) => {
        setModels(body);
        const saved = window.localStorage.getItem(TEXT_MODEL_KEY) || "";
        // With no routed model (live mode with only agent CLIs), the first choice is the default;
        // with no text model at all, copying the prompt is.
        const known = saved === COPY_PROMPT || body.choices.some((row) => row.id === saved);
        setPick(known ? saved : body.auto ? "" : body.choices[0]?.id || COPY_PROMPT);
      })
      .catch((err) => console.warn("[shows] text models", message(err)));
  }, []);
  const keep = (id: string) => {
    setPick(id);
    window.localStorage.setItem(TEXT_MODEL_KEY, id);
  };
  return [models, pick, keep];
}

/** The text model select: Auto, each model, and "Your agent · copy prompt". */
export function TextModelPick({
  models,
  value,
  disabled,
  onPick,
  testId,
}: {
  models: OlfModels;
  value: string;
  disabled?: boolean;
  onPick: (id: string) => void;
  testId: string;
}) {
  return (
    <select className="olf-input olf-small" value={value} disabled={disabled} onChange={(event) => onPick(event.target.value)} data-testid={testId}>
      {models.auto ? <option value="">{autoLabel(models.auto.model, models.choices)}</option> : null}
      {models.choices.map((row) => (
        <option key={row.id} value={row.id}>
          {choiceLabel(row)}
        </option>
      ))}
      <option value={COPY_PROMPT}>Your agent · copy prompt</option>
    </select>
  );
}

/** Ask before money is spent: the question, Confirm and Cancel. */
export function Confirm({ text, onYes, onNo }: { text: string; onYes: () => void; onNo: () => void }) {
  return (
    <div className="olf-confirm" role="alertdialog" aria-label="Confirm spend">
      <span>{text}</span>
      <button type="button" className="run olf-small" onClick={onYes}>
        Confirm
      </button>
      <button type="button" className="ghost olf-small" onClick={onNo}>
        Cancel
      </button>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="olf-field">
      <span className="olf-label">{label}</span>
      <div className="olf-value">{children}</div>
    </div>
  );
}

export function Swatches({ colors, large }: { colors?: unknown; large?: boolean }) {
  if (!Array.isArray(colors) || !colors.length) return null;
  return (
    <span className={`swatches${large ? " large" : ""}`}>
      {colors.map((color) => (
        <i key={String(color)} style={{ background: String(color) }} title={String(color)} />
      ))}
    </span>
  );
}

export function Chips({ items, onPick }: { items?: unknown; onPick?: (item: string) => void }) {
  if (!Array.isArray(items) || !items.length) return <span className="muted olf-small-text">None</span>;
  return (
    <span className="olf-chips">
      {items.map((item) =>
        onPick ? (
          <button key={String(item)} type="button" className="chip" onClick={() => onPick(String(item))}>
            {String(item)}
          </button>
        ) : (
          <span key={String(item)} className="chip">
            {String(item)}
          </span>
        ),
      )}
    </span>
  );
}

/** A reference image, always the whole file (OLF has no crops). */
export function RefThumb({ show, file, height }: { show: OlfShow; file: string | null; height: number }) {
  if (!file) {
    return (
      <span className="ref-thumb ref-missing" style={{ height, minWidth: height }}>
        no file
      </span>
    );
  }
  return <img className="ref-thumb" src={mediaUrl(show, file)} alt="" style={{ height }} title={file} />;
}

/** A shot's first frame as pills, for a shot with no picture yet: who stands where, how large,
 * and where they look. The e-conte sheet draws the same pills (vinci_olf.previs). */
export function PillFrame({ pills }: { pills: OlfPills }) {
  const [w, h] = [160, 90]; // the frame in viewBox units
  const people = [...pills.start].sort((a, b) => a.size - b.size); // the near pills last
  const names = people.map((pill) => pill.name || pill.slot).join(", ");
  return (
    <svg className="olf-pills" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid slice" role="img" aria-label={names ? `Pills: ${names}` : "No characters"} data-testid="pill-frame">
      {Array.from({ length: 15 }, (_, k) => (
        <line key={`x${k}`} x1={((k + 1) * w) / 16} x2={((k + 1) * w) / 16} y1={0} y2={h} className="olf-pills-grid" />
      ))}
      <line x1={0} x2={w} y1={h * 0.55} y2={h * 0.55} className="olf-pills-horizon" />
      {/* The key holds the place too: a layout can name one slot twice (CodeRabbit, #530). */}
      {people.map((pill, n) => (
        <PillShape key={`${pill.slot}${n}`} pill={pill} w={w} h={h} />
      ))}
    </svg>
  );
}

/** One pill: a body 7 heads tall with the stripe of its slot, and a dot at the eye line on the
 * side it looks to (no dot when it looks away). */
function PillShape({ pill, w, h }: { pill: OlfPill; w: number; h: number }) {
  const head = pill.size * h;
  const [x, eye, wide] = [pill.x * w, pill.y * h, head * 1.6];
  const top = eye - head * 0.6;
  const color = pill.color || SLOT_COLORS[pill.slot] || "currentColor";
  const dot = x + ({ left: -0.28, right: 0.28 }[pill.facing || ""] || 0) * wide;
  return (
    <g data-testid="pill" data-slot={pill.slot} data-facing={pill.facing || ""}>
      <rect x={x - wide / 2} y={top} width={wide} height={head * 7} rx={wide / 2} className="olf-pill-body" stroke={color} strokeWidth={Math.max(0.6, head * 0.06)} />
      <rect x={x - wide / 2 + 0.4} y={top + head * 2.2} width={wide - 0.8} height={head * 0.5} fill={color} />
      {pill.facing === "away" ? null : <circle cx={dot} cy={eye} r={Math.max(0.8, head * 0.12)} className="olf-pill-eye" />}
      {head >= 8 && pill.name ? (
        <text x={x} y={eye - head * 0.32} fontSize={Math.min(6, Math.max(4, head * 0.3))} textAnchor="middle" dominantBaseline="middle" className="olf-pill-name">
          {pill.name.split(" ")[0]}
        </text>
      ) : null}
    </g>
  );
}
