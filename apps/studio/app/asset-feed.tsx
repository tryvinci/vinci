"use client";

import { libraryFileUrl, type LibraryItem } from "./library-types";

function kindLabel(kind: string): string {
  if (kind === "video") return "Video";
  if (kind === "audio") return "Audio";
  return "Image";
}

export function AssetFeed({
  items,
  pending,
  tool,
  onFavorite,
  onCopy,
  onReference,
  onAnimate,
}: {
  items: LibraryItem[];
  pending?: boolean;
  tool: "image" | "video";
  onFavorite: (item: LibraryItem) => void;
  onCopy: (item: LibraryItem) => void;
  onReference: (item: LibraryItem) => void;
  onAnimate?: (item: LibraryItem) => void;
}) {
  return (
    <div className="asset-feed" data-testid={`${tool}-feed`}>
      {pending ? (
        <article className="asset-feed-card pending" data-testid={`${tool}-feed-pending`}>
          <div className="asset-feed-thumb">
            <span className="assets-ph">Generating…</span>
          </div>
        </article>
      ) : null}
      {items.map((item) => (
        <article key={item.id} className="asset-feed-card">
          <div className="asset-feed-thumb">
            {item.media_missing ? (
              <span className="assets-ph">{kindLabel(item.media_kind)}</span>
            ) : item.media_kind === "video" ? (
              <video src={libraryFileUrl(item.id)} muted playsInline loop />
            ) : item.media_kind === "audio" ? (
              <span className="assets-ph">Audio</span>
            ) : (
              <img src={libraryFileUrl(item.id)} alt="" />
            )}
            <div className="asset-feed-hover">
              <button type="button" aria-label="Favorite" onClick={() => onFavorite(item)}>
                {item.favorite ? "♥" : "♡"}
              </button>
              <a
                href={libraryFileUrl(item.id)}
                download={`vinci-${item.asset_id.slice(0, 12) || item.id}`}
                aria-label="Download"
              >
                ↓
              </a>
              <button type="button" onClick={() => onCopy(item)}>
                Copy
              </button>
              <button type="button" onClick={() => onReference(item)}>
                Use as reference
              </button>
              {tool === "image" && onAnimate ? (
                <button type="button" onClick={() => onAnimate(item)}>
                  Animate
                </button>
              ) : null}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
