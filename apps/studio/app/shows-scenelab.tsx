"use client";

import { type MutableRefObject, useEffect, useRef, useState } from "react";
import { PIN_SHAPES, type PinShape, aspectOf } from "../lib/pillframe";
import type { OlfRoom, OlfShotTry, ShotMove } from "../lib/scenelab";
import type { SceneOptions, SceneViewer } from "../lib/scenelab-gl";
import { COPY_PROMPT, type Drawn, type OlfShow, type OlfTextStep, durationSeconds, framingShort, takesOf, textStepQuestion } from "../lib/shows";
import { message, olf, send } from "./shows-api";
import { Confirm, TextModelPick, useTextModel } from "./shows-parts";
import { CompareTries, SceneRoom, TryEditor } from "./shows-scenelab-screens";

/** `GET /olf/scene` (`vinci_olf.scene_lab.overview`). For a shot: its tries and the rooms they
 * stand in. For a scene: every room version, the room tries, and the room each shot stands in. */
export type Lab = {
  scene: string;
  versions: number[];
  room: OlfRoom | null;
  rooms: Record<string, OlfRoom>;
  tries: OlfShotTry[];
  room_tries?: (OlfRoom & { try: number })[];
  shots?: Record<string, { tries: number; try: number | null; room: number | null }>;
};
/** The lab's screens: A on the shot page; the others open full screen (prototype boards). */
export type Mode = "lab" | "compare" | "people" | "motion" | "background" | "props" | "room";
type Move = ShotMove & { lens?: string };
const TITLES: Record<Mode, string> = {
  lab: "Scene lab",
  compare: "Compare tries",
  people: "Edit by hand",
  motion: "Motion: start, end and the camera move",
  background: "Background people",
  props: "Props and camera",
  room: "Scene room",
};

/** A file as a `data:` URL (base64), to send in a JSON body. */
function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/** One 3D view of a try (`SceneViewer`); three.js loads only here. `viewer` lets a screen play or
 * scrub the move. A new `staged` or `room` (an edit, a reload) builds the view again. */
export function SceneView({
  room,
  staged,
  move,
  aspect,
  opts,
  free,
  viewer: shared,
  label,
}: {
  room: OlfRoom;
  staged: OlfShotTry;
  move: Move;
  aspect: number;
  opts: SceneOptions;
  free: boolean;
  viewer?: MutableRefObject<SceneViewer | null>;
  label: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const own = useRef<SceneViewer | null>(null);
  const viewer = shared || own;
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    import("../lib/scenelab-gl")
      .then(({ SceneViewer }) => {
        if (!live || !canvas.current) return;
        const first = !viewer.current;
        viewer.current ||= new SceneViewer(canvas.current);
        viewer.current.show(room, staged, move, aspect, opts);
        if (first && free) viewer.current.freeView(true);
      })
      .catch((err) => {
        console.error("[shows] scene lab view", err); // e.g. no WebGL, or three.js did not load
        setError(`Could not draw the scene: ${message(err)}`);
      });
    return () => {
      live = false;
    };
  }, [room, staged, opts.standin, opts.pin, aspect]);
  useEffect(() => viewer.current?.freeView(free), [free]);
  useEffect(
    () => () => {
      viewer.current?.dispose();
      viewer.current = null;
    },
    [],
  );
  return (
    <>
      <canvas ref={canvas} aria-label={label} data-testid="scene-lab-canvas" />
      {error ? <span className="olf-preview-ph olf-error">{error}</span> : null}
    </>
  );
}

/**
 * The scene lab on the shot page (prototype screen A, COREPRODUC-722). The person describes the
 * scene; a text model, or their own agent with a copied prompt, answers with a scene description
 * (JSON, never code), and `scenelab-gl.ts` builds it in 3D under the shot's camera. Each answer is a
 * try. **Use as keyframe layout** saves a try's start frame and its pills (`POST /olf/scene/use`).
 * Compare, the hand edits (people, motion, background people, props) and the scene room open full
 * screen (`shows-scenelab-screens.tsx`, COREPRODUC-723).
 *
 * @param onUse Renders the frame (`draw`) and saves try `n` with it and its pin shape; the page
 *   reloads the show.
 */
