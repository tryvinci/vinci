export type LibraryItem = {
  id: string;
  asset_id: string;
  run_id: string;
  media_kind: string;
  mime: string;
  prompt: string;
  model_id: string;
  provider: string;
  params: Record<string, unknown>;
  source_ids: Record<string, unknown>;
  destination_kind: string;
  media_path: string;
  sidecar_path: string;
  photos_album?: string | null;
  saved_at: string;
  run_completed_at?: string | null;
  media_missing: boolean;
  local: boolean;
  favorite: boolean;
  trashed_at?: string | null;
  origin: string;
  enhanced: boolean;
  rerun_skill: string;
  rerun_page: string;
};

export type LibraryStatus = {
  library_exists: boolean;
  destination_kind: string;
  roots: { path: string; exists: boolean }[];
  total: number;
  reason: "empty" | "ready" | string;
};

export type LibraryFacets = {
  kinds: string[];
  models: { model_id: string; provider: string }[];
  providers: string[];
};

export type LibraryResponse = {
  items: LibraryItem[];
  facets: LibraryFacets;
  status: LibraryStatus;
  tool?: string | null;
  section?: string | null;
};

export const LIBRARY_API = "/vinci-api";

export function libraryFileUrl(id: string): string {
  return `${LIBRARY_API}/library/items/${encodeURIComponent(id)}/file`;
}

export function localDay(iso: string): string {
  if (!iso) return "unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "unknown";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function dateGroupLabel(key: string): string {
  if (key === "unknown") return "Unknown";
  const today = new Date();
  const ymd = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  if (key === ymd(today)) return "Today";
  const yest = new Date(today);
  yest.setDate(today.getDate() - 1);
  if (key === ymd(yest)) return "Yesterday";
  const parsed = new Date(`${key}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return key;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function groupLibraryItems(items: LibraryItem[]): { key: string; label: string; items: LibraryItem[] }[] {
  const buckets = new Map<string, LibraryItem[]>();
  for (const item of items) {
    const key = localDay(item.saved_at || item.run_completed_at || "");
    const list = buckets.get(key) || [];
    list.push(item);
    buckets.set(key, list);
  }
  return [...buckets.entries()].map(([key, rows]) => ({
    key,
    label: dateGroupLabel(key),
    items: rows,
  }));
}
