"use client";

import { type FormEvent, type ReactNode, useState } from "react";
import {
  BIBLE_KINDS,
  type OlfData,
  type OlfEntry,
  type OlfShow,
  entryName,
  findEntry,
  mediaUrl,
  sheetsOf,
  words,
} from "../lib/shows";
import { olf, useOlfRoute } from "./shows-api";
import { Chips, Field, OlfOnly, Panel, RefThumb, Swatches, VoicePick, fileData } from "./shows-parts";

export type FormFields = { name: string; description: string; palette: string[]; front?: string };
/** One bible edit (`PATCH /olf/entry`, `POST /olf/reference`, `POST /olf/variant`) and its notice. */
export type BibleEdit = (method: "POST" | "PATCH", route: string, body: Record<string, unknown>, notice: (out: Record<string, unknown>) => string) => void;

/** Kinds with a name and a description, and kinds with references (vinci_olf.author, COREPRODUC-682). */
const TEXT_KINDS = ["character", "location", "prop", "voice"];
const REFERENCE_KINDS = ["character", "location", "prop", "style"];

/** What a person edits to change the render inputs of each kind (credits and license are not inputs). */
const EDITS: Record<string, string> = {
  character: "the description, a form or an outfit",
  location: "the description or a variant",
  prop: "the description or a reference",
  voice: "the voice",
  style: "the look, the lenses or the negative list",
  camerawork: "the camera, the prompt words or the avoid words",
};

function plural(count: number, one: string): string {
  return `${count} ${count === 1 ? one : `${one}s`}`;
}

/** Image references with a label: a map key (`eyes` -> Eyes), else the file name. */
function labeled(value: unknown, suffix = ""): { ref: string; label: string }[] {
  const name = (ref: string) =>
    ref.startsWith("asset/") ? "Reference" : words(ref.split("/").pop()?.replace(/\.[^.]+$/, "") || ref);
  if (typeof value === "string") return [{ ref: value, label: `${name(value)}${suffix}` }];
  if (Array.isArray(value)) return value.flatMap((item) => labeled(item, suffix));
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) =>
      typeof item === "string" ? [{ ref: item, label: words(key) }] : labeled(item, suffix),
    );
  }
  return [];
}

/**
 * A bible page (Claude Design, screen 2): the name and description, how much the entry is used, the
 * entry's look on the left, and its looks, links, credit, license and edit impact on the right.
 * A character's sheet can be replaced and a form added; any entry's name, description, references
 * and (a location's) variants can be edited (vinci_olf.author). The top bar names the YAML file.
 */
