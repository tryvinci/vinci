"use client";

import { useEffect, useRef, useState } from "react";
import {
  ANGLES,
  CANVASES,
  EASES,
  FRAMINGS,
  MOVES,
  RENDERS,
  type OlfData,
  type OlfShotDetail,
  type OlfShow,
  type OlfStaleCause,
  type OlfTake,
  type RenderKind,
  autoLabel,
  cameraworkMenu,
  choiceLabel,
  chosenKeyframe,
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
import { Confirm, Field, Panel, PillFrame, Pick, PlayBar, RefThumb, StalePill } from "./shows-parts";

const DRAWS = [1, 2, 3, 4]; // keyframe variations per draw (the engine's MAX_VARIATIONS)

/** Takes in render order for the strip: keyframes, then videos, then dialogue, oldest first. */
function stripOrder(show: OlfShow, id: string): OlfTake[] {
  return (["keyframe", "video", "audio"] as const).flatMap((kind) => [...takesOf(show, id, kind)].reverse());
}

/**
 * Shot page (Claude Design, screen 3): full width, with no left panel; the top bar holds the crumb
 * and the previous and next shot. Keyframes first: approve a keyframe (approving also chooses it,
 * as the design outlines approved takes), then render video from it. Dialogue renders as an audio
 * take (one line after another in each speaker's voice), which the Cut can play as separate sound.
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
  onEdit: (fields: Record<string, string | null>) => void;
  /** Put a camerawork template on the shot (a library ID or `cam/<slug>`), or take it off (`null`). */
  onCamerawork: (template: string | null) => void;
  /** What changed since a take was rendered (`GET /olf/stale`). */
  onExplain: (take: string) => Promise<OlfStaleCause>;
  /** Keep a stale take on purpose (`POST /olf/keep`). */
  onKeep: (take: string) => void;
}) {
  const shot = show.shots[id];
  const [current, setCurrent] = useState<string | null>(null);
  // After a render, show its first new take: else Approve acts on the take clicked before
  // (found in the live test of 2026-11-09, COREPRODUC-558). The first load shows the default.
  const ids = (shot.takes || []).join(" ");
  const seen = useRef<string[] | null>(null);
  useEffect(() => {
    const now = ids ? ids.split(" ") : [];
    const added = seen.current ? now.filter((take) => !seen.current?.includes(take)) : [];
    seen.current = now;
    if (added.length) setCurrent(added[0]);
  }, [ids]);
  const [confirm, setConfirm] = useState<RenderKind | null>(null);
  const [draws, setDraws] = useState(1);
  const [videoModel, setVideoModel] = useState(""); // "" is Auto (routing)
  const [media, setMedia] = useState<HTMLMediaElement | null>(null); // what the play bar drives
  const strip = stripOrder(show, id);
  const chosen = chosenKeyframe(show, id);
  const videos = takesOf(show, id, "video");
  const pickedVideo = videos.find((take) => takeName(take.id) === shot.select?.video);
  const take = (current && show.takes[current]) || pickedVideo || videos[0] || chosen || shownKeyframe(show, id);
  // An audio take plays over the shot's picture: the chosen video, else the keyframe it shows.
  const audioTake = take?.kind === "audio" ? take : null;
  const picture = audioTake ? pickedVideo || videos[0] || chosen || shownKeyframe(show, id) : take;
  const staleTakes = strip.filter((row) => row.stale);
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
  const cam = shot.camera || {};
  const lenses = ((show.style?.data.lenses as string[] | undefined) || []).map(String); // a shot may use only these
  // An engine move: the frame moves over the chosen keyframe, with no video model ($0).
  const engineMove = cam.render === "engine";
  const template = findEntry(show, cam.template?.id);
  const menu = cameraworkMenu(show, library);
  /** A camera field that the template fills says so; a value typed here goes in the shot and wins. */
  const from = (field: string) => (origins?.camera_fields?.[field]?.startsWith("cam/") ? " · template" : "");
  // A shot animates from a keyframe when a control points at one (control.first_frame: keyframe),
  // and an engine move has only the keyframe to move.
  const needs = Object.values(shot.control || {}).includes("keyframe") || engineMove;
  const canVideo = !needs || Boolean(chosen);
  const plans = detail?.plans;
  const next: RenderKind = canVideo ? "video" : "keyframe"; // the next useful render
  const videoModelRouted = plans?.video.plan?.find((row) => row.node === "video")?.model;
  const planError = plans?.keyframe.error || plans?.video.error;
  const lines = (resolved.dialogue || []) as OlfData[];
  const spoken = takesOf(show, id, "audio");
  const choice = plans?.video.choices?.find((row) => row.id === videoModel);
  // A keyframe render draws `draws` variations, each at the keyframe price; a picked video model
  // replaces the routed one's price.
  const total = (kind: RenderKind) => {
    if (kind === "video" && choice) {
      const other = (plans?.video.plan || []).filter((row) => row.node !== "video");
      return other.reduce((sum, row) => sum + row.amount, 0) + choice.amount;
    }
    return (plans?.[kind]?.total || 0) * (kind === "keyframe" ? draws : 1);
  };
  const unpriced = (kind: RenderKind) =>
    kind === "video" && choice
      ? [...(plans?.video.unpriced || []).filter((id) => id !== videoModel && id !== videoModelRouted), ...(choice.unpriced ? [choice.id] : [])]
      : plans?.[kind]?.unpriced;
  const go = (kind: RenderKind, yes: boolean) =>
    onRender(kind, yes, kind === "keyframe" ? draws : 1, kind === "video" && choice ? choice.id : undefined, total(kind));

  function renderButton(kind: RenderKind, label: string, primary: boolean) {
    const plan = plans?.[kind];
    const blocked = Boolean(busy) || locked || !plan || Boolean(plan.error) || (kind === "video" && !canVideo);
    return (
      <button
        type="button"
        className={primary ? "run olf-grow" : "ghost olf-grow"}
        disabled={blocked}
        onClick={() => (total(kind) || unpriced(kind)?.length ? setConfirm(kind) : go(kind, false))}
        data-testid={`render-${kind}`}
      >
        {busy === kind ? "Rendering…" : label}
      </button>
    );
  }

  function ask(kind: RenderKind) {
    const what = kind === "audio" ? "the dialogue" : kind === "keyframe" && draws > 1 ? `${draws} keyframes` : "this render";
    return (
      <Confirm
        text={spendText(total(kind), unpriced(kind), what)}
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
                <span>{audioTake ? "Dialogue only: no picture yet." : "No takes yet. Draw a keyframe first."}</span>
              </span>
            )}
            {audioTake?.file ? (
              <audio key={audioTake.id} ref={setMedia} src={fileUrl(show.path, audioTake.file)} data-testid="take-audio" />
            ) : null}
            {media && (audioTake || picture?.kind === "video") ? <PlayBar media={media} /> : null}
          </div>
          <div className="olf-strip-head">
            <h3>Takes</h3>
            <span className="muted">Keyframes first, then video from the selected keyframe</span>
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
              <span className="olf-label">Prompt for the {canVideo ? "video" : "keyframe"}</span>
              <pre>{detail.prompts[canVideo ? "video" : "keyframe"]}</pre>
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
          {/* A template fills the move fields and the length (POST /olf/camerawork); each field stays editable. */}
          <Field label="Camerawork">
            <select
              className="olf-input"
              value={cam.template?.id || ""}
              disabled={locked}
              onChange={(event) => onCamerawork(event.target.value || null)}
              aria-label="Camerawork"
              data-testid="shot-camerawork"
            >
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
          <div className="olf-grid2">
            <Field label="Framing">
              <Pick value={cam.framing} options={FRAMINGS} disabled={locked} onPick={(v) => v && onEdit({ framing: v })} testId="shot-framing" />
            </Field>
            <Field label="Angle">
              <Pick value={cam.angle} options={ANGLES} blank disabled={locked} onPick={(v) => onEdit({ angle: v })} testId="shot-angle" />
            </Field>
            <Field label="Lens">
              <Pick value={cam.lens} options={lenses} blank disabled={locked} onPick={(v) => onEdit({ lens: v })} testId="shot-lens" />
            </Field>
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
            <Field label={`Move${from("move")}`}>
              <Pick value={cam.move} options={MOVES} blank disabled={locked} onPick={(v) => onEdit({ move: v })} testId="shot-move" />
            </Field>
            <Field label={`Render${from("render")}`}>
              <Pick value={cam.render} options={RENDERS} blank disabled={locked} onPick={(v) => onEdit({ render: v })} testId="shot-render" />
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
            <Field label={`Canvas${from("canvas")}`}>
              <Pick value={cam.canvas} options={CANVASES} blank disabled={locked} onPick={(v) => onEdit({ canvas: v })} testId="shot-canvas" />
            </Field>
          </div>
          {shot.pills?.crosses ? (
            <p className="olf-error" data-testid="shot-crosses">
              Crosses the 180° line: {shot.pills.crosses}
            </p>
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
                  {resolved.blocking?.[char.id] ? <p className="olf-small-text">{resolved.blocking[char.id]}</p> : null}
                </div>
              ))}
            </Field>
          ) : null}
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
            <div className="olf-cost">
              <span>Estimated cost{canVideo ? "" : draws > 1 ? ` (${draws} keyframes)` : " (keyframe)"}</span>
              <b>
                {price(total(next))}
                {unpriced(next)?.length ? " + no flat price" : ""}
              </b>
            </div>
            {planError ? <p className="olf-error">{planError}</p> : null}
            {(plans?.video.notes || []).map((note) => (
              <p key={note} className="olf-warn" data-testid="render-note">
                {note.slice(0, 1).toUpperCase() + note.slice(1)}.
              </p>
            ))}
            <p className="muted olf-small-text" data-testid="render-hint">
              {!needs
                ? "This shot animates from text: no control points at a keyframe."
                : chosen
                  ? `${engineMove ? "The engine moves" : "Video animates from"} the chosen keyframe ${takeName(chosen.id)}.`
                  : "Approve a keyframe first: video renders from the chosen keyframe."}
            </p>
            {chosen?.stale ? (
              <p className="olf-warn">{takeName(chosen.id)} is stale. Draw a new keyframe first, or the video keeps the old look.</p>
            ) : null}
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
            {confirm && confirm !== "audio" ? (
              ask(confirm)
            ) : (
              <div className="olf-row">
                {renderButton("keyframe", draws > 1 ? `${draws} new keyframes` : "New keyframe", false)}
                {renderButton("video", videos.length ? "Re-render video" : "Render video", true)}
              </div>
            )}
          </section>
        </aside>
      </div>
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
    ["Cost", prov.cost ? `${Number(prov.cost.amount).toFixed(2)} ${prov.cost.currency}` : null],
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
