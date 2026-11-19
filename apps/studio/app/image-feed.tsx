"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IMAGE_HOW_STEPS, trashRequest, type ImageFeedItem } from "../lib/image-page";
import { daemonHasPath } from "../lib/daemon-routes";
import { DockIcon, DOCK_ICON } from "./ui/icons";
import { GenProgress } from "./ui/gen-progress";
import { ProblemNote } from "./ui/problem-note";
import { MediaViewer, type FeedActions, type ViewerItem } from "./media-viewer";
import { plainError, type RunAction, type RunProblem } from "./ui/plain-text";
import type { RunClock } from "../lib/progress";

const API = "/vinci-api";
const FILE = `${API}/assets`;

function fileUrl(assetId: string): string {
  return `${FILE}/${encodeURIComponent(assetId)}/file`;
}

/**
 * Delete and Undo for the Image and Video feeds (COREPRODUC-729). Both are soft: the local daemon
 * trashes the library row (Assets → Trash lists it), the hosted Studio trashes the asset.
 *
 * Args:
 *   fromLibrary: True when the feed came from GET /library, false when it came from /runs.
 *   onLog: The Studio status line.
 * Returns:
 *   The feed's `onTrash`, or undefined when this backend cannot delete (a daemon with no /library).
 */
export function useFeedTrash(fromLibrary: boolean, onLog: (message: string) => void) {
  const [hostTrash, setHostTrash] = useState(false);
  useEffect(() => {
    void daemonHasPath(API, "/assets/{asset_id}/restore").then(setHostTrash);
  }, []);
  const trash = useCallback(
    async (item: ViewerItem, restore = false): Promise<boolean> => {
      const req = trashRequest(item, fromLibrary, restore);
      try {
        const res = await fetch(`${API}${req.path}`, { method: req.method });
        if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
        console.info("[feed] trash", { id: item.id, restore, path: req.path });
        onLog(restore ? "Restored." : "Deleted. Undo is on its card.");
        return true;
      } catch (err) {
        console.warn("[feed] trash failed", { id: item.id, restore, err: String(err) });
        onLog(plainError(err));
        return false;
      }
    },
    [fromLibrary, onLog],
  );
  return fromLibrary || hostTrash ? trash : undefined;
}

type HowStep = { n: string; title: string; copy: string };

/**
 * Video empty state: three staged cards, not a row of bare text.
 *
 * Args:
 *   steps: The three how-it-works lines from the video page.
 */