export function BibleView({
  show,
  id,
  onOpenEntry,
  onReplaceSheet,
  onAddSheet,
  onAddForm,
  onSetVoice,
  onCloneVoice,
  onEdit,
  onSaveSource,
  library = [],
}: {
  show: OlfShow;
  id: string;
  onOpenEntry: (id: string) => void;
  /** Replace one sheet in place (`sheet`: its image; the primary when null). */
  onReplaceSheet: (data: string, sheet: string | null) => void;
  /** Add a sheet; resolves to its image name. */
  onAddSheet: (data: string) => Promise<string | null>;
  onAddForm: (fields: FormFields) => void;
  /** Set the ElevenLabs voice the character speaks in (`POST /olf/voice`). */
  onSetVoice: (voiceId: string, name: string) => void;
  /** Clone a voice from a recording, after the person's consent (`POST /olf/voice/clone`). */
  onCloneVoice: (name: string, sample: string) => Promise<boolean>;
  /** A name, description, reference or variant edit; the server writes it and the page reloads. */
  onEdit: BibleEdit;
  /** Save the entry's YAML as written (`PUT /olf/source`); resolves to false when refused. */
  onSaveSource: (text: string) => Promise<boolean>;
  /** The camerawork library: a template that is a copy says when the library has a newer version. */
  library?: readonly OlfData[];
}) {
  const [active, setActive] = useState(""); // the sheet shown (its image); "" is the primary
  const [editing, setEditing] = useState(false); // the name and description form is open
  const canRef = useOlfRoute("/olf/reference"); // a host on an older engine has no bible edits
  const [yaml, setYaml] = useState<{ file: string; text: string } | null>(null); // Edit YAML is open
  const [yamlError, setYamlError] = useState("");
  const entry = id === "style" ? show.style : findEntry(show, id);
  if (!entry) return <p className="muted">This bible entry is not in the show. Reload, or pick another entry.</p>;
  const kind = id === "style" ? "style" : BIBLE_KINDS.find((row) => show.bible[row.id]?.includes(entry))?.id || "prop";
  const data = entry.data;
  const look = (data.look || {}) as OlfData;
  const sheets = kind === "character" ? sheetsOf(entry) : [];
  const current = sheets.find((sheet) => sheet.image === active) || sheets[0];
  const episodes = new Set(entry.used_in.map((shot) => shot.split("/")[0])).size;
  const grid = (items: { ref: string; label: string }[]) => <RefGrid show={show} entry={entry} items={items} />;
  const voice = typeof data.voice === "string" ? findEntry(show, data.voice) : undefined;
  const voiceId = String(((voice?.data.extensions as OlfData | undefined)?.elevenlabs as OlfData | undefined)?.voice_id || "");
  const links = [
    ...(data.voice ? [data.voice] : []),
    ...((data.accessories as string[] | undefined) || []),
    ...show.bible.character.filter((row) => row.data.voice === entry.id).map((row) => row.id),
  ];
  return (
    <section data-testid="shows-entry" data-entry={entry.id}>
      <header className="olf-head">
        {editing ? (
          <EntryForm
            name={String(data.name || "")}
            description={String(data.description || "")}
            onCancel={() => setEditing(false)}
            onSave={(fields) => {
              setEditing(false);
              onEdit("PATCH", "/entry", { entry: id, ...fields }, () => `Saved ${fields.name || entryName(entry)}`);
            }}
          />
        ) : (
          <div>
            <h1>{kind === "style" ? String(look.medium || "Style") : entryName(entry)}</h1>
            <p className="muted">{String(data.description || data.intent || look.grade || "")}</p>
          </div>
        )}
        <span className="olf-head-actions">
          <span className="olf-usage" data-testid="entry-usage">
            Used in {plural(entry.used_in.length, "shot")} · {plural(episodes, "episode")}
          </span>
          {TEXT_KINDS.includes(kind) && !editing && !yaml ? (
            <OlfOnly path="/olf/entry">
              <button type="button" className="ghost" onClick={() => setEditing(true)} data-testid="edit-entry">
                Edit
              </button>
            </OlfOnly>
          ) : null}
          {!yaml && !editing ? (
            <OlfOnly path="/olf/source">
              <button
                type="button"
                className="ghost"
                data-testid="edit-yaml"
                title="Edit any field of this entry's file. A change that makes the show invalid is not saved."
                onClick={() =>
                  olf<{ file: string; text: string }>(`/source?path=${encodeURIComponent(show.path)}&entry=${encodeURIComponent(id)}`).then(
                    (source) => {
                      setYamlError("");
                      setYaml(source);
                    },
                    (err) => setYamlError(err instanceof Error ? err.message : String(err)),
                  )
                }
              >
                Edit YAML
              </button>
            </OlfOnly>
          ) : null}
          {kind === "character" ? (
            // The new image keeps the sheet's file name, so the character file does not change.
            <FilePick
              className="ghost olf-file-btn"
              testId="replace-sheet"
              title={current ? `Replace ${current.image}` : "Add a sheet"}
              label={current ? "Replace sheet" : "Add a sheet"}
              onPick={(file) => onReplaceSheet(file, current && current !== sheets[0] ? current.image : null)}
            />
          ) : null}
        </span>
      </header>
      {yamlError ? <p className="olf-error">{yamlError}</p> : null}
      {yaml ? (
        <YamlEditor
          source={yaml}
          onCancel={() => setYaml(null)}
          onSave={async (text) => {
            if (await onSaveSource(text)) setYaml(null); // a refusal keeps the text; the notice says why
          }}
        />
      ) : null}
      <div className="olf-two" style={yaml ? { display: "none" } : undefined}>
        <div className="olf-col">
          {kind === "character" && current?.file ? (
            <SheetPanel
              show={show}
              sheets={sheets}
              current={current}
              onPick={setActive}
              onAddSheet={async (data) => {
                const name = await onAddSheet(data);
                if (name) setActive(name);
              }}
            >
              {data.details || data.textures ? (
                <>
                  <h4 className="olf-subhead">Details</h4>
                  {grid([...labeled(data.details), ...labeled(data.textures, " texture")])}
                </>
              ) : null}
            </SheetPanel>
          ) : null}
          {kind === "style" ? (
            <Panel title="Look">
              <Field label="Palette">
                <Swatches colors={look.palette} large />
              </Field>
              <div className="olf-grid2">
                <Field label="Medium">{String(look.medium || "—")}</Field>
                <Field label="Grain">{String(look.grain || "—")}</Field>
              </div>
              <Field label="Grade">{String(look.grade || "—")}</Field>
            </Panel>
          ) : null}
          {kind === "voice" ? (
            <Panel title="Details">
              {data.sample && entry.files[data.sample] ? (
                <Field label="Sample">
                  <audio controls src={mediaUrl(show, entry.files[data.sample])} />
                </Field>
              ) : null}
              <Field label="Providers">{data.extensions ? Object.keys(data.extensions).join(", ") : "None"}</Field>
            </Panel>
          ) : null}
          {kind === "camerawork" ? <CameraworkPanels data={data} library={library} /> : null}
          {data.references || kind === "prop" || (canRef && REFERENCE_KINDS.includes(kind)) ? (
            <Panel
              title="References"
              testId="entry-references"
              aside={
                canRef && REFERENCE_KINDS.includes(kind) ? (
                  <FilePick
                    testId="add-reference"
                    label="+ Reference"
                    onPick={(file, name) => onEdit("POST", "/reference", { entry: id, data: file, label: name }, (o) => `Added ${o.reference}`)}
                  />
                ) : undefined
              }
            >
              {data.references ? (
                <RefGrid
                  show={show}
                  entry={entry}
                  items={labeled(data.references)}
                  onReplace={canRef ? (ref, file) => onEdit("POST", "/reference", { entry: id, ref, data: file }, () => `Replaced ${ref}. Takes that used it are stale.`) : undefined}
                  onRemove={canRef ? (ref) => onEdit("POST", "/reference", { entry: id, ref, remove: true }, () => `Removed ${ref}`) : undefined}
                />
              ) : (
                <p className="muted olf-small-text">
                  {kind === "prop" ? "No reference images. The engine draws this prop from its description." : "No reference images."}
                </p>
              )}
            </Panel>
          ) : null}
        </div>

        <div className="olf-col">
          {data.forms || kind === "character" ? (
            <Panel title="Forms" aside="Whole-body looks">
              {Object.entries((data.forms || {}) as Record<string, OlfData>).map(([name, form]) => (
                <div key={name} className="olf-look" data-testid="entry-form">
                  {form.views?.front ? (
                    <RefThumb show={show} file={entry.files[String(form.views.front)] || null} height={80} />
                  ) : (
                    // No front view: renders send the character's whole sheets for this form.
                    <span className="ref-thumb ref-missing" style={{ height: 80, minWidth: 80 }} title="No front view: renders send the whole sheets">
                      sheet
                    </span>
                  )}
                  <div>
                    <div className="olf-look-line">
                      <b>{name}</b>
                      <span className="muted">{plural(entry.forms_usage?.[name] || 0, "shot")}</span>
                    </div>
                    <p className="olf-small-text">{form.description}</p>
                    <Swatches colors={form.palette} />
                  </div>
                </div>
              ))}
              {kind === "character" ? <AddForm taken={Object.keys(data.forms || {})} onAdd={onAddForm} /> : null}
            </Panel>
          ) : null}
          {data.outfits ? (
            <Panel title="Outfits">
              {Object.entries(data.outfits as Record<string, OlfData>).map(([name, outfit]) => (
                <div key={name} className="olf-kv">
                  <b>{name}</b>
                  <span>{outfit.description}</span>
                </div>
              ))}
            </Panel>
          ) : null}
          {data.variants || (kind === "location" && canRef) ? (
            <Panel title="Variants" aside="A scene picks one" testId="entry-variants">
              <Chips items={data.variants} />
              {kind === "location" ? (
                <OlfOnly path="/olf/variant">
                  <VariantForm
                    variants={(data.variants as string[] | undefined) || []}
                    onAdd={(name) => onEdit("POST", "/variant", { entry: id, name }, () => `Added variant ${name}`)}
                    onRemove={(name) => onEdit("POST", "/variant", { entry: id, name, remove: true }, () => `Removed variant ${name}`)}
                  />
                </OlfOnly>
              ) : null}
            </Panel>
          ) : null}
          {kind === "camerawork" ? (
            <Panel title="Words for the model" aside="Slots {a}, {b}, {c}: the shot's characters">
              {data.keyframe ? <Field label="Keyframe">{String(data.keyframe)}</Field> : null}
              {data.prompt ? <Field label={data.camera?.render === "engine" ? "Video (for a shot that sets render: model)" : "Video"}>{String(data.prompt)}</Field> : null}
              {data.avoid ? (
                <Field label="Avoid">
                  <Chips items={data.avoid} />
                </Field>
              ) : null}
              {!data.keyframe && !data.prompt && !data.avoid ? <span className="muted olf-small-text">No words: the camera fields say it all.</span> : null}
            </Panel>
          ) : null}
          {kind === "style" ? (
            <>
              <Panel title="Lenses" aside="A shot may use only these">
                <Chips items={data.lenses} />
              </Panel>
              <Panel title="Negative" aside="Never in a frame">
                <Chips items={data.negative} />
              </Panel>
            </>
          ) : null}
          <Panel title="Linked">
            {kind === "character" ? (
              <OlfOnly path="/olf/voices">
                <div className="olf-field">
                  <span className="olf-label">Voice</span>
                  {/* key: a new clone is a new voice ID, so the menu loads the account's list again */}
                  <VoicePick key={voiceId} value={voiceId} onPick={onSetVoice} testId="voice-pick">
                    <OlfOnly path="/olf/voice/clone">
                      <CloneVoice who={entryName(entry)} onClone={onCloneVoice} />
                    </OlfOnly>
                  </VoicePick>
                </div>
              </OlfOnly>
            ) : null}
            {links.length ? (
              <span className="olf-chips">
                {links.map((ref) => (
                  <button key={ref} type="button" className="chip" onClick={() => onOpenEntry(ref)} title={entryName(findEntry(show, ref), ref)}>
                    {ref}
                  </button>
                ))}
              </span>
            ) : (
              <span className="muted olf-small-text">No links.</span>
            )}
            {Object.entries((data.credits || {}) as Record<string, string>).map(([role, who]) => (
              <div key={role} className="olf-kv">
                <span className="muted">{role === "design" ? "Design credit" : words(role)}</span>
                <span>{who}</span>
              </div>
            ))}
            {kind !== "style" && Object.keys(entry.files).length ? <LicenseRow entry={entry} show={show} /> : null}
            <div className={`olf-impact${entry.impact ? " is-stale" : ""}`} data-testid="entry-impact">
              {entry.impact
                ? `Editing ${EDITS[kind]} makes ${plural(entry.impact, "take")} stale. Credits and license edits do not.`
                : "No takes use this entry yet, so an edit makes nothing stale."}
            </div>
          </Panel>
        </div>
      </div>
    </section>
  );
}

