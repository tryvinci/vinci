"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useMenuEscape } from "./ui/focus";
import { asLibraryItem, mentionableItems, type LibraryItem } from "../lib/library";
import { AdvancedDisclosure } from "./ui/advanced";
import { PromptMention } from "./prompt-mention";
import { useUrlPart } from "./url-part";
import { ProblemNote } from "./ui/problem-note";
import type { RunAction, RunProblem } from "./ui/plain-text";
import {
  VIDEO_REF_MODES,
  VIDEO_TABS,
  durationOptions,
  refModeBlock,
  visibleVideoControls,
  type MentionRow,
  type VideoModel,
  type VideoRefMode,
} from "../lib/video-page";

type Menu = "mention" | null;
type VideoTab = (typeof VIDEO_TABS)[number];

const FILE = "/vinci-api/assets";

/** A file on its way up: the slot it fills and a local preview URL. */
export type PendingRef = { label: string; kind: "image" | "video" | "audio"; url: string };

/**
 * Higgsfield Video left panel: preset, References | Extend, refs, prompt, tiles, Generate.
 *
 * Args:
 *   Props are the live compose fields. Unsupported tiles hide when the model changes.
 */
export function VideoPanel({
  models,
  selected,
  prompt,
  onPrompt,
  aspect,
  onAspect,
  resolution,
  onResolution,
  duration,
  onDuration,
  seed,
  onSeed,
  steps,
  onSteps,
  extendMode,
  onExtendMode,
  startId,
  endId,
  clipId,
  audioId,
  extraIds,
  onAddFile,
  refMode,
  onRefMode,
  uploading,
  onRemoveStart,
  onRemoveEnd,
  onRemoveClip,
  onRemoveAudio,
  onRemoveExtra,
  audioOn,
  onAudioOn,
  motion,
  onMotion,
  motions,
  cast,
  cost,
  busy,
  disabled,
  hint,
  problem,
  onProblemAction,
  onGenerate,
  onOpenPresets,
}: {
  models: VideoModel[];
  selected?: VideoModel;
  prompt: string;
  onPrompt: (value: string) => void;
  aspect: string;
  onAspect: (value: string) => void;
  resolution: string;
  onResolution: (value: string) => void;
  duration: string;
  onDuration: (value: string) => void;
  seed: string;
  onSeed: (value: string) => void;
  steps: string;
  onSteps: (value: string) => void;
  extendMode: boolean;
  onExtendMode: (value: boolean) => void;
  startId: string | null;
  endId: string | null;
  clipId: string | null;
  audioId: string | null;
  extraIds: string[];
  /** A file for a slot ("Start", "End", "Reference"), or with no slot for the mode's next one. */
  onAddFile: (file: File, slot?: string) => void;
  /** Start frame, Start + End, or References (COREPRODUC-667). */
  refMode: VideoRefMode;
  onRefMode: (mode: VideoRefMode) => void;
  uploading?: PendingRef | null;
  onRemoveStart: () => void;
  onRemoveEnd: () => void;
  onRemoveClip: () => void;
  onRemoveAudio: () => void;
  onRemoveExtra: (id: string) => void;
  audioOn: boolean;
  onAudioOn: (value: boolean) => void;
  motion: string;
  onMotion: (value: string) => void;
  motions: string[];
  cast: MentionRow[];
  cost: string;
  busy: boolean;
  disabled: boolean;
  /** Why Generate is off (shown under the button and as its title). */
  hint?: string;
  /** Why the last Generate was refused: red, with its next step, in place of the hint (COREPRODUC-692). */
  problem?: RunProblem | null;
  onProblemAction?: (action: RunAction) => void;
  onGenerate: () => void;
  onOpenPresets: () => void;
}) {
  const [tab, setTab] = useState<VideoTab>("Create");
  // The tab is in the URL: `#video/motion-control` (COREPRODUC-698). "Create" is the page itself.
  const tabPart = (name: string) => (name === VIDEO_TABS[0] ? "" : name.toLowerCase().replace(/\s+/g, "-"));
  useUrlPart("video", true, tabPart(tab), (part) => setTab(VIDEO_TABS.find((name) => tabPart(name) === part) || VIDEO_TABS[0]));
  const [menu, setMenu] = useState<Menu>(null);
  const [over, setOver] = useState(false);
  const [modeNote, setModeNote] = useState(""); // why a grayed-out mode cannot be picked
  const target = useRef<string | undefined>(undefined); // the slot the file picker fills
  const maxRefs = Number(selected?.constraints?.max_references || 0);
  const allBlocked = VIDEO_REF_MODES.every((row) => refModeBlock(selected, row.mode));
  const rootRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const controls = visibleVideoControls(selected);
  const aspects = selected?.constraints?.aspect_ratios || [];
  const resolutions = selected?.constraints?.resolutions || [];
  const durs = durationOptions(Number(selected?.constraints?.max_duration || 0), selected?.constraints?.durations);
  const items: LibraryItem[] = mentionableItems(cast.map(asLibraryItem));

  /** An empty slot: click it or drop on it to fill that slot. */
  const empty = (name: string, label: string) => (
    <button
      type="button"
      className="video-slot"
      data-testid={`video-slot-${name.toLowerCase()}`}
      onClick={(ev) => {
        ev.stopPropagation();
        target.current = name;
        fileRef.current?.click();
      }}
      onDrop={(ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        setOver(false);
        const file = ev.dataTransfer.files?.[0];
        if (file) onAddFile(file, name);
      }}
    >
      <span aria-hidden="true">+</span>
      {label}
    </button>
  );
  // One slot: the upload in flight, else the file, else the empty label.
  const slot = (label: string, id: string | null, kind: PendingRef["kind"], onRemove: () => void, empty: ReactNode = null) =>
    uploading?.label === label ? (
      <PendingChip pending={uploading} />
    ) : id ? (
      <RefChip kind={kind} id={id} label={label} onRemove={onRemove} />
    ) : (
      empty
    );

  const closeMenu = useCallback(() => setMenu(null), []);
  useMenuEscape(rootRef, closeMenu);

  useEffect(() => {
    const onDown = (ev: PointerEvent) => {
      if (!rootRef.current?.contains(ev.target as Node)) setMenu(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  return (
    <aside className="video-panel" data-testid="video-panel" ref={rootRef}>
      <input
        ref={fileRef}
        className="hidden"
        type="file"
        accept="image/*,video/*,audio/*"
        aria-label="Add reference"
        onChange={(ev) => {
          const file = ev.target.files?.[0];
          const slotName = target.current;
          target.current = undefined;
          ev.target.value = "";
          if (file) onAddFile(file, slotName);
        }}
      />
      <div className="video-tabs" role="tablist" aria-label="Video mode">
        {VIDEO_TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? "on" : ""}
            data-testid={`video-tab-${name.toLowerCase().replace(" ", "-")}`}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </div>
      <div className="video-preset-row">
        <div className="video-preset-mini">
          <strong>{selected?.display_name || "Model"}</strong>
          <span className="muted">{extendMode ? "Extend Video" : "References"}</span>
        </div>
        <button type="button" className="ghost" data-testid="video-preset-change" data-model-menu-trigger onClick={onOpenPresets}>
          Change
        </button>
      </div>
      {tab === "Motion control" ? (
        <div className="video-tiles" data-testid="video-motion">
          {motions.map((value) => (
            <button
              key={value}
              type="button"
              className={"video-tile" + (motion === value ? " on" : "")}
              onClick={() => onMotion(value)}
            >
              {value}
            </button>
          ))}
        </div>
      ) : null}
      {tab === "Create" ? (
        <>
          <div className="video-mode" data-testid="video-mode">
            <button
              type="button"
              className={!extendMode ? "on" : ""}
              data-testid="video-mode-references"
              onClick={() => onExtendMode(false)}
            >
              References
            </button>
            <button
              type="button"
              className={extendMode ? "on" : ""}
              data-testid="video-mode-extend"
              onClick={() => onExtendMode(true)}
            >
              Extend Video
            </button>
          </div>
          {!extendMode ? (
            <div className="video-ref-modes" role="radiogroup" aria-label="Inputs" data-testid="video-ref-modes">
              {VIDEO_REF_MODES.map(({ mode, label }) => {
                const why = refModeBlock(selected, mode);
                return (
                  <button
                    key={mode}
                    type="button"
                    role="radio"
                    aria-checked={refMode === mode && !why}
                    aria-disabled={Boolean(why)}
                    title={why || undefined}
                    className={(refMode === mode && !why ? "on" : "") + (why ? " off" : "")}
                    data-testid={`video-ref-mode-${mode}`}
                    onClick={() => {
                      setModeNote(why);
                      if (!why) onRefMode(mode);
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          ) : null}
          {!extendMode && (modeNote || allBlocked) ? (
            <p className="video-ref-note muted" role="status" data-testid="video-ref-note">
              {allBlocked ? `${selected?.display_name || "This model"} makes the clip from the prompt alone.` : modeNote}
            </p>
          ) : null}
          <div
            className={"video-drop" + (over ? " over" : "") + (!extendMode && allBlocked ? " off" : "")}
            data-testid="video-drop"
            onClick={() => fileRef.current?.click()}
            onDragOver={(ev) => (ev.preventDefault(), setOver(true))}
            onDragLeave={() => setOver(false)}
            onDrop={(ev) => {
              ev.preventDefault();
              setOver(false);
              const file = ev.dataTransfer.files?.[0];
              if (file) onAddFile(file);
            }}
          >
            {extendMode ? (
              <>
                {slot("Clip", clipId, "video", onRemoveClip, <span>Drop a clip to continue it</span>)}
                {slot("Start", startId, "image", onRemoveStart, <span>Add the last frame</span>)}
              </>
            ) : (
              <>
                {refMode !== "refs" ? slot("Start", startId, "image", onRemoveStart, empty("Start", "Start frame")) : null}
                {refMode === "start-end" ? slot("End", endId, "image", onRemoveEnd, empty("End", "End frame")) : null}
                {refMode === "refs" ? (
                  <>
                    {extraIds.map((id) => (
                      <RefChip key={id} kind="image" id={id} label="Reference" onRemove={() => onRemoveExtra(id)} />
                    ))}
                    {slot("Reference", null, "image", () => {}, extraIds.length < (maxRefs || 1) ? empty("Reference", "Add reference") : null)}
                  </>
                ) : null}
                {slot("Audio", audioId, "audio", onRemoveAudio)}
                {slot("Clip", null, "video", () => {})}
              </>
            )}
          </div>
          <div className="video-prompt">
            <PromptMention
              id="video-prompt"
              testId="video-prompt"
              mentionTestId="video-mention"
              rows={4}
              placeholder="Describe the clip. Type @ to mention someone."
              aria-label="Video prompt"
              value={prompt}
              items={items}
              open={menu === "mention"}
              onOpenChange={(next) => setMenu(next ? "mention" : null)}
              onChange={onPrompt}
              onMetaEnter={() => {
                if (!disabled) onGenerate();
              }}
            />
          </div>
          {controls.audio ? (
            <button
              type="button"
              className={"image-chip" + (audioOn ? " on" : "")}
              data-testid="video-audio"
              onClick={() => onAudioOn(!audioOn)}
            >
              Audio
            </button>
          ) : null}
          <div className="image-chip-wrap video-model-row">
            <button
              type="button"
              className="image-chip"
              data-testid="video-model-chip"
              data-model-menu-trigger
              onClick={onOpenPresets}
            >
              {selected?.display_name || "Model"}
            </button>
          </div>
          <div className="video-tiles">
            {controls.duration ? (
              <TileGroup
                testId="video-duration"
                label="Duration"
                values={durs.map((n) => `${n}s`)}
                current={duration ? `${duration}s` : ""}
                onPick={(v) => onDuration(v.replace(/s$/, ""))}
              />
            ) : null}
            {controls.aspect ? (
              <TileGroup testId="video-aspect" label="Aspect" values={aspects} current={aspect} onPick={onAspect} />
            ) : null}
            {controls.quality ? (
              <TileGroup
                testId="video-quality"
                label="Quality"
                values={resolutions}
                current={resolution}
                onPick={onResolution}
              />
            ) : null}
          </div>
        </>
      ) : null}
      {/* Motion control only sets the camera move: Generate stays on Create, so a run never sends
          inputs this tab does not show (COREPRODUC-641). */}
      {tab === "Motion control" ? (
        <p className="run-hint" data-testid="video-motion-note">
          Camera move: {motion || "none"}. Go back to Create to write the prompt and generate.
        </p>
      ) : null}
      {tab === "Create" ? (
        <button
          className="run image-generate"
          type="button"
          data-testid="video-generate"
          disabled={disabled}
          title={hint || undefined}
          onClick={onGenerate}
        >
          <span>{busy ? "Generating…" : "Generate"}</span>
          <span>{cost}</span>
        </button>
      ) : null}
      {/* What blocks Generate now wins over why the last Generate was refused. */}
      {tab === "Create" && hint && !busy ? (
        <p className="run-hint" role="status" data-testid="video-blocked">
          {hint}
        </p>
      ) : tab === "Create" && problem && !busy ? (
        <ProblemNote problem={problem} onAction={onProblemAction} className="run-hint" testId="video-problem" />
      ) : null}
      {tab === "Create" && controls.advanced ? (
        <AdvancedDisclosure testId="video-advanced">
          <label>
            Steps
            <input data-testid="video-steps" type="number" min={0} placeholder="Model default" value={steps} onChange={(ev) => onSteps(ev.target.value)} />
          </label>
          <label>
            Seed
            <input data-testid="video-seed" type="number" placeholder="Random" value={seed} onChange={(ev) => onSeed(ev.target.value)} />
          </label>
        </AdvancedDisclosure>
      ) : null}
    </aside>
  );
}

function TileGroup({
  testId,
  label,
  values,
  current,
  onPick,
}: {
  testId: string;
  label: string;
  values: string[];
  current: string;
  onPick: (value: string) => void;
}) {
  return (
    <div className="video-tile-group" data-testid={testId}>
      <span>{label}</span>
      <div>
        {values.map((v) => (
          <button key={v} type="button" className={"video-tile" + (v === current ? " on" : "")} onClick={() => onPick(v)}>
            {v}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The file still uploading: its local preview, dimmed, under a spinner. */
function PendingChip({ pending }: { pending: PendingRef }) {
  return (
    <div
      className="video-ref pending"
      data-testid={`video-ref-${pending.label.toLowerCase()}-uploading`}
      role="status"
      onClick={(ev) => ev.stopPropagation()}
    >
      <div className="video-ref-thumb">
        {pending.kind === "video" ? <video src={pending.url} muted /> : pending.kind === "image" ? <img src={pending.url} alt="" /> : <span>♪</span>}
        <span className="spinner" aria-hidden="true" />
      </div>
      <span>Uploading…</span>
    </div>
  );
}

function RefChip({
  kind,
  id,
  label,
  onRemove,
}: {
  kind: "image" | "video" | "audio";
  id: string;
  label: string;
  onRemove: () => void;
}) {
  const src = `${FILE}/${encodeURIComponent(id)}/file`;
  return (
    <div className="video-ref" data-testid={`video-ref-${label.toLowerCase()}`} onClick={(ev) => ev.stopPropagation()}>
      {kind === "video" ? <video src={src} muted /> : kind === "image" ? <img src={src} alt="" /> : <span>♪</span>}
      <span>
        {label}
        <button type="button" aria-label={`Remove ${label}`} onClick={onRemove}>
          ×
        </button>
      </span>
    </div>
  );
}
