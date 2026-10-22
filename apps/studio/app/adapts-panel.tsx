"use client";

import type { RefObject } from "react";
import type { AdaptPresetRow, AdaptTarget, BatchStatus } from "./adapt-ui-shared";
import { byteCapLabel, engineLabel, formatBytes, groupPresets, groupTitle, sourceOf } from "./adapt-ui-shared";

type PresetDraft = {
  label: string;
  platform: string;
  width: string;
  height: string;
  kb: string;
  left: string;
  right: string;
  top: string;
  bottom: string;
};

type Props = {
  apiBase: string;
  liveSpend: boolean;
  busy: boolean;
  adaptSourceId: string | null;
  lastStill: string | null;
  adaptPartnerOnly: boolean;
  adaptLayout: "fit_pad_crop" | "ai_extend";
  adaptFit: "fit" | "pad" | "crop";
  adaptTargets: AdaptTarget[];
  adaptPresetChoices: AdaptPresetRow[];
  adaptNote: string;
  adaptEstimateUsd: number | null;
  batch: BatchStatus | null;
  showSafe: boolean;
  presetFormOpen: boolean;
  presetDraft: PresetDraft;
  money: (n: number | undefined) => string;
  onPartnerOnlyChange: (partnerOnly: boolean) => void;
  onLayoutChange: (layout: "fit_pad_crop" | "ai_extend") => void;
  onFitChange: (fit: "fit" | "pad" | "crop") => void;
  onTargetsChange: (rows: AdaptTarget[]) => void;
  onUseLastStill: () => void;
  onEstimate: () => void;
  onRun: () => void;
  onOpenFlow: () => void;
  onToggleSafe: () => void;
  onTogglePresetForm: () => void;
  onDraftChange: (draft: PresetDraft) => void;
  onCreatePreset: () => void;
  onDeletePreset: (id: string) => void;
  fileInputRef: RefObject<HTMLInputElement | null>;
};