/**
 * A camerawork template (COREPRODUC-564): what the camera does, and what the template suits. A
 * shot names it in `camera.template`; the template fills the camera fields that the shot leaves out.
 */
function CameraworkPanels({ data, library }: { data: OlfData; library: readonly OlfData[] }) {
  const camera = (data.camera || {}) as OlfData;
  const timing = (data.timing || {}) as OlfData;
  const rules = Object.entries((data.rules || {}) as Record<string, unknown>).map(([rule, value]) => `${words(rule)}: ${String(value)}`);
  const [origin, version] = String(data.source || "").split("@");
  const newer = library.find((row) => row.id === origin && Number(row.version) > Number(version));
  const slots = data.slots as string[] | undefined;
  return (
    <>
      <Panel title="Camera" aside={[data.notation, words(data.family)].filter(Boolean).join(" · ")}>
        <div className="olf-grid2" data-testid="camerawork-camera">
          <Field label="Render">{camera.render === "engine" ? "Engine move · $0" : "Model"}</Field>
          <Field label="Move">{[camera.move || "—", camera.direction].filter(Boolean).join(" ")}</Field>
          <Field label="Amount">{String(camera.amount ?? "—")}</Field>
          <Field label="Ease">{String(camera.ease || "—")}</Field>
          <Field label="Hold at start">{String(camera.hold_start ?? "—")}</Field>
          <Field label="Hold at end">{String(camera.hold_end ?? "—")}</Field>
        </div>
      </Panel>
      <Panel title="Suits" aside="A shot outside these gets a warning">
        <Field label="Length">
          {[`${timing.default || "—"} by default`, timing.min ? `from ${timing.min}` : null, timing.max ? `to ${timing.max}` : null].filter(Boolean).join(", ")}
        </Field>
        <Field label="Framing">
          <Chips items={data.framing} />
        </Field>
        <Field label="Cast">{slots === undefined ? "Any" : slots.length ? `Slots ${slots.join(", ")}` : "None: background only"}</Field>
        {rules.length ? (
          <Field label="Rules">
            <Chips items={rules} />
          </Field>
        ) : null}
      </Panel>
      <Panel title="Source">
        <span className="olf-small-text" data-testid="camerawork-source">
          {origin ? `A copy of ${data.source} from the camerawork library (CC0). The show owns it: an edit here changes this show only.` : "A template of this show."}
          {newer ? ` The library now has version ${newer.version}.` : ""}
        </span>
      </Panel>
    </>
  );
}

