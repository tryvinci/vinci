import assert from "node:assert/strict";
import { test } from "node:test";
import type { DurableObjectState } from "@cloudflare/workers-types";
import type { Env } from "../src/auth";
import {
  acquireReviewProxySlot,
  applyReviewExpiry,
  beginContainerAwakeSession,
  handleReviewMaintenanceAlarm,
  parseReviewConfig,
  releaseReviewProxySlot,
  strictStopContainer,
  tickContainerAwakeMs,
} from "../src/review-budget";

type Row = {
  expires_at_unix: number;
  expired: number;
  proxy_requests: number;
  proxy_wall_ms: number;
  container_awake_ms: number;
  r2_debit_bytes: number;
  in_flight: number;
  awake_tick_unix: number;
  stop_pending: number;
};

function makeReviewState(nowUnix: () => number) {
  const row: Row = {
    expires_at_unix: 0,
    expired: 0,
    proxy_requests: 0,
    proxy_wall_ms: 0,
    container_awake_ms: 0,
    r2_debit_bytes: 0,
    in_flight: 0,
    awake_tick_unix: 0,
    stop_pending: 0,
  };
  let initialized = false;

  const sql = {
    async exec<T>(query: string, ...binds: unknown[]): Promise<{ rowsWritten?: number } & Iterable<T>> {
      const q = query.replace(/\s+/g, " ").trim();
      if (q.startsWith("CREATE TABLE")) return Object.assign([], { rowsWritten: 0 });
      if (q.startsWith("PRAGMA")) return Object.assign([], { rowsWritten: 0 });
      if (q.startsWith("INSERT INTO review_budget")) {
        row.expires_at_unix = Number(binds[0]);
        row.awake_tick_unix = Number(binds[1]);
        initialized = true;
        return Object.assign([], { rowsWritten: 1 });
      }
      if (q.startsWith("SELECT * FROM review_budget")) {
        if (!initialized) return Object.assign([], { rowsWritten: 0 });
        return Object.assign([{ id: 1, ...row }], { rowsWritten: 0 });
      }
      if (q.includes("SET expired = 1")) {
        row.expired = 1;
        row.in_flight = 0;
        return Object.assign([], { rowsWritten: 1 });
      }
      if (q.includes("in_flight = in_flight + 1")) {
        const max = Number(binds[1]);
        if (row.expired || row.expires_at_unix <= Number(binds[0]) || row.in_flight >= max) {
          return Object.assign([], { rowsWritten: 0 });
        }
        row.in_flight += 1;
        return Object.assign([], { rowsWritten: 1 });
      }
      if (q.includes("proxy_requests = proxy_requests + 1")) {
        const max = Number(binds[1]);
        if (row.expired || row.expires_at_unix <= Number(binds[0]) || row.proxy_requests >= max) {
          return Object.assign([], { rowsWritten: 0 });
        }
        row.proxy_requests += 1;
        return Object.assign([], { rowsWritten: 1 });
      }
      if (q.includes("container_awake_ms = container_awake_ms +")) {
        const delta = Number(binds[0]);
        const max = Number(binds[4]);
        if (row.container_awake_ms + delta > max) return Object.assign([], { rowsWritten: 0 });
        row.container_awake_ms += delta;
        row.awake_tick_unix = Number(binds[1]);
        return Object.assign([], { rowsWritten: 1 });
      }
      if (q.includes("in_flight = CASE")) {
        row.in_flight = Math.max(0, row.in_flight - 1);
        return Object.assign([], { rowsWritten: 1 });
      }
      if (q.includes("awake_tick_unix =")) {
        row.awake_tick_unix = Number(binds[0]);
        return Object.assign([], { rowsWritten: 1 });
      }
      return Object.assign([], { rowsWritten: 0 });
    },
  };

  const alarms: number[] = [];
  const state = {
    storage: {
      sql,
      async getAlarm() {
        return alarms[0] ?? null;
      },
      async setAlarm(at: number) {
        alarms[0] = at;
      },
      async deleteAlarm() {
        alarms.length = 0;
      },
    },
  } as DurableObjectState;

  return { state, row, nowUnix, alarms };
}

const env: Env = {
  HOST: {} as DurableObjectNamespace,
  VINCI_INSTANCE_SECRET: "x".repeat(16),
  VINCI_REVIEW_MODE: "1",
  VINCI_REVIEW_MAX_REQUESTS: "10",
  VINCI_REVIEW_MAX_CONCURRENT_PROXY: "1",
  VINCI_REVIEW_MAX_CONTAINER_AWAKE_MS: "5000",
};

