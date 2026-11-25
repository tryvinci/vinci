"use client";

import { useEffect, useState } from "react";

/** Theme key in localStorage. layout.tsx reads it before paint, so the page does not flash. */
export const THEME_KEY = "vinci-theme";

const SUN = "M9 5.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM9 1.5v1.5M9 15v1.5M1.5 9H3M15 9h1.5M3.7 3.7l1 1M13.3 13.3l1 1M3.7 14.3l1-1M13.3 4.7l1-1";
const MOON = "M14.5 10.6A6 6 0 0 1 7.4 3.5a6 6 0 1 0 7.1 7.1z";

/**
 * Rail switch between Paper (light, default) and Graphite (dark).
 *
 * Sets `html[data-theme]` (theme.css) and saves the choice. Storage can throw in a sandboxed
 * frame: then the switch still works for this visit.
 */
export function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.dataset.theme === "graphite"), []);
  const flip = () => {
    const next = dark ? "paper" : "graphite";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      console.warn("[vinci] theme: localStorage unavailable; theme kept for this visit only");
    }
    setDark(!dark);
  };
  return (
    <button type="button" className="rail-theme" aria-label={dark ? "Use light theme" : "Use dark theme"} aria-pressed={dark} onClick={flip} data-testid="theme-toggle">
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
        <path d={dark ? SUN : MOON} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="rail-label">{dark ? "Light" : "Dark"}</span>
    </button>
  );
}
