"use client";

import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { inheritQueryMatches, rankModels, type ModelSearchRow } from "../lib/model-search";

export type ComboModel = ModelSearchRow & { label: string };

type Item = { id: string; label: string };

type Props = {
  inputId: string;
  models: ComboModel[];
  value: string;
  onChange: (id: string) => void;
  blankLabel?: string;
};

function placeList(input: HTMLInputElement, list: HTMLUListElement): void {
  const box = input.getBoundingClientRect();
  const spaceBelow = window.innerHeight - box.bottom;
  const spaceAbove = box.top;
  const openUp = spaceBelow < 240 && spaceAbove > spaceBelow;
  const room = Math.max(120, Math.min(240, (openUp ? spaceAbove : spaceBelow) - 8));
  list.style.left = `${box.left}px`;
  list.style.width = `${box.width}px`;
  list.style.maxHeight = `${room}px`;
  if (openUp) {
    list.style.top = "auto";
    list.style.bottom = `${window.innerHeight - box.top + 4}px`;
  } else {
    list.style.bottom = "auto";
    list.style.top = `${box.bottom + 4}px`;
  }
}

function itemsFor(models: ComboModel[], query: string, blankLabel?: string): Item[] {
  const ranked = rankModels(models, query);
  const items: Item[] = [];
  if (blankLabel && inheritQueryMatches(query)) items.push({ id: "", label: blankLabel });
  for (const row of ranked) items.push({ id: row.id, label: row.label });
  return items;
}

/** Type-ahead model picker. The list is position:fixed so overflow on the stack and drawer does not clip it. */
export function ModelCombo({ inputId, models, value, onChange, blankLabel }: Props) {
  const listId = `${inputId}-list`;
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const selected = models.find((row) => row.id === value);
  const selectedLabel = blankLabel && value === "" ? blankLabel : selected?.label || "";
  const items = itemsFor(models, editing ? query : "", blankLabel);
  const shown = editing ? query : selectedLabel;

  useLayoutEffect(() => {
    if (!open) return;
    const input = inputRef.current;
    const list = listRef.current;
    if (!input || !list) return;
    placeList(input, list);
  }, [open, items, query, shown]);

  useEffect(() => {
    if (!open) return;
    const onPlace = () => {
      const input = inputRef.current;
      const list = listRef.current;
      if (!input || !list) return;
      placeList(input, list);
    };
    const onDown = (ev: PointerEvent) => {
      if (!rootRef.current?.contains(ev.target as Node)) {
        setOpen(false);
        setEditing(false);
      }
    };
    window.addEventListener("scroll", onPlace, true);
    window.addEventListener("resize", onPlace);
    document.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("scroll", onPlace, true);
      window.removeEventListener("resize", onPlace);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    document.getElementById(`${listId}-opt-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active, listId, open, items.length]);

  function pick(id: string) {
    setOpen(false);
    setEditing(false);
    setQuery("");
    if (id !== value) onChange(id);
    inputRef.current?.blur();
  }

  function onKey(ev: KeyboardEvent<HTMLInputElement>) {
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      setActive((i) => Math.min(Math.max(items.length - 1, 0), i + 1));
      return;
    }
    if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setActive((i) => Math.max(0, i - 1));
      return;
    }
    if (ev.key === "Enter") {
      if (!open) return;
      ev.preventDefault();
      const item = items[active];
      if (item) pick(item.id);
      return;
    }
    if (ev.key === "Escape") {
      ev.preventDefault();
      setOpen(false);
      setEditing(false);
    }
  }

  return (
    <div className="model-combo" ref={rootRef}>
      <input
        id={inputId}
        ref={inputRef}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && items[active] ? `${listId}-opt-${active}` : undefined}
        autoComplete="off"
        value={shown}
        onPointerDown={() => {
          if (!editing) requestAnimationFrame(() => inputRef.current?.select());
        }}
        onFocus={(ev) => {
          setEditing(false);
          setOpen(true);
          const ids = itemsFor(models, "", blankLabel).map((item) => item.id);
          const idx = ids.indexOf(value);
          setActive(idx >= 0 ? idx : 0);
          ev.currentTarget.select();
        }}
        onChange={(ev) => {
          setEditing(true);
          setQuery(ev.target.value);
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={onKey}
        onBlur={() => {
          setOpen(false);
          setEditing(false);
        }}
      />
      <ul id={listId} ref={listRef} className="model-combo-list" role="listbox" hidden={!open}>
        {open && items.length === 0 ? <li className="model-combo-empty">No matches</li> : null}
        {open
          ? items.map((item, i) => (
              <li
                key={`${item.id}:${i}`}
                id={`${listId}-opt-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "on" : ""}
                onPointerDown={(ev) => {
                  ev.preventDefault();
                  const startY = ev.clientY;
                  let moved = false;
                  const clear = () => {
                    window.removeEventListener("pointermove", onMove);
                    window.removeEventListener("pointerup", onUp);
                    window.removeEventListener("pointercancel", onCancel);
                  };
                  const onMove = (move: PointerEvent) => {
                    if (Math.abs(move.clientY - startY) > 6) moved = true;
                  };
                  const onUp = () => {
                    clear();
                    if (!moved) pick(item.id);
                  };
                  const onCancel = () => {
                    clear();
                  };
                  window.addEventListener("pointermove", onMove);
                  window.addEventListener("pointerup", onUp);
                  window.addEventListener("pointercancel", onCancel);
                }}
              >
                {item.label}
              </li>
            ))
          : null}
      </ul>
    </div>
  );
}