test("expiry boundary fails closed", async () => {
  const now = 1000;
  const cfg = parseReviewConfig(
    { ...env, VINCI_REVIEW_EXPIRES_AT: String(now) },
    now - 1,
  );
  assert.ok(cfg);
  const { state, row } = makeReviewState(() => now);
  row.expires_at_unix = cfg.expiresAtUnix;
  row.awake_tick_unix = now - 1;
  const destroyed: boolean[] = [];
  const container = {
    running: true,
    destroy: async () => {
      destroyed.push(true);
    },
  };
  const closed = await applyReviewExpiry(state, cfg, container);
  assert.equal(closed, true);
  assert.equal(row.expired, 1);
  assert.equal(destroyed.length, 1);
});

test("concurrent proxy slot rejects second acquire", async () => {
  const now = Math.floor(Date.now() / 1000);
  const cfg = parseReviewConfig({ ...env, VINCI_REVIEW_EXPIRES_AT: String(now + 3600) });
  assert.ok(cfg);
  const { state, row } = makeReviewState(() => now);
  row.expires_at_unix = cfg.expiresAtUnix;
  const container = { running: false, destroy: async () => {} };
  const first = await acquireReviewProxySlot(state, cfg, container);
  assert.equal(first, null);
  const second = await acquireReviewProxySlot(state, cfg, container);
  assert.ok(second);
  assert.equal(second?.status, 429);
  const body = (await second!.json()) as { error?: string };
  assert.equal(body.error, "review_concurrent_proxy");
  await releaseReviewProxySlot(state);
  const third = await acquireReviewProxySlot(state, cfg, container);
  assert.equal(third, null);
  await releaseReviewProxySlot(state);
});

test("strictStopContainer requires destroy", async () => {
  await assert.rejects(
    () => strictStopContainer({ running: true }),
    /review_stop_requires_destroy/,
  );
});

test("container awake tick enforces quota", async () => {
  const now = 10_000;
  const cfg = parseReviewConfig(
    {
      ...env,
      VINCI_REVIEW_EXPIRES_AT: String(now + 10_000_000),
      VINCI_REVIEW_MAX_CONTAINER_AWAKE_MS: "1000",
    },
    now,
  );
  assert.ok(cfg);
  const { state, row } = makeReviewState(() => now);
  row.expires_at_unix = cfg.expiresAtUnix;
  row.awake_tick_unix = now - 5;
  const deny = await tickContainerAwakeMs(state, cfg, { running: true, destroy: async () => {} });
  assert.ok(deny);
  assert.ok(deny!.status === 429 || deny!.status === 503);
  assert.equal(row.expired, 1);
});

test("beginContainerAwakeSession schedules DO maintenance alarm", async () => {
  const now = 20_000;
  const cfg = parseReviewConfig(
    { ...env, VINCI_REVIEW_EXPIRES_AT: String(now + 10_000_000) },
    now,
  );
  assert.ok(cfg);
  const { state, row, alarms } = makeReviewState(() => now);
  row.expires_at_unix = cfg.expiresAtUnix;
  await beginContainerAwakeSession(state, cfg);
  assert.ok(alarms.length >= 1);
});

test("maintenance alarm ticks container awake while idle", async () => {
  const wallNow = Math.floor(Date.now() / 1000);
  const reviewEnv: Env = {
    HOST: {} as DurableObjectNamespace,
    VINCI_INSTANCE_SECRET: "x".repeat(16),
    VINCI_REVIEW_MODE: "1",
    VINCI_REVIEW_EXPIRES_AT: String(wallNow + 3600),
    VINCI_REVIEW_MAX_REQUESTS: "10",
    VINCI_REVIEW_MAX_CONCURRENT_PROXY: "1",
    VINCI_REVIEW_MAX_CONTAINER_AWAKE_MS: "600000",
  };
  const cfg = parseReviewConfig(reviewEnv, wallNow);
  assert.ok(cfg);
  const { state, row } = makeReviewState(() => wallNow);
  row.expires_at_unix = cfg.expiresAtUnix;
  await beginContainerAwakeSession(state, cfg);
  row.awake_tick_unix = wallNow - 30;
  const container = { running: true, destroy: async () => {} };
  await handleReviewMaintenanceAlarm(state, reviewEnv, container);
  assert.ok(row.container_awake_ms >= 30_000);
});
