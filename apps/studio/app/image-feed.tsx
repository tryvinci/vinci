"use client";

import { IMAGE_HOW_STEPS, type ImageFeedItem } from "../lib/image-page";
import { DockIcon, DOCK_ICON } from "./ui/icons";
import { GenProgress } from "./ui/gen-progress";
import { ProblemNote } from "./ui/problem-note";
import type { RunAction, RunProblem } from "./ui/plain-text";
import type { RunClock } from "../lib/progress";

const FILE = "/vinci-api/assets";

function fileUrl(assetId: string): string {
  return `${FILE}/${encodeURIComponent(assetId)}/file`;
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
 * Masonry feed of the user's runs. Hover shows Higgsfield card actions.
 *
 * Args:
 *   items: Pending cards first, then newest outputs.
 *   steps: Empty-state strip (Image or Video how-it-works).
 *   emptyLayout: `stage` is the Video history empty state.
 *   onFavorite / onCopyPrompt / onReference / onAnimate / onExtend / onMore: Card actions.
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
}: {
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
  onFavorite: (item: ImageFeedItem) => void;
  onCopyPrompt: (item: ImageFeedItem) => void;
  onReference?: (item: ImageFeedItem) => void;
  onAnimate?: (item: ImageFeedItem) => void;
  onExtend?: (item: ImageFeedItem) => void;
  /** Copy the file's vinci:// link. Off on a host: the link means nothing there, and Download is beside it. */
  onMore?: (item: ImageFeedItem) => void;
}) {
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
          item.pending ? (
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
                  {/* Under the buttons, over the picture: a click opens it full size (COREPRODUC-650 paid-8). */}
                  <a className="image-card-open" href={fileUrl(item.assetId)} target="_blank" rel="noreferrer" aria-label="Open full size" data-testid="image-card-open" />
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
                </div>
              </div>
            </article>
          ),
        )}
      </div>
    </div>
  );
}
