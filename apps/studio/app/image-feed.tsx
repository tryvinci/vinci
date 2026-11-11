"use client";

import { IMAGE_HOW_STEPS, type ImageFeedItem } from "../lib/image-page";
import { DockIcon, DOCK_ICON } from "./ui/icons";

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
  onFavorite: (item: ImageFeedItem) => void;
  onCopyPrompt: (item: ImageFeedItem) => void;
  onReference?: (item: ImageFeedItem) => void;
  onAnimate?: (item: ImageFeedItem) => void;
  onExtend?: (item: ImageFeedItem) => void;
  onMore: (item: ImageFeedItem) => void;
}) {
  if (!items.length && emptyLayout === "stage") {
    return <VideoHow steps={steps} testId={emptyTestId} />;
  }
  if (!items.length) {
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
        {items.map((item) =>
          item.pending ? (
            <article key={item.id} className="image-card pending" data-testid={pendingTestId}>
              <div className="image-card-thumb">
                <span className="spinner" aria-hidden="true" />
                <span>Generating…</span>
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
                  <button type="button" className="icon-btn" aria-label="More" onClick={() => onMore(item)}>
                    <DockIcon d={DOCK_ICON.more} />
                    <span className="dock-tip">More</span>
                  </button>
                </div>
              </div>
            </article>
          ),
        )}
      </div>
    </div>
  );
}
