"use client";

import type { AdaptCheck, AdaptPresetRow, AdaptTarget, BatchStatus } from "./adapt-ui-shared";
import { engineLabel, formatBytes, presetLabel as labelFor } from "./adapt-ui-shared";

type Props = {
  apiBase: string;
  liveSpend: boolean;
  busy: boolean;
  sourceId: string | null;
  targets: AdaptTarget[];
  presets: AdaptPresetRow[];
  layout: "fit_pad_crop" | "ai_extend";
  fit: "fit" | "pad" | "crop";
  batch: BatchStatus | null;
  showSafe: boolean;
  onToggleSafe: () => void;
  onBack: () => void;
  onRun: () => void;
  onPickSource: () => void;
};

export function AdaptFlowCanvas({
  apiBase,
  liveSpend,
  busy,
  sourceId,
  targets,
  presets,
  layout,
  fit,
  batch,
  showSafe,
  onToggleSafe,
  onBack,
  onRun,
  onPickSource,
}: Props) {
  const engine = engineLabel(layout, liveSpend);
  const fitLabel = layout === "fit_pad_crop" ? fit : "extend";
  const checks = batch?.items?.[0]?.outputs || [];

  return (
    <div className="adapt-flow" id="adapt-flow-canvas">
      <header className="adapt-flow-head">
        <div>
          <p className="eyebrow">Image › Adapts</p>
          <h2>Flow</h2>
        </div>
        <div className="adapt-head-actions">
          <span className={engine.real ? "adapt-pill adapt-pill-real" : "adapt-pill adapt-pill-mock"}>{engine.text}</span>
          <button className="ghost" type="button" onClick={onToggleSafe}>
            {showSafe ? "Safe area on" : "Safe area off"}
          </button>
          <button className="ghost" type="button" onClick={onBack}>
            Form
          </button>
          <button className="run" type="button" disabled={busy || !sourceId} onClick={onRun}>
            Run Adapts
          </button>
        </div>
      </header>

      <div className="adapt-flow-board">
        <section className="adapt-flow-lane" aria-label="Source">
          <h3 className="adapt-flow-lane-title">Source</h3>
          <div className="adapt-flow-node adapt-flow-node-lg">
            <div className="adapt-flow-thumb adapt-flow-thumb-lg">
              {sourceId ? (
                <img alt="Source creative" src={`${apiBase}/assets/${sourceId}/file`} />
              ) : (
                <button type="button" className="ghost adapt-flow-upload" onClick={onPickSource}>
                  Upload
                </button>
              )}
            </div>
          </div>
        </section>

        <div className="adapt-flow-connector" aria-hidden="true">
          <span className="adapt-flow-arrow" />
        </div>

        <section className="adapt-flow-lane" aria-label="Adapts transform">
          <h3 className="adapt-flow-lane-title">Adapts</h3>
          <div className="adapt-flow-node adapt-flow-node-lg">
            <p className="adapt-flow-meta">{fitLabel}</p>
            <ul className="adapt-flow-targets">
              {targets.map((target, i) => {
                const preset = presets.find((row) => row.id === target.preset_id);
                return <li key={`${target.preset_id || "custom"}-${i}`}>{labelFor(preset, target, i)}</li>;
              })}
            </ul>
          </div>
        </section>

        <div className="adapt-flow-connector" aria-hidden="true">
          <span className="adapt-flow-arrow" />
        </div>

        <section className="adapt-flow-lane adapt-flow-lane-outputs" aria-label="Exports">
          <h3 className="adapt-flow-lane-title">Exports</h3>
          <div className="adapt-flow-output-stack">
            {targets.map((target, i) => {
              const preset = presets.find((row) => row.id === target.preset_id);
              const check = checks[i];
              return (
                <ExportThumb
                  key={`${target.preset_id || "out"}-${i}`}
                  apiBase={apiBase}
                  label={labelFor(preset, target, i)}
                  check={check}
                  showSafe={showSafe}
                />
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}

function ExportThumb({
  apiBase,
  label,
  check,
  showSafe,
}: {
  apiBase: string;
  label: string;
  check?: AdaptCheck;
  showSafe: boolean;
}) {
  const width = check?.width || 0;
  const height = check?.height || 0;
  const margins = check?.safe_area?.margins_px;
  return (
    <div className="adapt-flow-node adapt-flow-node-out">
      <strong className="adapt-flow-out-label">{label}</strong>
      <div className="adapt-pixel-frame">
        {check?.asset_id && width && height ? (
          <div className="adapt-pixel-stage" style={{ width, height }}>
            <img alt="" width={width} height={height} src={`${apiBase}/assets/${check.asset_id}/file`} />
            {showSafe && margins ? (
              <span
                className="adapt-safe-overlay"
                style={{
                  left: margins.left,
                  top: margins.top,
                  width: Math.max(0, width - margins.left - margins.right),
                  height: Math.max(0, height - margins.top - margins.bottom),
                }}
              />
            ) : null}
          </div>
        ) : (
          <span className="adapt-flow-placeholder">—</span>
        )}
      </div>
      {check?.byte_cap ? (
        <p className={check.byte_cap.pass ? "adapt-bytes ok" : "adapt-bytes bad"}>
          {formatBytes(check.byte_cap.actual_bytes)} / {formatBytes(check.byte_cap.max_bytes)}
        </p>
      ) : null}
    </div>
  );
}
