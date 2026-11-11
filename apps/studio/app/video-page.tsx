"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { clipPrice } from "../lib/canvas-node";
import { daemonHasPath } from "../lib/daemon-routes";
import { ImageFeed } from "./image-feed";
import { VideoPanel } from "./video-panel";
import { VideoPresetOverlay } from "./video-preset-overlay";
import { plainError } from "./ui/plain-text";
import {
  VIDEO_HOW_STEPS,
  applyFavorites,
  applyPreset,
  closestAspect,
  defaultVideoModelId,
  extendFromItem,
  feedFromLibrary,
  feedFromRuns,
  generateCost,
  needsStartFrame,
  toggleFavorite,
  videoModels,
  withPendingCards,
  type LibraryRow,
  type MentionRow,
  type VideoAsset,
  type VideoFeedItem,
  type VideoModel,
  type VideoRun,
} from "../lib/video-page";

const FAV_KEY = "vinci-video-favorites";
const API = "/vinci-api";

function money(n: number): string {
  if (n === 0) return "$0";
  if (n < 0.01) return "$" + n.toFixed(5).replace(/0+$/, "").replace(/\.$/, "");
  return "$" + n.toFixed(3);
}

function readFavs(): string[] {
  try {
    const raw = localStorage.getItem(FAV_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

function fileUrl(assetId: string): string {
  return `${API}/assets/${encodeURIComponent(assetId)}/file`;
}

/**
 * Draw the last frame of a clip. Used by Extend (Higgsfield: last frame + same settings).
 *
 * Args:
 *   url: Clip file URL.
 * Returns:
 *   A PNG file of the last decoded frame.
 */
async function lastFrameFile(url: string): Promise<File> {
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  video.crossOrigin = "anonymous";
  video.src = url;
  await new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error("Could not read the last frame.")), 8000);
    const ok = () => {
      window.clearTimeout(timer);
      resolve();
    };
    video.onloadeddata = ok;
    video.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error("Could not read the last frame."));
    };
    video.load();
  });
  const end = Number.isFinite(video.duration) && video.duration > 0.1 ? Math.max(0, video.duration - 0.05) : 0;
  if (end > 0) {
    await new Promise<void>((resolve) => {
      const timer = window.setTimeout(resolve, 1500);
      video.onseeked = () => {
        window.clearTimeout(timer);
        resolve();
      };
      video.currentTime = end;
    });
  }
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth || 960;
  canvas.height = video.videoHeight || 540;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Could not read the last frame.");
  ctx.drawImage(video, 0, 0);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Could not read the last frame.");
  return new File([blob], "last-frame.png", { type: "image/png" });
}

/**
 * Read width/height of a still so a start frame can set aspect.
 *
 * Args:
 *   url: Still file URL.
 *   fallback: Asset width/height when the daemon already stored them.
 */
