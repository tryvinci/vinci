"use client";

import { useEffect, useState } from "react";
import { filterMentions, type LibraryItem } from "../lib/library";

/**
 * Shared Higgsfield/Magnific @ list. Image, Video, and canvas nodes render this.
 *
 * Args:
 *   items: Mentionable library rows (same list on every surface).
 *   prompt / cursor: Live caret so the query filters as you type.
 *   onPick: Insert `@Name` and attach that item's refs.
 */
export function MentionPopover({
  items,
  prompt,
  cursor,
  onPick,
  onClose,
  testId = "mention-popover",
}: {
  items: readonly LibraryItem[];
  prompt: string;
  cursor: number;
  onPick: (item: LibraryItem) => void;
  onClose?: () => void;
  testId?: string;
}) {
  const rows = filterMentions(items, prompt, cursor);
  const [active, setActive] = useState(0);

  useEffect(() => {
    setActive(0);
  }, [prompt, cursor, rows.length]);

  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        setActive((n) => (rows.length ? (n + 1) % rows.length : 0));
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        setActive((n) => (rows.length ? (n - 1 + rows.length) % rows.length : 0));
      } else if (ev.key === "Enter" && rows[active]) {
        ev.preventDefault();
        onPick(rows[active]);
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        onClose?.();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [active, onClose, onPick, rows]);

  return (
    <div className="image-mention" data-testid={testId} role="listbox">
      {rows.length === 0 ? (
        <p className="muted">No people, places, or props yet. Add one in the Library.</p>
      ) : (
        rows.map((row, i) => (
          <button
            key={row.id + row.name}
            type="button"
            role="option"
            aria-selected={i === active}
            className={i === active ? "on" : ""}
            onClick={() => onPick(row)}
          >
            {row.refs[0] ? <img src={`/vinci-api/assets/${encodeURIComponent(row.refs[0])}/file`} alt="" /> : null}
            <strong>{row.name}</strong>
            <span>{row.kind}</span>
          </button>
        ))
      )}
    </div>
  );
}
