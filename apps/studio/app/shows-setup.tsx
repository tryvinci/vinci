"use client";

import { type ReactNode, useEffect, useState } from "react";
import {
  KEYFRAME_OPTIONS,
  type OlfBatch,
  type OlfModels,
  type OlfScriptPreview,
  type OlfTextStep,
  TEXT_MODEL_KEY,
  autoLabel,
  choiceLabel,
  framingShort,
  keyframeEstimate,
  newEntries,
  price,
  readyJobs,
  runtimeText,
  scriptFound,
  spendText,
  textStepQuestion,
} from "../lib/shows";
import { message, olf, runJobs, send } from "./shows-api";
import { Confirm, OlfOnly, VoicePick, fileData } from "./shows-parts";

const MEDIUMS = ["2D anime", "3D animation", "Live-action", "Stop-motion"];
const ASPECTS = ["16:9", "9:16", "1:1"];
const STEPS = ["Show", "First character", "First episode"];

/** The ID the engine gives a new character: its first name as a slug (`Mira Sol` -> `char/mira`). */
function charId(name: string): string {
  return `char/${(name.trim().split(/\s+/)[0] || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`;
}

/**
 * The script box and its shot list (design: New show, step 3; Storyboard: Shot list from script).
 * The shot list comes from rules, without AI (`POST /olf/script/preview`). "Split with a model" and
 * "Draft from idea" ask a text model, price first, and put its script in the box.
 *
 * Args:
 *   path: The open show, whose bible names the script's characters and places; else `characters`.
 *   onView: Gets each new preview, so the parent can count shots and price keyframes.
 */
