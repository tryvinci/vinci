import assert from "node:assert/strict";
import { test } from "node:test";
import type { Env } from "../src/auth";
import {
  REVIEW_DEFAULT_LIMITS,
  REVIEW_INCREMENTAL_USD_CAP,
  REVIEW_MAX_LIFETIME_SEC,
  REVIEW_R2_WORST_CASE_BYTES_PER_BLOB,
  clampReviewExpiresAt,
  estimateR2CommitDebit,
  parseReviewConfig,
  reviewBodyLimitBytes,
  reviewModeEnabled,
} from "../src/review-budget";

const baseEnv: Env = {
  HOST: {} as DurableObjectNamespace,
  VINCI_INSTANCE_SECRET: "x".repeat(16),
};

test("review mode is default off", () => {
  assert.equal(reviewModeEnabled(baseEnv), false);
  assert.equal(parseReviewConfig(baseEnv), null);
});

test("review mode requires future expires_at", () => {
  const env: Env = { ...baseEnv, VINCI_REVIEW_MODE: "1" };
  assert.equal(parseReviewConfig(env), null);
  const past: Env = { ...env, VINCI_REVIEW_EXPIRES_AT: "1" };
  assert.equal(parseReviewConfig(past, 100), null);
});

test("clampReviewExpiresAt caps to max lifetime", () => {
  const now = 1_000_000;
  const far = now + REVIEW_MAX_LIFETIME_SEC + 99_999;
  assert.equal(clampReviewExpiresAt(far, now), now + REVIEW_MAX_LIFETIME_SEC);
  assert.equal(clampReviewExpiresAt(now + 100, now), now + 100);
});

test("parseReviewConfig clamps expiry", () => {
  const now = 2_000_000;
  const env: Env = {
    ...baseEnv,
    VINCI_REVIEW_MODE: "1",
    VINCI_REVIEW_EXPIRES_AT: String(now + REVIEW_MAX_LIFETIME_SEC + 1),
  };
  const cfg = parseReviewConfig(env, now);
  assert.ok(cfg);
  assert.equal(cfg.expiresAtUnix, now + REVIEW_MAX_LIFETIME_SEC);
});

test("R2 debit uses per-blob worst case not JSON alone", () => {
  const oneBlob = estimateR2CommitDebit(["cas/ab"], "{}", "{}");
  assert.equal(oneBlob, REVIEW_R2_WORST_CASE_BYTES_PER_BLOB + 4);
  const none = estimateR2CommitDebit([], "{}", "{}");
  assert.equal(none, 4);
});

test("review body limit caps production max", () => {
  const env: Env = {
    ...baseEnv,
    VINCI_REVIEW_MODE: "1",
    VINCI_REVIEW_EXPIRES_AT: "2000000000",
  };
  assert.equal(reviewBodyLimitBytes(env, 32 * 1024 * 1024), REVIEW_DEFAULT_LIMITS.maxBodyBytes);
});

test("incremental cap constant", () => {
  assert.equal(REVIEW_INCREMENTAL_USD_CAP, 20);
});
