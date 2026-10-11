import assert from "node:assert/strict";
import { test } from "node:test";
import type { DurableObjectState } from "@cloudflare/workers-types";
import type { Env } from "../src/auth";
import {
  REVIEW_DEFAULT_LIMITS,
  REVIEW_STOP_RETRY_MS,
  handleReviewMaintenanceAlarm,
  handleReviewTeardown,
  parseReviewConfig,
  parseReviewEnvConfig,
  parseReviewLimits,
  recordReviewR2DebitBytes,
  reviewR2CommitGate,
  scheduleReviewMaintenanceAlarm,
} from "../src/review-budget";

const baseEnv: Env = {
  HOST: {} as DurableObjectNamespace,
  VINCI_INSTANCE_SECRET: "x".repeat(16),
  VINCI_REVIEW_MODE: "1",
};

test("parseReviewEnvConfig preserves expired stack config for teardown", () => {
  const now = 5_000;
  const env: Env = { ...baseEnv, VINCI_REVIEW_EXPIRES_AT: "1000" };
  assert.equal(parseReviewConfig(env, now), null);
  const envCfg = parseReviewEnvConfig(env, now);
  assert.ok(envCfg);
  assert.equal(envCfg.expiresAtUnix, 1000);
});

test("parseReviewLimits clamps env overrides to ceilings", () => {
  const env: Env = {
    ...baseEnv,
    VINCI_REVIEW_MAX_REQUESTS: "999999",
    VINCI_REVIEW_MAX_ASSUMED_BYTES_PER_BLOB: String(99 * 1024 * 1024),
  };
  const limits = parseReviewLimits(env);
  assert.equal(limits.maxProxyRequests, REVIEW_DEFAULT_LIMITS.maxProxyRequests);
  assert.equal(limits.maxAssumedBytesPerBlob, REVIEW_DEFAULT_LIMITS.maxAssumedBytesPerBlob);
});

test("reviewR2CommitGate rejects oversize single commit", () => {
  const now = 10_000;
  const cfg = parseReviewConfig(
    {
      ...baseEnv,
      VINCI_REVIEW_EXPIRES_AT: String(now + 3600),
      VINCI_REVIEW_MAX_R2_DEBIT_BYTES: "1000",
    },
    now,
  );
  assert.ok(cfg);
  const gate = reviewR2CommitGate(cfg, ["a"], "{}", "{}", 0);
  assert.equal(gate, "review_r2_debit_quota");
});

test("recordReviewR2DebitBytes rejects debit larger than cap without partial charge", async () => {
  const now = 20_000;
  const cfg = parseReviewConfig(
    {
      ...baseEnv,
      VINCI_REVIEW_EXPIRES_AT: String(now + 3600),
      VINCI_REVIEW_MAX_R2_DEBIT_BYTES: "100",
    },
    now,
  );
  assert.ok(cfg);
  let r2 = 0;
  const state = {
    storage: {
      sql: {
        async exec(query: string, ...binds: unknown[]) {
          const q = query.replace(/\s+/g, " ").trim();
          if (q.includes("SET expired = 1")) return Object.assign([], { rowsWritten: 1 });
          if (q.includes("r2_debit_bytes = r2_debit_bytes +")) {
            return Object.assign([], { rowsWritten: 0 });
          }
          if (q.includes("stop_pending = 0")) return Object.assign([], { rowsWritten: 1 });
          if (q.startsWith("SELECT * FROM review_budget")) {
            return Object.assign(
              [
                {
                  id: 1,
                  expires_at_unix: cfg.expiresAtUnix,
                  expired: 0,
                  proxy_requests: 0,
                  proxy_wall_ms: 0,
                  container_awake_ms: 0,
                  r2_debit_bytes: r2,
                  in_flight: 0,
                  awake_tick_unix: now,
                  stop_pending: 0,
                },
              ],
              { rowsWritten: 0 },
            );
          }
          if (q.startsWith("CREATE TABLE") || q.startsWith("PRAGMA")) {
            return Object.assign([], { rowsWritten: 0 });
          }
          if (q.startsWith("INSERT INTO review_budget")) return Object.assign([], { rowsWritten: 1 });
          return Object.assign([], { rowsWritten: 0 });
        },
      },
      async getAlarm() {
        return null;
      },
      async setAlarm() {},
      async deleteAlarm() {},
    },
  } as DurableObjectState;

  const deny = await recordReviewR2DebitBytes(state, cfg, 200, { running: false });
  assert.ok(deny);
  assert.equal(r2, 0);
});

