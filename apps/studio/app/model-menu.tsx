"use client";

import { useState } from "react";
import { priceText } from "../lib/model-capabilities";
import { modelBadges } from "../lib/image-page";
import { menuChips, menuFamily, menuFilters, menuSections, type MenuModel } from "../lib/model-menu";

const OPEN_ALL_UP_TO = 15; // a short catalog shows every group open; a long one only the selected family

/**
 * The model menu (COREPRODUC-666), after Magnific's: search on top, family and feature filters,
 * Featured, then every model grouped by family. One line per model: name, chips, price. No previews.
 *
 * Args:
 *   models: Catalog rows (image or video).
 *   value: The selected model id.
 *   onPick: A row was picked.
 *   query / onQuery: The search, when the parent keeps it; else the menu keeps its own.
 *   rowTestId: Test id of each model row.
 */
export function ModelMenu({
  models,
  value,
  onPick,
  query: shared,
  onQuery,
  rowTestId,
}: {
  models: MenuModel[];
  value: string;
  onPick: (id: string) => void;
  query?: string;
  onQuery?: (q: string) => void;
  rowTestId?: string;
}) {
  const [own, setOwn] = useState("");
  const [family, setFamily] = useState("All");
  const [feature, setFeature] = useState("All");
  const [opened, setOpened] = useState<Record<string, boolean>>({});
  const query = shared ?? own;
  const setQuery = onQuery ?? setOwn;
  const filters = menuFilters(models);
  const { featured, groups } = menuSections(models, query, family, feature);
  const narrowed = Boolean(query.trim()) || family !== "All" || feature !== "All";
  const mine = models.find((m) => m.id === value);
  const isOpen = (name: string) =>
    narrowed || (opened[name] ?? (models.length <= OPEN_ALL_UP_TO || (mine ? menuFamily(mine) === name : false)));
  const row = (m: MenuModel) => (
    <button
      key={m.id}
      type="button"
      role="option"
      aria-selected={m.id === value}
      className={"model-menu-row" + (m.id === value ? " on" : "")}
      data-testid={rowTestId}
      onClick={() => onPick(m.id)}
    >
      <span className="model-menu-name">
        {m.display_name}
        {modelBadges(m).map((b) => (
          <span key={b} className="image-badge">
            {b}
          </span>
        ))}
      </span>
      <span className="model-menu-chips">
        {menuChips(m).map((c) => (
          <span key={c}>{c}</span>
        ))}
      </span>
      <span className="image-picker-price" data-testid="model-price">
        {priceText(m)}
      </span>
    </button>
  );
  return (
    <div className="model-menu" data-testid="model-menu">
      <input
        className="model-menu-search"
        type="search"
        placeholder="Search models"
        aria-label="Search models"
        autoComplete="off"
        autoFocus
        value={query}
        onChange={(ev) => setQuery(ev.target.value)}
      />
      {[
        { name: "family", values: filters.families, current: family, set: setFamily },
        { name: "feature", values: filters.features, current: feature, set: setFeature },
      ]
        .filter((f) => f.values.length > 2)
        .map((f) => (
          <div key={f.name} className="model-menu-filters" role="group" aria-label={f.name === "family" ? "Families" : "Features"}>
            {f.values.map((v) => (
              <button
                key={v}
                type="button"
                className={"image-chip" + (f.current === v ? " on" : "")}
                aria-pressed={f.current === v}
                data-testid={`model-menu-${f.name}-${v}`}
                onClick={() => f.set(v)}
              >
                {v === "All" ? (f.name === "family" ? "All families" : "Any feature") : v}
              </button>
            ))}
          </div>
        ))}
      {!featured.length && !groups.length ? <p className="muted">No models match. Try another word or filter.</p> : null}
      {featured.length ? (
        <section>
          <h3>Featured</h3>
          {featured.map(row)}
        </section>
      ) : null}
      {groups.length ? (
        <section>
          <h3>All models</h3>
          {groups.map((g) => (
            <div key={g.family} className="model-menu-group">
              <button
                type="button"
                className="model-menu-group-head"
                aria-expanded={isOpen(g.family)}
                data-testid={`model-menu-group-${g.family}`}
                onClick={() => setOpened((prev) => ({ ...prev, [g.family]: !isOpen(g.family) }))}
              >
                <strong>{g.family}</strong>
                <span>{g.models.length === 1 ? "1 model" : `${g.models.length} models`}</span>
                <span aria-hidden="true">{isOpen(g.family) ? "▴" : "▾"}</span>
              </button>
              {isOpen(g.family) ? g.models.map(row) : null}
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
}
