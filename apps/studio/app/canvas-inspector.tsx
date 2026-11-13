"use client";

import { ModelCombo, type ComboModel } from "./model-combo";
import { AdvancedDisclosure } from "./ui/advanced";
import { DockIcon, DOCK_ICON } from "./ui/icons";
import {
  REF_LIMIT,
  REF_ROLES,
  refsOf,
  seedValue,
  shotPatch,
  shotRows,
  shotValue,
  showsCount,
  showsFrame,
  slotRef,
  usesPagePrompt,
  wiredPrompt,
} from "../lib/canvas-node";
import type { GraphNode } from "../lib/canvas-graph";
import type { LibraryItem } from "../lib/library";
import { PromptMention } from "./prompt-mention";

type Asset = { id: string; mime?: string };

type Props = {
  node: GraphNode;
  label: string;
  placeholder?: string;
  prompt: string;
  models: ComboModel[];
  modelId: string;
  aspects: string[];
  resolutions: string[];
  /** Video lengths in seconds ("5", "10"); empty for other nodes. */
  durations: string[];
  count: number;
  aspect: string;
  resolution: string;
  duration: string;
  costText: string;
  runDisabled: boolean;
  runTitle: string;
  assets: Asset[];
  apiBase: string;
  onPromptChange: (text: string) => void;
  onPromptFocus: () => void;
  onPromptBlur: () => void;
  onCount: (n: number) => void;
  onAspect: (v: string) => void;
  onResolution: (v: string) => void;
  onDuration: (v: string) => void;
  onModel: (id: string) => void;
  onSeed: (v: string) => void;
  /** Merge a shot patch (camera, lens, look, ...) into the node params. */
  onShot: (patch: Record<string, string>) => void;
  onRun: () => void;
  onClose: () => void;
  onAddSlot: (role: "style" | "character") => void;
  onRemoveRef: (assetId: string) => void;
  promptRef?: (el: HTMLTextAreaElement | null) => void;
  library?: readonly LibraryItem[];
  onMention?: (item: LibraryItem) => void;
};

/**
 * Magnific gear inspector: model, references 0/8 (Style + Character), prompt, seed,
 * aspect, resolution, duration (video), shot (camera, lens, look, ...), Run. Same params object as the card.
 */
