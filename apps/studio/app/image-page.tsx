"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  applyFavorites,
  clampBatch,
  defaultImageModelId,
  feedFromLibrary,
  feedFromRuns,
  generateCost,
  imageModels,
  needsReference,
  toggleFavorite,
  withPendingCards,
  type ImageAsset,
  type ImageFeedItem,
  type ImageModel,
  type ImageRun,
  type LibraryRow,
  type MentionRow,
} from "../lib/image-page";
import { daemonHasPath } from "../lib/daemon-routes";
import { isUnpriced, money, PRICE_VARIES } from "../lib/model-capabilities";
import { ImageFeed } from "./image-feed";
import { ImagePromptBar } from "./image-prompt-bar";
import { plainError } from "./ui/plain-text";

const FAV_KEY = "vinci-image-favorites";
const API = "/vinci-api";

function readFavs(): string[] {
  try {
    const raw = localStorage.getItem(FAV_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

/**
 * Higgsfield Image page: masonry feed + bottom-center prompt bar.
 *
 * Loads GET /library?tool=image when the #471 index exists; otherwise /runs.
 */
export function ImagePage({
  models,
  connected,
  availability,
  selected,
  modelId,
  onModelId,
  modelPicks,
  onPickModel,
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
  busy,
  pendingCount,
  runs,
  assets,
  ready,
  onGenerate,
  onReference,
  onAnimate,
  onLog,
}: {
  models: ImageModel[];
  /** Doctor provider ids. Mock stays only when this list has no real provider. */
  connected?: readonly string[];
  /** Lower is more usable. Tiebreak after modelsFor, not a new sort. */
  availability?: (model: ImageModel) => number;
  selected?: ImageModel;
  modelId: string;
  onModelId: (id: string) => void;
  /** The model a person last picked on each page (this page's picker, the rail flyout, All tools, Ctrl+K). Read in effects. */
  modelPicks: { readonly current: Partial<Record<string, string>> };
  /** A person's pick in this page's model picker. */
  onPickModel: (id: string) => void;
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
  busy: boolean;
  pendingCount: number;
  runs: ImageRun[];
  assets: ImageAsset[];
  ready: (model: ImageModel) => boolean;
  onGenerate: () => void;
  onReference: (assetId: string) => void;
  onAnimate: (assetId: string) => void;
  onLog: (message: string) => void;
}) {
  const imageRows = useMemo(
    () => imageModels(models, connected, availability),
    [availability, connected, models],
  );
  const [libraryItems, setLibraryItems] = useState<LibraryRow[] | null>(null);
  const [favs, setFavs] = useState<string[]>([]);

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
            console.info("[image-page] feed source=runs (no /library)");
          }
          return;
        }
        const res = await fetch(`${API}/library?tool=image`);
        if (!res.ok) {
          if (!cancelled) {
            setLibraryItems(null);
            console.info("[image-page] feed source=runs (no /library)", { status: res.status });
          }
          return;
        }
        const body = (await res.json()) as { items?: LibraryRow[] };
        if (!cancelled) {
          setLibraryItems(body.items || []);
          console.info("[image-page] feed source=library", { count: (body.items || []).length });
        }
      } catch (err) {
        if (!cancelled) {
          setLibraryItems(null);
          console.info("[image-page] feed source=runs", { err: String(err) });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runs, busy]);

  useEffect(() => {
    // Keep a model a person picked. Bug fixed (first occurrence 2026-11-12, reported in production, COREPRODUC-622):
    // the page had its own "picked" flag, false on each open, so a rail flyout, All tools or Ctrl+K
    // pick, or an earlier pick here, was replaced by this default.
    if (modelPicks.current.image === modelId && imageRows.some((row) => row.id === modelId)) return;
    const next = defaultImageModelId(imageRows, ready);
    if (next && next !== modelId) {
      console.info("[image-page] default model", { id: next });
      onModelId(next);
    }
  }, [imageRows, modelId, modelPicks, onModelId, ready]);

  const completed = useMemo(() => {
    const rows = libraryItems ? feedFromLibrary(libraryItems) : feedFromRuns(runs, assets);
    return applyFavorites(rows, favs);
  }, [assets, favs, libraryItems, runs]);

  const items = useMemo(
    () => withPendingCards(completed, busy ? pendingCount : 0),
    [busy, completed, pendingCount],
  );

  const favorite = useCallback(
    async (item: ImageFeedItem) => {
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
      console.info("[image-page] favorite", { id: item.id, on: !item.favorite });
    },
    [favs],
  );

  const copyPrompt = useCallback(
    async (item: ImageFeedItem) => {
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
    async (item: ImageFeedItem) => {
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

  const cost = selected && isUnpriced(selected) ? PRICE_VARIES : money(generateCost(selected?.pricing?.amount, batch), selected?.pricing?.currency);
  const blocked = needsReference(selected) && refs.length === 0;

  return (
    <div className="image-page" data-testid="image-page">
      <ImageFeed
        items={items}
        onFavorite={(item) => void favorite(item)}
        onCopyPrompt={(item) => void copyPrompt(item)}
        onReference={(item) => onReference(item.assetId)}
        onAnimate={(item) => onAnimate(item.assetId)}
        onMore={(item) => void more(item)}
      />
      <ImagePromptBar
        models={imageRows}
        selected={selected}
        prompt={prompt}
        onPrompt={onPrompt}
        aspect={aspect}
        onAspect={onAspect}
        resolution={resolution}
        onResolution={onResolution}
        quality={quality}
        onQuality={onQuality}
        batch={batch}
        onBatch={(n) => onBatch(clampBatch(n))}
        refs={refs}
        onAddRef={onAddRef}
        onRemoveRef={onRemoveRef}
        cast={cast}
        cost={cost}
        busy={busy}
        disabled={busy || !selected || blocked}
        onModelId={onPickModel}
        onGenerate={onGenerate}
      />
    </div>
  );
}
