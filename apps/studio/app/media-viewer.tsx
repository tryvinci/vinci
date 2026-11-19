"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ImageFeedItem } from "../lib/image-page";
import { DockIcon, DOCK_ICON } from "./ui/icons";

/** A feed card as the viewer reads it. Video cards also carry a length. */
export type ViewerItem = ImageFeedItem & { duration?: string };

/** The card actions. The feed's hover row and the viewer call the same ones. */
export type FeedActions = {
  onFavorite: (item: ViewerItem) => void;
  onCopyPrompt: (item: ViewerItem) => void;
  onReference?: (item: ViewerItem) => void;
  onAnimate?: (item: ViewerItem) => void;
  onExtend?: (item: ViewerItem) => void;
  /** Copy the file's vinci:// link. Off on a host. */
  onMore?: (item: ViewerItem) => void;
  /** Put the card's prompt, model and settings back in the prompt box. */
  onRecreate?: (item: ViewerItem) => void;
};

/**
 * Full-screen viewer of one feed card, as Higgsfield opens a generation (COREPRODUC-729): the media
 * on a blurred copy of itself, and a panel on the right with the prompt, the details and the actions.
 * Esc closes. ← and → step through the finished cards. It renders on `body`, so no feed scrolls behind it.
 *
 * Args:
 *   item: The card on screen.
 *   url: Its file URL.
 *   modelName: The model's display name, or its id.
 *   actions: The card actions (Animate or Extend is the primary one).
 *   onDelete: Delete the card (Undo is on its tile in the feed). Omitted when the backend cannot.
 *   onStep: Show the previous (-1) or next (1) card.
 *   onClose: Close the viewer.
 */
