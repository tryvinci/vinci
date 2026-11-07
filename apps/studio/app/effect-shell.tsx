"use client";

import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type ReactNode } from "react";
import {
  STUDIO_APPS,
  appDefaults,
  buildRunPayload,
  defaultAppIdForPage,
  getApp,
  appModelChoices,
  missingAppInputs,
  resolveAppModel,
  type AppInput,
  type EffectPage,
  type StudioApp,
} from "../lib/apps-catalog";
import {
  EFFECT_ASPECT_OPTIONS,
  EFFECT_RESOLUTION_OPTIONS,
  applyEffectParams,
  effectiveAspect,
  filterEffectHistory,
  generateButtonLabel,
  historyOutputIds,
  type EffectRunRow,
} from "../lib/effect-shell";
import { providerMentionInputs, type LibraryItem } from "../lib/library";
import { EffectsGalleryOverlay } from "./effects-gallery-overlay";
import { PromptMention } from "./prompt-mention";
import "./effects-shell.css";
import { AdvancedDisclosure } from "./ui/advanced";
import { plainError } from "./ui/plain-text";

const API = "/vinci-api";

type ModelRow = {
  id: string;
  display_name?: string;
  provider?: string;
  available?: boolean;
  capabilities?: readonly string[];
  pricing?: { amount?: number };
};

type AssetRow = { id: string; mime?: string };

export type EffectShellProps = {
  page: EffectPage;
  appId: string;
  onAppIdChange: (id: string) => void;
  models: ModelRow[];
  /** Doctor provider ids. Compatible models come from modelsFor. */
  connected?: readonly string[];
  liveSpend: boolean;
  runs: EffectRunRow[];
  assets: AssetRow[];
  money: (amount?: number) => string;
  onOpenConnect: () => void;
  onRunComplete?: () => void;
  /** Adapts batch outputs shown in history when page is adapts. */
  adaptOutputIds?: string[];
  adaptsPanel?: ReactNode;
  /** Same @ list as Image, Video, and canvas. */
  library?: readonly LibraryItem[];
};

