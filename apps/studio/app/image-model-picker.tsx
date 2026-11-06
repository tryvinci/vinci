"use client";

import {
  capabilityChips,
  modelBadges,
  modelBlurb,
  pickerSections,
  searchImageModels,
  type ImageModel,
} from "../lib/image-page";

/**
 * Upward model picker: search, Featured, All, one-line blurbs, badges, chips.
 *
 * Args:
 *   models: Image catalog rows.
 *   value: Selected model id.
 *   query: Search text.
 *   onQuery / onPick / onClose: Picker events.
 */
export function ImageModelPicker({
  models,
  value,
  query,
  onQuery,
  onPick,
}: {
  models: ImageModel[];
  value: string;
  query: string;
  onQuery: (q: string) => void;
  onPick: (id: string) => void;
}) {
  const hits = searchImageModels(models, query);
  const { featured, all } = pickerSections(hits);
  return (
    <div className="image-picker" data-testid="image-model-picker" role="listbox" aria-label="Image models">
      <input
        className="image-picker-search"
        type="search"
        placeholder="Search models"
        aria-label="Search models"
        autoComplete="off"
        value={query}
        onChange={(ev) => onQuery(ev.target.value)}
      />
      {hits.length === 0 ? <p className="muted">No models match. Try another word.</p> : null}
      {featured.length ? <PickerGroup title="Featured" models={featured} value={value} onPick={onPick} /> : null}
      {all.length ? <PickerGroup title="All" models={all} value={value} onPick={onPick} /> : null}
    </div>
  );
}

function PickerGroup({
  title,
  models,
  value,
  onPick,
}: {
  title: string;
  models: ImageModel[];
  value: string;
  onPick: (id: string) => void;
}) {
  return (
    <section>
      <h3>{title}</h3>
      {models.map((row) => {
        const badges = modelBadges(row);
        const chips = capabilityChips(row);
        return (
          <button
            key={row.id}
            type="button"
            role="option"
            aria-selected={row.id === value}
            className={"image-picker-row" + (row.id === value ? " on" : "")}
            onClick={() => onPick(row.id)}
          >
            <span className="image-picker-lead">
              <strong>{row.display_name}</strong>
              {badges.map((b) => (
                <span key={b} className="image-badge">
                  {b}
                </span>
              ))}
            </span>
            <span className="image-picker-blurb">{modelBlurb(row)}</span>
            {chips.length ? (
              <span className="image-picker-chips">
                {chips.map((c) => (
                  <span key={c}>{c}</span>
                ))}
              </span>
            ) : null}
          </button>
        );
      })}
    </section>
  );
}