/**
 * The character's sheets (design: "Character sheet"): tabs when there is more than one, and
 * "+ Sheet". Each whole sheet is a reference image; OLF has no crops (decision 2026-11-09).
 */
function SheetPanel({
  show,
  sheets,
  current,
  onPick,
  onAddSheet,
  children,
}: {
  show: OlfShow;
  sheets: ReturnType<typeof sheetsOf>;
  current: ReturnType<typeof sheetsOf>[number];
  onPick: (image: string) => void;
  onAddSheet: (data: string) => void;
  children?: ReactNode;
}) {
  return (
    <Panel
      title="Character sheet"
      aside={
        <>
          <span className="muted">{plural(sheets.length, "sheet")}</span>
          <FilePick testId="add-sheet" label="+ Sheet" onPick={(file) => onAddSheet(file)} />
        </>
      }
    >
      {sheets.length > 1 ? (
        <div className="olf-tabs" role="tablist" aria-label="Sheets">
          {sheets.map((sheet) => (
            <button
              key={sheet.image}
              type="button"
              role="tab"
              aria-selected={sheet.image === current.image}
              onClick={() => onPick(sheet.image)}
              data-testid="sheet-tab"
            >
              {sheet.image}
            </button>
          ))}
        </div>
      ) : null}
      <figure className="sheet-view" data-testid="sheet-view">
        <div className="sheet-frame">
          <img src={mediaUrl(show, current.file || "")} alt={`Character sheet ${current.image}`} draggable={false} />
        </div>
      </figure>
      <p className="muted olf-small-text">The whole sheet is the character reference. Form views and details are separate files.</p>
      {children}
    </Panel>
  );
}

