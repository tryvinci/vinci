"use client";

import { useEffect, useRef, useState } from "react";
import { asLibraryItem, mentionableItems, type LibraryItem } from "../lib/library";
import { AdvancedDisclosure } from "./ui/advanced";
import { ImageModelPicker } from "./image-model-picker";
import { PromptMention } from "./prompt-mention";
import {
  VIDEO_TABS,
  durationOptions,
  visibleVideoControls,
  type MentionRow,
  type VideoModel,
} from "../lib/video-page";
import type { ImageModel } from "../lib/image-page";

type Menu = "model" | "mention" | null;
type VideoTab = (typeof VIDEO_TABS)[number];

const FILE = "/vinci-api/assets";

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
  onModelId,
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
  onAddFile: (file: File) => void;
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
  onModelId: (id: string) => void;
  onGenerate: () => void;
  onOpenPresets: () => void;
}) {
  const [tab, setTab] = useState<VideoTab>("Create");
  const [menu, setMenu] = useState<Menu>(null);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const controls = visibleVideoControls(selected);
  const aspects = selected?.constraints?.aspect_ratios || [];
  const resolutions = selected?.constraints?.resolutions || [];
  const durs = durationOptions(Number(selected?.constraints?.max_duration || 0), selected?.constraints?.durations);
  const items: LibraryItem[] = mentionableItems(cast.map(asLibraryItem));

  useEffect(() => {
    const onDown = (ev: PointerEvent) => {
      if (!rootRef.current?.contains(ev.target as Node)) setMenu(null);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, []);

  function pickModel(id: string) {
    setMenu(null);
    setQuery("");
    onModelId(id);
  }

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
          ev.target.value = "";
          if (file) onAddFile(file);
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
        <button type="button" className="ghost" data-testid="video-preset-change" onClick={onOpenPresets}>
          Change
        </button>
      </div>
      {tab === "Edit" ? (
        <p className="muted" data-testid="video-edit-empty">
          This model cannot edit a region. Switch to Create, or press Change and pick another model.
        </p>
      ) : null}
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
          <div
            className="video-drop"
            data-testid="video-drop"
            onClick={() => fileRef.current?.click()}
            onDragOver={(ev) => ev.preventDefault()}
            onDrop={(ev) => {
              ev.preventDefault();
              const file = ev.dataTransfer.files?.[0];
              if (file) onAddFile(file);
            }}
          >
            {extendMode ? (
              <>
                {clipId ? (
                  <RefChip kind="video" id={clipId} label="Clip" onRemove={onRemoveClip} />
                ) : (
                  <span>Drop a clip to continue it</span>
                )}
                {startId ? <RefChip kind="image" id={startId} label="Start" onRemove={onRemoveStart} /> : <span>Add the last frame</span>}
              </>
            ) : (
              <>
                {startId ? (
                  <RefChip kind="image" id={startId} label="Start" onRemove={onRemoveStart} />
                ) : (
                  <span>Start frame</span>
                )}
                {endId ? (
                  <RefChip kind="image" id={endId} label="End" onRemove={onRemoveEnd} />
                ) : (
                  <span>End frame</span>
                )}
                {extraIds.map((id) => (
                  <RefChip key={id} kind="image" id={id} label="Reference" onRemove={() => onRemoveExtra(id)} />
                ))}
                {audioId ? <RefChip kind="audio" id={audioId} label="Audio" onRemove={onRemoveAudio} /> : null}
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
              className={"image-chip" + (menu === "model" ? " on" : "")}
              data-testid="video-model-chip"
              aria-expanded={menu === "model"}
              onClick={() => setMenu(menu === "model" ? null : "model")}
            >
              {selected?.display_name || "Model"}
            </button>
            {menu === "model" ? (
              <ImageModelPicker
                models={models as ImageModel[]}
                value={selected?.id || ""}
                query={query}
                onQuery={setQuery}
                onPick={pickModel}
              />
            ) : null}
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
      {tab !== "Edit" ? (
        <button
          className="run image-generate"
          type="button"
          data-testid="video-generate"
          disabled={disabled}
          onClick={onGenerate}
        >
          <span>{busy ? "Generating…" : "Generate"}</span>
          <span>{cost}</span>
        </button>
      ) : null}
      {tab === "Create" && controls.advanced ? (
        <AdvancedDisclosure testId="video-advanced">
          <label>
            Steps
            <input data-testid="video-steps" type="number" min={0} value={steps} onChange={(ev) => onSteps(ev.target.value)} />
          </label>
          <label>
            Seed
            <input data-testid="video-seed" type="number" value={seed} onChange={(ev) => onSeed(ev.target.value)} />
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