export function ScriptStep({
  script,
  onScript,
  path,
  characters = {},
  refs = false,
  draft = false,
  onView,
}: {
  script: string;
  onScript: (text: string) => void;
  path?: string;
  characters?: Record<string, string>;
  refs?: boolean;
  draft?: boolean;
  onView?: (view: OlfScriptPreview | null) => void;
}) {
  const [view, setView] = useState<OlfScriptPreview | null>(null);
  const [idea, setIdea] = useState<string | null>(null); // null: the idea box is closed
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  // A text step that costs money (or has no flat price) waits here for Confirm.
  const [ask, setAsk] = useState<{ route: string; body: Record<string, unknown>; plan: OlfTextStep; what: string } | null>(null);
  // The text model menu: "" is Auto (routing). An agent CLI is only ever a person's pick.
  const [models, setModels] = useState<OlfModels | null>(null);
  const [textModel, setTextModel] = useState("");
  const names = JSON.stringify(characters);

  useEffect(() => {
    olf<OlfModels>("/models?capability=t2t")
      .then((body) => {
        setModels(body);
        const saved = window.localStorage.getItem(TEXT_MODEL_KEY) || "";
        // With no routed model (live mode with only agent CLIs), the first choice is the default.
        setTextModel(body.choices.some((row) => row.id === saved) ? saved : body.auto ? "" : body.choices[0]?.id || "");
      })
      .catch((err) => console.warn("[shows] text models", message(err)));
  }, []);

  useEffect(() => {
    if (!script.trim()) {
      setView(null);
      onView?.(null);
      return;
    }
    let live = true;
    // Debounced: the rules run on each pause in typing, not on each key.
    const timer = window.setTimeout(() => {
      olf<OlfScriptPreview>("/script/preview", send("POST", { script, path, characters: JSON.parse(names), refs }))
        .then((body) => {
          if (!live) return;
          setView(body);
          setError("");
          onView?.(body);
        })
        .catch((err) => live && setError(message(err)));
    }, 350);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // onView is the parent's setter: the preview depends only on these inputs.
  }, [script, path, names, refs]);

  /** Run a text step: a dry run for the price, then the step itself (after Confirm when it costs money). */
  async function textStep(route: string, fields: Record<string, unknown>, what: string, confirmed?: OlfTextStep) {
    setError("");
    const body = { model: textModel || undefined, ...fields }; // a confirmed step keeps its model
    try {
      if (!confirmed) {
        setBusy("Checking the price…");
        const plan = await olf<OlfTextStep>(route, send("POST", { ...body, dry_run: true }));
        if (plan.total || plan.unpriced?.length) {
          setAsk({ route, body, plan, what });
          return;
        }
        confirmed = plan;
      }
      // An agent CLI can take a minute: say which model works.
      const who = models?.choices.find((row) => row.id === body.model)?.name;
      setBusy(`${route === "/draft" ? "Drafting the script" : "Splitting the script into shots"}${who ? ` with ${who}` : ""}…`);
      const out = await olf<OlfTextStep>(route, send("POST", { ...body, yes: true, max_total: confirmed.total || 0 }));
      console.info("[shows] text step", { route, model: out.plan?.[0]?.model, chars: out.text?.length });
      if (out.text) onScript(out.text);
      if (route === "/draft") setIdea(null);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy("");
    }
  }

  const found = view?.characters.filter((row) => !row.new) || [];
  return (
    <div className="setup-two">
      <section className="olf-panel script-box" data-testid="script-box">
        <header>
          <h3>Script</h3>
          <span className="olf-panel-aside">
            <label className="ghost olf-small olf-file-btn" data-testid="import-fountain">
              Import .fountain
              <input
                type="file"
                accept=".fountain,.txt,text/plain"
                hidden
                onChange={async (event) => {
                  const file = event.currentTarget.files?.[0];
                  event.currentTarget.value = "";
                  if (file) onScript(await file.text());
                }}
              />
            </label>
            {draft ? (
              <button type="button" className="ghost olf-small" onClick={() => setIdea(idea === null ? "" : null)} data-testid="draft-idea">
                Draft from idea
              </button>
            ) : null}
            <button
              type="button"
              className="ghost olf-small"
              disabled={!script.trim() || !!busy}
              title="A text model splits the script into shots with framing, lens and length."
              onClick={() => void textStep("/script/model", { script, path, characters }, "a shot list")}
              data-testid="split-model"
            >
              Split with a model
            </button>
          </span>
        </header>
        {idea !== null ? (
          <form
            className="olf-row script-idea"
            onSubmit={(event) => {
              event.preventDefault();
              void textStep("/draft", { idea, path, characters }, "a draft");
            }}
          >
            <input className="olf-input olf-grow" value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="Your idea in one or two sentences" aria-label="Idea" autoFocus />
            <button type="submit" className="run olf-small" disabled={!idea.trim() || !!busy}>
              Draft
            </button>
          </form>
        ) : null}
        {ask ? (
          <Confirm
            text={textStepQuestion(ask.plan, models?.choices || [], ask.what)}
            onYes={() => {
              const job = ask;
              setAsk(null);
              void textStep(job.route, job.body, job.what, job.plan);
            }}
            onNo={() => setAsk(null)}
          />
        ) : null}
        <div className="olf-row script-label">
          <span className="olf-label">Script (Fountain or plain text)</span>
          {models?.choices.length ? (
            <label className="olf-label script-model">
              Text model
              <select
                className="olf-input olf-small"
                value={textModel}
                disabled={!!busy}
                onChange={(event) => {
                  setTextModel(event.target.value);
                  window.localStorage.setItem(TEXT_MODEL_KEY, event.target.value);
                }}
                data-testid="text-model"
              >
                {models.auto ? <option value="">{autoLabel(models.auto.model, models.choices)}</option> : null}
                {models.choices.map((row) => (
                  <option key={row.id} value={row.id}>
                    {choiceLabel(row)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        <textarea
          className="olf-input script-text"
          value={script}
          onChange={(event) => onScript(event.target.value)}
          placeholder={"EXT. CLIFF PATH - DUSK\n\nMira climbs toward the lighthouse.\n\nMIRA\n(whisper)\nYou kept the key?"}
          aria-label="Script"
          spellCheck={false}
          data-testid="script-text"
        />
        <footer className="olf-row script-foot">
          <span className="muted olf-small-text" data-testid="script-found">
            {busy || scriptFound(view)}
          </span>
          <span className="muted olf-small-text">{found.map((row) => `${row.name.split(" ")[0]} → ${row.id}`).join(" · ")}</span>
        </footer>
        {error ? <p className="olf-error olf-small-text">{error}</p> : null}
      </section>
      <ShotList view={view} />
    </div>
  );
}

/** The design's shot list: each scene with its place, then `sh010 · WS · 24mm · text · 5s` rows. */
function ShotList({ view }: { view: OlfScriptPreview | null }) {
  const places = new Map((view?.locations || []).map((row) => [row.id, row]));
  return (
    <section className="olf-panel script-list" data-testid="script-list">
      <header>
        <h3>Shot list</h3>
        <span className="olf-panel-aside">{view?.shots ? `${view.shots} ${view.shots === 1 ? "shot" : "shots"} · about ${runtimeText(view.runtime)}` : "No shots yet"}</span>
      </header>
      {view?.scenes.map((scene, i) => (
        <div key={`${scene.heading}-${i}`} className="script-scene">
          <h4>
            {scene.heading}{" "}
            {scene.location ? (
              <span className="muted">
                {scene.location}
                {places.get(scene.location)?.new ? " · new" : ""}
              </span>
            ) : null}
          </h4>
          {scene.shots.map((shot, n) => (
            <div key={n} className="script-shot" data-testid="script-shot">
              <code>sh{String((n + 1) * 10).padStart(3, "0")}</code>
              <code className="script-frame">{framingShort(shot.camera)}</code>
              <span className="script-desc" title={shot.description}>
                {shot.description}
                {(shot.dialogue || []).map((row) => ` “${row.line}”`).join("")}
              </span>
              <span className="muted">{shot.duration}</span>
            </div>
          ))}
        </div>
      ))}
      {newEntries(view).notes.map((note) => (
        <p key={note} className="olf-info" data-testid="script-new">
          {note}
        </p>
      ))}
    </section>
  );
}

/**
 * New show (Claude Design, screen 5): show, first character, first episode. Everything is saved as
 * plain OLF files (`POST /olf/new`); "Create show and draw keyframes" then draws two keyframes per
 * shot, price first (`POST /olf/batch`, mode `keyframes`).
 */
export function NewShow({ onCancel, onOpen }: { onCancel: () => void; onOpen: (path: string, notice: string) => void }) {
  const [step, setStep] = useState(0);
  const [show, setShow] = useState({ title: "", medium: MEDIUMS[0], aspect: ASPECTS[0] });
  const [cast, setCast] = useState({ name: "", description: "", sheet: "", voice: "", voiceName: "" });
  const [script, setScript] = useState("");
  const [view, setView] = useState<OlfScriptPreview | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const title = show.title.trim() || "Untitled show";
  const characters: Record<string, string> = cast.name.trim() ? { [charId(cast.name)]: cast.name.trim() } : {};
  const estimate = keyframeEstimate(view);
  const people = newEntries(view).people;
  // Keyframes only for a show that will be valid: a new speaker needs a sheet first (render stays off).
  const draw = !!view?.shots && !people.length;
  const summary = [
    `${title} · ${show.medium} · ${show.aspect}`,
    cast.name.trim() ? `${cast.name.trim()} · ${cast.sheet ? "sheet" : "no sheet yet"}` : "None yet",
    "Script to shot list",
  ];

  /**
   * Create the show and, with `keyframes`, draw them (`yes` after a person confirmed the price).
   * `empty`: only the show ("Skip to an empty project").
   */
  async function create(keyframes: boolean, yes = false, empty = false) {
    setError("");
    setBusy("Creating the show…");
    try {
      const body = {
        ...show,
        title,
        character:
          !empty && cast.name.trim()
            ? { name: cast.name, description: cast.description, sheet: cast.sheet || null, voice_id: cast.voice || null, voice_name: cast.voiceName }
            : null,
        script: !empty && step === 2 && script.trim() ? script : null,
      };
      const made = await olf<{ path: string; episode?: string; scenes?: string[] }>("/new", send("POST", body));
      console.info("[shows] new show", { path: made.path, episode: made.episode, scenes: made.scenes });
      let notice = `Created ${title}`;
      if (keyframes && made.episode) {
        setBusy("Checking the keyframe price…");
        try {
          // One request per shot (runJobs): a whole episode in one request outlived the proxy.
          const plan = await olf<OlfBatch>("/batch", send("POST", { path: made.path, episode: made.episode, mode: "keyframes", dry_run: true }));
          if (plan.total > estimate.total + 1e-9) throw new Error(`the price changed: the keyframes cost ${price(plan.total)}, more than the ${price(estimate.total)} you confirmed`);
          const jobs = readyJobs(plan);
          const result = await runJobs(made.path, jobs, yes, (done) => setBusy(`Drawing keyframes: ${done} of ${jobs.length} shots done…`));
          notice +=
            ` and drew ${result.takes.length} keyframes · ${price(result.total)}` +
            (result.failed.length ? ` · ${result.failed.length} failed: ${result.failed[0].error}` : "");
        } catch (err) {
          // The show exists now: open it and say why, or a retry would make a second show.
          console.warn("[shows] keyframes for the new show", message(err));
          notice += `. No keyframes were drawn: ${message(err)}`;
        }
      }
      onOpen(made.path, notice);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy("");
    }
  }

  const next = (
    <button type="button" className="run" disabled={step === 0 && !show.title.trim()} onClick={() => setStep(step + 1)} data-testid="setup-next">
      {step === 1 && !cast.name.trim() ? "Skip" : "Next"}
    </button>
  );
  let body: ReactNode;
  if (step === 0) {
    body = (
      <div className="setup-form">
        <label className="olf-field">
          <span className="olf-label">Title</span>
          <input className="olf-input" value={show.title} onChange={(e) => setShow({ ...show, title: e.target.value })} placeholder="Tidewatch" autoFocus data-testid="setup-title" />
        </label>
        <label className="olf-field">
          <span className="olf-label">Medium</span>
          <select className="olf-input" value={show.medium} onChange={(e) => setShow({ ...show, medium: e.target.value })}>
            {MEDIUMS.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <div className="olf-field">
          <span className="olf-label">Aspect</span>
          <div className="olf-tabs" role="radiogroup" aria-label="Aspect">
            {ASPECTS.map((a) => (
              <button key={a} type="button" role="radio" aria-checked={show.aspect === a} aria-selected={show.aspect === a} onClick={() => setShow({ ...show, aspect: a })}>
                {a}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  } else if (step === 1) {
    body = (
      <div className="setup-form">
        <label className="olf-field">
          <span className="olf-label">Name</span>
          <input className="olf-input" value={cast.name} onChange={(e) => setCast({ ...cast, name: e.target.value })} placeholder="Mira Sol" autoFocus data-testid="setup-char-name" />
        </label>
        <label className="olf-field">
          <span className="olf-label">Description</span>
          <textarea className="olf-input olf-textarea" value={cast.description} onChange={(e) => setCast({ ...cast, description: e.target.value })} placeholder="Lighthouse keeper and fox spirit. Fox ears, long hair, large tail." aria-label="Character description" />
        </label>
        <div className="olf-field">
          <span className="olf-label">Character sheet</span>
          <label className="ghost olf-file-btn olf-small" data-testid="setup-sheet">
            {cast.sheet ? "Sheet picked · pick another" : "Upload a sheet"}
            <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={async (e) => { const file = e.currentTarget.files?.[0]; if (file) setCast({ ...cast, sheet: await fileData(file) }); }} />
          </label>
          {cast.sheet ? <img className="setup-sheet" src={cast.sheet} alt="Character sheet" /> : null}
          <p className="muted olf-small-text">The whole sheet is the character reference. You can add more sheets, form views and details later in the bible.</p>
        </div>
        <OlfOnly path="/olf/voices">
          <div className="olf-field">
            <span className="olf-label">Voice</span>
            <VoicePick value={cast.voice} onPick={(voice, voiceName) => setCast({ ...cast, voice, voiceName })} testId="setup-voice" />
          </div>
        </OlfOnly>
      </div>
    );
  } else {
    body = <ScriptStep script={script} onScript={setScript} characters={characters} refs={!!cast.sheet} draft onView={setView} />;
  }
  return (
    <div className="shows-page setup" data-testid="shows-setup">
      <header className="setup-head">
        <b>New show</b>
        <span className="olf-row">
          <button type="button" className="ghost olf-small" disabled={!!busy} onClick={() => void create(false, false, true)} data-testid="setup-skip">
            Skip to an empty project
          </button>
          <button type="button" className="olf-x" aria-label="Close" onClick={onCancel}>
            ×
          </button>
        </span>
      </header>
      <aside className="setup-steps">
        {STEPS.map((name, i) => (
          <button key={name} type="button" className={`setup-step${i === step ? " is-current" : i < step ? " is-done" : ""}`} disabled={i > step} onClick={() => setStep(i)}>
            <span className="setup-dot">{i < step ? "✓" : i + 1}</span>
            <span>
              <b>{name}</b>
              <small>{summary[i]}</small>
            </span>
          </button>
        ))}
        <p className="muted olf-small-text">Everything you set here is saved as plain OLF files. You can change it later in the bible.</p>
      </aside>
      <main className="setup-main">
        <span className="olf-label">
          Step {step + 1} of {STEPS.length}
        </span>
        <h1>{["Name your show", "Add your first character", "Write or paste your first episode"][step]}</h1>
        <p className="muted">
          {
            [
              "The title, the look and the frame. They go into project.yaml and the style.",
              "A name, a description and a character sheet.",
              "We turn the script into scenes and shots. You approve keyframes next, before any video is made.",
            ][step]
          }
        </p>
        {body}
        {error ? (
          <p className="shows-error" role="alert">
            {error}
          </p>
        ) : null}
        <footer className="setup-foot">
          {step ? (
            <button type="button" className="ghost" onClick={() => setStep(step - 1)}>
              Back
            </button>
          ) : (
            <span />
          )}
          {step < 2 ? (
            next
          ) : confirm ? (
            <Confirm
              text={spendText(estimate.total, estimate.unpriced ? [view?.keyframe?.model || "the image model"] : [], `${KEYFRAME_OPTIONS * (view?.shots || 0)} keyframes`)}
              onYes={() => {
                setConfirm(false);
                void create(true, true);
              }}
              onNo={() => setConfirm(false)}
            />
          ) : (
            <span className="olf-row">
              {draw ? <span className="muted olf-small-text">{estimate.text}</span> : null}
              <button
                type="button"
                className="run"
                disabled={!!busy}
                onClick={() => (draw && (estimate.total || estimate.unpriced) ? setConfirm(true) : void create(draw))}
                data-testid="setup-create"
              >
                {busy || (draw ? "Create show and draw keyframes" : "Create show")}
              </button>
            </span>
          )}
        </footer>
      </main>
    </div>
  );
}