/**
 * Design: Clone from sample (ElevenLabs Instant Voice Cloning). The person picks a recording and
 * confirms the right to the voice and the speaker's consent before anything is sent.
 */
function CloneVoice({ who, onClone }: { who: string; onClone: (name: string, sample: string) => Promise<boolean> }) {
  const [open, setOpen] = useState(false);
  const [sample, setSample] = useState<{ data: string; file: string } | null>(null);
  const [name, setName] = useState(`${who}'s voice`);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  // Consent covers one clone: every close (Cancel or a made clone) drops the recording and the tick.
  const close = () => {
    setOpen(false);
    setSample(null);
    setConsent(false);
  };
  if (!open) {
    return (
      <button type="button" className="ghost olf-small olf-clone-open" onClick={() => setOpen(true)} data-testid="voice-clone-open">
        Clone from sample
      </button>
    );
  }
  return (
    <form
      className="olf-clone"
      data-testid="voice-clone"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!sample || !consent) return;
        setBusy(true);
        const done = await onClone(name, sample.data); // never rejects: a failure is a notice
        setBusy(false);
        if (done) close();
      }}
    >
      <label className="ghost olf-file-btn olf-small">
        {sample ? sample.file : "Pick a recording (MP3, WAV, OGG or FLAC)"}
        <input
          type="file"
          accept="audio/mpeg,audio/wav,audio/x-wav,audio/ogg,audio/flac"
          hidden
          onChange={async (event) => {
            const file = event.currentTarget.files?.[0];
            if (file) setSample({ data: await fileData(file), file: file.name });
          }}
        />
      </label>
      <input className="olf-input" value={name} onChange={(event) => setName(event.target.value)} aria-label="Voice name" />
      <label className="olf-check">
        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} data-testid="voice-clone-consent" />
        I have the right to use this voice, and the speaker agreed to the clone.
      </label>
      <p className="muted olf-small-text">ElevenLabs makes an instant clone from at least 10 s of clean speech (1 to 2 minutes is best). It takes one of your account&apos;s voice slots.</p>
      <span className="olf-row">
        <button type="submit" className="run olf-small" disabled={!sample || !consent || busy} data-testid="voice-clone-run">
          {busy ? "Cloning…" : "Clone voice"}
        </button>
        <button type="button" className="ghost olf-small" onClick={close} data-testid="voice-clone-cancel">
          Cancel
        </button>
      </span>
    </form>
  );
}