export function AdaptsPanel(props: Props) {
  const engine = engineLabel(props.adaptLayout, props.liveSpend);
  const groups = groupPresets(props.adaptPresetChoices);
  const checks = props.batch?.items?.[0]?.outputs || [];
  const bundleHref = props.batch?.batch_id
    ? `${props.apiBase}/adapts/batch/${props.batch.batch_id}/bundle.zip`
    : "";

  return (
    <div className="adapt-studio" id="adapt-panel">
      <header className="adapt-head">
        <div>
          <p className="eyebrow">Image › Adapts</p>
          <h2>Exports</h2>
          <p className="muted adapt-note">
            Partner presets. Fit/pad/crop is local ffmpeg. Human-review advisories are guidance, not automatic compliance.
          </p>
        </div>
        <div className="adapt-head-actions">
          <span className={engine.real ? "adapt-pill adapt-pill-real" : "adapt-pill adapt-pill-mock"}>{engine.text}</span>
          <button className="ghost" type="button" onClick={props.onOpenFlow}>
            Flow
          </button>
        </div>
      </header>

      <div className="adapt-layout">
        <section className="adapt-col adapt-col-source">
          <h3>Source</h3>
          <div className="adapt-source-frame">
            {props.adaptSourceId ? (
              <img alt="Source creative" src={`${props.apiBase}/assets/${props.adaptSourceId}/file`} />
            ) : (
              <div className="adapt-source-empty">
                <button className="run" type="button" onClick={() => props.fileInputRef.current?.click()}>
                  Upload
                </button>
              </div>
            )}
          </div>
          <div className="adapt-source-actions">
            <button className="ghost" type="button" onClick={() => props.fileInputRef.current?.click()}>
              Replace
            </button>
            {props.lastStill ? (
              <button className="ghost" type="button" onClick={props.onUseLastStill}>
                Last still
              </button>
            ) : null}
          </div>
          <h3 className="adapt-subhead">Presets</h3>
          <div className="adapt-groups" id="adapt-preset-groups">
            {groups.map((group, index) => (
              <div key={group.partner} className="adapt-group">
                <h4>{groupTitle(group, index)}</h4>
                <ul>
                  {group.rows.map((preset) => {
                    const source = sourceOf(preset);
                    const cap = byteCapLabel(preset);
                    return (
                      <li key={preset.id}>
                        <span>
                          {preset.label}
                          <em className={"adapt-source adapt-source-" + source}>{source}</em>
                          {cap ? <em className="adapt-cap">{cap}</em> : null}
                        </span>
                        {source === "custom" ? (
                          <button className="ghost" type="button" onClick={() => props.onDeletePreset(preset.id)}>
                            Delete
                          </button>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
          <button className="ghost" id="adapt-add-preset" type="button" onClick={props.onTogglePresetForm}>
            Add preset
          </button>
          {props.presetFormOpen ? (
            <form
              className="adapt-preset-form"
              id="adapt-preset-form"
              onSubmit={(ev) => {
                ev.preventDefault();
                props.onCreatePreset();
              }}
            >
              <label>
                Label
                <input
                  value={props.presetDraft.label}
                  onChange={(ev) => props.onDraftChange({ ...props.presetDraft, label: ev.target.value })}
                />
              </label>
              <label>
                Platform
                <input
                  value={props.presetDraft.platform}
                  onChange={(ev) => props.onDraftChange({ ...props.presetDraft, platform: ev.target.value })}
                />
              </label>
              <div className="adapt-form-grid">
                <label>
                  Width
                  <input
                    inputMode="numeric"
                    value={props.presetDraft.width}
                    onChange={(ev) => props.onDraftChange({ ...props.presetDraft, width: ev.target.value })}
                  />
                </label>
                <label>
                  Height
                  <input
                    inputMode="numeric"
                    value={props.presetDraft.height}
                    onChange={(ev) => props.onDraftChange({ ...props.presetDraft, height: ev.target.value })}
                  />
                </label>
                <label>
                  KB cap
                  <input
                    inputMode="decimal"
                    placeholder="optional"
                    value={props.presetDraft.kb}
                    onChange={(ev) => props.onDraftChange({ ...props.presetDraft, kb: ev.target.value })}
                  />
                </label>
              </div>
              <p className="muted">Safe-area margins (px, optional)</p>
              <div className="adapt-form-grid">
                {(["left", "right", "top", "bottom"] as const).map((edge) => (
                  <label key={edge}>
                    {edge}
                    <input
                      inputMode="numeric"
                      value={props.presetDraft[edge]}
                      onChange={(ev) => props.onDraftChange({ ...props.presetDraft, [edge]: ev.target.value })}
                    />
                  </label>
                ))}
              </div>
              <button className="run" type="submit">
                Save preset
              </button>
            </form>
          ) : null}
        </section>

        <section className="adapt-col adapt-col-controls">
          <h3>Settings</h3>
          <label>Presets</label>
          <select
            value={props.adaptPartnerOnly ? "partner" : "all"}
            onChange={(ev) => props.onPartnerOnlyChange(ev.target.value === "partner")}
          >
            <option value="partner">Partner presets</option>
            <option value="all">All</option>
          </select>

          <label>Layout</label>
          <select
            id="adapt-layout"
            value={props.adaptLayout}
            onChange={(ev) => props.onLayoutChange(ev.target.value as "fit_pad_crop" | "ai_extend")}
          >
            <option value="fit_pad_crop">Fit / pad / crop</option>
            <option value="ai_extend">AI extend</option>
          </select>

          {props.adaptLayout === "fit_pad_crop" ? (
            <>
              <label>Fit</label>
              <select
                value={props.adaptFit}
                onChange={(ev) => props.onFitChange(ev.target.value as "fit" | "pad" | "crop")}
              >
                <option value="fit">Fit</option>
                <option value="pad">Pad</option>
                <option value="crop">Crop</option>
              </select>
            </>
          ) : null}

          <h4 className="adapt-subhead">Targets</h4>
          <div id="adapt-targets" className="adapt-target-list">
            {props.adaptTargets.map((row, i) => {
              const preset = props.adaptPresetChoices.find((item) => item.id === row.preset_id);
              return (
                <div key={i} className="adapt-target-card">
                  <label>Target {i + 1}</label>
                  <select
                    value={row.preset_id || ""}
                    onChange={(ev) => {
                      const val = ev.target.value;
                      const next = props.adaptTargets.slice();
                      next[i] = val ? { preset_id: val } : { width: 1080, height: 1080 };
                      props.onTargetsChange(next);
                    }}
                  >
                    <option value="">Custom…</option>
                    {groups.map((group, index) => (
                      <optgroup key={group.partner} label={groupTitle(group, index)}>
                        {group.rows.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.label}
                            {byteCapLabel(item) ? ` · ${byteCapLabel(item)}` : ""}
                            {` · ${sourceOf(item)}`}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                  {preset ? (
                    <p className="muted adapt-target-meta" data-safe={i}>
                      {preset.width}×{preset.height}
                      {byteCapLabel(preset) ? ` · ${byteCapLabel(preset)}` : ""}
                      {preset.safe_rect ? ` · margins ${preset.safe_rect.left}/${preset.safe_rect.right}px` : ""}
                      {` · ${sourceOf(preset)}`}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
          <button
            className="ghost"
            id="adapt-add-target"
            type="button"
            onClick={() =>
              props.onTargetsChange([
                ...props.adaptTargets,
                { preset_id: props.adaptPresetChoices[0]?.id || "instagram_feed" },
              ])
            }
          >
            + Target
          </button>

          {props.adaptNote ? (
            <p className="muted adapt-note" id="adapt-safe">
              {props.adaptNote}
            </p>
          ) : (
            <p className="muted adapt-note" id="adapt-safe">
              Safe-area overlay and export byte caps validate on run.
            </p>
          )}

          <div className="adapt-run-row">
            <button className="ghost" id="adapt-estimate" type="button" onClick={props.onEstimate}>
              Estimate
            </button>
            <button className="run" id="adapt-run" type="button" disabled={props.busy} onClick={props.onRun}>
              <span>{props.busy ? "Running…" : "Run Adapts"}</span>
              <span id="adapt-est-btn">{props.adaptEstimateUsd == null ? "$—" : props.money(props.adaptEstimateUsd)}</span>
            </button>
          </div>
          <p className="adapt-status" id="adapt-status">
            {props.busy ? "Running…" : props.batch ? `Done. ${checks.length} export${checks.length === 1 ? "" : "s"}.` : ""}
          </p>
          {props.batch ? (
            <section className="adapt-batch" id="adapt-batch">
              <header>
                <h3>Batch</h3>
                {bundleHref ? (
                  <a className="ghost adapt-bundle" id="adapt-bundle" href={bundleHref}>
                    bundle.zip
                  </a>
                ) : null}
              </header>
              <ul>
                {props.batch.items.map((item) => (
                  <li key={item.index} className={"adapt-batch-row is-" + item.status}>
                    <span>Item {item.index + 1}</span>
                    <strong>{item.status}</strong>
                    {item.error ? <em>{item.error}</em> : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {checks.length ? (
            <section className="adapt-outputs" id="adapt-results">
              <header>
                <h3>Results</h3>
                <button className="ghost" type="button" onClick={props.onToggleSafe}>
                  {props.showSafe ? "Hide safe area" : "Show safe area"}
                </button>
              </header>
              <div className="adapt-output-grid">
                {checks.map((check) => {
                  const preset = props.adaptPresetChoices.find((row) => row.id === check.preset_id);
                  const margins = check.safe_area?.margins_px;
                  const cap = check.byte_cap;
                  return (
                    <article key={check.asset_id + check.preset_id} className="adapt-output-card">
                      <header>
                        <strong>{preset?.label || check.preset_id}</strong>
                        {cap ? (
                          <span className={cap.pass ? "adapt-bytes ok" : "adapt-bytes bad"}>
                            {formatBytes(cap.actual_bytes)} / {formatBytes(cap.max_bytes)}
                          </span>
                        ) : null}
                      </header>
                      <div className="adapt-pixel-frame">
                        <div
                          className="adapt-pixel-stage"
                          style={{ width: check.width, height: check.height }}
                        >
                          <img
                            alt=""
                            width={check.width}
                            height={check.height}
                            src={`${props.apiBase}/assets/${check.asset_id}/file`}
                          />
                          {props.showSafe && margins ? (
                            <span
                              className="adapt-safe-overlay"
                              style={{
                                left: margins.left,
                                top: margins.top,
                                width: Math.max(0, check.width - margins.left - margins.right),
                                height: Math.max(0, check.height - margins.top - margins.bottom),
                              }}
                            />
                          ) : null}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}
        </section>
      </div>
    </div>
  );
}

export const EMPTY_PRESET_DRAFT: PresetDraft = {
  label: "",
  platform: "",
  width: "",
  height: "",
  kb: "",
  left: "",
  right: "",
  top: "",
  bottom: "",
};

export type { PresetDraft };
