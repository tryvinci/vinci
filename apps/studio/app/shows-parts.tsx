"use client";

import { type ReactNode, useEffect, useState } from "react";
import { type OlfPill, type OlfPills, type OlfShow, SLOT_COLORS, mediaUrl } from "../lib/shows";
import { message, olf } from "./shows-api";

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
  onPick: (value: string | null) => void;
  testId?: string;
}) {
  const list = value && !options.includes(value) ? [value, ...options] : options;
  return (
    <select
      className="olf-input"
      value={value || ""}
      disabled={disabled}
      onChange={(event) => onPick(event.target.value || null)}
      data-testid={testId}
    >
      {blank || !value ? <option value="">—</option> : null}
      {list.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
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
