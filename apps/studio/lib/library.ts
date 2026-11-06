/**
 * Magnific Library + Higgsfield @mentions.
 *
 * Tabs copy Magnific: References (Characters, Elements, Styles, Locations,
 * Brand kit) and Custom (Templates, Flows). Typing @ inserts a Character,
 * Location, Element or Style. Brand kit stays on the Library page. Create is
 * name + 1-8 images. The chosen item's refs go on the provider request.
 * `soul_id` is forwarded only when an item already has one and the model is
 * Higgsfield Soul — Vinci does not host Soul IDs.
 */

export const LIBRARY_STORAGE_KEY = "vinci-library-v1";

/** Provider hard cap, same as Higgsfield Soul / popcorn image_urls. */
export const LIBRARY_REF_LIMIT = 8;

export type LibraryKind = "character" | "element" | "style" | "location" | "brand";

export type LibraryTab =
  | "characters"
  | "elements"
  | "styles"
  | "locations"
  | "brand-kit"
  | "templates"
  | "flows";

export type LibraryItem = {
  id: string;
  name: string;
  kind: LibraryKind;
  refs: string[];
  soulId?: string;
};

/** Prompt-bar row. `assetId` is the first ref so older Image/Video code still type-checks. */
export type MentionRow = {
  id?: string;
  name: string;
  assetId: string;
  kind?: string;
  refs?: string[];
  soulId?: string;
};

export const REF_TABS: { id: Exclude<LibraryTab, "templates" | "flows">; label: string; kind: LibraryKind }[] = [
  { id: "characters", label: "Characters", kind: "character" },
  { id: "elements", label: "Elements", kind: "element" },
  { id: "styles", label: "Styles", kind: "style" },
  { id: "locations", label: "Locations", kind: "location" },
  { id: "brand-kit", label: "Brand kit", kind: "brand" },
];

export const CUSTOM_TABS: { id: "templates" | "flows"; label: string }[] = [
  { id: "templates", label: "Templates" },
  { id: "flows", label: "Flows" },
];

export const LIBRARY_TABS: LibraryTab[] = [...REF_TABS.map((row) => row.id), ...CUSTOM_TABS.map((row) => row.id)];

/** Kinds Higgsfield/Magnific insert with @. Brand kit is page-only. */
export const MENTION_KINDS: LibraryKind[] = ["character", "element", "style", "location"];

/**
 * Map a stored or inspector kind onto Magnific Library kinds.
 *
 * `prop` was the old inspector label for Elements.
 *
 * Args:
 *   kind: Raw kind from cast or storage.
 * Returns:
 *   A Library kind. Missing values become character (the old default).
 */
export function kindFromLegacy(kind?: string): LibraryKind {
  if (kind === "prop") return "element";
  if (kind === "character" || kind === "element" || kind === "style" || kind === "location" || kind === "brand") {
    return kind;
  }
  return "character";
}

/**
 * Kind for a reference tab. Custom tabs have no create kind.
 *
 * Args:
 *   tab: Library tab id.
 */
export function tabKind(tab: LibraryTab): LibraryKind | null {
  return REF_TABS.find((row) => row.id === tab)?.kind || null;
}

function slug(name: string): string {
  const base = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return base || "item";
}

/**
 * Normalize a cast/mention row into a Library item.
 *
 * Args:
 *   row: Current cast, a stored item, or a mention row.
 */
export function asLibraryItem(row: MentionRow | LibraryItem | { name: string; assetId?: string; refs?: string[]; kind?: string; id?: string; soulId?: string }): LibraryItem {
  const listed = "refs" in row && Array.isArray(row.refs) ? row.refs : [];
  const fallback = "assetId" in row && typeof row.assetId === "string" ? [row.assetId] : [];
  const refs = [...new Set((listed.length ? listed : fallback).filter((id): id is string => Boolean(id)))].slice(
    0,
    LIBRARY_REF_LIMIT,
  );
  return {
    id: row.id || slug(row.name),
    name: row.name,
    kind: kindFromLegacy(row.kind),
    refs,
    soulId: row.soulId,
  };
}

/** Cast snapshot shape used by Collab. */
export function asCastRow(item: LibraryItem): MentionRow {
  return {
    id: item.id,
    name: item.name,
    assetId: item.refs[0] || "",
    kind: item.kind,
    refs: item.refs,
    soulId: item.soulId,
  };
}

/** Items the shared @ popover lists. */
export function mentionableItems(items: readonly LibraryItem[]): LibraryItem[] {
  return items.filter((row) => MENTION_KINDS.includes(row.kind));
}

/**
 * Items on one Library tab.
 *
 * Args:
 *   items: Full library.
 *   tab: Active tab.
 */
export function itemsForTab(items: readonly LibraryItem[], tab: LibraryTab): LibraryItem[] {
  const kind = tabKind(tab);
  if (!kind) return [];
  return items.filter((row) => row.kind === kind);
}

/**
 * Create a Library item. Name + 1-8 images, matching Magnific create.
 *
 * Args:
 *   input: Name, kind, refs, optional existing soul id.
 */
export function createLibraryItem(input: {
  name: string;
  kind: LibraryKind;
  refs: readonly string[];
  soulId?: string;
  id?: string;
}): { ok: true; item: LibraryItem } | { ok: false; error: string } {
  const name = input.name.trim();
  if (!name) return { ok: false, error: "Name the item." };
  const refs = [...new Set(input.refs.filter(Boolean))].slice(0, LIBRARY_REF_LIMIT);
  if (refs.length < 1 || refs.length > LIBRARY_REF_LIMIT) return { ok: false, error: "Add 1 to 8 images." };
  return {
    ok: true,
    item: { id: input.id || slug(name), name, kind: input.kind, refs, soulId: input.soulId },
  };
}