function VideoHow({ steps, testId }: { steps: readonly HowStep[]; testId: string }) {
  const marks = ["prompt", "preset", "generate"] as const;
  return (
    <div className="video-how" data-testid={testId}>
      <header className="video-how-head">
        <p className="video-how-kicker">History</p>
        <h2>How it works</h2>
        <p>Your clips show up here. Write a prompt, pick a model, then Generate.</p>
      </header>
      <div className="video-how-row">
        {steps.map((step, index) => (
          <article key={step.n} className="video-how-card">
            <div className={"video-how-stage stage-" + marks[index]} aria-hidden="true">
              {marks[index] === "prompt" ? (
                <div className="vh-prompt">
                  <span />
                  <i />
                </div>
              ) : null}
              {marks[index] === "preset" ? (
                <div className="vh-tiles">
                  <span />
                  <span />
                  <span />
                  <span />
                </div>
              ) : null}
              {marks[index] === "generate" ? (
                <div className="vh-play">
                  <b>Generate</b>
                </div>
              ) : null}
            </div>
            <div className="video-how-copy">
              <span className="image-how-n">{step.n}</span>
              <strong>{step.title}</strong>
              <p>{step.copy}</p>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

/**
 * Masonry feed of the user's runs. Hover shows Higgsfield card actions; a click opens the viewer.
 *
 * Args:
 *   items: Pending cards first, then newest outputs.
 *   steps: Empty-state strip (Image or Video how-it-works).
 *   emptyLayout: `stage` is the Video history empty state.
 *   onFavorite / onCopyPrompt / onReference / onAnimate / onExtend / onMore / onRecreate: Card actions.
 *   onTrash: Delete a card, or Undo (`useFeedTrash`). A deleted card shows Undo until the feed reloads.
 *   modelName: A model id's display name, for the viewer.
 */
export function ImageFeed({
  items,
  steps = IMAGE_HOW_STEPS,
  emptyLayout = "plain",
  emptyTestId = "image-how",
  feedTestId = "image-feed",
  pendingTestId = "image-feed-pending",
  hoverTestId = "image-card-hover",
  clock,
  clocks,
  problems = [],
  onProblemAction,
  onFavorite,
  onCopyPrompt,
  onReference,
  onAnimate,
  onExtend,
  onMore,
  onRecreate,
  onTrash,
  modelName,
}: FeedActions & {
  items: ImageFeedItem[];
  steps?: readonly HowStep[];
  emptyLayout?: "plain" | "stage";
  emptyTestId?: string;
  feedTestId?: string;
  pendingTestId?: string;
  hoverTestId?: string;
  /** The run in flight: its pending cards fill a progress bar (COREPRODUC-659). */
  clock?: RunClock | null;
  /** One clock per pending card (a batch): card i uses clocks[i]; null shows "Waiting to start…". */
  clocks?: (RunClock | null)[];
  /** Runs that failed: each keeps a red card with its reason until the next Generate (COREPRODUC-692). */
  problems?: RunProblem[];
  /** Opens Credits or Connect from a failed card's button. */
  onProblemAction?: (action: RunAction) => void;
  onTrash?: (item: ViewerItem, restore?: boolean) => Promise<boolean>;
  modelName?: (id: string) => string;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  // Asset ids deleted here: every card of that file shows Undo until the feed reloads. A file, not a
  // card: on a host one file can be the output of several (cached) runs (CodeRabbit on #710).
  const [gone, setGone] = useState<string[]>([]);
  const shown = items.filter((item) => !item.pending && !gone.includes(item.assetId));
  const at = shown.findIndex((item) => item.id === openId);
  // An action that fills the prompt box also closes the viewer, so the box is in view.
  const closing = (act?: (item: ViewerItem) => void) => act && ((item: ViewerItem) => (act(item), setOpenId(null)));

  // One Delete or Undo request per file at a time: a late second Delete could mark a restored file
  // deleted again (CodeRabbit on #710).
  const busy = useRef(new Set<string>());
  async function trash(item: ViewerItem, restore = false) {
    if (!onTrash || busy.current.has(item.assetId)) return;
    busy.current.add(item.assetId);
    try {
      if (!(await onTrash(item, restore))) return;
      setGone((ids) => (restore ? ids.filter((id) => id !== item.assetId) : [...ids, item.assetId]));
    } finally {
      busy.current.delete(item.assetId);
    }
  }

  // A reload that leaves a deleted file out ends its Undo; a later run that makes it again shows it.
  useEffect(() => {
    setGone((ids) => {
      const kept = ids.filter((id) => items.some((item) => item.assetId === id));
      return kept.length === ids.length ? ids : kept;
    });
  }, [items]);

  if (!items.length && !problems.length && emptyLayout === "stage") {
    return <VideoHow steps={steps} testId={emptyTestId} />;
  }
  if (!items.length && !problems.length) {
    return (
      <div className="image-how" data-testid={emptyTestId}>
        {steps.map((step) => (
          <article key={step.n} className="image-how-step">
            <span className="image-how-n">{step.n}</span>
            <strong>{step.title}</strong>
            <p>{step.copy}</p>
          </article>
        ))}
      </div>
    );
  }
  return (
    <div className="image-feed" data-testid={feedTestId}>
      <div className="image-feed-cols">
        {problems.map((problem, i) => (
          <article key={`failed-${i}`} className="image-card failed" data-testid={`${pendingTestId}-failed`}>
            <div className="image-card-thumb">
              <ProblemNote problem={problem} onAction={onProblemAction} className="image-card-problem" />
            </div>
          </article>
        ))}
        {items.map((item, i) =>
          gone.includes(item.assetId) ? (
            <article key={item.id} className="image-card deleted" data-testid="feed-card-deleted">
              <div className="image-card-thumb">
                <span>Deleted</span>
                {/* Focus that was on the removed card (its trash icon, or the viewer closed before the delete ended) lands here. */}
                <button
                  type="button"
                  className="ghost"
                  ref={(el) => {
                    if (el && document.activeElement === document.body) el.focus({ preventScroll: true });
                  }}
                  onClick={() => void trash(item, true)}
                >
                  Undo
                </button>
              </div>
            </article>
          ) : item.pending ? (
            <article key={item.id} className="image-card pending" data-testid={pendingTestId}>
              <div className="image-card-thumb">
                {(clocks ? clocks[i] : clock) ? (
                  <GenProgress clock={(clocks ? clocks[i] : clock)!} testId={`${pendingTestId}-progress`} />
                ) : (
                  <>
                    <span className="spinner" aria-hidden="true" />
                    <span>{clocks ? "Waiting to start…" : "Generating…"}</span>
                  </>
                )}
              </div>
            </article>
          ) : (
            <article key={item.id} className="image-card">
              <div className="image-card-thumb">
                {item.mediaKind === "video" ? (
                  <video
                    src={fileUrl(item.assetId)}
                    muted
                    loop
                    playsInline
                    preload="metadata"
                    onMouseEnter={(ev) => void ev.currentTarget.play().catch(() => undefined)}
                    onMouseLeave={(ev) => {
                      ev.currentTarget.pause();
                      ev.currentTarget.currentTime = 0;
                    }}
                  />
                ) : (
                  <img src={fileUrl(item.assetId)} alt="" />
                )}
                <div className="image-card-hover" data-testid={hoverTestId}>
                  {/* Under the buttons, over the picture: a click opens the viewer (COREPRODUC-729; a new tab before, COREPRODUC-650 paid-8). */}
                  <button type="button" className="image-card-open" aria-label="Open" data-testid="image-card-open" onClick={() => setOpenId(item.id)} />
                  <button type="button" aria-label="Favorite" onClick={() => onFavorite(item)}>
                    {item.favorite ? "♥" : "♡"}
                  </button>
                  <a href={fileUrl(item.assetId)} download={`vinci-${item.assetId.slice(0, 12)}`} aria-label="Download">
                    ↓
                  </a>
                  <button type="button" className="icon-btn" aria-label="Copy prompt" onClick={() => onCopyPrompt(item)}>
                    <DockIcon d={DOCK_ICON.copy} />
                    <span className="dock-tip">Copy prompt</span>
                  </button>
                  {onReference ? (
                    <button type="button" className="icon-btn" aria-label="Use as reference" onClick={() => onReference(item)}>
                      <DockIcon d={DOCK_ICON.reference} />
                      <span className="dock-tip">Use as reference</span>
                    </button>
                  ) : null}
                  {onAnimate ? (
                    <button type="button" data-testid="image-animate" onClick={() => onAnimate(item)}>
                      Animate
                    </button>
                  ) : null}
                  {onExtend ? (
                    <button type="button" data-testid="video-extend" onClick={() => onExtend(item)}>
                      Extend
                    </button>
                  ) : null}
                  {onMore ? (
                    // It copies the file's vinci:// link, so it says so (it read "More" and opened nothing).
                    <button type="button" className="icon-btn" aria-label="Copy file link" onClick={() => onMore(item)}>
                      <DockIcon d={DOCK_ICON.link} />
                      <span className="dock-tip">Copy file link</span>
                    </button>
                  ) : null}
                  {onTrash ? (
                    <button type="button" className="icon-btn" aria-label="Delete" data-testid="feed-delete" onClick={() => void trash(item)}>
                      <DockIcon d={DOCK_ICON.trash} />
                      <span className="dock-tip">Delete</span>
                    </button>
                  ) : null}
                </div>
              </div>
            </article>
          ),
        )}
      </div>
      {at >= 0 ? (
        <MediaViewer
          item={shown[at]}
          url={fileUrl(shown[at].assetId)}
          modelName={modelName?.(shown[at].modelId) || shown[at].modelId}
          actions={{
            onFavorite,
            onCopyPrompt,
            onMore,
            onAnimate,
            onReference: closing(onReference),
            onExtend: closing(onExtend),
            onRecreate: closing(onRecreate),
          }}
          onDelete={
            onTrash
              ? () => {
                  setOpenId(shown[at + 1]?.id || shown[at - 1]?.id || null); // Higgsfield: the next card
                  void trash(shown[at]);
                }
              : undefined
          }
          onStep={(dir) => setOpenId(shown[(at + dir + shown.length) % shown.length].id)}
          onClose={() => setOpenId(null)}
        />
      ) : null}
    </div>
  );
}
