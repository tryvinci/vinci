"use client";

import { type MutableRefObject, type PointerEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { SENSOR_MM } from "../lib/pillframe";
import { type OlfFaces, type OlfGroup, type OlfPerson, type OlfPiece, type OlfRoom, type OlfShotTry, type ShotMove, type V3, roomChanges, staging, tryChanges } from "../lib/scenelab";
import type { SceneOptions, SceneViewer } from "../lib/scenelab-gl";
import { message, olf, send } from "./shows-api";
import { type Lab, type Mode, SceneView } from "./shows-scenelab";

/**
 * The scene lab's other screens (COREPRODUC-723, prototype boards B, D, E, F and G): compare two
 * tries, edit a try by hand (people, motion, background people, props and camera), and the scene's
 * room with its versions. Each opens full screen from the lab on the shot page. A hand edit runs no
 * model ($0): it changes the scene description only, and Vinci checks it as saving would.
 */

type Move = ShotMove & { lens?: string };
type View = { move: Move; aspect: number; opts: SceneOptions; free: boolean; names: Record<string, string> };
const SHAPES: OlfPiece["shape"][] = ["box", "cylinder", "cone", "sphere", "plane", "rock"];

/** A number field; a value that is not a number yet (a lone "-") is not sent. */
function Num({ label, value, step = 0.1, min, onChange }: { label: string; value: number | undefined; step?: number; min?: number; onChange: (v: number) => void }) {
  return (
    <label className="scene-lab-num">
      <span>{label}</span>
      <input
        type="number"
        className="olf-input olf-small"
        step={step}
        min={min}
        value={value ?? ""}
        onChange={(event) => {
          const v = parseFloat(event.target.value);
          if (Number.isFinite(v)) onChange(v);
        }}
      />
    </label>
  );
}

/** A floor plan value: to 0.05 m. */
const snap = (n: number) => Math.round(n * 20) / 20;
type Drag = "cam" | "aim" | `start:${number}` | `end:${number}`;

/**
 * The try from above (x to the right, z down the page: the camera usually stands at the bottom).
 * Set pieces and props are grey shapes, the camera a triangle with its horizontal field, a point it
 * aims at a cross, each named person a pin in their stripe color and their walk a dashed arrow.
 * Drag a person's start or end, the camera, or the point (to 0.05 m): `onChange` gets the new try,
 * so the 3D view, the number fields and the checks follow. The bounds hold still during a drag.
 */
function FloorPlan({ room, draft, view, onChange }: { room: OlfRoom; draft: OlfShotTry; view: View; onChange: (d: OlfShotTry) => void }) {
  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ what: Drag; box: number[] } | null>(null);
  const { at: cam, looks_at } = draft.camera;
  const pieces = [...room.set, ...(draft.props || [])];
  const aim = typeof looks_at === "string" ? draft.cast.find((p) => p.slot === looks_at)?.at : looks_at;
  const pts = [
    ...pieces.flatMap((p) => [[p.at[0] - p.size[0] / 2, p.at[2] - p.size[2] / 2], [p.at[0] + p.size[0] / 2, p.at[2] + p.size[2] / 2]]),
    ...draft.cast.flatMap((p) => [p.at, ...(p.end ? [p.end.at] : [])].map((at) => [at[0], at[2]])),
    [cam[0], cam[2]],
    ...(aim ? [[aim[0], aim[2]]] : []),
  ];
  const xs = pts.map((q) => q[0]), zs = pts.map((q) => q[1]);
  const box = drag?.box || [Math.min(...xs) - 1, Math.min(...zs) - 1, Math.max(...xs) - Math.min(...xs) + 2, Math.max(...zs) - Math.min(...zs) + 2];
  const u = Math.max(box[2], box[3]) / 60; // one plan unit: pins, labels and the camera scale with the plan
  const half = Math.atan(SENSOR_MM / 2 / (parseFloat(String(view.move.lens ?? "")) || 35)); // half the horizontal field
  const yaw = aim ? Math.atan2(aim[0] - cam[0], aim[2] - cam[2]) : Math.PI;
  const ray = (a: number, r: number) => `${cam[0] + Math.sin(a) * r},${cam[2] + Math.cos(a) * r}`;

  /** Move what is dragged to the pointer. */
  function move(event: PointerEvent<SVGSVGElement>) {
    const ctm = svg.current?.getScreenCTM();
    if (!drag || !ctm) return;
    const { x, y } = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
    const [px, pz] = [snap(x), snap(y)];
    const place = (at: V3): V3 => [px, at[1], pz];
    const [kind, n] = drag.what.split(":");
    const cast = (change: (p: OlfPerson) => OlfPerson) => draft.cast.map((p, k) => (k === +n ? change(p) : p));
    if (kind === "cam") onChange({ ...draft, camera: { ...draft.camera, at: place(cam) } });
    else if (kind === "aim" && typeof looks_at !== "string") onChange({ ...draft, camera: { ...draft.camera, looks_at: place(looks_at) } });
    else if (kind === "start") onChange({ ...draft, cast: cast((p) => ({ ...p, at: place(p.at) })) });
    else if (kind === "end") onChange({ ...draft, cast: cast((p) => (p.end ? { ...p, end: { ...p.end, at: place(p.end.at) } } : p)) });
  }
  /** Start a drag of `what` on a handle. */
  const grab = (what: Drag) => (event: PointerEvent) => {
    svg.current?.setPointerCapture(event.pointerId);
    setDrag({ what, box });
    console.info("[shows] floor plan drag", { what });
  };

  return (
    <svg
      ref={svg}
      className="scene-lab-plan"
      viewBox={box.join(" ")}
      onPointerMove={move}
      onPointerUp={() => setDrag(null)}
      onPointerCancel={() => setDrag(null)}
      role="img"
      aria-label="Floor plan from above: drag people, the camera and its aim"
      data-testid="scene-lab-plan"
    >
      {pieces.map((p, i) =>
        p.shape === "box" || p.shape === "plane" ? (
          <rect key={i} className="scene-lab-plan-piece" x={p.at[0] - p.size[0] / 2} y={p.at[2] - p.size[2] / 2} width={p.size[0]} height={p.size[2]} transform={`rotate(${-(p.turn || 0)} ${p.at[0]} ${p.at[2]})`} />
        ) : (
          <ellipse key={i} className="scene-lab-plan-piece" cx={p.at[0]} cy={p.at[2]} rx={p.size[0] / 2} ry={p.size[2] / 2} transform={`rotate(${-(p.turn || 0)} ${p.at[0]} ${p.at[2]})`} />
        ),
      )}
      <polyline className="scene-lab-plan-fov" points={[ray(yaw - half, u * 40), ray(yaw, 0), ray(yaw + half, u * 40)].join(" ")} />
      <polygon className="scene-lab-plan-cam" points={[ray(yaw, u * 2.4), ray(yaw + 2.5, u * 1.8), ray(yaw - 2.5, u * 1.8)].join(" ")} onPointerDown={grab("cam")} data-testid="scene-lab-plan-cam" />
      {typeof looks_at === "string" ? null : (
        <g className="scene-lab-plan-aim" onPointerDown={grab("aim")} data-testid="scene-lab-plan-aim">
          <circle cx={looks_at[0]} cy={looks_at[2]} r={u * 1.6} />
          <path d={`M${looks_at[0] - u * 2.2} ${looks_at[2]}h${u * 4.4}M${looks_at[0]} ${looks_at[2] - u * 2.2}v${u * 4.4}`} />
        </g>
      )}
      {draft.cast.map((p, i) => {
        const color = view.opts.stripes?.[p.slot] || "var(--teal)";
        // The walk's arrow stops at the end pin's edge: its head is a triangle in plan units.
        const [dx, dz] = p.end ? [p.end.at[0] - p.at[0], p.end.at[2] - p.at[2]] : [0, 0];
        const len = Math.hypot(dx, dz) || 1;
        const [ux, uz] = [dx / len, dz / len];
        const [hx, hz] = p.end ? [p.end.at[0] - ux * u * 1.6, p.end.at[2] - uz * u * 1.6] : [0, 0];
        return (
          <g key={p.slot}>
            {p.end ? (
              <>
                <line className="scene-lab-plan-walk" x1={p.at[0]} y1={p.at[2]} x2={hx} y2={hz} stroke={color} />
                <polygon points={`${hx},${hz} ${hx - ux * u * 2 - uz * u},${hz - uz * u * 2 + ux * u} ${hx - ux * u * 2 + uz * u},${hz - uz * u * 2 - ux * u}`} fill={color} />
                <circle className="scene-lab-plan-pin is-end" cx={p.end.at[0]} cy={p.end.at[2]} r={u * 1.4} color={color} onPointerDown={grab(`end:${i}`)} data-testid="scene-lab-plan-end" />
              </>
            ) : null}
            <circle className="scene-lab-plan-pin" cx={p.at[0]} cy={p.at[2]} r={u * 1.6} fill={color} onPointerDown={grab(`start:${i}`)} data-testid="scene-lab-plan-start" />
            <text className="scene-lab-plan-name" x={p.at[0] + u * 2.2} y={p.at[2] + u} fontSize={u * 3}>
              {view.names[p.slot] || p.slot}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Three (or four) numbers in a row: a place, a size, an area. */
function Vec({ label, value, keys = ["x", "y", "z"], onChange }: { label: string; value: number[]; keys?: string[]; onChange: (v: number[]) => void }) {
  return (
    <div className="olf-field">
      <span className="olf-label">{label}</span>
      <div className="scene-lab-vec">
        {keys.map((key, i) => (
          <Num key={key} label={key} value={value[i]} onChange={(v) => onChange(value.map((old, k) => (k === i ? v : old)))} />
        ))}
      </div>
    </div>
  );
}

/** Where someone looks: the camera, away, another person, any way (a group), or degrees. */
function Faces({ value, slots, names, any, onChange }: { value: OlfFaces | undefined; slots: string[]; names: Record<string, string>; any?: boolean; onChange: (v: OlfFaces | undefined) => void }) {
  const pick = typeof value === "number" ? "deg" : (value ?? (any ? "" : "camera"));
  return (
    <div className="olf-row scene-lab-faces">
      <select className="olf-input olf-small" value={pick} onChange={(e) => onChange(e.target.value === "deg" ? 0 : e.target.value || undefined)} aria-label="Faces">
        {any ? <option value="">Any way</option> : null}
        <option value="camera">The camera</option>
        <option value="away">Away from the camera</option>
        {slots.map((slot) => (
          <option key={slot} value={slot}>
            {names[slot] || `Slot ${slot}`}
          </option>
        ))}
        <option value="deg">Degrees</option>
      </select>
      {typeof value === "number" ? <Num label="°" value={value} step={15} onChange={onChange} /> : null}
    </div>
  );
}

function Tabs({ tab, onTab, tabs }: { tab: Mode; onTab: (m: Mode) => void; tabs: [Mode, string][] }) {
  return (
    <div className="olf-row scene-lab-tabs" role="tablist">
      {tabs.map(([m, label]) => (
        <button key={m} type="button" role="tab" className="olf-chip-btn" aria-pressed={tab === m} onClick={() => onTab(m)} data-testid={`scene-lab-tab-${m}`}>
          {label}
        </button>
      ))}
    </div>
  );
}

/**
 * Edit a try by hand (boards D, E, F): people, their end places (motion), background groups, props
 * and the camera. The view rebuilds at once; `POST /olf/scene/check` checks each change as saving
 * would; **Save as try N** saves the edit as a new try (`POST /olf/scene/paste`), and the edited try
 * stays as it was.
 */
export function TryEditor({
  path,
  shot,
  staged,
  room,
  view,
  seconds,
  tab,
  onTab,
  onSave,
  next,
}: {
  path: string;
  shot: string;
  staged: OlfShotTry;
  room: OlfRoom;
  view: View;
  seconds: number;
  tab: Mode;
  onTab: (m: Mode) => void;
  onSave: (data: OlfShotTry, request: string) => Promise<unknown>;
  next: number;
}) {
  const start = staging(staged);
  const [draft, setDraft] = useState<OlfShotTry>(start);
  const [issues, setIssues] = useState<{ level: string; message: string }[]>([]);
  const [t, setT] = useState(0);
  const [saving, setSaving] = useState(false);
  const viewer = useRef<SceneViewer | null>(null) as MutableRefObject<SceneViewer | null>;
  const slots = draft.cast.map((p) => p.slot);
  const changes = tryChanges(start, draft, view.names);
  const errors = issues.filter((i) => i.level === "error");

  // Check each change as saving would (debounced): outside the frame, inside a piece, floating.
  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      olf<{ issues: { level: string; message: string }[] }>("/scene/check", send("POST", { path, shot, data: draft }))
        .then((body) => live && setIssues(body.issues))
        .catch((err) => live && setIssues([{ level: "error", message: message(err) }]));
    }, 300);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [draft]);
  useEffect(() => viewer.current?.at(t), [t, draft]);

  const person = (i: number, change: Partial<OlfShotTry["cast"][number]>) =>
    setDraft({ ...draft, cast: draft.cast.map((p, k) => (k === i ? { ...p, ...change } : p)) });
  const group = (i: number, change: Partial<OlfGroup> | null) =>
    setDraft({ ...draft, groups: (draft.groups || []).flatMap((g, k) => (k !== i ? [g] : change ? [{ ...g, ...change }] : [])) });
  const prop = (i: number, change: Partial<OlfPiece> | null) =>
    setDraft({ ...draft, props: (draft.props || []).flatMap((p, k) => (k !== i ? [p] : change ? [{ ...p, ...change }] : [])) });

  const panels: Partial<Record<Mode, ReactNode>> = {
    people: draft.cast.map((p, i) => (
      <div key={p.slot} className="scene-lab-item">
        <b>{view.names[p.slot] || `Slot ${p.slot}`}</b>
        <Vec label="Place (metres)" value={p.at} onChange={(at) => person(i, { at: at as V3 })} />
        <span className="olf-label">Faces</span>
        <Faces value={p.faces} slots={slots.filter((s) => s !== p.slot)} names={view.names} onChange={(faces) => person(i, { faces })} />
        <Num label="Height (m)" value={p.height ?? 1.7} min={0.1} onChange={(height) => person(i, { height })} />
      </div>
    )),
    motion: (
      <>
        {draft.cast.map((p, i) => (
          <div key={p.slot} className="scene-lab-item">
            <b>{view.names[p.slot] || `Slot ${p.slot}`}</b>
            <span className="olf-small-text muted">Start {p.at.map((n) => +n.toFixed(2)).join(", ")}</span>
            {p.end ? (
              <>
                <Vec label="End place" value={p.end.at} onChange={(at) => person(i, { end: { ...p.end, at: at as V3 } })} />
                <span className="olf-label">Faces at the end</span>
                <Faces value={p.end.faces} slots={slots.filter((s) => s !== p.slot)} names={view.names} onChange={(faces) => person(i, { end: { ...p.end!, faces } })} />
                <Walk end={p.end} from={p.at} seconds={seconds} onChange={(end) => person(i, { end })} />
                <button type="button" className="ghost olf-small" onClick={() => person(i, { end: undefined })}>
                  Stays in place
                </button>
              </>
            ) : (
              <button type="button" className="ghost olf-small" onClick={() => person(i, { end: { at: [...p.at] as V3, faces: p.faces } })} data-testid="scene-lab-add-end">
                + End place
              </button>
            )}
          </div>
        ))}
        <p className="olf-small-text muted">
          Camera, from the shot: {view.move.move || "static"}
          {view.move.amount ? ` · amount ${view.move.amount}` : ""} · ease {view.move.ease || "in_out"} · {view.move.lens || "35mm"}. Change it in the shot&apos;s fields.
        </p>
        <p className="olf-small-text muted">
          What Use saves: the start frame as the keyframe layout, the start pills as <code>layout.start</code> and the end pills as <code>layout.end</code>
          (the animatic and the mock render play the move). The keyframe model gets the start frame only.
        </p>
      </>
    ),
    background: (
      <>
        {(draft.groups || []).map((g, i) => (
          <div key={i} className="scene-lab-item">
            <input className="olf-input olf-small" value={g.name || ""} placeholder="villagers" aria-label="Group name" onChange={(e) => group(i, { name: e.target.value || undefined })} />
            <div className="olf-row scene-lab-count">
              <button type="button" className="ghost olf-small" disabled={g.count <= 1} onClick={() => group(i, { count: g.count - 1 })} aria-label="One fewer">
                −
              </button>
              <Num label="People" value={g.count} step={1} min={1} onChange={(count) => group(i, { count: Math.max(1, Math.round(count)) })} />
              <button type="button" className="ghost olf-small" onClick={() => group(i, { count: g.count + 1 })} aria-label="One more" data-testid="scene-lab-more">
                +
              </button>
            </div>
            <Vec label="Area on the floor" keys={["x0", "z0", "x1", "z1"]} value={g.area} onChange={(area) => group(i, { area: area as OlfGroup["area"] })} />
            <span className="olf-label">They face</span>
            <Faces value={g.faces} slots={slots} names={view.names} any onChange={(faces) => group(i, { faces })} />
            <button type="button" className="ghost olf-small" onClick={() => group(i, null)}>
              Remove group
            </button>
          </div>
        ))}
        <button
          type="button"
          className="ghost olf-small"
          onClick={() => setDraft({ ...draft, groups: [...(draft.groups || []), { name: "people", count: 6, area: [-1.5, -2, 1.5, -1] }] })}
          data-testid="scene-lab-add-group"
        >
          + Background group
        </button>
        <p className="olf-small-text muted">
          Any number of people. Named people keep their own pin colors; background people share one white pin with dark stripes and are never named, so no color
          runs out.
        </p>
      </>
    ),
    props: (
      <>
        <Vec label="Camera place" value={draft.camera.at} onChange={(at) => setDraft({ ...draft, camera: { ...draft.camera, at: at as V3 } })} />
        <span className="olf-label">Camera aims at</span>
        <select
          className="olf-input olf-small"
          value={typeof draft.camera.looks_at === "string" ? draft.camera.looks_at : ""}
          onChange={(e) => setDraft({ ...draft, camera: { ...draft.camera, looks_at: e.target.value || [0, 1.2, 0] } })}
          aria-label="Camera aims at"
          data-testid="scene-lab-aim"
        >
          <option value="">A point</option>
          {slots.map((slot) => (
            <option key={slot} value={slot}>
              {view.names[slot] || `Slot ${slot}`}: follow them
            </option>
          ))}
        </select>
        {typeof draft.camera.looks_at === "string" ? null : (
          <Vec label="The point" value={draft.camera.looks_at} onChange={(looks_at) => setDraft({ ...draft, camera: { ...draft.camera, looks_at: looks_at as V3 } })} />
        )}
        {(draft.props || []).map((p, i) => (
          <PieceFields key={i} piece={p} onChange={(change) => prop(i, change)} />
        ))}
        <button type="button" className="ghost olf-small" onClick={() => setDraft({ ...draft, props: [...(draft.props || []), { name: "prop", shape: "box", size: [0.5, 0.5, 0.5], at: [0, 0, 0] }] })}>
          + Prop for this shot
        </button>
      </>
    ),
  };

  return (
    <div className="scene-lab-grid">
      <div className="olf-col">
        <div className="scene-lab-view" style={{ aspectRatio: String(view.aspect) }}>
          <SceneView room={room} staged={draft} move={view.move} aspect={view.aspect} opts={{ ...view.opts, t }} free={view.free} viewer={viewer} label={`Try ${staged.try}, edited`} />
        </div>
        {tab === "people" || tab === "motion" || tab === "props" ? <FloorPlan room={room} draft={draft} view={view} onChange={setDraft} /> : null}
        <div className="olf-row scene-lab-time">
          <button type="button" className="olf-chip-btn" onClick={() => viewer.current?.play(seconds, setT)} data-testid="scene-lab-play">
            Play
          </button>
          <span className="olf-label">Start</span>
          <input type="range" min={0} max={1} step={0.01} value={t} onChange={(e) => setT(+e.target.value)} aria-label="Time in the shot" data-testid="scene-lab-time" />
          <span className="olf-label">End</span>
          <span className="muted olf-small-text">{(t * seconds).toFixed(1)} s</span>
        </div>
        {issues.length ? (
          <ul className="olf-box scene-lab-issues" data-testid="scene-lab-checks">
            {issues.map((i) => (
              <li key={i.message} className={i.level === "error" ? "olf-error" : ""}>
                {i.message}
              </li>
            ))}
          </ul>
        ) : (
          <span className="muted olf-small-text">Checks: everyone is in the frame at the start and the end.</span>
        )}
      </div>
      <div className="olf-col">
        <Tabs tab={tab} onTab={onTab} tabs={[["people", "People"], ["motion", "Motion"], ["background", "Background people"], ["props", "Props and camera"]]} />
        {panels[tab]}
        <div className="scene-lab-use">
          <span className="olf-label">Changes from try {staged.try}</span>
          {changes.length ? (
            <ul className="olf-small-text scene-lab-changes" data-testid="scene-lab-changes">
              {changes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          ) : (
            <span className="muted olf-small-text">No changes yet.</span>
          )}
          <div className="olf-row">
            <button
              type="button"
              className="run olf-grow"
              disabled={!changes.length || errors.length > 0 || saving}
              onClick={async () => {
                setSaving(true);
                try {
                  await onSave(draft, `By hand from try ${staged.try}`);
                } finally {
                  setSaving(false);
                }
              }}
              data-testid="scene-lab-save"
            >
              {saving ? "Saving…" : `Save as try ${next}`}
            </button>
            <button type="button" className="ghost" disabled={!changes.length} onClick={() => setDraft(start)}>
              Reset to try {staged.try}
            </button>
          </div>
          <span className="muted olf-small-text">No model runs ($0). Each change edits the scene description only.</span>
        </div>
      </div>
    </div>
  );
}

/** When a walk starts and ends, in seconds of the shot (stored as 0..1 of it), and its speed. */
function Walk({ end, from, seconds, onChange }: { end: NonNullable<OlfPerson["end"]>; from: V3; seconds: number; onChange: (end: NonNullable<OlfPerson["end"]>) => void }) {
  const [s, e] = [end.start_t ?? 0, end.end_t ?? 1];
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
  const part = (v: number) => clamp(v / seconds, 0, 1); // seconds to 0..1, clamped
  const metres = Math.hypot(end.at[0] - from[0], end.at[2] - from[2]);
  const time = (e - s) * seconds;
  // Shrink the minimum gap near 0 or 1 so valid boundary edits never step outside 0..1 (CodeRabbit on #741).
  const maxStart = Math.max(0, e - Math.min(0.01, e / 2));
  const minEnd = Math.min(1, s + Math.min(0.01, (1 - s) / 2));
  return (
    <div className="olf-row scene-lab-walk">
      <Num label="Start (s)" value={+(s * seconds).toFixed(2)} min={0} onChange={(v) => onChange({ ...end, start_t: clamp(part(v), 0, maxStart) })} />
      <Num label="End (s)" value={+(e * seconds).toFixed(2)} min={0} onChange={(v) => onChange({ ...end, end_t: clamp(part(v), minEnd, 1) })} />
      <span className="muted olf-small-text" data-testid="scene-lab-walk-speed">
        {metres.toFixed(2)} m · {time > 0 ? `${(metres / time).toFixed(2)} m/s` : "a jump"}
      </span>
    </div>
  );
}

/** A set piece or a prop: name, shape, size, place and turn. */
function PieceFields({ piece, onChange }: { piece: OlfPiece; onChange: (change: Partial<OlfPiece> | null) => void }) {
  return (
    <div className="scene-lab-item">
      <div className="olf-row">
        <input className="olf-input olf-small olf-grow" value={piece.name || ""} aria-label="Name" onChange={(e) => onChange({ name: e.target.value || undefined })} />
        <select className="olf-input olf-small" value={piece.shape} aria-label="Shape" onChange={(e) => onChange({ shape: e.target.value as OlfPiece["shape"] })}>
          {SHAPES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <button type="button" className="ghost olf-small" onClick={() => onChange(null)} aria-label={`Remove ${piece.name || "piece"}`}>
          Remove
        </button>
      </div>
      <Vec label="Size (w, h, d)" keys={["w", "h", "d"]} value={piece.size} onChange={(size) => onChange({ size: size as V3 })} />
      <Vec label="Bottom centre" value={piece.at} onChange={(at) => onChange({ at: at as V3 })} />
      <Num label="Turn (°)" value={piece.turn ?? 0} step={15} onChange={(turn) => onChange({ turn })} />
    </div>
  );
}

/** Compare two tries side by side (board B); a new try can start from A. */
export function CompareTries({ lab, view, onUse, runBox }: { lab: Lab; view: View; onUse: (n: number) => void; runBox: (base: OlfShotTry) => ReactNode }) {
  const nums = lab.tries.map((t) => t.try as number);
  const [a, setA] = useState(nums[nums.length - 1]);
  const [b, setB] = useState(nums[nums.length - 2] ?? nums[nums.length - 1]);
  const pair = [a, b].map((n) => lab.tries.find((t) => t.try === n)).filter((t): t is OlfShotTry => !!t);
  return (
    <>
      <div className="scene-lab-pair">
        {pair.map((t, k) => {
          const room = lab.rooms[String(t.room)];
          return (
            <div key={k} className="olf-col">
              <label className="olf-row olf-small-text">
                <b>{k ? "B" : "A"}</b>
                <select className="olf-input olf-small" value={t.try} onChange={(e) => (k ? setB : setA)(+e.target.value)} data-testid={`scene-lab-${k ? "b" : "a"}`}>
                  {nums.map((n) => (
                    <option key={n} value={n}>
                      Try {n}
                    </option>
                  ))}
                </select>
                <span className="muted">
                  room v{t.room} · {t.model ? t.model.split("/").pop() : "by you"}
                </span>
              </label>
              <div className="scene-lab-view" style={{ aspectRatio: String(view.aspect) }}>
                {room ? <SceneView room={room} staged={t} move={view.move} aspect={view.aspect} opts={view.opts} free={view.free} label={`Try ${t.try}`} /> : null}
              </div>
              <span className="olf-small-text">{t.request || "No request"}</span>
              <span className={`olf-small-text ${t.issues?.length ? "olf-error" : "muted"}`}>{t.issues?.length ? t.issues.join(" · ") : "No checks fail"}</span>
            </div>
          );
        })}
      </div>
      <div className="scene-lab-grid">
        <div className="olf-col">
          <button type="button" className="run" onClick={() => onUse(a)} data-testid="scene-lab-use-a">
            Use A as keyframe layout
          </button>
        </div>
        <div className="olf-col">
          <span className="olf-label">Change A for a new try</span>
          {pair[0] ? runBox(pair[0]) : null}
          <span className="muted olf-small-text">The new try starts from A: the same places, cast and camera unless you ask for a change.</span>
        </div>
      </div>
    </>
  );
}

/**
 * The scene's room (board G): its versions with what changed, the shots that stand in each, room
 * tries to keep as a version, and a hand edit of the set pieces (a new version). A version never
 * changes; a shot moves to a new version only when its person says so (a new try in that room),
 * and its keyframe layout stays until they use a try again.
 */
export function SceneRoom({ path, lab, view, current, onChanged, runBox }: { path: string; lab: Lab; view: View; current: string; onChanged: () => Promise<unknown>; runBox: ReactNode }) {
  const newest = lab.versions[lab.versions.length - 1];
  const [pick, setPick] = useState(newest);
  const [pieces, setPieces] = useState<OlfPiece[] | null>(null); // a hand edit of the set
  const [error, setError] = useState("");
  useEffect(() => setPick(newest), [newest]); // a new version (a hand edit, a kept try) shows at once
  const room = lab.rooms[String(pick)];
  const before = lab.rooms[String(pick - 1)];
  const shown = pieces ? { ...room, set: pieces } : room;
  // A room alone: no people, the free view (a placeholder shot camera for the viewer).
  const empty: OlfShotTry = { shot: "", room: pick, camera: { at: [0, 1.6, 8], looks_at: [0, 1, 0] }, cast: [] };

  async function act(what: string, run: () => Promise<unknown>) {
    setError("");
    try {
      await run();
      console.info("[shows] scene room", what);
      await onChanged();
    } catch (err) {
      setError(message(err));
    }
  }
  /** A shot moves to the newest room: its newest try, again, in that room (a new try). */
  const move = (shot: string, n: number) =>
    act(`move ${shot} to v${newest}`, async () => {
      const found = (await olf<Lab>(`/scene?path=${encodeURIComponent(path)}&target=${encodeURIComponent(shot)}`)).tries.find((t) => t.try === n);
      if (!found) throw new Error(`${shot}: no try ${n}`);
      const text = JSON.stringify({ ...staging(found), room: newest });
      await olf("/scene/paste", send("POST", { path, target: shot, text, room: newest, request: `Moved to room v${newest} from try ${n}` }));
    });

  return (
    <div className="scene-lab-grid">
      <div className="olf-col">
        <div className="scene-lab-view" style={{ aspectRatio: String(view.aspect) }}>
          {shown ? <SceneView room={shown} staged={empty} move={{}} aspect={view.aspect} opts={view.opts} free label={`Room v${pick}`} /> : <span className="olf-preview-ph">No room yet: build a room try, or stage a shot (its first try builds the room).</span>}
        </div>
        <span className="muted olf-small-text">The room holds set pieces only. People, background groups and props for one shot live in each shot&apos;s try.</span>
        {room ? (
          <>
            <span className="olf-label">{before ? `Changes from v${pick - 1}` : `v${pick}: the first version`}</span>
            <ul className="olf-small-text scene-lab-changes" data-testid="scene-room-diff">
              {(before ? roomChanges(before.set, room.set) : room.set.map((p, i) => `${p.name || `${p.shape} ${i + 1}`}`)).map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
      <div className="olf-col">
        <span className="olf-label">Versions</span>
        <div className="olf-row scene-lab-tries" data-testid="scene-room-versions">
          {lab.versions.map((v) => (
            <button key={v} type="button" className="olf-chip-btn" aria-pressed={v === pick} onClick={() => (setPick(v), setPieces(null))}>
              v{v}
              {lab.rooms[String(v)]?.from ? ` · from ${lab.rooms[String(v)].from}` : ""}
            </button>
          ))}
        </div>
        <span className="muted olf-small-text">A change to the room is a new version. Frames on an older version stay as they are until you move their shot.</span>
        <span className="olf-label">Shots that use this scene&apos;s room</span>
        <ul className="scene-room-shots" data-testid="scene-room-shots">
          {Object.entries(lab.shots || {}).map(([shot, row]) => (
            <li key={shot} className="olf-row olf-small-text">
              <code>{shot.split("/").pop()}</code>
              {shot === current ? <span className="chip">this shot</span> : null}
              <span className="muted">{row.room ? `try ${row.try} · room v${row.room}` : "no try yet"}</span>
              {row.room && row.try && row.room !== newest ? (
                <button type="button" className="ghost olf-small" onClick={() => void move(shot, row.try as number)}>
                  Move to v{newest}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {lab.room_tries?.length ? (
          <>
            <span className="olf-label">Room tries</span>
            {lab.room_tries.map((t) => (
              <div key={t.try} className="olf-row olf-small-text">
                <span className="olf-grow">
                  Try {t.try} · {t.set.length} pieces{t.request ? ` · ${t.request}` : ""}
                </span>
                <button type="button" className="ghost olf-small" onClick={() => void act(`keep room try ${t.try}`, () => olf("/scene/room", send("POST", { path, scene: lab.scene, room_try: t.try })))}>
                  Keep as v{(newest || 0) + 1}
                </button>
              </div>
            ))}
          </>
        ) : null}
        <span className="olf-label">Build a room try</span>
        {runBox}
        {room ? (
          pieces ? (
            <>
              <span className="olf-label">Edit v{pick} by hand</span>
              {pieces.map((p, i) => (
                <PieceFields key={i} piece={p} onChange={(change) => setPieces(pieces.flatMap((q, k) => (k !== i ? [q] : change ? [{ ...q, ...change }] : [])))} />
              ))}
              <div className="olf-row">
                <button type="button" className="ghost olf-small" onClick={() => setPieces([...pieces, { name: "piece", shape: "box", size: [1, 1, 1], at: [0, 0, 0] }])}>
                  + Set piece
                </button>
                <button
                  type="button"
                  className="run olf-small"
                  onClick={() => void act(`edit v${pick}`, () => olf("/scene/room", send("POST", { path, scene: lab.scene, pieces, source: `v${pick}` })).then(() => setPieces(null)))}
                  data-testid="scene-room-save"
                >
                  Save as v{newest + 1}
                </button>
              </div>
            </>
          ) : (
            <button type="button" className="ghost" onClick={() => setPieces(room.set)} data-testid="scene-room-edit">
              Edit by hand → v{newest + 1}
            </button>
          )
        ) : null}
        {error ? <p className="olf-error olf-small-text">{error}</p> : null}
      </div>
    </div>
  );
}