test("handleReviewTeardown runs destroy when env expiry is past", async () => {
  const now = 50_000;
  const env: Env = { ...baseEnv, VINCI_REVIEW_EXPIRES_AT: String(now - 10) };
  assert.equal(parseReviewConfig(env, now), null);
  const destroyed: boolean[] = [];
  const container = {
    running: true,
    destroy: async () => {
      destroyed.push(true);
    },
  };
  const state = {
    storage: {
      sql: {
        async exec(query: string, ...binds: unknown[]) {
          const q = query.replace(/\s+/g, " ").trim();
          if (q.startsWith("CREATE TABLE") || q.startsWith("PRAGMA")) {
            return Object.assign([], { rowsWritten: 0 });
          }
          if (q.startsWith("INSERT INTO review_budget")) return Object.assign([], { rowsWritten: 1 });
          if (q.includes("SET expired = 1")) return Object.assign([], { rowsWritten: 1 });
          if (q.includes("stop_pending = 0")) return Object.assign([], { rowsWritten: 1 });
          if (q.startsWith("SELECT * FROM review_budget")) {
            return Object.assign(
              [
                {
                  id: 1,
                  expires_at_unix: now - 10,
                  expired: 0,
                  proxy_requests: 0,
                  proxy_wall_ms: 0,
                  container_awake_ms: 0,
                  r2_debit_bytes: 0,
                  in_flight: 0,
                  awake_tick_unix: now - 100,
                  stop_pending: 0,
                },
              ],
              { rowsWritten: 0 },
            );
          }
          return Object.assign([], { rowsWritten: 1 });
        },
      },
      async getAlarm() {
        return null;
      },
      async setAlarm() {},
      async deleteAlarm() {},
    },
  } as DurableObjectState;

  const res = await handleReviewTeardown(state, env, container);
  const body = (await res.json()) as { review?: boolean; tornDown?: boolean };
  assert.equal(body.review, true);
  assert.equal(body.tornDown, true);
  assert.equal(destroyed.length, 1);
});

test("markReviewClosed schedules alarm when destroy fails", async () => {
  const now = 60_000;
  const env: Env = { ...baseEnv, VINCI_REVIEW_EXPIRES_AT: String(now + 3600) };
  const cfg = parseReviewConfig(env, now);
  assert.ok(cfg);
  const alarms: number[] = [];
  let row = {
    expires_at_unix: cfg.expiresAtUnix,
    expired: 0,
    proxy_requests: 0,
    proxy_wall_ms: 0,
    container_awake_ms: 0,
    r2_debit_bytes: 0,
    in_flight: 0,
    awake_tick_unix: now - 120,
    stop_pending: 0,
  };
  const state = {
    storage: {
      sql: {
        async exec(query: string) {
          const q = query.replace(/\s+/g, " ").trim();
          if (q.startsWith("CREATE TABLE") || q.startsWith("PRAGMA")) {
            return Object.assign([], { rowsWritten: 0 });
          }
          if (q.startsWith("INSERT INTO review_budget")) return Object.assign([], { rowsWritten: 1 });
          if (q.includes("SET expired = 1")) {
            row.expired = 1;
            return Object.assign([], { rowsWritten: 1 });
          }
          if (q.includes("stop_pending = 1")) {
            row.stop_pending = 1;
            return Object.assign([], { rowsWritten: 1 });
          }
          if (q.startsWith("SELECT * FROM review_budget")) {
            return Object.assign([{ id: 1, ...row }], { rowsWritten: 0 });
          }
          if (q.includes("container_awake_ms = container_awake_ms +")) {
            row.container_awake_ms += 120_000;
            return Object.assign([], { rowsWritten: 1 });
          }
          return Object.assign([], { rowsWritten: 0 });
        },
      },
      async getAlarm() {
        return null;
      },
      async setAlarm(at: number) {
        alarms.push(at);
      },
      async deleteAlarm() {},
    },
  } as DurableObjectState;

  const container = {
    running: true,
    destroy: async () => {
      throw new Error("destroy_failed");
    },
  };

  await handleReviewMaintenanceAlarm(state, env, container);
  assert.equal(row.stop_pending, 1);
  assert.ok(alarms.length >= 1);
  const lastAlarm = alarms[alarms.length - 1];
  assert.ok(lastAlarm >= Date.now() + REVIEW_STOP_RETRY_MS - 50);
});

test("scheduleReviewMaintenanceAlarm coalesces to earliest fire time", async () => {
  const scheduled: number[] = [];
  const state = {
    storage: {
      async getAlarm() {
        return scheduled[0] ?? null;
      },
      async setAlarm(at: number) {
        scheduled[0] = at;
      },
    },
  } as DurableObjectState;
  await scheduleReviewMaintenanceAlarm(state, 5_000);
  const earliest = scheduled[0];
  await scheduleReviewMaintenanceAlarm(state, 10_000);
  assert.equal(scheduled[0], earliest);
});
