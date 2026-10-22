export type ModelSearchRow = {
  id: string;
  display_name?: string;
  provider?: string;
};

/** Rank catalog rows for the model combobox and gallery search.

 * Empty query keeps the incoming order. A typed query matches
 * display_name, then provider, then id. HTML Studio copies this
 * function because studio.html cannot import this module.
 */
export function rankModels<T extends ModelSearchRow>(rows: readonly T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return rows.slice();
  const scored: { row: T; rank: number; index: number }[] = [];
  rows.forEach((row, index) => {
    const name = (row.display_name || "").toLowerCase();
    const provider = (row.provider || "").toLowerCase();
    const id = (row.id || "").toLowerCase();
    let rank = 4;
    if (name.startsWith(q)) rank = 0;
    else if (name.includes(q)) rank = 1;
    else if (provider.includes(q)) rank = 2;
    else if (id.includes(q)) rank = 3;
    if (rank < 4) scored.push({ row, rank, index });
  });
  scored.sort((a, b) => a.rank - b.rank || a.index - b.index);
  return scored.map((item) => item.row);
}

export type ModelAvailability = "ready" | "spend_off" | "not_enabled" | "needs_key";

/** Why a catalog row can or cannot run.

 * ready: provider is enabled, its key resolves, and live spend is on.
 * spend_off: the model is available, but VINCI_ALLOW_LIVE_SPEND is not 1.
 * not_enabled: a key is saved and the provider is not enabled.
 * needs_key: no secret resolved. HTML Studio copies this function.
 */
export function modelAvailability(
  model: { provider?: string; available?: boolean } | undefined,
  provider: { configured?: boolean } | undefined,
  liveSpend: boolean,
): ModelAvailability {
  if (!model || model.provider === "mock") return "ready";
  if (model.available && liveSpend) return "ready";
  if (model.available) return "spend_off";
  if (provider?.configured) return "not_enabled";
  return "needs_key";
}

export function availabilityRank(status: ModelAvailability): number {
  if (status === "ready") return 0;
  if (status === "spend_off") return 1;
  if (status === "not_enabled") return 2;
  return 3;
}

/** Blank "inherit skill default" row stays visible only for those words. */
export function inheritQueryMatches(query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return ["inherit", "default", "skill", "inherit skill default"].some((word) => word.includes(q));
}