export function SceneLab({
  show,
  id,
  locked,
  onUse,
}: {
  show: OlfShow;
  id: string;
  locked: boolean;
  onUse: (n: number, draw: () => Promise<Drawn>, pin: PinShape) => Promise<unknown>;
}) {
  const shot = show.shots[id];
  const scene = id.slice(0, id.lastIndexOf("/"));
  const [lab, setLab] = useState<Lab | null>(null);
  const [roomLab, setRoomLab] = useState<Lab | null>(null);
  const [pick, setPick] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("lab");
  const [request, setRequest] = useState("");
  const [models, textModel, setTextModel] = useTextModel("scene");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  // A build that costs money waits for Confirm, with what it builds from (a try, a room).
  const [ask, setAsk] = useState<{ plan: OlfTextStep; extra: Record<string, unknown> } | null>(null);
  const [paste, setPaste] = useState<string | null>(null); // null: the paste box is closed
  const [standin, setStandin] = useState<"pin" | "figure">("pin");
  const [free, setFree] = useState(false);
  const [pin, setPin] = useState<PinShape>("pin"); // the pin shape comparison (COREPRODUC-718)
  const [using, setUsing] = useState<"ask" | "drawing" | null>(null);
  const viewer = useRef<SceneViewer | null>(null);
  const staged = lab?.tries.find((row) => row.try === pick) || null;
  const room = staged ? lab?.rooms[String(staged.room)] : undefined;
  const cam = shot.camera || {};
  const move = { lens: cam.lens, move: cam.move, amount: cam.amount, ease: cam.ease };
  const aspect = aspectOf(shot.pills?.aspect);
  const pills = shot.pills?.start || [];
  // Each slot's pin stripes: the shot's pills keep each character's show color (vinci_olf.layout).
  const stripes = Object.fromEntries(pills.map((pill) => [pill.slot, pill.stripe || ""]));
  const names = Object.fromEntries(pills.map((pill) => [pill.slot, pill.name || pill.id || pill.slot]));
  const seconds = durationSeconds(shot.duration) || 4;
  const view = { move, aspect, opts: { stripes, standin, pin }, free, names };
  const target = mode === "room" ? scene : id;
  const next = (lab?.tries.reduce((n, t) => Math.max(n, t.try || 0), 0) || 0) + 1;

  /** Read the lab again and show try `select` (else the newest). */
  async function load(select?: number) {
    const body = await olf<Lab>(`/scene?path=${encodeURIComponent(show.path)}&target=${encodeURIComponent(id)}`);
    setLab(body);
    setPick(select ?? body.tries[body.tries.length - 1]?.try ?? null);
  }
  const loadRoom = async () => setRoomLab(await olf<Lab>(`/scene?path=${encodeURIComponent(show.path)}&target=${encodeURIComponent(scene)}`));

  useEffect(() => {
    load().catch((err) => setError(message(err)));
  }, [show.path, id]);
  useEffect(() => {
    if (mode === "room") loadRoom().catch((err) => setError(message(err)));
    setError("");
    setCopied(false);
    setPaste(null);
  }, [mode]);

  /** After a new try or room try: show it. */
  async function saved(out: { try?: number; room_try?: number }) {
    if (mode === "room") return Promise.all([loadRoom(), load(pick ?? undefined)]);
    await load(out.try);
  }

  /** Make a try: copy the prompt for the person's own agent, or ask the text model (price first).
   * `extra` is what it builds from: `base` (a try to start from) and its `room`. */
  async function build(confirmed?: OlfTextStep, extra: Record<string, unknown> = {}) {
    setError("");
    setCopied(false);
    const body = { path: show.path, target, request: request.trim(), ...extra };
    try {
      if (textModel === COPY_PROMPT) {
        const out = await olf<OlfTextStep>("/scene/build", send("POST", { ...body, copy: true }));
        await navigator.clipboard.writeText(out.prompt || "");
        console.info("[shows] scene lab prompt copied", { target, chars: out.prompt?.length });
        setCopied(true);
        setPaste("");
        return;
      }
      const run = { ...body, model: textModel || undefined };
      if (!confirmed) {
        setBusy("Checking the price…");
        const plan = await olf<OlfTextStep>("/scene/build", send("POST", { ...run, dry_run: true }));
        if (plan.total || plan.unpriced?.length) return setAsk({ plan, extra });
        confirmed = plan;
      }
      const who = models?.choices.find((row) => row.id === textModel)?.name;
      setBusy(`Building the ${mode === "room" ? "room" : "scene"}${who ? ` with ${who}` : ""}…`);
      const out = await olf<{ try?: number; room?: number; room_try?: number; error?: string; text?: string | null }>("/scene/build", send("POST", { ...run, yes: true, max_total: confirmed.total || 0 }));
      console.info("[shows] scene lab try", { target, try: out.try, room: out.room, room_try: out.room_try, error: out.error });
      if (out.error) {
        // A refused answer is kept: it opens in the paste box to fix and save (COREPRODUC-738).
        setPaste(out.text || "");
        return setError(`The answer was not saved: ${out.error}. It is in the box below: fix it, then click Save as a try.`);
      }
      await saved(out);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy("");
    }
  }

  /** Save an answer pasted from the person's own agent as a try (or a room try). */
  async function pasteAnswer() {
    setError("");
    try {
      const out = await olf<{ try?: number; room_try?: number }>("/scene/paste", send("POST", { path: show.path, target, request: request.trim(), text: paste }));
      console.info("[shows] scene lab paste", { target, try: out.try, room_try: out.room_try });
      setPaste(null);
      setCopied(false);
      await saved(out);
    } catch (err) {
      setError(message(err));
    }
  }

  /** Save a hand edit as a new try in its room; the screen then shows the new try. */
  async function saveEdit(data: OlfShotTry, words: string) {
    try {
      const out = await olf<{ try?: number }>("/scene/paste", send("POST", { path: show.path, target: id, request: words, room: data.room, text: JSON.stringify(data) }));
      console.info("[shows] scene lab hand edit", { shot: id, try: out.try });
      await load(out.try);
    } catch (err) {
      setError(message(err));
    }
  }

  /** Render try `n`'s start frame (no lab overlays) and save it with its pills. */
  async function use(n = staged?.try) {
    const one = lab?.tries.find((t) => t.try === n);
    const where = one && lab?.rooms[String(one.room)];
    if (!one || !n || !where) return;
    setUsing("drawing");
    try {
      await onUse(
        n,
        async () => {
          const gl = await import("../lib/scenelab-gl");
          const frame = gl.renderSceneFrame(where, one, move, aspect, { stripes, pin });
          if (cam.render !== "reference") return frame;
          // A reference render follows the pin video: record the try's move (COREPRODUC-732).
          const { blob, raw } = await gl.recordMove(where, one, move, aspect, { stripes, pin }, seconds);
          return { frame, video: await dataUrl(blob), raw };
        },
        pin,
      );
    } finally {
      setUsing(null);
    }
  }

  /** The request, the model, build or copy, paste, and what happened. `extra`: what it builds from. */
  const runBox = (extra: Record<string, unknown> = {}, first = false) => (
    <>
      <label className="olf-field">
        <span className="olf-label">{mode === "room" ? "What should the room be?" : mode === "compare" ? "What should change?" : "What should the scene be?"}</span>
        <textarea
          className="olf-input olf-textarea"
          value={request}
          onChange={(event) => setRequest(event.target.value)}
          placeholder={mode === "room" ? "A cramped lamp room: a big lamp on a round base, a desk, a ledge." : "Mira stands by the lamp; the fox watches her from the ledge."}
          disabled={locked || !!busy}
          data-testid="scene-lab-request"
        />
      </label>
      {models ? (
        <label className="olf-field">
          <span className="olf-label">Run with</span>
          <TextModelPick models={models} value={textModel} disabled={!!busy} onPick={setTextModel} testId="scene-lab-model" />
        </label>
      ) : null}
      {ask ? (
        <Confirm
          text={textStepQuestion(ask.plan, models?.choices || [], "a try")}
          onYes={() => {
            const job = ask;
            setAsk(null);
            void build(job.plan, job.extra);
          }}
          onNo={() => setAsk(null)}
        />
      ) : null}
      <div className="olf-row">
        <button type="button" className="run olf-grow" disabled={locked || !!busy} onClick={() => void build(undefined, extra)} data-testid="scene-lab-build">
          {busy && mode !== "lab" ? busy : textModel === COPY_PROMPT ? "Copy prompt" : first ? "Build the scene" : mode === "room" ? "Build a room try" : "New try"}
        </button>
        {"base" in extra ? null : (
          <button type="button" className="ghost" disabled={locked} onClick={() => setPaste(paste === null ? "" : null)} data-testid="scene-lab-paste">
            Paste an answer
          </button>
        )}
      </div>
      {error ? (
        <p className="olf-error olf-small-text" data-testid="scene-lab-error">
          {error}
        </p>
      ) : null}
      {copied ? (
        <p className="muted olf-small-text" data-testid="scene-lab-copied">
          Copied the prompt for {target.split("/").pop()}. Paste it in your agent (for example Claude Code), then paste its answer here.
        </p>
      ) : null}
      {paste !== null ? (
        <form
          className="olf-field"
          onSubmit={(event) => {
            event.preventDefault();
            void pasteAnswer();
          }}
        >
          <textarea
            className="olf-input olf-textarea"
            value={paste}
            onChange={(event) => setPaste(event.target.value)}
            placeholder="Paste your agent's answer (the JSON scene description)"
            aria-label="Answer"
            data-testid="scene-lab-answer"
          />
          <button type="submit" className="run olf-small" disabled={!paste.trim()}>
            Save as a try
          </button>
        </form>
      ) : null}
    </>
  );

  const toggles = (
    <div className="scene-lab-tools">
      {(["shot", "free"] as const).map((one) => (
        <button key={one} type="button" className="olf-chip-btn" aria-pressed={free === (one === "free")} onClick={() => setFree(one === "free")} data-testid={`scene-lab-${one}`}>
          {one === "shot" ? `Shot camera · ${cam.lens || "35mm"}` : "Free view"}
        </button>
      ))}
      {(["figure", "pin"] as const).map((one) => (
        <button key={one} type="button" className="olf-chip-btn" aria-pressed={standin === one} onClick={() => setStandin(one)} data-testid={`scene-lab-${one}`}>
          {one === "pin" ? "Pins" : "Figures"}
        </button>
      ))}
      <select
        className="olf-chip-btn"
        value={pin}
        onChange={(e) => setPin(e.target.value as PinShape)}
        title="Pin shape: the comparison of COREPRODUC-718. Use saves the frame with this shape, and the keyframe prompt describes it."
        aria-label="Pin shape"
        data-testid="scene-lab-pin-shape"
      >
        {PIN_SHAPES.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </div>
  );

  const keyframes = takesOf(show, id, "keyframe").length;
  const warning = [
    shot.pills?.stated ? "It replaces this shot's own pills." : "",
    keyframes ? `${keyframes === 1 ? "Its keyframe goes" : `Its ${keyframes} keyframes go`} stale.` : "",
  ]
    .join(" ")
    .trim();

  if (mode !== "lab") {
    return (
      <section className="olf-panel scene-lab is-full" role="dialog" aria-label={TITLES[mode]} data-testid={`scene-lab-${mode}`}>
        <header>
          <span className="olf-row">
            <button type="button" className="ghost olf-small" onClick={() => setMode("lab")} data-testid="scene-lab-back">
              ‹ Scene lab
            </button>
            <h3>
              {TITLES[mode]} · {mode === "room" ? scene : id.split("/").pop()}
              {staged && mode !== "room" && mode !== "compare" ? ` · try ${staged.try}` : ""}
            </h3>
          </span>
          {mode === "room" ? null : <div className="scene-lab-head-tools">{toggles}</div>}
        </header>
        {mode === "compare" && lab ? (
          <CompareTries lab={lab} view={view} onUse={(n) => {
              // Back on the lab with try n picked; the same warning as Use there.
              setPick(n);
              setMode("lab");
              if (warning) setUsing("ask");
              else void use(n);
            }} runBox={(base) => runBox({ base: base.try, room: base.room })} />
        ) : mode === "room" ? (
          roomLab ? (
            <SceneRoom path={show.path} lab={roomLab} view={{ ...view, free: true }} current={id} onChanged={() => Promise.all([loadRoom(), load(pick ?? undefined)])} runBox={runBox()} />
          ) : (
            <span className="muted">Loading the room…</span>
          )
        ) : staged && room ? (
          <TryEditor key={staged.try} path={show.path} shot={id} staged={staged} room={room} view={view} seconds={seconds} tab={mode} onTab={setMode} onSave={saveEdit} next={next} />
        ) : null}
        {error && mode !== "compare" && mode !== "room" ? <p className="olf-error olf-small-text">{error}</p> : null}
      </section>
    );
  }

  const roomText = lab?.versions.length ? `scene room v${lab.versions[lab.versions.length - 1]}` : "none yet: the first try builds it";
  const links: [Mode, string][] = [
    ["compare", "Compare tries"],
    ["people", "Edit by hand · $0"],
    ["motion", "Motion"],
    ["background", "Background people"],
  ];
  return (
    <section className="olf-panel scene-lab" data-testid="scene-lab">
      <header>
        <h3>Scene lab</h3>
        <span className="olf-panel-aside">Before you render</span>
      </header>
      <div className="scene-lab-grid">
        <div className="olf-col">
          <div className="scene-lab-view" style={{ aspectRatio: String(aspect) }}>
            {staged && room ? (
              <SceneView room={room} staged={staged} move={move} aspect={aspect} opts={view.opts} free={free} viewer={viewer} label={`Try ${staged.try} in 3D`} />
            ) : (
              <span className="olf-preview-ph" data-testid="scene-lab-empty">
                <b>No scene yet</b>
                <span>Describe the scene. A model builds it in 3D under this shot&apos;s {cam.lens || "35mm"} lens.</span>
              </span>
            )}
            {busy ? <span className="olf-busy">{busy}</span> : null}
            {staged ? (
              <>
                {toggles}
                {move.move === "push_in" || move.move === "pull_out" || staged.cast.some((person) => person.end) ? (
                  <button type="button" className="olf-chip-btn scene-lab-play" onClick={() => viewer.current?.play(seconds)}>
                    Play
                  </button>
                ) : null}
              </>
            ) : null}
          </div>
          <div className="olf-strip-head">
            <h3>Tries</h3>
            <span className="muted">Each answer is a try. A keyframe gets a try&apos;s frame only when you use it.</span>
          </div>
          <div className="olf-row scene-lab-tries" data-testid="scene-lab-tries">
            {lab?.tries.length ? (
              lab.tries.map((row) => (
                <button
                  key={row.try}
                  type="button"
                  className="olf-chip-btn"
                  aria-pressed={row.try === pick}
                  title={row.request || ""}
                  onClick={() => {
                    setPick(row.try ?? null);
                    setError("");
                  }}
                  data-testid="scene-lab-try"
                >
                  Try {row.try} · {row.model ? row.model.split("/").pop() : "by you"}
                  {row.issues?.length ? ` · ${row.issues.length} ${row.issues.length === 1 ? "check" : "checks"}` : ""}
                </button>
              ))
            ) : (
              <span className="muted olf-small-text">No tries yet.</span>
            )}
          </div>
          {staged?.issues?.length ? (
            <ul className="olf-box scene-lab-issues" data-testid="scene-lab-issues">
              {staged.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          ) : null}
          <div className="olf-row scene-lab-links">
            {staged
              ? links.map(([m, label]) => (
                  <button key={m} type="button" className="ghost olf-small" disabled={locked} onClick={() => setMode(m)} data-testid={`scene-lab-open-${m}`}>
                    {label}
                  </button>
                ))
              : null}
            <button type="button" className="ghost olf-small" disabled={locked} onClick={() => setMode("room")} data-testid="scene-lab-open-room">
              Scene room
            </button>
          </div>
        </div>
        <div className="olf-col">
          <p className="olf-small-text muted">
            Describe the scene. A model builds it in 3D under this shot&apos;s camera, then Vinci swaps each person for a pin in their character&apos;s stripes.
          </p>
          <div className="scene-lab-from olf-small-text" data-testid="scene-lab-from">
            <span className="olf-label">From the shot</span>
            <span>
              <b>Camera</b> · {framingShort(cam)}
              {cam.angle ? ` · ${cam.angle.replace("_", " ")}` : ""}
            </span>
            <span>
              <b>Cast</b> ·{" "}
              {pills.length
                ? pills.map((pill) => (
                    <span key={pill.slot} className="scene-lab-pin">
                      <i style={{ background: pill.stripe }} />
                      {names[pill.slot]}
                    </span>
                  ))
                : "no one"}
            </span>
            <span>
              <b>Room</b> · {roomText}
            </span>
            <span>
              <b>Look</b> · colors come from the bible&apos;s references, not this frame
            </span>
          </div>
          {runBox({}, !lab?.tries.length)}
          {staged ? (
            <div className="scene-lab-use" data-testid="scene-lab-use">
              <span className="olf-small-text">
                <b>Try {staged.try}</b>
                {staged.request ? ` · ${staged.request}` : ""} · room v{staged.room}
              </span>
              {using === "ask" ? (
                <Confirm text={`Use try ${staged.try} as the keyframe layout? ${warning}`} onYes={() => void use()} onNo={() => setUsing(null)} />
              ) : (
                <button
                  type="button"
                  className="run"
                  disabled={locked || !!using || !room}
                  onClick={() => (warning ? setUsing("ask") : void use())}
                  data-testid="scene-lab-use-try"
                >
                  {using === "drawing"
                    ? cam.render === "reference"
                      ? "Recording the pin video…"
                      : "Saving…"
                    : cam.render === "reference"
                      ? "Use as keyframe layout and pin video"
                      : "Use as keyframe layout"}
                </button>
              )}
              <span className="muted olf-small-text">
                Saves the pin frame as this shot&apos;s keyframe layout (control.storyboard) and its places as the pills. The next keyframe gets it.
              </span>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

