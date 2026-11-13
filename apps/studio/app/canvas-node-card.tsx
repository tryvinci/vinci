"use client";

import { useEffect, useRef, useState, type KeyboardEvent as ReactKey } from "react";
import type { ComboModel } from "./model-combo";
import { DockIcon, DOCK_ICON } from "./ui/icons";
import { REF_LIMIT, showsCount, showsFrame, usesPagePrompt, wiredPrompt } from "../lib/canvas-node";
import type { GraphNode } from "../lib/canvas-graph";
import type { LibraryItem } from "../lib/library";
import { PromptMention } from "./prompt-mention";

type RunState = { state: "running" | "done" | "cached" | "error"; error?: string } | undefined;

type Props = {
  node: GraphNode;
  label: string;
  subtitle?: string;
  placeholder?: string;
  showPrompt?: boolean;
  prompt: string;
  digest: string | null;
  thumbSrc?: string;
  video?: boolean;
  runState: RunState;
  needs: string | null;
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
  inspectorOpen: boolean;
  refCount: number;
  onPromptChange: (text: string) => void;
  onPromptFocus: () => void;
  onPromptBlur: () => void;
  onCount: (n: number) => void;
  onAspect: (v: string) => void;
  onResolution: (v: string) => void;
  onDuration: (v: string) => void;
  onModel: (id: string) => void;
  onGear: () => void;
  onRun: () => void;
  onAddReference: () => void;
  onUpload?: (file: File) => void;
  promptRef?: (el: HTMLTextAreaElement | null) => void;
  library?: readonly LibraryItem[];
  onMention?: (item: LibraryItem) => void;
};

type PillOption = { id: string; label: string };

/** Visible label on the primary pill. The button's aria-label stays "Run …". */
function createLabel(capability: string): string {
  if (capability === "t2v" || capability === "i2v" || capability === "lipsync") return "Create video";
  if (capability === "tts") return "Create audio";
  if (capability === "upscale") return "Upscale";
  return "Create image";
}

/**
 * Prompt-bar style pill. Opens a listbox. Arrows move, Enter picks, Escape closes.
 *
 * Args:
 *   label: Accessible name.
 *   value: Selected id. Empty shows `placeholder`.
 *   options: Menu rows.
 *   open: Parent owns which pill is open so only one menu shows.
 */