/**
 * Replace an item with the same id or name.
 *
 * Args:
 *   items: Current library.
 *   item: Created or edited row.
 */
export function upsertLibraryItem(items: readonly LibraryItem[], item: LibraryItem): LibraryItem[] {
  return [...items.filter((row) => row.id !== item.id && row.name.toLowerCase() !== item.name.toLowerCase()), item];
}

/**
 * Insert `@Name` at the cursor after a typed `@`.
 *
 * Args:
 *   prompt: Current text.
 *   cursor: Caret index.
 *   name: Library item name.
 */
export function insertMention(prompt: string, cursor: number, name: string): { text: string; cursor: number } {
  const at = prompt.lastIndexOf("@", Math.max(0, cursor - 1));
  const start = at >= 0 ? at : cursor;
  let end = cursor;
  if (at >= 0) {
    const rest = prompt.slice(at + 1);
    const stop = rest.search(/\s/);
    end = stop < 0 ? prompt.length : at + 1 + stop;
  }
  const token = `@${name}`;
  const text = prompt.slice(0, start) + token + prompt.slice(end);
  return { text, cursor: start + token.length };
}

/** True when the caret is in an `@` token so the popover should open. */
export function mentionOpen(prompt: string, cursor: number): boolean {
  const at = prompt.lastIndexOf("@", Math.max(0, cursor - 1));
  if (at < 0) return false;
  const token = prompt.slice(at, cursor);
  return !token.includes(" ") && !token.includes("\n");
}

/**
 * Filter mentionable rows whose name contains the `@` query.
 *
 * Args:
 *   rows: Library or mention rows.
 *   prompt: Current text.
 *   cursor: Caret index.
 */
export function filterMentions<T extends { name: string }>(rows: readonly T[], prompt: string, cursor: number): T[] {
  const at = prompt.lastIndexOf("@", Math.max(0, cursor - 1));
  const q = (at >= 0 ? prompt.slice(at + 1, cursor) : "").toLowerCase();
  return rows.filter((row) => !q || row.name.toLowerCase().includes(q));
}

/**
 * Library items named by `@token`s in the prompt.
 *
 * Args:
 *   prompt: Prompt text.
 *   items: Full library.
 */
export function mentionedItems(prompt: string, items: readonly LibraryItem[]): LibraryItem[] {
  const names = new Set(
    [...prompt.matchAll(/@([^\s@]+)/g)].map((hit) => hit[1].toLowerCase()),
  );
  return mentionableItems(items).filter((row) => names.has(row.name.toLowerCase()));
}

/**
 * Refs for the provider request: explicit stills, then the chosen items' refs.
 *
 * Args:
 *   prompt: Prompt with `@Name` tokens.
 *   items: Full library.
 *   extra: +reference / start-frame stills already on the form.
 */
export function mentionRefs(prompt: string, items: readonly LibraryItem[], extra: readonly string[] = []): string[] {
  const urls: string[] = [];
  for (const id of extra) {
    if (id && !urls.includes(id)) urls.push(id);
  }
  for (const item of mentionedItems(prompt, items)) {
    for (const id of item.refs) {
      if (id && !urls.includes(id)) urls.push(id);
      if (urls.length >= LIBRARY_REF_LIMIT) return urls.slice(0, LIBRARY_REF_LIMIT);
    }
  }
  return urls.slice(0, LIBRARY_REF_LIMIT);
}

/** Magnific inspector role for a Library kind. Style → style; everything else → character. */
export function mentionRole(kind: LibraryKind): "style" | "character" {
  return kind === "style" ? "style" : "character";
}

/**
 * Map mentioned items onto provider inputs.
 *
 * Every provider gets `image_urls`. Higgsfield Soul also gets `soul_id` when
 * the chosen character already has one. No Soul id is invented.
 *
 * Args:
 *   prompt: Prompt with `@Name` tokens.
 *   items: Full library.
 *   model: Selected catalog row.
 *   extraRefs: Form stills that are not library items.
 */
export function providerMentionInputs(
  prompt: string,
  items: readonly LibraryItem[],
  model?: { id?: string; provider?: string },
  extraRefs: readonly string[] = [],
): { image_urls: string[]; soul_id?: string } {
  const image_urls = mentionRefs(prompt, items, extraRefs);
  const soul = mentionedItems(prompt, items).find((row) => row.soulId);
  const blob = `${model?.id || ""} ${model?.provider || ""}`.toLowerCase();
  if (soul?.soulId && blob.includes("higgsfield") && blob.includes("soul")) {
    console.info("[library] mention map soul", { name: soul.name, soulId: soul.soulId, model: model?.id });
    return { image_urls, soul_id: soul.soulId };
  }
  console.info("[library] mention map refs", { count: image_urls.length, model: model?.id });
  return { image_urls };
}

/**
 * Read persisted Library items. Invalid JSON is an empty library.
 *
 * Args:
 *   raw: localStorage value.
 */
export function parseLibraryStore(raw: string | null): LibraryItem[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((row) => row && typeof row === "object" && typeof (row as { name?: unknown }).name === "string")
      .map((row) => asLibraryItem(row as MentionRow));
  } catch {
    return [];
  }
}

/** Persist Library items. */
export function serializeLibraryStore(items: readonly LibraryItem[]): string {
  return JSON.stringify(items.map((row) => asLibraryItem(row)));
}
