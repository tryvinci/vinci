"use client";

import { useRef, useState, type KeyboardEvent, type TextareaHTMLAttributes } from "react";
import { insertMention, mentionOpen, type LibraryItem } from "../lib/library";
import { MentionPopover } from "./mention-popover";

type Props = {
  items: readonly LibraryItem[];
  value: string;
  onChange: (value: string) => void;
  onPick?: (item: LibraryItem, next: { text: string; cursor: number }) => void;
  testId?: string;
  mentionTestId?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onMetaEnter?: () => void;
  textareaRef?: (el: HTMLTextAreaElement | null) => void;
} & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange">;

/**
 * Prompt textarea plus the shared MentionPopover.
 *
 * Typing @ opens the same list on Image, Video, canvas, and other prompt boxes.
 * Picking a row inserts `@Name`. The parent maps that item's refs onto the run.
 */
export function PromptMention({
  items,
  value,
  onChange,
  onPick,
  testId,
  mentionTestId,
  open,
  onOpenChange,
  onMetaEnter,
  textareaRef,
  onFocus,
  onBlur,
  ...rest
}: Props) {
  const [cursor, setCursor] = useState(value.length);
  const [localOpen, setLocalOpen] = useState(false);
  const innerRef = useRef<HTMLTextAreaElement | null>(null);
  const shown = open ?? localOpen;
  const setShown = onOpenChange || setLocalOpen;
  const show = shown && mentionOpen(value, cursor);

  function bind(el: HTMLTextAreaElement | null) {
    innerRef.current = el;
    textareaRef?.(el);
  }

  function setText(text: string, nextCursor: number) {
    onChange(text);
    setCursor(nextCursor);
    requestAnimationFrame(() => {
      const el = innerRef.current;
      if (!el) return;
      el.selectionStart = nextCursor;
      el.selectionEnd = nextCursor;
    });
  }

  function pick(item: LibraryItem) {
    const next = insertMention(value, cursor, item.name);
    setText(next.text, next.cursor);
    setShown(false);
    onPick?.(item, next);
  }

  function onKey(ev: KeyboardEvent<HTMLTextAreaElement>) {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      onMetaEnter?.();
      return;
    }
    if (ev.key === "@") setShown(true);
    rest.onKeyDown?.(ev);
  }

  return (
    <div className="prompt-mention">
      {show ? (
        <MentionPopover
          items={items}
          prompt={value}
          cursor={cursor}
          onPick={pick}
          onClose={() => setShown(false)}
          testId={mentionTestId}
        />
      ) : null}
      <textarea
        {...rest}
        data-testid={testId}
        ref={bind}
        value={value}
        onFocus={onFocus}
        onBlur={onBlur}
        onKeyDown={onKey}
        onSelect={(ev) => setCursor(ev.currentTarget.selectionStart || 0)}
        onChange={(ev) => {
          const text = ev.target.value;
          const pos = ev.target.selectionStart || text.length;
          onChange(text);
          setCursor(pos);
          setShown(mentionOpen(text, pos));
        }}
      />
    </div>
  );
}

/**
 * Insert `@` at the caret so the Image bar `@` chip can open the same popover.
 *
 * Args:
 *   prompt: Current text.
 *   cursor: Caret index.
 */
export function startMention(prompt: string, cursor: number): { text: string; cursor: number } {
  if (mentionOpen(prompt, cursor)) return { text: prompt, cursor };
  const text = prompt.slice(0, cursor) + "@" + prompt.slice(cursor);
  return { text, cursor: cursor + 1 };
}