async function stillSize(
  url: string,
  fallback?: { width?: number; height?: number },
): Promise<{ width: number; height: number } | null> {
  if (fallback?.width && fallback?.height) return { width: fallback.width, height: fallback.height };
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/**
 * Higgsfield Video page: left panel + History feed + Change overlay.
 *
 * Loads GET /library?tool=video when the #471 index exists; otherwise /runs.
 */
export function VideoPage({
  models,
  connected,
  availability,
  selected,
  modelId,
  onModelId,
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
  onStart,
  onEnd,
  onClip,
  onAudio,
  onExtra,
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
  busy,
  runs,
  assets,
  ready,
  onGenerate,
  onIngest,
  onLog,
}: {
  models: VideoModel[];
  /** Doctor provider ids. Mock stays only when this list has no real provider. */
  connected?: readonly string[];
  /** Lower is more usable. Tiebreak after modelsFor, not a new sort. */
  availability?: (model: VideoModel) => number;
  selected?: VideoModel;
  modelId: string;
  onModelId: (id: string) => void;
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
  onStart: (id: string) => void;
  onEnd: (id: string) => void;
  onClip: (id: string) => void;
  onAudio: (id: string) => void;
  onExtra: (id: string) => void;
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
  busy: boolean;
  runs: VideoRun[];
  assets: VideoAsset[];
  ready: (model: VideoModel) => boolean;
  onGenerate: () => void;
  onIngest: (file: File) => Promise<{ id: string; mime?: string; width?: number; height?: number }>;
  onLog: (message: string) => void;
}) {
  const videoRows = useMemo(
    () => videoModels(models, connected, availability),
    [availability, connected, models],
  );
  const [libraryItems, setLibraryItems] = useState<LibraryRow[] | null>(null);
  const [favs, setFavs] = useState<string[]>([]);
  const [picked, setPicked] = useState(false);
  const [overlay, setOverlay] = useState(false);
  const didDefault = useRef(false);

  useEffect(() => {
    setFavs(readFavs());
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (!(await daemonHasPath(API, "/library"))) {
          if (!cancelled) {
            setLibraryItems(null);
            console.info("[video-page] feed source=runs (no /library)");
          }
          return;
        }
        const res = await fetch(`${API}/library?tool=video`);
        if (!res.ok) {
          if (!cancelled) {
            setLibraryItems(null);
            console.info("[video-page] feed source=runs (no /library)", { status: res.status });
          }
          return;
        }
        const body = (await res.json()) as { items?: LibraryRow[] };
        if (!cancelled) {
          setLibraryItems(body.items || []);
          console.info("[video-page] feed source=library", { count: (body.items || []).length });
        }
      } catch (err) {
        if (!cancelled) {
          setLibraryItems(null);
          console.info("[video-page] feed source=runs", { err: String(err) });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runs, busy]);

  useEffect(() => {
    if (picked || didDefault.current || !videoRows.length) return;
    const next = defaultVideoModelId(videoRows, ready);
    if (!next) return;
    didDefault.current = true;
    const defaults = applyPreset(videoRows.find((row) => row.id === next));
    if (next !== modelId) {
      console.info("[video-page] default model", { id: next });
      onModelId(next);
    }
    if (defaults.duration) onDuration(defaults.duration);
    if (defaults.aspect && !startId) onAspect(defaults.aspect);
    if (defaults.resolution) onResolution(defaults.resolution);
  }, [modelId, onAspect, onDuration, onModelId, onResolution, picked, ready, startId, videoRows]);

  const ratioKey = (selected?.constraints?.aspect_ratios || []).join(",");
  useEffect(() => {
    if (!startId) return;
    const asset = assets.find((row) => row.id === startId);
    const ratios = ratioKey ? ratioKey.split(",") : [];
    if (!ratios.length) return;
    let cancelled = false;
    void stillSize(fileUrl(startId), asset).then((size) => {
      if (cancelled || !size) return;
      const next = closestAspect(size.width, size.height, ratios);
      if (next) {
        console.info("[video-page] start frame set aspect", { startId, next, w: size.width, h: size.height });
        onAspect(next);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [assets, onAspect, ratioKey, startId]);

  const completed = useMemo(() => {
    const rows = libraryItems ? feedFromLibrary(libraryItems) : feedFromRuns(runs, assets);
    return applyFavorites(rows, favs);
  }, [assets, favs, libraryItems, runs]);

  const items = useMemo(() => withPendingCards(completed, busy ? 1 : 0), [busy, completed]);

  const previews = useMemo(() => {
    const map: Record<string, VideoFeedItem> = {};
    for (const item of completed) {
      if (item.modelId && !map[item.modelId]) map[item.modelId] = item;
    }
    return map;
  }, [completed]);

  const favorite = useCallback(
    async (item: VideoFeedItem) => {
      const next = toggleFavorite(favs, item.id);
      setFavs(next);
      try {
        localStorage.setItem(FAV_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      try {
        await fetch(`${API}/library/items/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ favorite: !item.favorite }),
        });
      } catch {
        /* local heart still applies until #471 lands */
      }
      console.info("[video-page] favorite", { id: item.id, on: !item.favorite });
    },
    [favs],
  );

  const copyPrompt = useCallback(
    async (item: VideoFeedItem) => {
      try {
        await navigator.clipboard.writeText(item.prompt);
        onLog("Prompt copied.");
      } catch (err) {
        onLog(plainError(err));
      }
    },
    [onLog],
  );

  const more = useCallback(
    async (item: VideoFeedItem) => {
      const uri = `vinci://assets/${item.assetId}`;
      try {
        await navigator.clipboard.writeText(uri);
        onLog("Copied the file link.");
      } catch (err) {
        onLog(plainError(err));
      }
    },
    [onLog],
  );

  const pickPreset = useCallback(
    (id: string) => {
      const row = videoRows.find((item) => item.id === id);
      const next = applyPreset(row);
      setPicked(true);
      onModelId(next.modelId);
      onDuration(next.duration);
      onAspect(next.aspect);
      onResolution(next.resolution);
      setOverlay(false);
      console.info("[video-page] preset", { id: next.modelId, duration: next.duration, aspect: next.aspect });
      onLog(`Using ${row?.display_name || id}.`);
    },
    [onAspect, onDuration, onLog, onModelId, onResolution, videoRows],
  );

  const addFile = useCallback(
    async (file: File) => {
      try {
        const asset = await onIngest(file);
        const mime = asset.mime || file.type || "";
        if (mime.startsWith("video/")) {
          onClip(asset.id);
          onExtendMode(true);
          onLog("Clip added.");
          return;
        }
        if (mime.startsWith("audio/")) {
          onAudio(asset.id);
          onLog("Audio added.");
          return;
        }
        if (extendMode || !startId) {
          onStart(asset.id);
          onLog("Start frame added.");
          return;
        }
        if (!endId) {
          onEnd(asset.id);
          onLog("End frame added.");
          return;
        }
        onExtra(asset.id);
        onLog("Reference added.");
      } catch (err) {
        onLog(plainError(err));
      }
    },
    [endId, extendMode, onAudio, onClip, onEnd, onExtendMode, onExtra, onIngest, onLog, onStart, startId],
  );

  const extend = useCallback(
    async (item: VideoFeedItem) => {
      const next = extendFromItem(item);
      onExtendMode(true);
      onClip(next.clipId);
      onPrompt(next.prompt);
      if (next.modelId) {
        setPicked(true);
        onModelId(next.modelId);
      }
      if (next.duration) onDuration(next.duration);
      if (next.aspect) onAspect(next.aspect);
      if (next.resolution) onResolution(next.resolution);
      if (next.seed) onSeed(next.seed);
      if (next.steps) onSteps(next.steps);
      console.info("[video-page] extend", { clipId: next.clipId, modelId: next.modelId });
      try {
        const file = await lastFrameFile(fileUrl(next.clipId));
        const asset = await onIngest(file);
        onStart(asset.id);
        onLog("Extend filled the last frame and the settings.");
      } catch (err) {
        onLog("Extend filled the settings. Add a last frame if it is still empty.");
      }
    },
    [onAspect, onClip, onDuration, onExtendMode, onIngest, onLog, onModelId, onPrompt, onResolution, onSeed, onStart, onSteps],
  );

  const cost = money(generateCost(clipPrice(selected, duration)));
  const blocked =
    (needsStartFrame(selected) && !extendMode && !startId) || (extendMode && !clipId && !startId);

  return (
    <div className="video-page" data-testid="video-page">
      <VideoPanel
        models={videoRows}
        selected={selected}
        prompt={prompt}
        onPrompt={onPrompt}
        aspect={aspect}
        onAspect={onAspect}
        resolution={resolution}
        onResolution={onResolution}
        duration={duration}
        onDuration={onDuration}
        seed={seed}
        onSeed={onSeed}
        steps={steps}
        onSteps={onSteps}
        extendMode={extendMode}
        onExtendMode={onExtendMode}
        startId={startId}
        endId={endId}
        clipId={clipId}
        audioId={audioId}
        extraIds={extraIds}
        onAddFile={(file) => void addFile(file)}
        onRemoveStart={onRemoveStart}
        onRemoveEnd={onRemoveEnd}
        onRemoveClip={onRemoveClip}
        onRemoveAudio={onRemoveAudio}
        onRemoveExtra={onRemoveExtra}
        audioOn={audioOn}
        onAudioOn={onAudioOn}
        motion={motion}
        onMotion={onMotion}
        motions={motions}
        cast={cast}
        cost={cost}
        busy={busy}
        disabled={busy || !selected || blocked}
        onModelId={(id) => {
          setPicked(true);
          pickPreset(id);
        }}
        onGenerate={onGenerate}
        onOpenPresets={() => setOverlay(true)}
      />
      <div className="video-main">
        <ImageFeed
          items={items}
          steps={VIDEO_HOW_STEPS}
          emptyLayout="stage"
          emptyTestId="video-how"
          feedTestId="video-feed"
          pendingTestId="video-feed-pending"
          hoverTestId="video-card-hover"
          onFavorite={(item) => void favorite(item)}
          onCopyPrompt={(item) => void copyPrompt(item)}
          onExtend={(item) => void extend(item)}
          onMore={(item) => void more(item)}
        />
      </div>
      {overlay ? (
        <VideoPresetOverlay
          models={videoRows}
          value={selected?.id || ""}
          previews={previews}
          onPick={pickPreset}
          onClose={() => setOverlay(false)}
        />
      ) : null}
    </div>
  );
}
