/**
 * Review-only cost envelope (default off). Quotas in VinciHost SQLite (atomic DO SQL, not KV).
 * See docs/REVIEW_BUDGET_MATH.md.
 */

import type { DurableObjectState } from "@cloudflare/workers-types";
import type { Env } from "./auth";

/** Marginal bill ceiling for dedicated mock review (USD, excl. sunk Workers Paid). */
export const REVIEW_INCREMENTAL_USD_CAP = 20;

/** Hard max wall-clock lifetime from first DO touch (seconds). */
export const REVIEW_MAX_LIFETIME_SEC = 48 * 60 * 60;

/** Worst-case assumed CAS object size per blob key for R2 debit (not journal JSON alone). */
export const REVIEW_R2_WORST_CASE_BYTES_PER_BLOB = 10 * 1024 * 1024;

export const REVIEW_DEFAULT_LIMITS = {
  maxProxyRequests: 500,
  /** Sum of Worker→container proxy wall time only (not full container CPU). */
  maxProxyWallMs: 2 * 60 * 60 * 1000,
  /** Container billed awake time (prepare, waitReady, gaps between proxy ticks, in-flight work). */
  maxContainerAwakeMs: 4 * 60 * 60 * 1000,
  /** Worst-case R2 byte debit (per-blob cap × keys + JSON), not exact stored bytes. */
  maxR2DebitBytes: 500 * 1024 * 1024,
  maxBodyBytes: 5 * 1024 * 1024,
  maxConcurrentProxy: 1,
  maxSingleProxyMs: 120_000,
  /** Conservative per-blob debit on journal commit (R2 uploads are not metered in the worker). */
  maxAssumedBytesPerBlob: REVIEW_R2_WORST_CASE_BYTES_PER_BLOB,
} as const;

/** DO alarm interval for idle/background awake metering between proxy requests. */
export const REVIEW_AWAKE_ALARM_INTERVAL_MS = 60_000;

/** Retry container.destroy() after a failed stop until confirmed not running. */
export const REVIEW_STOP_RETRY_MS = 30_000;

export type ReviewLimits = {
  maxProxyRequests: number;
  maxProxyWallMs: number;
  maxContainerAwakeMs: number;
  maxR2DebitBytes: number;
  maxBodyBytes: number;
  maxConcurrentProxy: number;
  maxSingleProxyMs: number;
  maxAssumedBytesPerBlob: number;
};

/** Env overrides cannot exceed these ceilings (same as shipped defaults). */
export const REVIEW_LIMIT_CEILINGS: ReviewLimits = { ...REVIEW_DEFAULT_LIMITS };

export type ReviewConfig = {
  expiresAtUnix: number;
  limits: ReviewLimits;
};

export type ReviewStatus = {
  enabled: true;
  expiresAtUnix: number;
  expired: boolean;
  proxyRequests: number;
  proxyWallMs: number;
  containerAwakeMs: number;
  r2DebitBytes: number;
  inFlight: number;
  limits: ReviewLimits;
};