function NodePill({
  label,
  value,
  placeholder,
  options,
  testId,
  open,
  onOpen,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  options: readonly PillOption[];
  testId: string;
  open: boolean;
  onOpen: (next: boolean) => void;
  onChange: (id: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const current = options.find((row) => row.id === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (ev: PointerEvent) => {
      if (!rootRef.current?.contains(ev.target as Node)) onOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [onOpen, open]);

  function onKey(ev: ReactKey<HTMLButtonElement>) {
    if (!open && (ev.key === "ArrowDown" || ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      ev.stopPropagation();
      setActive(Math.max(0, options.findIndex((row) => row.id === value)));
      onOpen(true);
      return;
    }
    if (!open) return;
    if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      onOpen(false);
      return;
    }
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      ev.stopPropagation();
      setActive((index) => {
        const next = ev.key === "ArrowDown" ? index + 1 : index - 1;
        return Math.max(0, Math.min(options.length - 1, next));
      });
      return;
    }
    if (ev.key === "Enter") {
      ev.preventDefault();
      ev.stopPropagation();
      const row = options[active];
      if (row) onChange(row.id);
      onOpen(false);
    }
  }

  return (
    <div className="node-pill" ref={rootRef} onPointerDown={(ev) => ev.stopPropagation()}>
      <button
        type="button"
        className={"image-chip node-pill-btn" + (open ? " on" : "")}
        data-testid={testId}
        aria-label={label}
        title={current?.label || placeholder}
        aria-haspopup="listbox"
        aria-expanded={open}
        onKeyDown={onKey}
        onClick={(ev) => {
          ev.stopPropagation();
          if (!open) setActive(Math.max(0, options.findIndex((row) => row.id === value)));
          onOpen(!open);
        }}
      >
        {current?.label || placeholder}
      </button>
      {open ? (
        <div className="image-chip-menu node-pill-menu" role="listbox" aria-label={label}>
          {options.map((row, index) => (
            <button
              key={row.id || label}
              type="button"
              role="option"
              aria-selected={row.id === value}
              className={(row.id === value ? "on " : "") + (index === active ? "active" : "")}
              onClick={(ev) => {
                ev.stopPropagation();
                onChange(row.id);
                onOpen(false);
              }}
            >
              {row.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Magnific node card: preview, inline prompt, +reference, pill bar, Run with cost.
 *
 * Interactive bits use `.node-ui` so the board drag handler ignores them.
 */
export function CanvasNodeCard({
  node,
  label,
  subtitle,
  placeholder,
  showPrompt = true,
  prompt,
  digest,
  thumbSrc,
  video,
  runState,
  needs,
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
  inspectorOpen,
  refCount,
  onPromptChange,
  onPromptFocus,
  onPromptBlur,
  onCount,
  onAspect,
  onResolution,
  onDuration,
  onModel,
  onGear,
  onRun,
  onAddReference,
  onUpload,
  promptRef,
  library = [],
  onMention,
}: Props) {
  const [openPill, setOpenPill] = useState<string | null>(null);
  const cap = node.capability;
  const generate = node.type === "generate";
  const pagePrompt = usesPagePrompt(node.params);
  const wired = wiredPrompt(node.params);
  return (
    <>
      <div className="thumb">
        {digest && thumbSrc ? video ? <video src={thumbSrc} muted /> : <img alt="" src={thumbSrc} /> : <span className="thumb-empty" aria-hidden="true" />}
        {runState?.state === "running" ? <span className="spinner" aria-label="Running" /> : null}
        {runState?.state === "cached" ? <span className="chip-cached">Saved</span> : null}
      </div>
      <div className="node-caption">
        <strong className="node-title">{label}</strong>
        <p className="node-sub" title={runState?.state === "error" ? runState.error : undefined}>
          {needs ? <span className="needs">{needs}</span> : runState?.state === "error" ? runState.error || "Run failed. Check the prompt and try again." : subtitle}
        </p>
      </div>
      {cap === "media" && onUpload ? (
        <label className="node-ui node-prompt-wrap">
          <span className="sr-only">Upload a file</span>
          <input
            type="file"
            accept="image/*,video/*,audio/*"
            data-testid="node-media-upload"
            onPointerDown={(ev) => ev.stopPropagation()}
            onChange={(ev) => {
              const file = ev.target.files?.[0];
              if (file) onUpload(file);
              ev.target.value = "";
            }}
          />
        </label>
      ) : null}
      {showPrompt && cap !== "media" ? (
        <label className="node-ui node-prompt-wrap" htmlFor={`node-prompt-${node.id}`}>
          <span className="sr-only">Prompt</span>
          <PromptMention
            id={`node-prompt-${node.id}`}
            className="node-prompt"
            data-node-prompt={node.id}
            testId={`canvas-prompt-${node.id}`}
            mentionTestId="canvas-mention"
            value={prompt}
            items={library}
            placeholder={wired ? "Using the wired text. Type here to add to it." : pagePrompt ? "Using the page prompt. Type here to override it." : placeholder || "Describe what to generate"}
            textareaRef={promptRef}
            onPointerDown={(ev) => ev.stopPropagation()}
            onFocus={onPromptFocus}
            onBlur={onPromptBlur}
            onChange={onPromptChange}
            onPick={(item) => onMention?.(item)}
          />
          {wired && prompt ? <span className="node-wired">+ text from the wired node</span> : null}
        </label>
      ) : null}
      {generate ? (
      <div className="node-ui node-refs">
        <button
          type="button"
          className="icon-btn"
          disabled={refCount >= REF_LIMIT}
          aria-label="Add reference"
          onPointerDown={(ev) => ev.stopPropagation()}
          onClick={(ev) => {
            ev.stopPropagation();
            onAddReference();
          }}
        >
          <DockIcon d={DOCK_ICON.add} />
          <span className="dock-tip">
            {refCount >= REF_LIMIT ? "Reference limit reached (8)" : `Add reference (${refCount}/8)`}
          </span>
        </button>
        <span className="node-ref-count">
          {refCount}/8
        </span>
      </div>
      ) : null}
      {generate ? (
      <>
      <div className="node-ui node-pills">
        {showsCount(cap) ? (
          <span className="node-stepper" data-testid="node-count">
            <button type="button" aria-label="Fewer" disabled={count <= 1} onClick={() => onCount(count - 1)}>
              −
            </button>
            <span>{count}</span>
            <button type="button" aria-label="More" disabled={count >= 10} onClick={() => onCount(count + 1)}>
              +
            </button>
          </span>
        ) : null}
        <NodePill
          label="Model"
          value={modelId}
          placeholder="Model"
          testId="node-model-chip"
          open={openPill === "model"}
          onOpen={(next) => setOpenPill(next ? "model" : null)}
          onChange={onModel}
          options={models.map((row) => ({
            id: row.id,
            label: row.label || row.display_name || row.id, // the label carries the price (comboModels)
          }))}
        />
        {showsFrame(cap) && aspects.length ? (
          <NodePill
            label="Aspect"
            value={aspect}
            placeholder="Aspect"
            testId="node-aspect-chip"
            open={openPill === "aspect"}
            onOpen={(next) => setOpenPill(next ? "aspect" : null)}
            onChange={onAspect}
            options={aspects.map((v) => ({ id: v, label: v }))}
          />
        ) : null}
        {showsFrame(cap) && resolutions.length ? (
          <NodePill
            label="Resolution"
            value={resolution}
            placeholder="Resolution"
            testId="node-resolution-chip"
            open={openPill === "resolution"}
            onOpen={(next) => setOpenPill(next ? "resolution" : null)}
            onChange={onResolution}
            options={resolutions.map((v) => ({ id: v, label: v }))}
          />
        ) : null}
        {durations.length ? (
          <NodePill
            label="Duration"
            value={duration}
            placeholder="Duration"
            testId="node-duration-chip"
            open={openPill === "duration"}
            onOpen={(next) => setOpenPill(next ? "duration" : null)}
            onChange={onDuration}
            options={durations.map((v) => ({ id: v, label: `${v}s` }))}
          />
        ) : null}
      </div>
      <div className="node-ui node-actions">
        <button
            type="button"
            className="run node-run"
            data-testid="node-run"
            aria-label="Run"
            disabled={runDisabled}
            title={runTitle}
            onPointerDown={(ev) => ev.stopPropagation()}
            onClick={(ev) => {
              ev.stopPropagation();
              onRun();
            }}
          >
            {createLabel(cap || "")}
          </button>
        <button
          type="button"
          className={"icon-btn" + (inspectorOpen ? " on" : "")}
          data-testid="node-gear"
          aria-label="Open inspector"
          aria-pressed={inspectorOpen}
          onPointerDown={(ev) => ev.stopPropagation()}
          onClick={(ev) => {
            ev.stopPropagation();
            onGear();
          }}
        >
          <DockIcon d={DOCK_ICON.gear} />
          <span className="dock-tip">Settings</span>
        </button>
      </div>
      </>
      ) : null}
    </>
  );
}
