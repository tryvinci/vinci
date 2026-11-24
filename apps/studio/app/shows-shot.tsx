"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  ANGLES,
  CANVASES,
  EASES,
  FRAMINGS,
  MOVES,
  RENDERS,
  type Drawn,
  type OlfData,
  type OlfOwnStep,
  type OlfShotDetail,
  type OlfShow,
  type OlfStaleCause,
  type OlfTake,
  type RenderKind,
  autoLabel,
  cameraworkMenu,
  choiceLabel,
  chosenKeyframe,
  costText,
  isOwnChoice,
  entryName,
  fileUrl,
  findEntry,
  frames,
  framingShort,
  levelLabel,
  price,
  shortHash,
  shownKeyframe,
  spendText,
  takeName,
  takesOf,
} from "../lib/shows";
import { olf, useOlfRoute } from "./shows-api";
import { Confirm, Field, Panel, PillFrame, Pick, PinStale, PlayBar, RefThumb, StalePill, usePick } from "./shows-parts";

// The scene lab (and its screens) loads only when a shot page shows its Stage step.
const SceneLab = dynamic(() => import("./shows-scenelab").then((m) => m.SceneLab), { ssr: false });

const DRAWS = [1, 2, 3, 4]; // keyframe variations per draw (the engine's MAX_VARIATIONS)

/** The shot page's steps (COREPRODUC-739): stage it in 3D, draw the keyframe, render the video. */
type Step = "stage" | "keyframe" | "video";
/** The scene lab try the shot's keyframe layout came from, and the framing and angle it measured. */
type Used = { try: number; framing?: string; angle?: string };
/** The ways a move can go (`camera.direction`); a move not listed has no direction. */
const DIRECTIONS: Record<string, string[]> = { pan: ["left", "right"], truck: ["left", "right"], orbit: ["left", "right"], tilt: ["up", "down"], crane: ["up", "down"], dolly: ["in", "out"] };
const say = (word: string | undefined) => (word || "—").replace(/_/g, " ");

/** Takes in render order for the strip: keyframes, then videos, then dialogue, oldest first. */
function stripOrder(show: OlfShow, id: string): OlfTake[] {
  return (["keyframe", "video", "audio"] as const).flatMap((kind) => [...takesOf(show, id, kind)].reverse());
}

/**
 * Shot page (Claude Design, screen 3): full width, with no left panel; the top bar holds the crumb
 * and the previous and next shot. Three steps in one place (COREPRODUC-739, user decision
 * 2026-11-20): **Stage** (the scene lab, with the shot's lens and move), **Keyframe** (approve a
 * keyframe: approving also chooses it) and **Video** (render from the chosen keyframe; dialogue
 * renders as an audio take the Cut can play as separate sound). The page opens on the step the shot
 * needs next. Before, the scene lab sat under the render box, and the right column also held fields
 * the 3D stage decides (framing and angle, the 3D pill frame).
 */