type ReviewRow = {
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

export type ComputeContainer = {
  running: boolean;
  destroy?: () => Promise<void>;
};

export function reviewModeEnabled(env: Env): boolean {
  return String(env.VINCI_REVIEW_MODE || "").trim() === "1";
}

export function clampReviewExpiresAt(requestedUnix: number, nowUnixSec = nowUnix()): number {
  const req = Math.floor(requestedUnix);
  const cap = nowUnixSec + REVIEW_MAX_LIFETIME_SEC;
  return Math.min(req, cap);
}

function positiveInt(raw: string | undefined, fallback: number): number {
  const n = Number(String(raw || "").trim());
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.floor(n);
}

function clampedLimit(raw: string | undefined, fallback: number, ceiling: number): number {
  return Math.min(positiveInt(raw, fallback), ceiling);
}

export function parseReviewLimits(env: Env): ReviewLimits {
  return {
    maxProxyRequests: clampedLimit(
      env.VINCI_REVIEW_MAX_REQUESTS,
      REVIEW_DEFAULT_LIMITS.maxProxyRequests,
      REVIEW_LIMIT_CEILINGS.maxProxyRequests,
    ),
    maxProxyWallMs: clampedLimit(
      env.VINCI_REVIEW_MAX_PROXY_WALL_MS,
      REVIEW_DEFAULT_LIMITS.maxProxyWallMs,
      REVIEW_LIMIT_CEILINGS.maxProxyWallMs,
    ),
    maxContainerAwakeMs: clampedLimit(
      env.VINCI_REVIEW_MAX_CONTAINER_AWAKE_MS,
      REVIEW_DEFAULT_LIMITS.maxContainerAwakeMs,
      REVIEW_LIMIT_CEILINGS.maxContainerAwakeMs,
    ),
    maxR2DebitBytes: clampedLimit(
      env.VINCI_REVIEW_MAX_R2_DEBIT_BYTES,
      REVIEW_DEFAULT_LIMITS.maxR2DebitBytes,
      REVIEW_LIMIT_CEILINGS.maxR2DebitBytes,
    ),
    maxBodyBytes: clampedLimit(
      env.VINCI_REVIEW_MAX_BODY_BYTES,
      REVIEW_DEFAULT_LIMITS.maxBodyBytes,
      REVIEW_LIMIT_CEILINGS.maxBodyBytes,
    ),
    maxConcurrentProxy: clampedLimit(
      env.VINCI_REVIEW_MAX_CONCURRENT_PROXY,
      REVIEW_DEFAULT_LIMITS.maxConcurrentProxy,
      REVIEW_LIMIT_CEILINGS.maxConcurrentProxy,
    ),
    maxSingleProxyMs: clampedLimit(
      env.VINCI_REVIEW_MAX_SINGLE_PROXY_MS,
      REVIEW_DEFAULT_LIMITS.maxSingleProxyMs,
      REVIEW_LIMIT_CEILINGS.maxSingleProxyMs,
    ),
    maxAssumedBytesPerBlob: clampedLimit(
      env.VINCI_REVIEW_MAX_ASSUMED_BYTES_PER_BLOB,
      REVIEW_DEFAULT_LIMITS.maxAssumedBytesPerBlob,
      REVIEW_LIMIT_CEILINGS.maxAssumedBytesPerBlob,
    ),
  };
}

/** Review env config (includes past expiry) for teardown, alarms, and misconfig checks. */
export function parseReviewEnvConfig(env: Env, nowUnixSec = nowUnix()): ReviewConfig | null {
  if (!reviewModeEnabled(env)) return null;
  const raw = String(env.VINCI_REVIEW_EXPIRES_AT || "").trim();
  const requested = Number(raw);
  if (!Number.isFinite(requested) || requested <= 0) return null;
  const expiresAtUnix = clampReviewExpiresAt(requested, nowUnixSec);
  return { expiresAtUnix, limits: parseReviewLimits(env) };
}

/** Active review window only (not expired at `nowUnixSec`). */
export function parseReviewConfig(env: Env, nowUnixSec = nowUnix()): ReviewConfig | null {
  const cfg = parseReviewEnvConfig(env, nowUnixSec);
  if (!cfg || cfg.expiresAtUnix <= nowUnixSec) return null;
  return cfg;
}

export function reviewMisconfiguredEnv(env: Env): boolean {
  return reviewModeEnabled(env) && parseReviewEnvConfig(env) === null;
}

export function reviewBodyLimitBytes(env: Env, productionMax: number): number {
  const cfg = parseReviewConfig(env);
  if (!cfg) return productionMax;
  return Math.min(productionMax, cfg.limits.maxBodyBytes);
}

export async function ensureReviewSchema(state: DurableObjectState): Promise<void> {
  await state.storage.sql.exec(`
    CREATE TABLE IF NOT EXISTS review_budget (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      expires_at_unix INTEGER NOT NULL,
      expired INTEGER NOT NULL DEFAULT 0,
      proxy_requests INTEGER NOT NULL DEFAULT 0,
      proxy_wall_ms INTEGER NOT NULL DEFAULT 0,
      container_awake_ms INTEGER NOT NULL DEFAULT 0,
      r2_debit_bytes INTEGER NOT NULL DEFAULT 0,
      in_flight INTEGER NOT NULL DEFAULT 0,
      awake_tick_unix INTEGER NOT NULL DEFAULT 0
    );
  `);
  const cols = await state.storage.sql.exec<{ name: string }>("PRAGMA table_info(review_budget)");
  const names = new Set([...cols].map((c) => c.name));
  if (!names.has("proxy_wall_ms")) {
    await state.storage.sql.exec(`ALTER TABLE review_budget ADD COLUMN proxy_wall_ms INTEGER NOT NULL DEFAULT 0`);
  }
  if (!names.has("container_awake_ms")) {
    await state.storage.sql.exec(`ALTER TABLE review_budget ADD COLUMN container_awake_ms INTEGER NOT NULL DEFAULT 0`);
  }
  if (!names.has("r2_debit_bytes")) {
    await state.storage.sql.exec(`ALTER TABLE review_budget ADD COLUMN r2_debit_bytes INTEGER NOT NULL DEFAULT 0`);
  }
  if (!names.has("in_flight")) {
    await state.storage.sql.exec(`ALTER TABLE review_budget ADD COLUMN in_flight INTEGER NOT NULL DEFAULT 0`);
  }
  if (!names.has("awake_tick_unix")) {
    await state.storage.sql.exec(`ALTER TABLE review_budget ADD COLUMN awake_tick_unix INTEGER NOT NULL DEFAULT 0`);
  }
  if (!names.has("stop_pending")) {
    await state.storage.sql.exec(`ALTER TABLE review_budget ADD COLUMN stop_pending INTEGER NOT NULL DEFAULT 0`);
  }
}

async function readReviewRow(state: DurableObjectState): Promise<ReviewRow | null> {
  const cur = await state.storage.sql.exec<ReviewRow>("SELECT * FROM review_budget WHERE id = 1");
  return [...cur][0] ?? null;
}

async function ensureReviewRow(state: DurableObjectState, config: ReviewConfig): Promise<ReviewRow> {
  await ensureReviewSchema(state);
  let row = await readReviewRow(state);
  const now = nowUnix();
  if (!row) {
    await state.storage.sql.exec(
      `INSERT INTO review_budget (
         id, expires_at_unix, expired, proxy_requests, proxy_wall_ms,
         container_awake_ms, r2_debit_bytes, in_flight, awake_tick_unix
       ) VALUES (1, ?, 0, 0, 0, 0, 0, 0, ?)`,
      config.expiresAtUnix,
      now,
    );
    row = await readReviewRow(state);
  } else if (row.expires_at_unix > config.expiresAtUnix) {
    await state.storage.sql.exec(
      `UPDATE review_budget SET expires_at_unix = ? WHERE id = 1 AND expires_at_unix > ?`,
      config.expiresAtUnix,
      config.expiresAtUnix,
    );
    row = await readReviewRow(state);
  }
  if (!row) throw new Error("review_budget_init_failed");
  return row;
}

function nowUnix(): number {
  return Math.floor(Date.now() / 1000);
}

/** Fail-closed: review stacks must use container.destroy(); no idle-timeout fallback. */
export async function strictStopContainer(container: ComputeContainer | undefined): Promise<void> {
  if (!container?.running) return;
  if (!container.destroy) {
    throw new Error("review_stop_requires_destroy");
  }
  await container.destroy();
}

async function tryStrictStopContainer(container: ComputeContainer | undefined): Promise<boolean> {
  try {
    await strictStopContainer(container);
    return true;
  } catch {
    return false;
  }
}

export async function scheduleReviewMaintenanceAlarm(
  state: DurableObjectState,
  delayMs: number,
): Promise<void> {
  const at = Date.now() + Math.max(1, delayMs);
  const existing = await state.storage.getAlarm();
  if (existing === null || existing > at) {
    await state.storage.setAlarm(at);
  }
}

async function markReviewClosed(
  state: DurableObjectState,
  config: ReviewConfig,
  container: ComputeContainer | undefined,
): Promise<void> {
  const now = nowUnix();
  await state.storage.sql.exec(
    `UPDATE review_budget SET expired = 1, in_flight = 0 WHERE id = 1 AND expired = 0`,
  );
  await state.storage.sql.exec(
    `UPDATE review_budget SET expired = 1, in_flight = 0
     WHERE id = 1 AND expires_at_unix <= ?`,
    now,
  );
  const stopped = await tryStrictStopContainer(container);
  if (stopped) {
    await state.storage.sql.exec(`UPDATE review_budget SET stop_pending = 0 WHERE id = 1`);
  } else if (container?.running) {
    await state.storage.sql.exec(`UPDATE review_budget SET stop_pending = 1 WHERE id = 1`);
    await scheduleReviewMaintenanceAlarm(state, REVIEW_STOP_RETRY_MS);
  }
}

/** DO alarm: background awake metering, expiry teardown, destroy retries. */
export async function handleReviewMaintenanceAlarm(
  state: DurableObjectState,
  env: Env,
  container: ComputeContainer | undefined,
): Promise<void> {
  const config = parseReviewEnvConfig(env);
  if (!config) {
    await state.storage.deleteAlarm();
    return;
  }
  await ensureReviewRow(state, config);
  const row = await readReviewRow(state);
  const now = nowUnix();
  if (!row) return;

  const timeExpired = row.expired !== 0 || row.expires_at_unix <= now;
  if (timeExpired) {
    await markReviewClosed(state, config, container);
  } else if (container?.running) {
    const deny = await tickContainerAwakeMs(state, config, container);
    if (deny) {
      await markReviewClosed(state, config, container);
    }
  }

  const after = await readReviewRow(state);
  if (!after) return;

  if (after.stop_pending !== 0 || (container?.running && after.expired !== 0)) {
    if (container?.running) {
      const stopped = await tryStrictStopContainer(container);
      if (stopped) {
        await state.storage.sql.exec(`UPDATE review_budget SET stop_pending = 0 WHERE id = 1`);
      } else {
        await state.storage.sql.exec(`UPDATE review_budget SET stop_pending = 1 WHERE id = 1`);
        await scheduleReviewMaintenanceAlarm(state, REVIEW_STOP_RETRY_MS);
        return;
      }
    } else {
      await state.storage.sql.exec(`UPDATE review_budget SET stop_pending = 0 WHERE id = 1`);
    }
  }

  if (
    container?.running &&
    after.expired === 0 &&
    after.expires_at_unix > now &&
    after.stop_pending === 0
  ) {
    await scheduleReviewMaintenanceAlarm(state, REVIEW_AWAKE_ALARM_INTERVAL_MS);
  }
}

export async function applyReviewExpiry(
  state: DurableObjectState,
  config: ReviewConfig,
  container: ComputeContainer | undefined,
): Promise<boolean> {
  await ensureReviewRow(state, config);
  const now = nowUnix();
  const row = await readReviewRow(state);
  if (!row) return true;
  if (row.expired !== 0 || row.expires_at_unix <= now) {
    await markReviewClosed(state, config, container);
    return true;
  }
  return false;
}

export async function getReviewStatus(
  state: DurableObjectState,
  config: ReviewConfig,
): Promise<ReviewStatus> {
  const row = await ensureReviewRow(state, config);
  const now = nowUnix();
  const expired = row.expired !== 0 || row.expires_at_unix <= now;
  return {
    enabled: true,
    expiresAtUnix: row.expires_at_unix,
    expired,
    proxyRequests: row.proxy_requests,
    proxyWallMs: row.proxy_wall_ms,
    containerAwakeMs: row.container_awake_ms,
    r2DebitBytes: row.r2_debit_bytes,
    inFlight: row.in_flight,
    limits: config.limits,
  };
}

export type ReviewDenyReason =
  | "review_expired"
  | "review_request_quota"
  | "review_proxy_wall_quota"
  | "review_container_awake_quota"
  | "review_r2_debit_quota"
  | "review_concurrent_proxy";

export function reviewDenyResponse(reason: ReviewDenyReason, status: ReviewStatus | null): Response {
  return Response.json({ error: reason, review: status }, {
    status: reason === "review_expired" ? 503 : 429,
  });
}

/** Charge container awake time since last tick (covers prepare/wait/background between proxies). */
export async function tickContainerAwakeMs(
  state: DurableObjectState,
  config: ReviewConfig,
  container: ComputeContainer | undefined,
): Promise<Response | null> {
  if (await applyReviewExpiry(state, config, container)) {
    return reviewDenyResponse("review_expired", await getReviewStatus(state, config));
  }
  const now = nowUnix();
  const row = await readReviewRow(state);
  if (!row || row.awake_tick_unix <= 0) {
    await state.storage.sql.exec(`UPDATE review_budget SET awake_tick_unix = ? WHERE id = 1`, now);
    return null;
  }
  const deltaSec = Math.max(0, now - row.awake_tick_unix);
  const deltaMs = deltaSec * 1000;
  if (deltaMs === 0) return null;
  const updated = await state.storage.sql.exec(
    `UPDATE review_budget
     SET container_awake_ms = container_awake_ms + ?, awake_tick_unix = ?
     WHERE id = 1 AND expired = 0 AND expires_at_unix > ?
       AND container_awake_ms + ? <= ?`,
    deltaMs,
    now,
    now,
    deltaMs,
    config.limits.maxContainerAwakeMs,
  );
  if (updated.rowsWritten === 0) {
    await markReviewClosed(state, config, container);
    const status = await getReviewStatus(state, config);
    return reviewDenyResponse(
      status.expired ? "review_expired" : "review_container_awake_quota",
      status,
    );
  }
  return null;
}

export async function beginContainerAwakeSession(state: DurableObjectState, config: ReviewConfig): Promise<void> {
  await ensureReviewRow(state, config);
  const now = nowUnix();
  await state.storage.sql.exec(`UPDATE review_budget SET awake_tick_unix = ? WHERE id = 1`, now);
  await scheduleReviewMaintenanceAlarm(state, REVIEW_AWAKE_ALARM_INTERVAL_MS);
}

export async function acquireReviewProxySlot(
  state: DurableObjectState,
  config: ReviewConfig,
  container: ComputeContainer | undefined,
): Promise<Response | null> {
  if (await applyReviewExpiry(state, config, container)) {
    return reviewDenyResponse("review_expired", await getReviewStatus(state, config));
  }
  const tickDeny = await tickContainerAwakeMs(state, config, container);
  if (tickDeny) return tickDeny;
  const now = nowUnix();
  const slot = await state.storage.sql.exec(
    `UPDATE review_budget SET in_flight = in_flight + 1
     WHERE id = 1 AND expired = 0 AND expires_at_unix > ?
       AND in_flight < ?`,
    now,
    config.limits.maxConcurrentProxy,
  );
  if (slot.rowsWritten === 0) {
    const status = await getReviewStatus(state, config);
    return reviewDenyResponse(
      status.expired ? "review_expired" : "review_concurrent_proxy",
      status,
    );
  }
  const updated = await state.storage.sql.exec(
    `UPDATE review_budget
     SET proxy_requests = proxy_requests + 1
     WHERE id = 1 AND expired = 0 AND expires_at_unix > ? AND proxy_requests < ?`,
    now,
    config.limits.maxProxyRequests,
  );
  if (updated.rowsWritten === 0) {
    await state.storage.sql.exec(
      `UPDATE review_budget SET in_flight = CASE WHEN in_flight > 0 THEN in_flight - 1 ELSE 0 END WHERE id = 1`,
    );
    const status = await getReviewStatus(state, config);
    await markReviewClosed(state, config, container);
    return reviewDenyResponse(
      status.expired ? "review_expired" : "review_request_quota",
      status,
    );
  }
  return null;
}

export async function releaseReviewProxySlot(state: DurableObjectState): Promise<void> {
  await state.storage.sql.exec(
    `UPDATE review_budget SET in_flight = CASE WHEN in_flight > 0 THEN in_flight - 1 ELSE 0 END WHERE id = 1`,
  );
}

export async function recordReviewProxyWallMs(
  state: DurableObjectState,
  config: ReviewConfig,
  ms: number,
  container: ComputeContainer | undefined,
): Promise<Response | null> {
  if (ms <= 0) return null;
  const delta = Math.min(ms, config.limits.maxSingleProxyMs);
  const updated = await state.storage.sql.exec(
    `UPDATE review_budget
     SET proxy_wall_ms = proxy_wall_ms + ?
     WHERE id = 1 AND expired = 0 AND expires_at_unix > ?
       AND proxy_wall_ms + ? <= ?`,
    delta,
    nowUnix(),
    delta,
    config.limits.maxProxyWallMs,
  );
  if (updated.rowsWritten === 0) {
    await markReviewClosed(state, config, container);
    const status = await getReviewStatus(state, config);
    return reviewDenyResponse(
      status.expired ? "review_expired" : "review_proxy_wall_quota",
      status,
    );
  }
  return null;
}

export async function recordReviewR2DebitBytes(
  state: DurableObjectState,
  config: ReviewConfig,
  bytes: number,
  container: ComputeContainer | undefined,
): Promise<Response | null> {
  if (bytes <= 0) return null;
  if (await applyReviewExpiry(state, config, container)) {
    return reviewDenyResponse("review_expired", await getReviewStatus(state, config));
  }
  if (bytes > config.limits.maxR2DebitBytes) {
    await markReviewClosed(state, config, container);
    const status = await getReviewStatus(state, config);
    return reviewDenyResponse(
      status.expired ? "review_expired" : "review_r2_debit_quota",
      status,
    );
  }
  const updated = await state.storage.sql.exec(
    `UPDATE review_budget
     SET r2_debit_bytes = r2_debit_bytes + ?
     WHERE id = 1 AND expired = 0 AND expires_at_unix > ?
       AND r2_debit_bytes + ? <= ?`,
    bytes,
    nowUnix(),
    bytes,
    config.limits.maxR2DebitBytes,
  );
  if (updated.rowsWritten === 0) {
    await markReviewClosed(state, config, container);
    const status = await getReviewStatus(state, config);
    return reviewDenyResponse(
      status.expired ? "review_expired" : "review_r2_debit_quota",
      status,
    );
  }
  return null;
}

export async function handleReviewTeardown(
  state: DurableObjectState,
  env: Env,
  container: ComputeContainer | undefined,
): Promise<Response> {
  const config = parseReviewEnvConfig(env);
  if (!config) return Response.json({ ok: true, review: false });
  await ensureReviewRow(state, config);
  const closed = await applyReviewExpiry(state, config, container);
  if (!closed && container?.running) {
    await markReviewClosed(state, config, container);
  }
  const status = await getReviewStatus(state, config);
  return Response.json({
    ok: true,
    review: true,
    tornDown: closed || status.expired,
    status,
  });
}

/** Worst-case R2 debit per journal commit (enforced assumed bytes per blob key). */
export function estimateR2CommitDebit(
  blobKeys: string[],
  payloadJson: string,
  responseJson: string,
  maxAssumedBytesPerBlob = REVIEW_R2_WORST_CASE_BYTES_PER_BLOB,
): number {
  const jsonBytes =
    new TextEncoder().encode(payloadJson).byteLength +
    new TextEncoder().encode(responseJson).byteLength;
  return jsonBytes + blobKeys.length * maxAssumedBytesPerBlob;
}

/** Max blob keys allowed on one journal commit under review limits. */
export function maxReviewBlobKeysPerCommit(config: ReviewConfig): number {
  const perBlob = config.limits.maxAssumedBytesPerBlob;
  if (perBlob <= 0) return 0;
  return Math.floor(config.limits.maxR2DebitBytes / perBlob);
}

/** Pre-commit gate: journal JSON size + blob key count (R2 uploads are not proxied). */
export function reviewR2CommitGate(
  config: ReviewConfig,
  blobKeys: string[],
  payloadJson: string,
  responseJson: string,
  currentR2DebitBytes = 0,
): ReviewDenyReason | null {
  const maxKeys = maxReviewBlobKeysPerCommit(config);
  if (blobKeys.length > maxKeys) return "review_r2_debit_quota";
  const payloadBytes = new TextEncoder().encode(payloadJson).byteLength;
  const responseBytes = new TextEncoder().encode(responseJson).byteLength;
  const jsonBytes = payloadBytes + responseBytes;
  if (jsonBytes > config.limits.maxBodyBytes) return "review_r2_debit_quota";
  const debit = estimateR2CommitDebit(
    blobKeys,
    payloadJson,
    responseJson,
    config.limits.maxAssumedBytesPerBlob,
  );
  if (debit > config.limits.maxR2DebitBytes) return "review_r2_debit_quota";
  if (currentR2DebitBytes + debit > config.limits.maxR2DebitBytes) return "review_r2_debit_quota";
  return null;
}

/** @deprecated use estimateR2CommitDebit */
export function estimateJournalStorageDebit(payloadJson: string, blobKeysJson: string): number {
  let keys: string[] = [];
  try {
    keys = JSON.parse(blobKeysJson) as string[];
  } catch {
    keys = [];
  }
  return estimateR2CommitDebit(keys, payloadJson, "{}");
}