/** Design "+ Form": a name, a description, palette colors and a front view image. */
function AddForm({ taken, onAdd }: { taken: string[]; onAdd: (fields: FormFields) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [palette, setPalette] = useState("");
  const [front, setFront] = useState<string | undefined>();
  const slug = /^[a-z0-9-]+$/.test(name) && !taken.includes(name);
  if (!open) {
    return (
      <button type="button" className="olf-add-row" onClick={() => setOpen(true)} data-testid="add-form">
        + Form
      </button>
    );
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    const colors = palette.split(/[\s,]+/).filter(Boolean);
    onAdd({ name, description: description.trim(), palette: colors, front });
    setOpen(false);
  }
  return (
    <form className="olf-add-form" onSubmit={submit} data-testid="add-form-panel">
      <input className="olf-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="name, for example storm" aria-label="Form name" autoFocus />
      <textarea className="olf-input olf-textarea" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Hair, palette, motifs: what changes in this form" aria-label="Form description" />
      <input className="olf-input" value={palette} onChange={(e) => setPalette(e.target.value)} placeholder="#555566, #223344" aria-label="Palette colors" />
      <label className="ghost olf-file-btn olf-small">
        {front ? "Front view picked" : "Front view image"}
        <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={async (e) => { const file = e.currentTarget.files?.[0]; if (file) setFront(await fileData(file)); }} />
      </label>
      <div className="olf-row">
        <button type="submit" className="run olf-small olf-grow" disabled={!slug || !description.trim()}>
          Add form
        </button>
        <button type="button" className="ghost olf-small" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {name && !slug ? <p className="olf-error olf-small-text">Use lowercase letters, digits and dashes, and a new name.</p> : null}
    </form>
  );
}

/** Edit YAML (COREPRODUC-683): the entry's file as written, saved only if the show stays as valid. */
function YamlEditor({ source, onSave, onCancel }: { source: { file: string; text: string }; onSave: (text: string) => Promise<void>; onCancel: () => void }) {
  const [text, setText] = useState(source.text);
  const [busy, setBusy] = useState(false);
  return (
    <Panel title="Edit YAML" aside={<span className="olf-yaml-file">{source.file}</span>} testId="yaml-editor">
      <textarea
        className="olf-input olf-textarea olf-yaml"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        aria-label={`YAML of ${source.file}`}
        readOnly={busy} // the save sends this text; typing now would be lost when it closes
        rows={Math.min(30, Math.max(10, text.split("\n").length + 2))}
        autoFocus
      />
      <p className="muted olf-small-text">Vinci checks the whole show before it saves. A change that adds an error is not saved, and the notice names the error.</p>
      <div className="olf-row">
        <button
          type="button"
          className="run olf-small"
          disabled={busy || text === source.text}
          onClick={async () => {
            setBusy(true);
            await onSave(text);
            setBusy(false);
          }}
          data-testid="yaml-save"
        >
          {busy ? "Checking…" : "Save"}
        </button>
        <button type="button" className="ghost olf-small" onClick={onCancel} disabled={busy} data-testid="yaml-cancel">
          Cancel
        </button>
      </div>
    </Panel>
  );
}

/** An image file button (a label around a hidden input): `onPick` gets the data URL and the file's name. */
function FilePick({
  label,
  testId,
  title,
  className = "ghost olf-small olf-file-btn",
  onPick,
}: {
  label: string;
  testId: string;
  title?: string;
  className?: string;
  onPick: (data: string, name: string) => void;
}) {
  return (
    <label className={className} data-testid={testId} title={title}>
      {label}
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={async (event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = ""; // the same file can be picked again
          if (file) onPick(await fileData(file), file.name.replace(/\.[^.]+$/, ""));
        }}
      />
    </label>
  );
}

/**
 * Labelled reference images (design: the Details grid of the character sheet). With `onReplace`
 * and `onRemove`, each image gets Replace and Remove; Remove asks once more before it deletes.
 */
function RefGrid({
  show,
  entry,
  items,
  onReplace,
  onRemove,
}: {
  show: OlfShow;
  entry: OlfEntry;
  items: { ref: string; label: string }[];
  onReplace?: (ref: string, data: string) => void;
  onRemove?: (ref: string) => void;
}) {
  const [armed, setArmed] = useState(""); // the reference whose Remove was clicked once
  return (
    <div className="olf-ref-grid">
      {items.map(({ ref, label }) => (
        <figure key={ref} data-testid="entry-reference" data-ref={ref}>
          <RefThumb show={show} file={entry.files[ref] || null} height={96} />
          <figcaption>{label}</figcaption>
          {onReplace && onRemove ? (
            <span className="olf-row olf-ref-actions">
              <FilePick testId="replace-reference" label="Replace" onPick={(data) => onReplace(ref, data)} />
              <button
                type="button"
                className={armed === ref ? "ghost olf-small olf-danger" : "ghost olf-small"}
                onClick={() => (armed === ref ? onRemove(ref) : setArmed(ref))}
                onBlur={() => setArmed("")}
                data-testid="remove-reference"
              >
                {armed === ref ? "Delete file" : "Remove"}
              </button>
            </span>
          ) : null}
        </figure>
      ))}
    </div>
  );
}

/** The name and description of a bible entry, in place of the page title (`PATCH /olf/entry`). */
function EntryForm({
  name: first,
  description: text,
  onSave,
  onCancel,
}: {
  name: string;
  description: string;
  onSave: (fields: { name?: string; description: string }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(first);
  const [description, setDescription] = useState(text);
  function submit(event: FormEvent) {
    event.preventDefault();
    onSave({ ...(name.trim() && name.trim() !== first ? { name: name.trim() } : {}), description: description.trim() });
  }
  return (
    <form className="olf-add-form olf-entry-form" onSubmit={submit} data-testid="entry-edit-form">
      <input className="olf-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" aria-label="Name" />
      <textarea
        className="olf-input olf-textarea"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="What the engine draws: shapes, materials, light"
        aria-label="Description"
        autoFocus
      />
      <div className="olf-row">
        <button type="submit" className="run olf-small" disabled={!description.trim()}>
          Save
        </button>
        <button type="button" className="ghost olf-small" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Design "+ Variant" for a location: a new slug, and Remove for each (a scene that picks one keeps it). */
function VariantForm({ variants, onAdd, onRemove }: { variants: string[]; onAdd: (name: string) => void; onRemove: (name: string) => void }) {
  const [name, setName] = useState("");
  const slug = /^[a-z0-9-]+$/.test(name) && !variants.includes(name);
  return (
    <form
      className="olf-row olf-variant-form"
      onSubmit={(event) => {
        event.preventDefault();
        onAdd(name);
        setName("");
      }}
    >
      <input className="olf-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="new variant" aria-label="New variant" data-testid="variant-name" />
      <button type="submit" className="ghost olf-small" disabled={!slug} data-testid="add-variant">
        + Variant
      </button>
      {variants.length ? (
        <select className="olf-input" value="" onChange={(e) => e.target.value && onRemove(e.target.value)} aria-label="Remove a variant" data-testid="remove-variant">
          <option value="">Remove…</option>
          {variants.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      ) : null}
    </form>
  );
}

/** The lock file's license; before the first render, the project license the engine will copy. */
function LicenseRow({ entry, show }: { entry: OlfEntry; show: OlfShow }) {
  const license = entry.license || show.license;
  const text = license
    ? [license.terms, license.ai_training ? `AI training ${license.ai_training}` : null].filter(Boolean).join(" · ")
    : "None yet: add one to project.yaml";
  return (
    <div className="olf-kv" title={entry.license ? "From the lock file" : "From project.yaml; the engine copies it at the first render"}>
      <span className="muted">License</span>
      <span>
        {text}
        {license && !entry.license ? <span className="muted"> (project default)</span> : null}
      </span>
    </div>
  );
}

/** Validation results; the health pill in the top bar opens this page. */
export function IssuesView({ show }: { show: OlfShow }) {
  return (
    <section data-testid="shows-issues">
      <header className="olf-head">
        <div>
          <h1>{show.issues.length ? "Issues" : "No issues"}</h1>
          <p className="muted">
            Vinci checks every file against the OLF v0.1 schema, then the references, looks, lenses, assets and
            lock file. Fix a file on disk, then reload.
          </p>
        </div>
      </header>
      {show.issues.length ? (
        <ul className="issue-list">
          {show.issues.map((issue, index) => (
            <li key={index} className={issue.level}>
              <b>{issue.level}</b>
              <code>{issue.where}</code>
              <span>{issue.message}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="olf-ok">Valid OLF v0.1. Every reference, asset and hash checks out.</p>
      )}
    </section>
  );
}