export function ShotView({
  show,
  id,
  detail,
  library,
  busy,
  locked,
  onRender,
  onApprove,
  onReject,
  onOpenEntry,
  onEdit,
  onCamerawork,
  onExplain,
  onKeep,
  onStoryboard,
}: {
  show: OlfShow;
  id: string;
  detail: OlfShotDetail | null;
  /** The camerawork library (`GET /olf/camerawork`): templates a shot can take. */
  library: readonly OlfData[];
  busy?: string;
  locked: boolean;
  /** Render: `model` is a person's pick (else routing); `total` is the price they saw. */
  onRender: (kind: RenderKind, yes: boolean, count: number, model: string | undefined, total: number) => void;
  onApprove: (take: OlfTake) => void;
  onReject: (take: OlfTake) => void;
  onOpenEntry: (id: string) => void;
  /** Change shot fields in its file (description, duration, camera); `null` removes an optional field. */
  onEdit: (fields: Record<string, string | null>) => Promise<unknown>;
  /** Put a camerawork template on the shot (a library ID or `cam/<slug>`), or take it off (`null`). */
  onCamerawork: (template: string | null) => Promise<unknown>;
  /** What changed since a take was rendered (`GET /olf/stale`). */
  onExplain: (take: string) => Promise<OlfStaleCause>;
  /** Keep a stale take on purpose (`POST /olf/keep`). */
  onKeep: (take: string) => void;
  /** Draw the shot's 3D pill frame (`draw` gives a PNG `data:` URL) and save it as its keyframe layout
   * (`POST /olf/storyboard`); with `n`, the frame of scene lab try `n`, saved with its pills (`POST /olf/scene/use`). */
  onStoryboard: (draw: () => Promise<Drawn>, n?: number, pin?: string) => Promise<unknown>;
}) {
  const shot = show.shots[id];
  const labRoute = useOlfRoute("/olf/scene"); // an older host has no scene lab: no Stage step
  const [picked, setStep] = useState<Step | null>(null); // null: the step the shot needs next
  useEffect(() => setStep(null), [id]);
  // The used try: framing and angle are measured from it, and the blocking words give way to it.
  const [used, setUsed] = useState<Used | null>(null);
  // The pin video's camera and length fields that changed since Use recorded it.
  const [pinStale, setPinStale] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    setUsed(null);
    setPinStale([]);
    if (labRoute) {
      olf<{ used?: Used | null; pin_stale?: string[] }>(`/scene?path=${encodeURIComponent(show.path)}&target=${encodeURIComponent(id)}`)
        .then((body) => {
          if (!live) return;
          setUsed(body.used || null);
          setPinStale(body.pin_stale || []);
        })
        .catch((err) => console.warn("[shows] used try", err));
    }
    return () => {
      live = false;
    };
  }, [labRoute, show, id]);
  const [current, setCurrent] = useState<string | null>(null);
  // After a render, show its first new take: else Approve acts on the take clicked before
  // (found in the live test of 2026-11-09, COREPRODUC-558). The first load shows the default.
  const ids = (shot.takes || []).join(" ");
  const seen = useRef<string[] | null>(null);
  useEffect(() => {
    const now = ids ? ids.split(" ") : [];
    const added = seen.current ? now.filter((take) => !seen.current?.includes(take)) : [];
    seen.current = now;
    if (added.length) {
      setCurrent(added[0]);
      setStep(show.takes[added[0]]?.kind === "keyframe" ? "keyframe" : "video");
    }
  }, [ids]);
  const [confirm, setConfirm] = useState<RenderKind | null>(null);
  const [draws, setDraws] = useState(1);
  const [videoModel, setVideoModel] = useState(""); // "" is Auto (routing)
  const [media, setMedia] = useState<HTMLMediaElement | null>(null); // what the play bar drives
  const chosen = chosenKeyframe(show, id);
  const videos = takesOf(show, id, "video");
  const pickedVideo = videos.find((take) => takeName(take.id) === shot.select?.video);
  const cam = shot.camera || {};
  // A reference render follows a pin video, which only the stage records.
  const stageNext = labRoute && cam.render === "reference" && !shot.reference_video;
  const step: Step = picked || (stageNext ? "stage" : chosen ? "video" : "keyframe");
  const kinds = step === "video" ? ["video", "audio"] : ["keyframe"]; // the takes of this step
  const strip = stripOrder(show, id).filter((row) => kinds.includes(row.kind));
  const clicked = current ? show.takes[current] : undefined;
  const take =
    (clicked && kinds.includes(clicked.kind) ? clicked : undefined) ||
    (step === "video" ? pickedVideo || videos[0] || strip[0] : chosen || shownKeyframe(show, id));
  // An audio take plays over the shot's picture: the chosen video, else the keyframe it shows.
  const audioTake = take?.kind === "audio" ? take : null;
  const picture = audioTake ? pickedVideo || videos[0] || chosen || shownKeyframe(show, id) : take;
  const staleTakes = stripOrder(show, id).filter((row) => row.stale);
  // The banner explains the take on screen when it is stale, else the first stale take.
  const banner = take?.stale ? take : staleTakes[0];
  const others = staleTakes.filter((row) => row.id !== banner?.id);
  const [cause, setCause] = useState<OlfStaleCause | null>(null);
  const [diff, setDiff] = useState(false);
  useEffect(() => {
    let live = true;
    setCause(null);
    setDiff(false);
    if (banner) onExplain(banner.id).then((body) => live && setCause(body)).catch(() => undefined);
    return () => {
      live = false;
    };
    // A reload (new `show`) can change the cause; onExplain is a new function on every render.
  }, [banner?.id, show]);
  const resolved = (detail?.resolved || {}) as OlfData;
  const origins = detail?.origins;
  const location = resolved.location as OlfData | undefined;
  const lenses = ((show.style?.data.lenses as string[] | undefined) || []).map(String); // a shot may use only these
  // An engine move: the frame moves over the chosen keyframe, with no video model ($0).
  const engineMove = cam.render === "engine";
  const template = findEntry(show, cam.template?.id);
  const menu = cameraworkMenu(show, library);
  const camerawork = usePick(cam.template?.id, onCamerawork); // shows a pick while it saves
  /** A camera field that the template fills says so; a value typed here goes in the shot and wins. */
  const from = (field: string) => (origins?.camera_fields?.[field]?.startsWith("cam/") ? " · template" : "");
  // A shot animates from a keyframe when a control points at one (control.first_frame: keyframe),
  // and an engine move has only the keyframe to move.
  const needs = Object.values(shot.control || {}).includes("keyframe") || engineMove || cam.render === "reference";
  const canVideo = !needs || Boolean(chosen);
  const plans = detail?.plans;
  const next: RenderKind = step === "video" ? "video" : "keyframe"; // this step's render
  const videoModelRouted = plans?.video.plan?.find((row) => row.node === "video")?.model;
  const lines = (resolved.dialogue || []) as OlfData[];
  const spoken = takesOf(show, id, "audio");
  const choice = plans?.video.choices?.find((row) => row.id === videoModel);
  // A reference video with no routed model (hosted): picking a model in the menu clears it.
  const planError = plans?.keyframe.error || (choice ? "" : plans?.video.error);
  // A keyframe render draws `draws` variations, each at the keyframe price; a picked video model
  // replaces the routed one's price.
  // A step on the person's own account (COREPRODUC-615) costs 0 credits: `own` lists what the
  // account pays, in its unit, and `total` stays in the page's unit.
  const own = (kind: RenderKind): OlfOwnStep[] => {
    const steps = plans?.[kind]?.own || [];
    if (kind === "video" && choice) {
      const other = steps.filter((row) => row.node !== "video");
      return isOwnChoice(choice) ? [...other, { node: "video", model: choice.id, amount: choice.amount, currency: choice.currency || "" }] : other;
    }
    return kind === "keyframe" ? steps.map((row) => ({ ...row, amount: row.amount * draws })) : steps;
  };
  const total = (kind: RenderKind) => {
    if (kind === "video" && choice) {
      const other = (plans?.video.plan || []).filter((row) => row.node !== "video" && !(plans?.video.own || []).some((step) => step.node === row.node));
      return other.reduce((sum, row) => sum + row.amount, 0) + (isOwnChoice(choice) ? 0 : choice.amount);
    }
    return (plans?.[kind]?.total || 0) * (kind === "keyframe" ? draws : 1);
  };
  const unpriced = (kind: RenderKind) =>
    kind === "video" && choice
      ? [...(plans?.video.unpriced || []).filter((id) => id !== videoModel && id !== videoModelRouted), ...(choice.unpriced ? [choice.id] : [])]
      : plans?.[kind]?.unpriced;
  const go = (kind: RenderKind, yes: boolean) =>
    onRender(kind, yes, kind === "keyframe" ? draws : 1, kind === "video" && choice ? choice.id : undefined, total(kind));

  const directions = DIRECTIONS[cam.move || ""];
  /** The shot camera's lens, move and render: in the stage's side column (the lab plays and records them),
   * or in the right column on a host with no scene lab. Camerawork templates are presets of the move. */
  const cameraFields = (
    <div className="olf-camera" data-testid="shot-camera">
      <span className="olf-label">Shot camera</span>
      <div className="olf-grid2">
        <Field label="Lens">
          <Pick value={cam.lens} options={lenses} blank disabled={locked} onPick={(v) => onEdit({ lens: v })} testId="shot-lens" />
        </Field>
        <Field label={`Move${from("move")}`}>
          <Pick value={cam.move} options={MOVES} blank disabled={locked} onPick={(v) => onEdit({ move: v })} testId="shot-move" />
        </Field>
        <Field label={`Amount${from("amount")}`}>
              <input
                key={`amount-${cam.amount}`}
                className="olf-input"
                type="number"
                min={0.01}
                max={5}
                step={0.05}
                defaultValue={cam.amount ?? ""}
                disabled={locked}
                onBlur={(event) => {
                  const text = event.currentTarget.value.trim();
                  if (text !== String(cam.amount ?? "")) onEdit({ amount: text || null });
                }}
                title="Push and pull: the part of the frame the move removes. Pan and tilt: travel in frame widths. Shake: its size."
                aria-label="Amount"
                data-testid="shot-amount"
              />
        </Field>
        <Field label={`Ease${from("ease")}`}>
          <Pick value={cam.ease} options={EASES} blank disabled={locked} onPick={(v) => onEdit({ ease: v })} testId="shot-ease" />
        </Field>
        {directions ? (
          <Field label={`Direction${from("direction")}`}>
            <Pick value={cam.direction} options={directions} blank disabled={locked} onPick={(v) => onEdit({ direction: v })} testId="shot-direction" />
          </Field>
        ) : null}
        {/* Also in the Video step: a reference render needs the stage's pin video (no Step 1 ↔ 3 trap).
            With no scene lab these fields sit beside the Video step's own Render. */}
        {labRoute ? (
          <Field label={`Render${from("render")}`}>
            <Pick value={cam.render} options={RENDERS} blank disabled={locked} onPick={(v) => onEdit({ render: v })} testId="shot-render" />
          </Field>
        ) : null}
      </div>
          <Field label="Move preset">
            <select className="olf-input" disabled={locked} aria-label="Move preset" data-testid="shot-camerawork" {...camerawork}>
              <option value="">—</option>
              {menu.map((group) => (
                <optgroup key={group.label} label={group.label}>
                  {group.rows.map((row) => (
                    <option key={row.value} value={row.value}>
                      {row.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            {template ? (
              <span className="olf-small-text" data-testid="camerawork-intent">
                {template.data.intent}{" "}
                <button type="button" className="olf-link" onClick={() => onOpenEntry(template.id)}>
                  {template.id}
                </button>
              </span>
            ) : null}
          </Field>
    </div>
  );
  const shown_ = pickedVideo || videos[0];
  const steps: [Step, string, string][] = [
    ...(labRoute ? [["stage", "Stage", used ? `try ${used.try} used` : cam.render === "reference" ? "needed for a reference render" : "optional"] as [Step, string, string]] : []),
    ["keyframe", "Keyframe", chosen ? `${takeName(chosen.id)} chosen` : "none chosen yet"],
    ["video", "Video", shown_ ? `${takeName(shown_.id)} · ${shown_.status}` : "none yet"],
  ];

  function renderButton(kind: RenderKind, label: string, primary: boolean) {
    const plan = plans?.[kind];
    const picked = kind === "video" && Boolean(choice); // a picked model plans its own step
    const blocked = Boolean(busy) || locked || !plan || (Boolean(plan.error) && !picked) || (kind === "video" && !canVideo);
    return (
      <button
        type="button"
        className={primary ? "run olf-grow" : "ghost olf-grow"}
        disabled={blocked}
        onClick={() => (total(kind) || unpriced(kind)?.length || own(kind).length ? setConfirm(kind) : go(kind, false))}
        data-testid={`render-${kind}`}
      >
        {busy === kind ? "Rendering…" : label}
      </button>
    );
  }

  function ask(kind: RenderKind) {
    const what = kind === "audio" ? "the dialogue" : kind === "keyframe" && draws > 1 ? `${draws} keyframes` : `this ${kind}`;
    return (
      <Confirm
        text={spendText(total(kind), unpriced(kind), what, own(kind))}
        onYes={() => {
          go(kind, true);
          setConfirm(null);
        }}
        onNo={() => setConfirm(null)}
      />
    );
  }

  return (
    <section className="olf-shot" data-testid="shot-page" data-shot={id}>
      {banner ? (
        <div className="olf-stale-banner" role="status" data-testid="stale-banner">
          <span>
            Stale: {cause?.summary || "an input changed"} after {takeName(banner.id)} was rendered.
            {cause && !cause.known ? " The engine kept no inputs for this take, so it cannot say what changed." : ""}
            {others.length ? ` Also stale: ${others.map((row) => takeName(row.id)).join(", ")}.` : ""}
          </span>
          <span className="olf-row">
            {cause?.changes.length ? (
              <button type="button" className="ghost olf-small olf-stale-btn" aria-expanded={diff} onClick={() => setDiff(!diff)} data-testid="see-change">
                See change
              </button>
            ) : null}
            <button type="button" className="ghost olf-small olf-stale-btn" disabled={locked} onClick={() => onKeep(banner.id)} data-testid="keep-take">
              Keep {takeName(banner.id)} anyway
            </button>
          </span>
        </div>
      ) : null}
      {diff && cause ? (
        <table className="olf-diff" data-testid="stale-diff">
          <thead>
            <tr>
              <th>Changed</th>
              <th>Before</th>
              <th>Now</th>
            </tr>
          </thead>
          <tbody>
            {cause.changes.map((row) => (
              <tr key={row.field} title={row.field}>
                <td>{row.label}</td>
                <td>{shown(row.before)}</td>
                <td>{shown(row.after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {steps.length ? (
        <nav className="olf-steps" aria-label="Steps of this shot" data-testid="shot-steps">
          {steps.map(([key, label, state], index) => (
            <button key={key} type="button" className="olf-step" aria-current={step === key ? "step" : undefined} onClick={() => setStep(key)} data-testid={`shot-step-${key}`}>
              <span className="olf-step-n">{index + 1}</span>
              <span>
                <b>{label}</b>
                <span className="muted olf-small-text">{state}</span>
              </span>
            </button>
          ))}
        </nav>
      ) : null}
      {step === "stage" ? (
        <SceneLab show={show} id={id} locked={locked} onUse={(n, draw, pin) => onStoryboard(draw, n, pin)} camera={cameraFields} />
      ) : (
        <div className="olf-shot-grid">
          <div className="olf-shot-main">
            <div className="olf-preview" data-testid="shot-preview">
              {picture?.file && picture.kind === "video" ? (
                <video
                  key={picture.id}
                  ref={audioTake ? undefined : setMedia}
                  src={fileUrl(show.path, picture.file)}
                  muted={Boolean(audioTake)}
                  loop
                  playsInline
                />
              ) : picture?.file ? (
                <img src={fileUrl(show.path, picture.file)} alt="" />
              ) : shot.pills?.start.length ? (
                <>
                  <PillFrame pills={shot.pills} />
                  <span className="olf-pills-tag">{audioTake ? "Dialogue only: pills until a keyframe" : "Pills: no keyframe yet"}</span>
                </>
              ) : (
                <span className="olf-preview-ph">
                  <b>{framingShort(shot.camera)}</b>
                  <span>{audioTake ? "Dialogue only: no picture yet." : step === "video" ? "No video yet: render it from the chosen keyframe." : "No keyframe yet. Draw one: it gives the shot its look."}</span>
                </span>
              )}
              {audioTake?.file ? (
                <audio key={audioTake.id} ref={setMedia} src={fileUrl(show.path, audioTake.file)} data-testid="take-audio" />
              ) : null}
              {media && (audioTake || picture?.kind === "video") ? <PlayBar media={media} /> : null}
            </div>
            <div className="olf-strip-head">
              <h3>{step === "video" ? "Video takes" : "Keyframes"}</h3>
              <span className="muted">{step === "video" ? "Video from the chosen keyframe, and the dialogue" : "Approve a keyframe to choose it: it gives the video its look"}</span>
            </div>
            <div className="olf-strip" data-testid="take-strip">
              {strip.length ? (
                strip.map((row) => {
                  const isChosen = shot.select?.[row.kind] === takeName(row.id);
                  return (
                    <button
                      key={row.id}
                      type="button"
                      className={`olf-strip-item${take?.id === row.id ? " on" : ""}${isChosen ? " chosen" : ""}${row.stale ? " is-stale" : ""}`}
                      onClick={() => setCurrent(row.id)}
                      data-testid="strip-take"
                      data-take={row.id}
                    >
                      <span className="olf-strip-media">
                        {row.file && row.kind === "keyframe" ? <img src={fileUrl(show.path, row.file)} alt="" /> : null}
                        {row.file && row.kind === "video" ? (
                          <video src={fileUrl(show.path, row.file)} muted playsInline preload="metadata" />
                        ) : null}
                        {row.kind === "audio" ? <span className="olf-strip-len">{row.duration || "audio"}</span> : null}
                        <code>{takeName(row.id)}</code>
                      </span>
                      <span className="olf-strip-meta">
                        <span>{row.kind === "audio" ? "dialogue" : row.kind}</span>
                        <span className={`status-text status-${row.status}`}>{row.stale ? "stale" : row.status}</span>
                      </span>
                    </button>
                  );
                })
              ) : (
                <p className="muted olf-small-text">No takes yet.</p>
              )}
            </div>
            {take ? <TakeDetails take={take} onApprove={() => onApprove(take)} onReject={() => onReject(take)} /> : null}
            {detail ? (
              <details className="olf-details" data-testid="engine-details">
                <summary>What the engine sends next</summary>
                <span className="olf-label">References, first is primary</span>
                <div className="ref-row">
                  {detail.references.map((ref) => (
                    <RefThumb key={ref.asset} show={show} file={ref.file} height={64} />
                  ))}
                </div>
                <span className="olf-label">Prompt for the {step === "video" ? "video" : "keyframe"}</span>
                <pre>{detail.prompts[step === "video" ? "video" : "keyframe"]}</pre>
                <dl className="hash-list">
                  {Object.entries(detail.hashes).map(([name, hash]) => (
                    <div key={name}>
                      <dt>{name}</dt>
                      <dd title={hash || ""}>{hash ? shortHash(hash) : "needs a chosen keyframe"}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            ) : null}
          </div>

          <aside className="olf-shot-side">
            {/* Edits write one line of the file that holds the shot (vinci_olf.author.set_shot). */}
            <Field label="Description">
              <textarea
                key={`description-${shot.description}`}
                className="olf-input olf-textarea"
                defaultValue={shot.description}
                disabled={locked}
                onBlur={(event) => {
                  const text = event.currentTarget.value.trim();
                  if (text && text !== shot.description) onEdit({ description: text });
                }}
                aria-label="Description"
                data-testid="shot-description"
              />
            </Field>
            {used?.framing ? (
              // The stage decides these: Use writes what the try's camera shows (COREPRODUC-739).
              <Field label="Framing · angle">
                <span className="olf-small-text" data-testid="shot-measured">
                  <b>
                    {say(cam.framing)} · {say(cam.angle)}
                  </b>{" "}
                  · measured from try {used.try}.{" "}
                  <button type="button" className="olf-link" onClick={() => setStep("stage")}>
                    Change in the stage
                  </button>
                </span>
              </Field>
            ) : null}
            <div className="olf-grid2">
              {used?.framing ? null : (
                <>
                  <Field label="Framing">
                    <Pick value={cam.framing} options={FRAMINGS} disabled={locked} onPick={(v) => v && onEdit({ framing: v })} testId="shot-framing" />
                  </Field>
                  <Field label="Angle">
                    <Pick value={cam.angle} options={ANGLES} blank disabled={locked} onPick={(v) => onEdit({ angle: v })} testId="shot-angle" />
                  </Field>
                </>
              )}
              <Field label="Length">
                <input
                  key={`length-${shot.duration}`}
                  className="olf-input"
                  defaultValue={frames(shot.duration)}
                  disabled={locked}
                  onBlur={(event) => {
                    const text = event.currentTarget.value.trim();
                    if (text && text !== frames(shot.duration)) onEdit({ duration: text });
                  }}
                  title="Seconds+frames at 24 frames a second (3+12 is 3.5 s), or seconds (3.5s)"
                  aria-label="Length"
                  data-testid="shot-length"
                />
              </Field>
              <Field label={`Canvas${from("canvas")}`}>
                <Pick value={cam.canvas} options={CANVASES} blank disabled={locked} onPick={(v) => onEdit({ canvas: v })} testId="shot-canvas" />
              </Field>
            </div>
            {labRoute ? null : cameraFields}
            {shot.pills?.crosses ? (
              <p className="olf-error" data-testid="shot-crosses">
                Crosses the 180° line: {shot.pills.crosses}
              </p>
            ) : null}
            {shot.storyboard || labRoute ? (
              <Field label="Keyframe layout">
                <div className="olf-box olf-storyboard" data-testid="shot-storyboard">
                  {shot.storyboard ? (
                    <img src={`${fileUrl(show.path, shot.storyboard)}&v=${String(shot.control?.storyboard || "").slice(6, 18)}`} alt="Keyframe layout of this shot" />
                  ) : (
                    <span className="muted">No keyframe layout yet: the keyframe model gets the staging in words only.</span>
                  )}
                    {shot.reference_video ? (
                      // The pin video a `render: reference` video follows (COREPRODUC-732).
                      <video
                        src={`${fileUrl(show.path, shot.reference_video)}&v=${String(shot.control?.reference_video || "").slice(6, 18)}`}
                        muted
                        loop
                        autoPlay
                        playsInline
                        aria-label="Pin video of this shot"
                        title="The pin video: a reference render follows its camera path and timing"
                        data-testid="shot-reference-video"
                      />
                    ) : null}
                    {shot.reference_video ? <span className="muted olf-small-text">Pin video · a reference render follows its camera and timing</span> : null}
                  {pinStale.length ? <PinStale fields={pinStale} /> : null}
                  {labRoute ? (
                    <button type="button" className="ghost olf-small" onClick={() => setStep("stage")} data-testid="open-stage">
                      {shot.storyboard ? "Open in the stage" : "Stage the shot in 3D"}
                    </button>
                  ) : null}
                </div>
              </Field>
            ) : null}
            {((resolved.characters || []) as OlfData[]).length ? (
              <Field label="Characters">
                {((resolved.characters || []) as OlfData[]).map((char) => (
                  <div key={char.id} className="olf-box olf-cast" data-testid="shot-cast">
                    <div className="olf-cast-line">
                      <button type="button" className="olf-link" onClick={() => onOpenEntry(char.id)}>
                        {char.name || char.id}
                      </button>
                      <code>{char.id}</code>
                    </div>
                    <div className="olf-chips">
                      {char.form ? (
                        <span className="chip">
                          form: <b>{char.form.name}</b> · {levelLabel(origins?.forms?.[char.id])}
                        </span>
                      ) : null}
                      {char.outfit ? (
                        <span className="chip">
                          outfit: <b>{char.outfit.name}</b> · {levelLabel(origins?.outfits?.[char.id])}
                        </span>
                      ) : null}
                    </div>
                    {!used && resolved.blocking?.[char.id] ? <p className="olf-small-text">{resolved.blocking[char.id]}</p> : null}
                  </div>
                ))}
              </Field>
            ) : null}
            {step === "video" ? (
              <>
                {lines.length ? (
                  <Field label="Dialogue">
                    {lines.map((line, index) => (
                      <div key={index} className="olf-box olf-line">
                        <span className="olf-label">
                          {entryName(findEntry(show, line.speaker), line.speaker).toUpperCase()}
                          {line.delivery ? ` · ${line.delivery}` : ""}
                        </span>
                        “{line.line}”
                      </div>
                    ))}
                    {/* Each line in its speaker's voice (extensions.<provider> of the voice), as one audio take. */}
                    {confirm === "audio" ? (
                      ask("audio")
                    ) : (
                      <div className="olf-row">{renderButton("audio", spoken.length ? "Re-render dialogue" : "Render dialogue", false)}</div>
                    )}
                    {plans?.audio?.plan?.length ? (
                      <span className="muted olf-small-text" data-testid="dialogue-plan">
                        {plans.audio.plan[0].model} · {price(total("audio"))}
                      </span>
                    ) : null}
                  </Field>
                ) : null}
              </>
            ) : null}
            {detail ? (
              <Field label={`Inherited from scene ${shot.scene}`}>
                <span className="olf-small-text">
                  {[location ? location.name || location.id : null, location?.variant, resolved.mood ? `mood: ${resolved.mood}` : null]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </Field>
            ) : null}

            <section className="olf-panel olf-render" data-testid="render-box">
              {!detail ? (
                <p className={shot.error ? "olf-error" : "muted olf-small-text"}>{shot.error || "Checking the price…"}</p>
              ) : null}
              {step === "video" ? (
                <>
                  <Field label={`Render${from("render")}`}>
                    <Pick value={cam.render} options={RENDERS} blank disabled={locked} onPick={(v) => onEdit({ render: v })} testId="shot-render" />
                  </Field>
                  {engineMove ? (
                    <Field label="Video">
                      <span className="olf-small-text" data-testid="engine-move">
                        <b>Engine move · $0.</b> The frame moves over the chosen keyframe. No video model runs.
                      </span>
                    </Field>
                  ) : (
                    <Field label="Video model">
                      <select
                        className="olf-input"
                        value={videoModel}
                        disabled={locked || !plans?.video.choices?.length}
                        onChange={(event) => setVideoModel(event.target.value)}
                        data-testid="video-model"
                      >
                        <option value="">{autoLabel(videoModelRouted, plans?.video.choices)}</option>
                        {(plans?.video.choices || []).map((row) => (
                          <option key={row.id} value={row.id}>
                            {choiceLabel(row)}
                          </option>
                        ))}
                      </select>
                    </Field>
                  )}
                </>
              ) : null}
              <div className="olf-cost">
                <span>Estimated cost{step === "video" ? "" : draws > 1 ? ` (${draws} keyframes)` : " (keyframe)"}</span>
                <b>
                  {costText(total(next), own(next))}
                  {unpriced(next)?.length ? " + no flat price" : ""}
                </b>
              </div>
              {planError ? <p className="olf-error">{planError}</p> : null}
              {step === "video" && stageNext ? (
                <button type="button" className="ghost olf-small" onClick={() => setStep("stage")} data-testid="open-stage-pin">
                  Open Stage to record pin video
                </button>
              ) : null}
              {(step === "video" ? plans?.video.notes || [] : []).map((note) => (
                <p key={note} className="olf-warn" data-testid="render-note">
                  {note.slice(0, 1).toUpperCase() + note.slice(1)}.
                </p>
              ))}
              {step === "video" ? (
                <p className="muted olf-small-text" data-testid="render-hint">
                  {!needs
                    ? "This shot animates from text: no control points at a keyframe."
                    : chosen
                      ? cam.render === "reference"
                        ? `Video follows the pin video and takes the chosen keyframe ${takeName(chosen.id)} as its look.`
                        : `${engineMove ? "The engine moves" : "Video animates from"} the chosen keyframe ${takeName(chosen.id)}.`
                      : "Approve a keyframe first: video renders from the chosen keyframe."}
                </p>
              ) : null}
              {step === "video" && chosen?.stale ? (
                <p className="olf-warn">{takeName(chosen.id)} is stale. Draw a new keyframe first, or the video keeps the old look.</p>
              ) : null}
              {step === "keyframe" ? (
                <div className="olf-draws" role="group" aria-label="Keyframes per draw">
                  <span className="olf-label">Keyframes per draw</span>
                  {DRAWS.map((n) => (
                    <button
                      key={n}
                      type="button"
                      className="olf-chip-btn"
                      aria-pressed={draws === n}
                      onClick={() => setDraws(n)}
                      data-testid={`draws-${n}`}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              ) : null}
              {confirm && confirm !== "audio" ? (
                ask(confirm)
              ) : (
                <div className="olf-row">
                  {step === "keyframe"
                    ? renderButton("keyframe", draws > 1 ? `${draws} new keyframes` : "New keyframe", true)
                    : renderButton("video", videos.length ? "Re-render video" : "Render video", true)}
                </div>
              )}
            </section>
          </aside>
        </div>
      )}
    </section>
  );
}

/** A changed value for people: text as it is, other values as JSON, "—" when absent. */
function shown(value: unknown): string {
  if (value === undefined || value === null) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function TakeDetails({ take, onApprove, onReject }: { take: OlfTake; onApprove: () => void; onReject: () => void }) {
  const prov = take.provenance || {};
  const from = take.inputs?.first_frame ? takeName(String(take.inputs.first_frame)) : null;
  const rows: [string, unknown][] = [
    ["Provider", prov.provider],
    ["Model", prov.model],
    ["Seed", prov.seed],
    ["From keyframe", from],
    ["Audio source", take.audio_source],
    // Up to 4 decimals: a dialogue line on an ElevenLabs key costs a fraction of a cent (COREPRODUC-787).
    ["Cost", prov.cost ? `${+Number(prov.cost.amount).toFixed(4)} ${prov.cost.currency}` : null],
    ["Created", prov.created?.replace("T", " ")],
    ["Length", take.duration],
    // The palette check (vinci_olf.qa): does the render keep the forms' colors?
    ...(take.qa || []).map((row): [string, unknown] => [
      `QA ${row.check}`,
      [row.score?.toFixed(2), row.pass === undefined ? null : row.pass ? "pass" : "fail"].filter(Boolean).join(" "),
    ]),
  ];
  const approved = take.status === "approved";
  const rejected = take.status === "rejected";
  return (
    <Panel
      title={`Provenance · ${takeName(take.id)}`}
      aside={
        <>
          {take.stale ? <StalePill /> : null}
          <button type="button" className="olf-chip-btn" aria-pressed={approved} onClick={onApprove}>
            {approved ? "Approved" : "Approve"}
          </button>
          <button type="button" className="olf-chip-btn" aria-pressed={rejected} onClick={onReject}>
            {rejected ? "Rejected" : "Reject"}
          </button>
        </>
      }
      testId="take-details"
    >
      <dl className="olf-prov">
        {rows
          .filter(([, value]) => value !== undefined && value !== null && value !== "")
          .map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
      </dl>
      {prov.prompt ? (
        <details className="olf-details">
          <summary>{take.kind === "audio" ? "Lines sent to the voice model" : "Prompt sent to the model"}</summary>
          <pre>{prov.prompt}</pre>
        </details>
      ) : null}
    </Panel>
  );
}