export function CanvasInspector({
  node,
  label,
  placeholder,
  prompt,
  models,
  modelId,
  aspects,
  resolutions,
  durations,
  count,
  aspect,
  resolution,
  duration,
  costText,
  runDisabled,
  runTitle,
  assets,
  apiBase,
  onPromptChange,
  onPromptFocus,
  onPromptBlur,
  onCount,
  onAspect,
  onResolution,
  onDuration,
  onModel,
  onSeed,
  onShot,
  onRun,
  onClose,
  onAddSlot,
  onRemoveRef,
  promptRef,
  library = [],
  onMention,
}: Props) {
  const cap = node.capability;
  const refs = refsOf(node.params);
  const pagePrompt = usesPagePrompt(node.params);
  const wired = wiredPrompt(node.params);
  return (
    <aside className="insp canvas-insp" data-testid="canvas-inspector">
      <div className="insp-h" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <h2>{label}</h2>
        <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}>
          <DockIcon d={DOCK_ICON.close} />
          <span className="dock-tip">Close</span>
        </button>
      </div>
      <div className="fields">
        <div>
          <label htmlFor="node-model">Model</label>
          <ModelCombo
            inputId="node-model"
            blankLabel="Same as the page"
            value={modelId}
            models={models}
            onChange={onModel}
          />
        </div>
        <div>
          <label>References {refs.length}/{REF_LIMIT}</label>
          <div className="insp-ref-slots" data-testid="insp-refs">
            {REF_ROLES.map((role) => {
              const slot = slotRef(refs, role);
              const asset = slot ? assets.find((a) => a.id === slot.assetId) : undefined;
              return (
                <div key={role} className="insp-ref-slot" data-ref-role={role}>
                  <span className="insp-ref-role">{role === "style" ? "Style" : "Character"}</span>
                  {slot ? (
                    <button type="button" className="insp-ref-thumb" onClick={() => onRemoveRef(slot.assetId)} title="Remove reference">
                      {asset?.mime?.startsWith("video/") ? (
                        <video src={`${apiBase}/assets/${slot.assetId}/file`} muted />
                      ) : (
                        <img alt="" src={`${apiBase}/assets/${slot.assetId}/file`} />
                      )}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="insp-ref-empty"
                      disabled={refs.length >= REF_LIMIT}
                      onClick={() => onAddSlot(role)}
                    >
                      +
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          {refs.filter((row) => slotRef(refs, row.role)?.assetId !== row.assetId).length ? (
            <ul className="insp-ref-extra">
              {refs
                .filter((row) => slotRef(refs, row.role)?.assetId !== row.assetId)
                .map((row) => (
                  <li key={row.assetId}>
                    <button type="button" onClick={() => onRemoveRef(row.assetId)}>
                      Remove
                    </button>
                  </li>
                ))}
            </ul>
          ) : null}
        </div>
        <div>
          <label htmlFor="node-prompt">Prompt</label>
          <PromptMention
            id="node-prompt"
            className="prompt"
            testId="insp-prompt"
            mentionTestId="canvas-mention"
            value={prompt}
            items={library}
            placeholder={
              wired
                ? "Using the wired text. Type here to add to it."
                : pagePrompt
                  ? "Using the page prompt. Type here to override it."
                  : placeholder || "Describe what to generate"
            }
            textareaRef={promptRef}
            onFocus={onPromptFocus}
            onChange={onPromptChange}
            onBlur={onPromptBlur}
            onPick={(item) => onMention?.(item)}
          />
          {wired && prompt ? <span className="node-wired">+ text from the wired node</span> : null}
        </div>
        <AdvancedDisclosure testId="inspector-advanced">
          <div>
            <label htmlFor="node-seed">Seed</label>
            <input
              id="node-seed"
              data-testid="node-seed"
              inputMode="numeric"
              placeholder="Random"
              value={seedValue(node.params)}
              onChange={(ev) => onSeed(ev.target.value)}
            />
          </div>
          {showsCount(cap) ? (
            <div>
              <label htmlFor="insp-count">Count</label>
              <div className="node-stepper" id="insp-count">
                <button type="button" aria-label="Fewer" disabled={count <= 1} onClick={() => onCount(count - 1)}>
                  −
                </button>
                <span>{count}</span>
                <button type="button" aria-label="More" disabled={count >= 10} onClick={() => onCount(count + 1)}>
                  +
                </button>
              </div>
            </div>
          ) : null}
          {showsFrame(cap) && aspects.length ? (
            <div>
              <label>Aspect</label>
              <div className="pills" id="node-aspect-pills">
                {aspects.map((v) => (
                  <button key={v} type="button" className={v === aspect ? "on" : ""} onClick={() => onAspect(v)}>
                    {v}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {showsFrame(cap) && resolutions.length ? (
            <div>
              <label>Resolution</label>
              <div className="pills" id="node-resolution-pills">
                {resolutions.map((v) => (
                  <button key={v} type="button" className={v === resolution ? "on" : ""} onClick={() => onResolution(v)}>
                    {v}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {durations.length ? (
            <div>
              <label>Duration</label>
              <div className="pills" id="node-duration-pills">
                {durations.map((v) => (
                  <button key={v} type="button" className={v === duration ? "on" : ""} onClick={() => onDuration(v)}>
                    {v}s
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {shotRows(cap).map((row) => (
            <div key={row.key} data-testid={`node-shot-${row.key}`}>
              <label>{row.label}</label>
              <div className="pills" id={`node-${row.key}-pills`}>
                {row.values.map((v) => (
                  <button
                    key={v}
                    type="button"
                    className={v === shotValue(node.params, row.key) ? "on" : ""}
                    onClick={() => onShot(shotPatch(node.params, row.key, v))}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </AdvancedDisclosure>
      </div>
      <div className="foot">
        <button className="run" type="button" disabled={runDisabled} title={runTitle} onClick={onRun} data-testid="insp-run">
          Run{costText ? ` · ${costText}` : ""}
        </button>
      </div>
    </aside>
  );
}
