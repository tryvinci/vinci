"use client";

import { useEffect, useRef } from "react";
import { useDialogFocus } from "./ui/focus";
import { type VideoModel } from "../lib/video-page";
import { ModelMenu } from "./model-menu";

/**
 * The Video page's model menu (COREPRODUC-666): a popover beside the left panel, after Magnific's.
 * It replaced a full-page grid of large preview cards that Siddhant called too cluttered.
 *
 * Args:
 *   models: Video catalog rows.
 *   value: Selected model id.
 *   onPick / onClose: Menu events. Escape and a click outside close it.
 */
export function VideoPresetOverlay({
  models,
  value,
  onPick,
  onClose,
}: {
  models: VideoModel[];
  value: string;
  onPick: (id: string) => void;
  onClose: () => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  useDialogFocus(rootRef);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onClose();
    };
    // The opening click lands before this runs, so only a later click outside closes it.
    const onDown = (ev: PointerEvent) => {
      const at = ev.target as HTMLElement | null;
      if (!rootRef.current?.contains(at) && !at?.closest("[data-model-menu-trigger]")) onClose();
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [onClose]);

  return (
    <div className="video-overlay" data-testid="video-preset-overlay" role="dialog" aria-label="Video models" ref={rootRef}>
      <div className="video-overlay-bar">
        <strong>Model</strong>
        <button type="button" className="ghost" data-testid="video-preset-close" onClick={onClose}>
          Close
        </button>
      </div>
      <div role="listbox" aria-label="Video models">
        <ModelMenu models={models} value={value} onPick={onPick} rowTestId="video-preset-card" />
      </div>
    </div>
  );
}
