"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMenuEscape } from "./ui/focus";
import { asLibraryItem, mentionableItems, type LibraryItem } from "../lib/library";
import {
  IMAGE_BATCH,
  qualityOptions,
  takesReference,
  visibleControls,
  type ImageModel,
  type MentionRow,
} from "../lib/image-page";
import { ImageModelPicker } from "./image-model-picker";
import { PromptMention, startMention } from "./prompt-mention";
import { AdvancedDisclosure } from "./ui/advanced";
import { DockIcon, DOCK_ICON } from "./ui/icons";

type Menu = "model" | "aspect" | "quality" | "resolution" | "batch" | "mention" | null;

/**
 * Bottom-center Higgsfield prompt bar: +ref, @, model, aspect, quality, resolution, 1/4, Generate $.
 *
 * Args:
 *   Props are the live compose fields. Unsupported chips hide when the model changes.
 */
export function ImagePromptBar({
  models,
  selected,
  prompt,
  onPrompt,
  aspect,
  onAspect,
  resolution,
  onResolution,
  quality,
  onQuality,
  batch,
  onBatch,
  refs,
  onAddRef,
  onRemoveRef,
  cast,
  cost,
  busy,
  disabled,
  hint,
  onModelId,
  onGenerate,
}: {
  models: ImageModel[];
  selected?: ImageModel;
  prompt: string;
  onPrompt: (value: string) => void;
  aspect: string;
  onAspect: (value: string) => void;
  resolution: string;
  onResolution: (value: string) => void;
  quality: string;
  onQuality: (value: string) => void;
  batch: number;
  onBatch: (value: number) => void;
  refs: string[];
  onAddRef: (file: File) => void;
  onRemoveRef: (id: string) => void;
  cast: MentionRow[];
  cost: string;
  busy: boolean;
  disabled: boolean;
  /** Why Generate is off (shown above the button and as its title). */
  hint?: string;
  onModelId: (id: string) => void;
  onGenerate: () => void;
}) {
  const [menu, setMenu] = useState<Menu>(null);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const controls = visibleControls(selected);
  const aspects = selected?.constraints?.aspect_ratios || [];
  const resolutions = selected?.constraints?.resolutions || [];
  const qualities = qualityOptions(selected);
  const items: LibraryItem[] = mentionableItems(cast.map(asLibraryItem));
  // A text-only model drops references, so do not take one (COREPRODUC-648). aria-disabled keeps the
  // button focusable, so keyboard users see the reason in its tip too.
  const refOff = Boolean(selected) && !takesReference(selected);
  const refTip = refOff ? `${selected?.display_name || "This model"} does not use references` : "Add reference";

  const closeMenu = useCallback(() => setMenu(null), []);
  useMenuEscape(rootRef, closeMenu);

  useEffect(() => {
    const onDown = (ev: PointerEvent) => {
      if (!rootRef.current?.contains(ev.target as Node)) setMenu(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  function openElements() {
    const el = textRef.current;
    const pos = el?.selectionStart ?? prompt.length;
    const next = startMention(prompt, pos);
    onPrompt(next.text);
    requestAnimationFrame(() => {
      const box = textRef.current;
      if (!box) return;
      box.focus();
      box.selectionStart = next.cursor;
      box.selectionEnd = next.cursor;
    });
    setMenu("mention");
  }

  function pickModel(id: string) {
    setMenu(null);
    setQuery("");
    const row = models.find((m) => m.id === id);
    if (row) {
      const next = visibleControls(row);
      const ratios = row.constraints?.aspect_ratios || [];
      const res = row.constraints?.resolutions || [];
      const quals = qualityOptions(row);
      onAspect(next.aspect ? (ratios.includes(aspect) ? aspect : ratios[0] || "") : "");
      onQuality(next.quality ? (quals.includes(quality) ? quality : quals[0] || "") : "");
      onResolution(next.resolution ? (res.includes(resolution) ? resolution : res[0] || "") : "");
    }
    onModelId(id);
  }

  return (
    <div className="image-bar" data-testid="image-bar" ref={rootRef}>
      <input
        ref={fileRef}
        className="hidden"
        type="file"
        accept="image/*"
        aria-label="Add reference"
        onChange={(ev) => {
          const file = ev.target.files?.[0];
          ev.target.value = "";
          if (file) onAddRef(file);
        }}
      />
      <div className="image-bar-refs">
        <button
          type="button"
          className="icon-btn"
          data-testid="image-ref"
          aria-label={refTip}
          aria-disabled={refOff}
          onClick={() => !refOff && fileRef.current?.click()}
        >
          <DockIcon d={DOCK_ICON.add} />
          <span className="dock-tip">{refTip}</span>
        </button>
        {refs.map((id) => (
          <button key={id} type="button" className="image-ref-chip" onClick={() => onRemoveRef(id)} title="Remove reference">
            <img src={`/vinci-api/assets/${encodeURIComponent(id)}/file`} alt="" />
          </button>
        ))}
        <button
          type="button"
          className={"image-ref-add" + (menu === "mention" ? " on" : "")}
          data-testid="image-elements"
          aria-label="Elements"
          onClick={openElements}
        >
          @
        </button>
      </div>
      <div className="image-bar-prompt">
        <PromptMention
          id="image-prompt"
          testId="image-prompt"
          mentionTestId="image-mention"
          rows={2}
          placeholder="Describe the still. Type @ to mention someone."
          aria-label="Image prompt"
          value={prompt}
          items={items}
          textareaRef={(el) => {
            textRef.current = el;
          }}
          open={menu === "mention"}
          onOpenChange={(next) => setMenu(next ? "mention" : null)}
          onChange={onPrompt}
          onMetaEnter={() => {
            if (!disabled) onGenerate();
          }}
        />
      </div>
      <div className="image-bar-chips">
        <div className="image-chip-wrap">
          <button
            type="button"
            className={"image-chip" + (menu === "model" ? " on" : "")}
            data-testid="image-model-chip"
            aria-expanded={menu === "model"}
            onClick={() => setMenu(menu === "model" ? null : "model")}
          >
            {selected?.display_name || "Model"}
          </button>
          {menu === "model" ? (
            <ImageModelPicker
              models={models}
              value={selected?.id || ""}
              query={query}
              onQuery={setQuery}
              onPick={pickModel}
            />
          ) : null}
        </div>
        {controls.aspect ? (
          <ChipMenu
            testId="image-aspect"
            label={aspect || "Aspect"}
            ariaLabel={`Aspect ratio: ${aspect || "not set"}`}
            open={menu === "aspect"}
            onToggle={() => setMenu(menu === "aspect" ? null : "aspect")}
            values={aspects}
            current={aspect}
            onPick={(v) => {
              onAspect(v);
              setMenu(null);
            }}
          />
        ) : null}
        {controls.quality ? (
          <AdvancedDisclosure testId="image-advanced">
            <ChipMenu
              testId="image-quality"
              label={quality || "Quality"}
              ariaLabel={`Quality: ${quality || "not set"}`}
              open={menu === "quality"}
              onToggle={() => setMenu(menu === "quality" ? null : "quality")}
              values={qualities}
              current={quality}
              onPick={(v) => {
                onQuality(v);
                setMenu(null);
              }}
            />
          </AdvancedDisclosure>
        ) : null}
        {controls.resolution ? (
          <ChipMenu
            testId="image-resolution"
            label={resolution || "Resolution"}
            ariaLabel={`Resolution: ${resolution || "not set"}`}
            open={menu === "resolution"}
            onToggle={() => setMenu(menu === "resolution" ? null : "resolution")}
            values={resolutions}
            current={resolution}
            onPick={(v) => {
              onResolution(v);
              setMenu(null);
            }}
          />
        ) : null}
        <ChipMenu
          testId="image-batch"
          label={String(batch)}
          ariaLabel={`Images per run: ${batch}`}
          open={menu === "batch"}
          onToggle={() => setMenu(menu === "batch" ? null : "batch")}
          values={IMAGE_BATCH.map(String)}
          current={String(batch)}
          onPick={(v) => {
            onBatch(Number(v));
            setMenu(null);
          }}
        />
      </div>
      <button
        className="run image-generate"
        type="button"
        data-testid="image-generate"
        disabled={disabled}
        title={hint || undefined}
        onClick={onGenerate}
      >
        <span>{busy ? "Generating…" : "Generate"}</span>
        <span>{cost}</span>
      </button>
      {hint && !busy ? (
        <p className="run-hint" role="status" data-testid="image-blocked">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function ChipMenu({
  testId,
  label,
  ariaLabel,
  open,
  onToggle,
  values,
  current,
  onPick,
}: {
  testId: string;
  label: string;
  /** Name for screen readers when the visible label is only a value ("1", "16:9"). */
  ariaLabel?: string;
  open: boolean;
  onToggle: () => void;
  values: string[];
  current: string;
  onPick: (value: string) => void;
}) {
  return (
    <div className="image-chip-wrap">
      <button type="button" className={"image-chip" + (open ? " on" : "")} data-testid={testId} aria-expanded={open} aria-label={ariaLabel} onClick={onToggle}>
        {label}
      </button>
      {open ? (
        <div className="image-chip-menu" role="listbox">
          {values.map((v) => (
            <button key={v} type="button" role="option" aria-selected={v === current} className={v === current ? "on" : ""} onClick={() => onPick(v)}>
              {v}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