export function MediaViewer({
  item,
  url,
  modelName,
  actions,
  onDelete,
  onStep,
  onClose,
}: {
  item: ViewerItem;
  url: string;
  modelName: string;
  actions: FeedActions;
  onDelete?: () => void;
  onStep: (dir: -1 | 1) => void;
  onClose: () => void;
}) {
  const video = item.mediaKind === "video";
  const [size, setSize] = useState("");
  const [wide, setWide] = useState(false); // the panel is hidden
  const closeRef = useRef<HTMLButtonElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  // The page behind is inert while the viewer is open. On close, focus goes back to what opened it
  // (the card), or, when that card was deleted here, to its Undo (same card element).
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    const card = back?.closest("article");
    const page = Array.from(document.body.children).filter(
      (el): el is HTMLElement => el instanceof HTMLElement && el !== rootRef.current && !el.inert,
    );
    page.forEach((el) => (el.inert = true));
    return () => {
      page.forEach((el) => (el.inert = false));
      const target = back?.isConnected ? back : card?.querySelector<HTMLElement>("button");
      target?.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    setSize(""); // the next card's file reads its own size on load
    closeRef.current?.focus();
    console.info("[media-viewer] open", { id: item.id, kind: item.mediaKind });
  }, [item.id, item.mediaKind]);

  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "Escape") return onClose();
      if (ev.key === "Tab") {
        // A modal keeps Tab inside it, with the details shown or hidden.
        const stops = rootRef.current?.querySelectorAll<HTMLElement>("button, a[href], video[controls]");
        if (!stops?.length) return;
        const first = stops[0];
        const last = stops[stops.length - 1];
        const at = document.activeElement;
        if (!rootRef.current?.contains(at) || (ev.shiftKey && at === first) || (!ev.shiftKey && at === last)) {
          ev.preventDefault();
          (ev.shiftKey ? last : first).focus();
        }
        return;
      }
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      if ((ev.target as HTMLElement | null)?.closest?.("input, textarea, video")) return; // a clip seeks
      ev.preventDefault();
      onStep(ev.key === "ArrowLeft" ? -1 : 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onStep]);

  const created = item.createdAt ? new Date(item.createdAt) : null;
  const details: [string, string][] = [
    ["Model", modelName],
    ["Aspect", item.aspect || ""],
    ["Quality", [item.resolution, item.quality].filter(Boolean).join(" · ")],
    ["Length", item.duration ? `${item.duration}s` : ""],
    ["Size", size],
    ["Created", created && !Number.isNaN(created.getTime()) ? created.toLocaleString() : ""],
  ];
  const primary = video ? actions.onExtend : actions.onAnimate;

  return createPortal(
    <div ref={rootRef} className={"media-viewer" + (wide ? " wide" : "")} role="dialog" aria-modal="true" aria-label={video ? "Video" : "Image"} data-testid="media-viewer">
      <div className="media-viewer-stage">
        {video ? null : <div className="media-viewer-glow" style={{ backgroundImage: `url("${url}")` }} aria-hidden="true" />}
        {video ? (
          <video
            key={url}
            src={url}
            controls
            autoPlay
            loop
            playsInline
            onLoadedMetadata={(ev) => setSize(`${ev.currentTarget.videoWidth}×${ev.currentTarget.videoHeight}`)}
          />
        ) : (
          <img
            key={url}
            src={url}
            alt={item.prompt || "Generated image"}
            onLoad={(ev) => setSize(`${ev.currentTarget.naturalWidth}×${ev.currentTarget.naturalHeight}`)}
          />
        )}
        <button type="button" className="icon-btn media-viewer-expand" aria-label={wide ? "Show details" : "Hide details"} onClick={() => setWide((on) => !on)}>
          <DockIcon d={DOCK_ICON.expand} />
        </button>
      </div>
      {wide ? null : (
        <aside className="media-viewer-panel">
          <header>
            <strong>{video ? "Video" : "Image"}</strong>
            <button ref={closeRef} type="button" className="icon-btn" aria-label="Close" data-testid="media-viewer-close" onClick={onClose}>
              <DockIcon d={DOCK_ICON.close} />
            </button>
          </header>
          <section className="media-viewer-box">
            <div className="media-viewer-label">
              <span>Prompt</span>
              {item.prompt ? (
                <button type="button" className="ghost" onClick={() => actions.onCopyPrompt(item)}>
                  Copy
                </button>
              ) : null}
            </div>
            <p className="media-viewer-prompt" data-testid="media-viewer-prompt">{item.prompt || "No prompt."}</p>
          </section>
          <dl className="media-viewer-box media-viewer-details">
            {details
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
          </dl>
          <div className="media-viewer-actions">
            {primary ? (
              <button type="button" className="run" data-testid="media-viewer-primary" onClick={() => primary(item)}>
                {video ? "Extend" : "Animate"}
              </button>
            ) : null}
            <div className="media-viewer-row">
              {actions.onRecreate ? (
                <button type="button" className="ghost" data-testid="media-viewer-recreate" onClick={() => actions.onRecreate?.(item)}>
                  Recreate
                </button>
              ) : null}
              {actions.onReference ? (
                <button type="button" className="ghost" title="Use as reference" onClick={() => actions.onReference?.(item)}>
                  Reference
                </button>
              ) : null}
              <a className="ghost" href={url} download={`vinci-${item.assetId.slice(0, 12)}`}>
                Download
              </a>
            </div>
            <div className="media-viewer-row">
              <button type="button" className="ghost" aria-label="Favorite" aria-pressed={item.favorite} onClick={() => actions.onFavorite(item)}>
                {item.favorite ? "♥" : "♡"}
              </button>
              {actions.onMore ? (
                <button type="button" className="ghost" aria-label="Copy file link" onClick={() => actions.onMore?.(item)}>
                  <DockIcon d={DOCK_ICON.link} />
                </button>
              ) : null}
              {onDelete ? (
                <button type="button" className="ghost media-viewer-delete" data-testid="media-viewer-delete" onClick={onDelete}>
                  <DockIcon d={DOCK_ICON.trash} />
                  Delete
                </button>
              ) : null}
            </div>
          </div>
        </aside>
      )}
    </div>,
    document.body,
  );
}
