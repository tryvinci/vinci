"use client";

import { useMemo, useState } from "react";
import {
  APP_CATEGORIES,
  STUDIO_APPS,
  filterApps,
  type StudioApp,
} from "../lib/apps-catalog";
import { tabLabel } from "../lib/studio-shell";
import "./effects-shell.css";

type Props = {
  open: boolean;
  onClose: () => void;
  onPick: (app: StudioApp) => void;
};

/** Full-screen masonry overlay to pick another effect preset (Higgsfield Change). */
export function EffectsGalleryOverlay({ open, onClose, onPick }: Props) {
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");

  const visible = useMemo(() => filterApps(STUDIO_APPS, category, query), [category, query]);

  if (!open) return null;

  function pick(app: StudioApp) {
    onPick(app);
    onClose();
  }

  return (
    <div className="effects-overlay" data-testid="effects-gallery-overlay" role="dialog" aria-modal="true" aria-label="Change effect">
      <div className="effects-overlay-scrim" onClick={onClose} aria-hidden="true" />
      <div className="effects-overlay-panel">
        <header className="effects-overlay-head">
          <h2>Effects</h2>
          <button className="ghost" type="button" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="apps-toolbar">
          <div className="effects-chips" role="tablist" aria-label="Categories">
            {APP_CATEGORIES.map((cat) => (
              <button
                key={cat}
                type="button"
                role="tab"
                aria-selected={category === cat}
                className={category === cat ? "on" : ""}
                onClick={() => setCategory(cat)}
              >
                {tabLabel(cat)}
              </button>
            ))}
          </div>
          <input
            className="apps-search"
            type="search"
            placeholder="Search effects"
            aria-label="Search effects"
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
          />
        </div>
        {visible.length ? (
          <div className="apps-grid effects-overlay-grid">
            {visible.map((app) => (
              <button key={app.id} type="button" className="apps-card" onClick={() => pick(app)}>
                <div className="apps-thumb" aria-hidden="true">
                  <div className={`apps-thumb-art thumb-${app.id}`} />
                  <p className="apps-thumb-cat">{app.category}</p>
                </div>
                <div className="apps-card-copy">
                  <strong>{app.name}</strong>
                  <p>{app.description}</p>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <p className="apps-empty">No effects match. Try another word.</p>
        )}
      </div>
    </div>
  );
}
