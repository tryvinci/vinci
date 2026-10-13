/** Stable cursor pagination for GET /operations/committed (shared with tests). */

export type CommittedCursor = {
  after_created_at: string;
  after_op_id: string;
};

export function offsetRejected(hasOffset: boolean): { status: number; body: Record<string, string> } | null {
  if (!hasOffset) return null;
  return {
    status: 400,
    body: {
      error: "offset_unsupported_use_cursor",
      detail: "after_created_at + after_op_id",
    },
  };
}

export function parseCommittedLimit(raw: string | null): number {
  return Math.min(500, Math.max(1, Number(raw || "500")));
}

export function committedNextCursor(
  items: { created_at?: string; op_id?: string }[],
  limit: number,
): CommittedCursor | null {
  if (items.length < limit || !items.length) return null;
  const last = items[items.length - 1];
  if (!last?.created_at || !last?.op_id) return null;
  return {
    after_created_at: String(last.created_at),
    after_op_id: String(last.op_id),
  };
}

/** In-memory page matching DO SQLite ordering (for protocol tests). */
export function pageCommittedRows<T extends { created_at: string; op_id: string }>(
  rows: T[],
  limit: number,
  afterCreated: string | null,
  afterOp: string | null,
): T[] {
  const sorted = [...rows].sort((a, b) => {
    if (a.created_at !== b.created_at) return a.created_at < b.created_at ? -1 : 1;
    return a.op_id < b.op_id ? -1 : a.op_id > b.op_id ? 1 : 0;
  });
  const filtered =
    afterCreated && afterOp
      ? sorted.filter(
          (r) =>
            r.created_at > afterCreated ||
            (r.created_at === afterCreated && r.op_id > afterOp),
        )
      : sorted;
  return filtered.slice(0, limit);
}
