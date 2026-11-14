"use client";

import { useMemo } from "react";
import {
  ADD_CHIPS,
  buildAddMenu,
  flattenAddMenu,
  type AddChipId,
  type AddMenuRow,
  type AddModel,
  type AddPick,
  type AddTemplate,
  type MediaKind,
} from "../lib/canvas-graph";

type Props = {
  x: number;
  y: number;
  query: string;
  index: number;
  chip: AddChipId | null;
  takes?: MediaKind | null;
  models: AddModel[];
  templates: AddTemplate[];
  /** On a host: false for a node no model can run (see `buildAddMenu`). */
  canAdd?: (capability: string) => boolean;
  onQuery: (value: string) => void;
  onIndex: (value: number) => void;
  onChip: (chip: AddChipId | null) => void;
  onPick: (pick: AddPick) => void;
  onClose: () => void;
};

/**
 * Magnific add-node popover: search, chips, Media / Nodes / providers / Flows, ↑↓ + ⏎.
 */
export function CanvasAddMenu({
  x,
  y,
  query,
  index,
  chip,
  takes,
  models,
  templates,
  canAdd,
  onQuery,
  onIndex,
  onChip,
  onPick,
  onClose,
}: Props) {
  const sections = useMemo(
    () => buildAddMenu(query, { chip, takes, models, templates, canAdd }),
    [query, chip, takes, models, templates, canAdd],
  );
  const rows = useMemo(() => flattenAddMenu(sections), [sections]);
  const pick = rows[Math.min(index, Math.max(0, rows.length - 1))];

  function move(step: number) {
    if (!rows.length) return;
    const at = Math.min(index, rows.length - 1);
    const next = (at + step + rows.length) % rows.length;
    onIndex(next);
    document.getElementById("add-menu-list")?.querySelectorAll("[role='option']")[next]?.scrollIntoView({ block: "nearest" });
  }

  function cycleChip(step: number) {
    const ids = ADD_CHIPS.map((row) => row.id);
    if (!chip) {
      onChip(step > 0 ? ids[0] : ids[ids.length - 1]);
      return;
    }
    const at = ids.indexOf(chip);
    const next = at + step;
    onChip(next < 0 || next >= ids.length ? null : ids[next]);
  }

  return (
    <div
      className="add-menu"
      role="dialog"
      aria-label="Add node"
      data-testid="add-menu"
      style={{ left: x, top: y }}
      onPointerDown={(ev) => ev.stopPropagation()}
    >
      <input
        autoFocus
        placeholder={takes ? `Steps that take ${takes}` : "Search steps"}
        value={query}
        aria-controls="add-menu-list"
        data-testid="add-menu-search"
        onChange={(ev) => {
          onQuery(ev.target.value);
          onIndex(0);
        }}
        onKeyDown={(ev) => {
          if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            move(ev.key === "ArrowDown" ? 1 : -1);
          } else if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
            ev.preventDefault();
            onIndex(0);
            cycleChip(ev.key === "ArrowRight" ? 1 : -1);
          } else if (ev.key === "Enter" && pick && !ev.nativeEvent.isComposing) {
            ev.preventDefault();
            onPick(pick.pick);
          } else if (ev.key === "Escape") {
            ev.preventDefault();
            onClose();
          }
        }}
      />
      <div className="add-chips" role="tablist" aria-label="Filter">
        {ADD_CHIPS.map((row) => (
          <button
            key={row.id}
            type="button"
            role="tab"
            aria-selected={chip === row.id}
            className={chip === row.id ? "on" : ""}
            data-testid={`add-chip-${row.id}`}
            onClick={() => {
              onChip(chip === row.id ? null : row.id);
              onIndex(0);
            }}
          >
            {row.label}
          </button>
        ))}
      </div>
      <div className="add-list" id="add-menu-list" role="listbox">
        {sections.map((section) => (
          <section key={section.id} className="add-section" data-section={section.id}>
            <p className="add-sec">{section.label}</p>
            {section.rows.map((row, i, list) => {
              const showVendor = Boolean(row.vendor && (i === 0 || list[i - 1]?.vendor !== row.vendor));
              return (
                <AddRowButton
                  key={row.id}
                  row={row}
                  selected={row === pick}
                  showVendor={showVendor}
                  onHover={() => onIndex(rows.indexOf(row))}
                  onPick={() => onPick(row.pick)}
                />
              );
            })}
          </section>
        ))}
        {!rows.length ? <p className="muted">Nothing matches. Clear the filter or try another word.</p> : null}
      </div>
      <p className="add-hint">
        <kbd>↑↓</kbd> move <kbd>←→</kbd> filter <kbd>⏎</kbd> add <kbd>Esc</kbd> close
      </p>
    </div>
  );
}

function AddRowButton({
  row,
  selected,
  showVendor,
  onHover,
  onPick,
}: {
  row: AddMenuRow;
  selected: boolean;
  showVendor: boolean;
  onHover: () => void;
  onPick: () => void;
}) {
  return (
    <>
      {showVendor ? (
        <p className="add-vendor">
          {row.vendor} <span>{row.vendorCount}</span>
        </p>
      ) : null}
      <button
        type="button"
        role="option"
        aria-selected={selected}
        className={selected ? "on" : ""}
        data-testid="add-row"
        data-add={row.id}
        onMouseMove={(ev) => {
          if (ev.movementX || ev.movementY) onHover();
        }}
        onClick={onPick}
      >
        <span className={"kind-dot kind-" + (row.output || "none")} />
        <span className="what">
          <strong>{row.label}</strong>
          <span>{row.blurb}</span>
        </span>
      </button>
    </>
  );
}