async function postRun(payload: { skill: string; model_id?: string; inputs: Record<string, unknown> }) {
  const res = await fetch(`${API}/runs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = (await res.json().catch(() => ({}))) as { detail?: string; state?: string; error?: unknown };
  if (!res.ok) throw new Error(body.detail || res.statusText || "Run failed");
  return body as { state?: string; outputs?: string[]; error?: unknown };
}

async function uploadAsset(file: File): Promise<string> {
  const data = new FormData();
  data.append("file", file);
  const res = await fetch(`${API}/assets`, { method: "POST", body: data });
  if (!res.ok) throw new Error(await res.text());
  const asset = (await res.json()) as { id: string };
  if (!asset.id) throw new Error("Upload did not finish. Try the file again.");
  return asset.id;
}

function PresetCard({ app, onChange }: { app: StudioApp; onChange: () => void }) {
  return (
    <div className="effects-preset-card" data-testid="effects-preset-card">
      <div className="apps-thumb effects-preset-thumb" aria-hidden="true">
        <div className={`apps-thumb-art thumb-${app.id}`} />
        <p className="apps-thumb-cat">{app.category}</p>
      </div>
      <div className="effects-preset-copy">
        <strong>{app.name}</strong>
        <p>{app.description}</p>
        <button className="ghost effects-change" type="button" onClick={onChange} data-testid="effects-change">
          Change
        </button>
      </div>
    </div>
  );
}

function HistoryFeed({
  outputIds,
  assets,
  outputKind,
  emptyLabel,
}: {
  outputIds: string[];
  assets: AssetRow[];
  outputKind: StudioApp["output_kind"];
  emptyLabel: string;
}) {
  if (!outputIds.length) {
    return (
      <div className="effects-history-empty" data-testid="effects-history-empty">
        <p>{emptyLabel}</p>
      </div>
    );
  }
  return (
    <div className="effects-history-grid" data-testid="effects-history-grid">
      {outputIds.map((id) => {
        const row = assets.find((a) => a.id === id);
        const mime = row?.mime || "";
        const src = `${API}/assets/${id}/file`;
        return (
          <figure key={id} className="effects-history-item">
            {mime.startsWith("video/") || outputKind === "video" ? (
              <video src={src} controls muted playsInline />
            ) : mime.startsWith("audio/") || outputKind === "audio" ? (
              <audio src={src} controls />
            ) : (
              <img src={src} alt="" />
            )}
          </figure>
        );
      })}
    </div>
  );
}

/**
 * Higgsfield-style Effects shell: preset-driven left panel, per-effect history on the right.
 *
 * Speak, Upscale, and catalog presets share one component; Adapts embeds its batch panel.
 */
export function EffectShell(props: EffectShellProps) {
  const {
    page,
    appId,
    onAppIdChange,
    models,
    connected,
    liveSpend,
    runs,
    assets,
    money,
    onOpenConnect,
    onRunComplete,
    adaptOutputIds = [],
    adaptsPanel,
    library = [],
  } = props;

  const app = getApp(appId) ?? getApp(defaultAppIdForPage(page));
  const [galleryOpen, setGalleryOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string | number>>(() => (app ? appDefaults(app) : {}));
  const [aspect, setAspect] = useState("");
  const [resolution, setResolution] = useState("2K");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sessionOutputs, setSessionOutputs] = useState<string[]>([]);

  useEffect(() => {
    if (!app) return;
    setValues(appDefaults(app));
    setError("");
  }, [app?.id]);

  useEffect(() => {
    const expected = defaultAppIdForPage(page);
    if (page !== "adapts" && appId !== expected && !getApp(appId)) {
      onAppIdChange(expected);
    }
  }, [page, appId, onAppIdChange]);

  const history = useMemo(() => (app ? filterEffectHistory(runs, app) : []), [app, runs]);
  const historyIds = useMemo(() => historyOutputIds(history), [history]);
  const outputIds = useMemo(() => {
    const merged = [...sessionOutputs, ...adaptOutputIds, ...historyIds];
    const seen = new Set<string>();
    return merged.filter((id) => {
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }, [adaptOutputIds, historyIds, sessionOutputs]);

  const generateLabel = app ? generateButtonLabel(app, models, liveSpend, money) : "Generate";
  const modelChoices = useMemo(
    () => (app ? appModelChoices(app, models, connected) : []),
    [app, connected, models],
  );
  const pinnedModel = app ? resolveAppModel(app, models, liveSpend, connected) : undefined;
  const [modelPick, setModelPick] = useState(pinnedModel || "");
  useEffect(() => {
    setModelPick(pinnedModel || modelChoices[0]?.id || "");
  }, [pinnedModel, modelChoices]);

  const setField = useCallback((id: string, value: string | number) => {
    setValues((prev) => ({ ...prev, [id]: value }));
  }, []);

  async function onMedia(fieldId: string, file: File | undefined) {
    if (!file) return;
    setError("");
    try {
      const id = await uploadAsset(file);
      setField(fieldId, id);
    } catch (err) {
      setError(plainError(err));
    }
  }

  async function generate() {
    if (!app || busy || page === "adapts") return;
    const missing = missingAppInputs(app, values);
    if (missing.length) {
      setError(`Add ${missing.join(", ")}, then press Generate.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const picked = modelChoices.find((row) => row.id === modelPick);
      const modelId =
        picked && (picked.provider === "mock" || (picked.available && liveSpend))
          ? picked.id
          : resolveAppModel(app, models, liveSpend, connected);
      const base = buildRunPayload(app, values, modelId);
      const promptText = Object.values(values)
        .filter((v) => typeof v === "string")
        .join(" ");
      const mapped = providerMentionInputs(promptText, library, picked || { id: modelId }, []);
      const payload = {
        ...base,
        inputs: {
          ...applyEffectParams(base.inputs, app, aspect, resolution),
          ...(mapped.image_urls.length ? { image_urls: mapped.image_urls } : {}),
          ...(mapped.soul_id ? { soul_id: mapped.soul_id } : {}),
        },
      };
      const body = await postRun(payload);
      if (body.state !== "completed" || !body.outputs?.[0]) {
        throw new Error(plainError(typeof body.error === "string" ? body.error : ""));
      }
      setSessionOutputs((prev) => [body.outputs![0], ...prev]);
      onRunComplete?.();
    } catch (err) {
      setError(plainError(err));
    } finally {
      setBusy(false);
    }
  }

  function onPickApp(next: StudioApp) {
    onAppIdChange(next.id);
    if (next.category === "audio" && page === "upscale") {
      // Keep rail page; user picked a different effect in-gallery.
    }
  }

  /** One form field. Number fields with min and max render as a slider. */
  function renderField(field: AppInput) {
    return (
      <label key={field.id} htmlFor={`effect-field-${field.id}`}>
        {field.label}
        {field.type === "textarea" ? (
          <PromptMention
            id={`effect-field-${field.id}`}
            testId={`effect-field-${field.id}`}
            mentionTestId="effect-mention"
            value={String(values[field.id] ?? "")}
            placeholder={field.placeholder}
            items={library}
            onChange={(text) => setField(field.id, text)}
          />
        ) : field.type === "select" ? (
          <select
            id={`effect-field-${field.id}`}
            value={String(values[field.id] ?? field.default ?? "")}
            onChange={(ev) => setField(field.id, ev.target.value)}
          >
            {(field.options || []).map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        ) : field.type === "number" && field.min !== undefined && field.max !== undefined ? (
          <span className="range-row">
            <span>{String(values[field.id] ?? field.default ?? 0)}</span>
            <input
              id={`effect-field-${field.id}`}
              data-testid={`effect-field-${field.id}`}
              type="range"
              min={field.min}
              max={field.max}
              value={Number(values[field.id] ?? field.default ?? 0)}
              onChange={(ev) => setField(field.id, Number(ev.target.value))}
            />
          </span>
        ) : field.type === "media" ? (
          <div className={"apps-drop" + (values[field.id] ? " has-file" : "")}>
            {values[field.id] ? (
              <img alt="" src={`${API}/assets/${values[field.id]}/file`} />
            ) : (
              <span>Drop a file, or click to choose one</span>
            )}
            <input
              id={`effect-field-${field.id}`}
              type="file"
              accept="image/*,video/*,audio/*"
              onChange={(ev: ChangeEvent<HTMLInputElement>) => void onMedia(field.id, ev.target.files?.[0])}
            />
          </div>
        ) : (
          <input
            id={`effect-field-${field.id}`}
            type="text"
            value={String(values[field.id] ?? "")}
            placeholder={field.placeholder}
            onChange={(ev) => setField(field.id, ev.target.value)}
          />
        )}
      </label>
    );
  }

  if (!app) {
    return <p className="apps-empty">This effect is missing. Press Change and pick another.</p>;
  }

  const cardApp =
    page === "adapts"
      ? { ...app, id: "adapts", name: "Adapts", description: "Resize one still into the ad sizes you pick." }
      : app;

  return (
    <div className="effects-shell" data-testid="effects-shell" data-page={page} data-app={app.id}>
      <EffectsGalleryOverlay open={galleryOpen} onClose={() => setGalleryOpen(false)} onPick={onPickApp} />
      <aside className="effects-panel" aria-label="Effect controls">
        <PresetCard app={cardApp} onChange={() => setGalleryOpen(true)} />
        {page === "adapts" && adaptsPanel ? (
          <div className="effects-adapts-slot" data-testid="effects-adapts-panel">
            {adaptsPanel}
          </div>
        ) : (
          <form
            className="effects-form apps-form"
            onSubmit={(ev) => {
              ev.preventDefault();
              void generate();
            }}
          >
            {app.inputs.filter((field) => !field.advanced).map(renderField)}
            {modelChoices.length ? (
              <label htmlFor="effect-model">
                Model
                <select
                  id="effect-model"
                  data-testid="effect-model"
                  value={modelPick}
                  onChange={(ev) => setModelPick(ev.target.value)}
                >
                  {modelChoices.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.display_name || row.id}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <AdvancedDisclosure testId="effects-advanced">
              {app.inputs.filter((field) => field.advanced).map(renderField)}
              {app.params.aspect_ratio !== undefined || app.output_kind !== "audio" ? (
                <div className="effects-tiles">
                  <p className="effects-tiles-label">Aspect</p>
                  <div className="effects-tile-row">
                    {EFFECT_ASPECT_OPTIONS.map((row) => (
                      <button
                        key={row}
                        type="button"
                        className={effectiveAspect(app, aspect) === row ? "on" : ""}
                        onClick={() => setAspect(row)}
                      >
                        {row}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {app.output_kind !== "audio" ? (
                <div className="effects-tiles">
                  <p className="effects-tiles-label">Resolution</p>
                  <div className="effects-tile-row">
                    {EFFECT_RESOLUTION_OPTIONS.map((row) => (
                      <button key={row} type="button" className={resolution === row ? "on" : ""} onClick={() => setResolution(row)}>
                        {row}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </AdvancedDisclosure>
            {error ? <p className="effects-error">{error}</p> : null}
            <div className="apps-actions">
              <button className="run" type="submit" disabled={busy} data-testid="effects-generate">
                {busy ? "Generating…" : generateLabel}
              </button>
              {!liveSpend ? (
                <button className="ghost" type="button" onClick={onOpenConnect}>
                  Connect a key
                </button>
              ) : null}
            </div>
          </form>
        )}
      </aside>
      <section className="effects-history" aria-label="Effect history">
        <header className="effects-history-head">
          <h2>History</h2>
          <p className="muted">{app.name}</p>
        </header>
        <HistoryFeed
          outputIds={outputIds}
          assets={assets}
          outputKind={app.output_kind}
          emptyLabel={page === "adapts" ? "Nothing here yet. Set the sizes, then press Run Adapts." : "Nothing here yet. Fill in the form, then press Generate."}
        />
      </section>
    </div>
  );
}

export { STUDIO_APPS, defaultAppIdForPage, getApp };
