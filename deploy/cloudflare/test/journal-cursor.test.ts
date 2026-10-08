import assert from "node:assert/strict";
import { test } from "node:test";
import {
  committedNextCursor,
  offsetRejected,
  pageCommittedRows,
  parseCommittedLimit,
} from "../src/journal-cursor";

test("offset query param is rejected", () => {
  const bad = offsetRejected(true);
  assert.ok(bad);
  assert.equal(bad!.status, 400);
  assert.equal(bad!.body.error, "offset_unsupported_use_cursor");
  assert.equal(offsetRejected(false), null);
});

test("committed limit is bounded 1..500", () => {
  assert.equal(parseCommittedLimit(null), 500);
  assert.equal(parseCommittedLimit("0"), 1);
  assert.equal(parseCommittedLimit("9999"), 500);
  assert.equal(parseCommittedLimit("50"), 50);
});

test("next cursor only when page is full", () => {
  const rows = [
    { created_at: "2026-01-01T00:00:00.000Z", op_id: "a" },
    { created_at: "2026-01-01T00:00:01.000Z", op_id: "b" },
  ];
  assert.deepEqual(committedNextCursor(rows, 2), {
    after_created_at: "2026-01-01T00:00:01.000Z",
    after_op_id: "b",
  });
  assert.equal(committedNextCursor(rows, 3), null);
});

test("in-memory paging walks more than 10000 committed rows without repeat", () => {
  const total = 10_050;
  const all = Array.from({ length: total }, (_, i) => ({
    created_at: `2026-01-01T12:00:00.${String(i).padStart(6, "0")}Z`,
    op_id: `op-${String(i).padStart(6, "0")}`,
    status: "committed",
  }));
  const limit = 500;
  const seen: string[] = [];
  let afterCreated: string | null = null;
  let afterOp: string | null = null;
  for (;;) {
    const page = pageCommittedRows(all, limit, afterCreated, afterOp);
    if (!page.length) break;
    for (const row of page) seen.push(row.op_id);
    const nc = committedNextCursor(page, limit);
    if (!nc) break;
    afterCreated = nc.after_created_at;
    afterOp = nc.after_op_id;
  }
  assert.equal(seen.length, total);
  assert.equal(new Set(seen).size, total);
  assert.equal(seen[0], "op-000000");
  assert.equal(seen[total - 1], `op-${String(total - 1).padStart(6, "0")}`);
});
