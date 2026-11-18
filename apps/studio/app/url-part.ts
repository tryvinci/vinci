"use client";

import { useEffect, useRef } from "react";

/**
 * The visible URL names the page and where in it you are: `#shows/lamp-oil-b1b8cc8b/cut/e01`,
 * `#video/motion-control`, `#library/elements`. A reload, Back and a shared link open the same place
 * (COREPRODUC-698; before, only the page was in the URL).
 */

/** The window whose URL the person sees: the host page around the Studio frame, else this one. */
export function topWindow(): Window {
  try {
    return window.top && window.top.location.href ? window.top : window;
  } catch {
    return window; // a frame from another origin
  }
}

/**
 * The page and the rest of the visible URL: `#shows/a-1/cut/e01` → ["shows", "a-1/cut/e01"]. With no
 * hash, `?page=library` names the page (as in `pageFromUrl`), with no part.
 */
export function urlParts(): [string, string] {
  if (typeof window === "undefined") return ["", ""];
  const { hash: raw, search } = topWindow().location;
  if (!raw.replace(/^#/, "")) return [new URLSearchParams(search).get("page") || "", ""];
  let hash = raw.replace(/^#/, "");
  try {
    hash = decodeURIComponent(hash);
  } catch {
    return ["", ""]; // a malformed hash names nothing
  }
  const [page, ...rest] = hash.split("/");
  return [page, rest.join("/")];
}

/**
 * Put `#<page>/<part>` in the visible URL.
 *
 * Args:
 *   page: The Studio page id.
 *   part: Where in the page ("" for the page itself).
 *   replace: Change the URL in place, with no new Back step.
 */
export function setUrlPart(page: string, part: string, replace = false): void {
  const w = topWindow();
  const hash = "#" + (part ? `${page}/${part}` : page);
  if (w.location.hash === hash) return;
  if (replace) w.history.replaceState(w.history.state, "", hash);
  else w.history.pushState(w.history.state, "", hash);
  console.info("[studio] url part", { page, part, replace });
}

/**
 * Keep a page's sub-view (a tab) in the URL: read it once from a link or a reload, write it when it
 * changes (a Back step) or when the page opens (in place), and follow Back and Forward.
 *
 * Args:
 *   page: The page id the part belongs to.
 *   active: The page is the one on screen (only then is the URL written).
 *   part: The sub-view now ("" for the default one).
 *   onPart: Shows the sub-view a URL names.
 */
export function useUrlPart(page: string, active: boolean, part: string, onPart: (part: string) => void): void {
  const onPartRef = useRef(onPart);
  onPartRef.current = onPart;
  const wasActive = useRef<boolean | null>(null); // null: the first run, which waits for the URL's own part
  useEffect(() => {
    const [named, rest] = urlParts();
    if (named === page && rest) onPartRef.current(rest);
    const onPop = () => {
      const [now, sub] = urlParts();
      if (now === page) onPartRef.current(sub);
    };
    const w = topWindow();
    w.addEventListener("popstate", onPop);
    return () => w.removeEventListener("popstate", onPop);
  }, [page]);
  useEffect(() => {
    const opened = wasActive.current === false && active;
    const first = wasActive.current === null;
    wasActive.current = active;
    if (first || !active) return;
    const [named, rest] = urlParts();
    if (named === page && rest !== part) setUrlPart(page, part, opened);
  }, [page, active, part]);
}
