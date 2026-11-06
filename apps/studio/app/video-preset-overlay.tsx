"use client";

import { useEffect, useState } from "react";
import {
  filterPresets,
  modelFamily,
  presetFilterChips,
  presetTabs,
  type VideoFeedItem,
  type VideoModel,
} from "../lib/video-page";
import { capabilityChips, modelBadges, modelBlurb } from "../lib/image-page";

const FILE = "/vinci-api/assets";

/**
 * Higgsfield Video Change overlay: model tabs, catalog chips, hover-play masonry.
 *
 * Cards are catalog video models. A History clip from that model plays on hover
 * when one exists; the catalog has no demo reels.
 *
 * Args:
 *   models: Video catalog rows.
 *   value: Selected model id.
 *   previews: User clips keyed by model id (hover-play only).
 *   onPick / onClose: Overlay events.
 */
export function VideoPresetOverlay({
  models,
  value,
  previews,
  onPick,
  onClose,
}: {
  models: VideoModel[];
  value: string;
  previews: Record<string, VideoFeedItem>;
  onPick: (id: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("All");
  const [chip, setChip] = useState("All");
  const [query, setQuery] = useState("");
  const tabs = presetTabs(models);
  const chips = presetFilterChips(models);
  const cards = filterPresets(models, tab, chip, query);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="video-overlay" data-testid="video-preset-overlay" role="dialog" aria-label="Video presets">
      <div className="video-overlay-bar">
        <div className="video-overlay-tabs">
          {tabs.map((name) => (
            <button
              key={name}
              type="button"
              className={name === tab ? "on" : ""}
              data-testid={name === "All" ? "video-preset-tab-all" : undefined}
              onClick={() => setTab(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <button type="button" className="ghost" data-testid="video-preset-close" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="video-overlay-filters">
        <input
          type="search"
          placeholder="Search presets"
          aria-label="Search presets"
          autoComplete="off"
          value={query}
          onChange={(ev) => setQuery(ev.target.value)}
        />
        <div className="video-overlay-chips">
          {chips.map((name) => (
            <button
              key={name}
              type="button"
              className={"image-chip" + (name === chip ? " on" : "")}
              data-testid={name === "All" ? "video-preset-chip-all" : `video-preset-chip-${name}`}
              onClick={() => setChip(name)}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      <div className="video-overlay-grid" data-testid="video-preset-grid">
        {cards.length === 0 ? <p className="muted">No presets match. Try another word.</p> : null}
        {cards.map((row) => {
          const preview = previews[row.id];
          const badges = modelBadges(row);
          const chipsRow = capabilityChips(row);
          return (
            <button
              key={row.id}
              type="button"
              className={"video-preset-card" + (row.id === value ? " on" : "")}
              data-testid="video-preset-card"
              onClick={() => onPick(row.id)}
            >
              <div className="video-preset-thumb">
                {preview ? (
                  <video
                    src={`${FILE}/${encodeURIComponent(preview.assetId)}/file`}
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
                  <span>{modelFamily(row)}</span>
                )}
              </div>
              <strong>{row.display_name}</strong>
              <span className="video-preset-blurb">{modelBlurb(row)}</span>
              <span className="image-picker-chips">
                {badges.map((b) => (
                  <span key={b} className="image-badge">
                    {b}
                  </span>
                ))}
                {chipsRow.map((c) => (
                  <span key={c}>{c}</span>
                ))}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
