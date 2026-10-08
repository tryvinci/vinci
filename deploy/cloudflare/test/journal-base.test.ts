import assert from "node:assert/strict";
import { test } from "node:test";
import { normalizeDoJournalBase } from "../src/journal-base";

test("normalizeDoJournalBase appends journal suffix to worker origin", () => {
  assert.equal(
    normalizeDoJournalBase("https://example.workers.dev"),
    "https://example.workers.dev/__vinci/journal",
  );
});

test("normalizeDoJournalBase is idempotent when suffix present", () => {
  const full = "https://example.workers.dev/__vinci/journal";
  assert.equal(normalizeDoJournalBase(full), full);
  assert.equal(normalizeDoJournalBase(`${full}/`), full);
});
