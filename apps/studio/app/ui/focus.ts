import { type RefObject, useEffect } from "react";

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Escape closes the open chip menu inside `root` and puts focus back on its chip (the element with
 * `aria-expanded="true"`). Bug fixed (first occurrence, 2026-11-13 production crawl, COREPRODUC-642):
 * Escape left the model list open on Image and Video.
 *
 * Args:
 *   root: The bar or panel that holds the chips and their menus.
 *   close: Closes the open menu.
 */
export function useMenuEscape(root: RefObject<HTMLElement | null>, close: () => void) {
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape") return;
      const chip = root.current?.querySelector<HTMLElement>('button[aria-expanded="true"]');
      if (!chip) return;
      close();
      chip.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [root, close]);
}

/**
 * Keep keyboard focus in a dialog while it is open: focus its first control, wrap Tab at both ends,
 * and on close give focus back to what had it when focus would fall to the page. Bug fixed (first
 * occurrence, 2026-11-13 production crawl, COREPRODUC-642): Tab left the Video presets panel for the
 * fields behind it.
 *
 * Args:
 *   root: The dialog element (mounted while the dialog is open).
 */
export function useDialogFocus(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const back = document.activeElement as HTMLElement | null;
    const items = () => [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => !x.hasAttribute("disabled"));
    if (!el.contains(document.activeElement)) items()[0]?.focus();
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== "Tab") return;
      const list = items();
      if (!list.length) return;
      const [first, last] = [list[0], list[list.length - 1]];
      const at = document.activeElement;
      if (!el.contains(at) || (ev.shiftKey && at === first) || (!ev.shiftKey && at === last)) {
        ev.preventDefault();
        (ev.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const lost = !document.activeElement || document.activeElement === document.body;
      if (lost && back?.isConnected) back.focus();
    };
  }, [root]);
}
