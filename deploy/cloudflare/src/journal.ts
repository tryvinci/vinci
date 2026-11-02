/** Durable operation journal on VinciHost SQLite (sole cloud metadata authority). */

import type { DurableObjectState } from "@cloudflare/workers-types";
import type { Env } from "./auth";
import { committedNextCursor, offsetRejected, parseCommittedLimit } from "./journal-cursor";
import { allowProviderSubmitRefUpgrade } from "./journal-submit-intent";
import {
  applyReviewExpiry,
  estimateR2CommitDebit,
  getReviewStatus,
  parseReviewConfig,
  recordReviewR2DebitBytes,
  reviewDenyResponse,
  reviewR2CommitGate,
} from "./review-budget";

const LEASE_SECONDS = 120;

type WriterRow = {
  generation: number;
  fence_token: string;
  writer_id: string;
  lease_until: string;
  released: number;
  etag: string;
};

type OperationRow = {
  op_id: string;
  kind?: string;
  path?: string;
  payload_digest: string;
  payload_json: string;
  response_json: string;
  status: string;
};

async function ensureSchema(state: DurableObjectState): Promise<void> {
  await state.storage.sql.exec(`
    CREATE TABLE IF NOT EXISTS writer_lease (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      generation INTEGER NOT NULL,
      fence_token TEXT NOT NULL,
      writer_id TEXT NOT NULL,
      lease_until TEXT NOT NULL,
      released INTEGER NOT NULL DEFAULT 0,
      etag TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS operations (
      op_id TEXT PRIMARY KEY,
      generation INTEGER NOT NULL,
      fence_token TEXT NOT NULL,
      kind TEXT NOT NULL,
      path TEXT NOT NULL,
      blob_keys_json TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      payload_digest TEXT NOT NULL DEFAULT '',
      response_json TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      committed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS outbox (
      op_id TEXT PRIMARY KEY,
      dispatch_state TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
  `);
}

function nowIso(): string {
  return new Date().toISOString();
}

function leaseUntil(): string {
  return new Date(Date.now() + LEASE_SECONDS * 1000).toISOString();
}

function newFence(): string {
  return crypto.randomUUID();
}

async function shaEtag(parts: string[]): Promise<string> {
  const data = new TextEncoder().encode(parts.join(":"));
  const buf = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function payloadDigest(payload: Record<string, unknown>): Promise<string> {
  const raw = JSON.stringify(payload, Object.keys(payload).sort());
  return shaEtag([raw]);
}

async function readWriter(state: DurableObjectState): Promise<WriterRow | null> {
  const cur = await state.storage.sql.exec<WriterRow>(
    "SELECT generation, fence_token, writer_id, lease_until, released, etag FROM writer_lease WHERE id = 1",
  );
  const rows = [...cur];
  return rows[0] ?? null;
}

function leaseActive(row: WriterRow): boolean {
  if (row.released) return false;
  return Date.parse(row.lease_until) > Date.now();
}

function journalSubpath(pathname: string): string {
  const prefix = "/__vinci/journal";
  if (pathname.startsWith(prefix)) {
    return pathname.slice(prefix.length) || "/";
  }
  return pathname;
}

async function reviewJournalGate(
  state: DurableObjectState,
  env: Env,
): Promise<Response | null> {
  const config = parseReviewConfig(env);
  if (!config) return null;
  if (await applyReviewExpiry(state, config, undefined)) {
    return reviewDenyResponse("review_expired", null);
  }
  return null;
}

export async function handleJournal(
  request: Request,
  state: DurableObjectState,
  env: Env,
): Promise<Response> {
  await ensureSchema(state);
  const gate = await reviewJournalGate(state, env);
  if (gate) return gate;
  const url = new URL(request.url);
  const path = journalSubpath(url.pathname);

  if (path === "/acquire" && request.method === "POST") {
    const existing = await readWriter(state);
    if (existing && leaseActive(existing)) {
      return Response.json({ error: "lease_active" }, { status: 409 });
    }
    const fence = newFence();
    const generation = existing ? existing.generation + 1 : 0;
    const etag = await shaEtag([String(generation), fence]);
    if (!existing) {
      await state.storage.sql.exec(
        `INSERT INTO writer_lease (id, generation, fence_token, writer_id, lease_until, released, etag)
         VALUES (1, ?, ?, 'do', ?, 0, ?)`,
        generation,
        fence,
        leaseUntil(),
        etag,
      );
    } else {
      const updated = await state.storage.sql.exec(
        `UPDATE writer_lease SET generation = ?, fence_token = ?, writer_id = 'do',
         lease_until = ?, released = 0, etag = ?
         WHERE id = 1 AND etag = ?`,
        generation,
        fence,
        leaseUntil(),
        etag,
        existing.etag,
      );
      if (updated.rowsWritten === 0) {
        return Response.json({ error: "acquire_conflict" }, { status: 409 });
      }
    }
    return Response.json({ generation, fence_token: fence, etag });
  }

  if (path === "/renew" && request.method === "POST") {
    const body = (await request.json()) as { fence_token?: string };
    const row = await readWriter(state);
    if (!row || row.fence_token !== body.fence_token || !leaseActive(row) || row.released) {
      return Response.json({ error: "stale_token" }, { status: 409 });
    }
    const etag = await shaEtag(["renew", row.fence_token]);
    await state.storage.sql.exec(
      `UPDATE writer_lease SET lease_until = ?, released = 0, etag = ? WHERE id = 1 AND fence_token = ?`,
      leaseUntil(),
      etag,
      row.fence_token,
    );
    return Response.json({ ok: true, etag });
  }

  if (path === "/release" && request.method === "POST") {
    const body = (await request.json()) as { fence_token?: string };
    const row = await readWriter(state);
    if (!row || row.fence_token !== body.fence_token) {
      return Response.json({ error: "stale_token" }, { status: 409 });
    }
    await state.storage.sql.exec(
      `UPDATE writer_lease SET released = 1 WHERE id = 1 AND fence_token = ?`,
      row.fence_token,
    );
    return Response.json({ ok: true });
  }

  if (path === "/intent" && request.method === "POST") {
    const body = (await request.json()) as {
      fence_token?: string;
      op_id?: string;
      kind?: string;
      path?: string;
      blob_keys?: string[];
      payload?: Record<string, unknown>;
    };
    const row = await readWriter(state);
    if (!row || row.fence_token !== body.fence_token || !leaseActive(row) || row.released) {
      return Response.json({ error: "stale_token" }, { status: 409 });
    }
    const opId = body.op_id ?? crypto.randomUUID();
    const digest = await payloadDigest(body.payload ?? {});
    const blobs = body.blob_keys ?? [];
    for (const key of blobs) {
      if (!key) return Response.json({ error: "missing_blob_key" }, { status: 400 });
    }
    const reviewCfg = parseReviewConfig(env);
    if (reviewCfg) {
      const payloadJson = JSON.stringify(body.payload ?? {});
      const gate = reviewR2CommitGate(reviewCfg, blobs, payloadJson, "{}");
      if (gate) {
        const status = await getReviewStatus(state, reviewCfg);
        return reviewDenyResponse(gate, status);
      }
    }
    const existing = await state.storage.sql.exec<OperationRow>(
      "SELECT op_id, payload_digest, payload_json, response_json, status FROM operations WHERE op_id = ?",
      opId,
    );
    const prior = [...existing][0];
    if (prior) {
      if (prior.payload_digest !== digest) {
        return Response.json({ error: "payload_conflict" }, { status: 409 });
      }
      if (prior.status === "committed") {
        return Response.json({
          cached: true,
          op_id: opId,
          response: JSON.parse(prior.response_json || "{}"),
        });
      }
      return Response.json({ cached: false, op_id: opId });
    }
    const created = nowIso();
    await state.storage.sql.exec(
      `INSERT INTO operations (
        op_id, generation, fence_token, kind, path, blob_keys_json, payload_json,
        payload_digest, response_json, status, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', 'pending', ?)`,
      opId,
      row.generation,
      row.fence_token,
      body.kind ?? "unknown",
      body.path ?? "/",
      JSON.stringify(blobs),
      JSON.stringify(body.payload ?? {}),
      digest,
      created,
    );
    return Response.json({ cached: false, op_id: opId });
  }

  if (path === "/commit" && request.method === "POST") {
    const body = (await request.json()) as {
      fence_token?: string;
      kind?: string;
      path?: string;
      blob_keys?: string[];
      payload?: Record<string, unknown>;
      response?: Record<string, unknown>;
      op_id?: string;
    };
    const row = await readWriter(state);
    if (!row || row.fence_token !== body.fence_token || !leaseActive(row) || row.released) {
      return Response.json({ error: "stale_token" }, { status: 409 });
    }
    const opId = body.op_id ?? crypto.randomUUID();
    const digest = await payloadDigest(body.payload ?? {});
    const blobs = body.blob_keys ?? [];
    const responseJson = JSON.stringify(body.response ?? {});
    const reviewCfg = parseReviewConfig(env);
    if (reviewCfg) {
      const payloadJson = JSON.stringify(body.payload ?? {});
      const gate = reviewR2CommitGate(reviewCfg, blobs, payloadJson, responseJson);
      if (gate) {
        const status = await getReviewStatus(state, reviewCfg);
        return reviewDenyResponse(gate, status);
      }
    }
    const created = nowIso();
    const result = await state.storage.transaction(async () => {
      const cur = await state.storage.sql.exec<WriterRow>(
        "SELECT generation, fence_token, writer_id, lease_until, released, etag FROM writer_lease WHERE id = 1",
      );
      const writer = [...cur][0];
      if (!writer || writer.fence_token !== body.fence_token || writer.etag !== row.etag) {
        return { ok: false as const, code: "commit_conflict" };
      }
      const opCur = await state.storage.sql.exec<OperationRow>(
        `SELECT op_id, kind, path, payload_digest, payload_json, response_json, status
         FROM operations WHERE op_id = ?`,
        opId,
      );
      const existing = [...opCur][0];
      if (existing) {
        const existingPayload = JSON.parse(existing.payload_json || "{}") as Record<
          string,
          unknown
        >;
        const bodyPayload = body.payload ?? {};
        const commitKind = body.kind ?? "unknown";
        const commitPath = body.path ?? "/";
        const allowRefUpgrade = allowProviderSubmitRefUpgrade(
          existing.status,
          existingPayload,
          bodyPayload,
          existing.kind ?? "unknown",
          existing.path ?? "/",
          commitKind,
          commitPath,
        );
        if (existing.payload_digest !== digest && !allowRefUpgrade) {
          return { ok: false as const, code: "payload_conflict" };
        }
        if (existing.status === "committed") {
          return { ok: true as const, op_id: opId, response: JSON.parse(existing.response_json) };
        }
        const payloadJson = JSON.stringify(bodyPayload);
        const updated = allowRefUpgrade
          ? await state.storage.sql.exec(
              `UPDATE operations SET payload_json = ?, payload_digest = ?, response_json = ?,
               status = 'committed', committed_at = ?
               WHERE op_id = ? AND status = 'pending'`,
              payloadJson,
              digest,
              responseJson,
              created,
              opId,
            )
          : await state.storage.sql.exec(
              `UPDATE operations SET response_json = ?, status = 'committed', committed_at = ?
               WHERE op_id = ? AND status = 'pending' AND payload_digest = ?`,
              responseJson,
              created,
              opId,
              digest,
            );
        if (updated.rowsWritten === 0) {
          return { ok: false as const, code: "commit_conflict" };
        }
      } else {
        await state.storage.sql.exec(
          `INSERT INTO operations (
            op_id, generation, fence_token, kind, path, blob_keys_json, payload_json,
            payload_digest, response_json, status, created_at, committed_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'committed', ?, ?)`,
          opId,
          writer.generation,
          writer.fence_token,
          body.kind ?? "unknown",
          body.path ?? "/",
          JSON.stringify(blobs),
          JSON.stringify(body.payload ?? {}),
          digest,
          responseJson,
          created,
          created,
        );
      }
      await state.storage.sql.exec(
        `INSERT INTO outbox (op_id, dispatch_state, updated_at) VALUES (?, 'pending', ?)
         ON CONFLICT(op_id) DO NOTHING`,
        opId,
        created,
      );
      const newEtag = await shaEtag(["commit", opId, writer.fence_token]);
      await state.storage.sql.exec(
        `UPDATE writer_lease SET etag = ?, lease_until = ? WHERE id = 1 AND fence_token = ?`,
        newEtag,
        leaseUntil(),
        writer.fence_token,
      );
      return { ok: true as const, op_id: opId, response: body.response ?? {} };
    });
    if (result.ok) {
      const config = parseReviewConfig(env);
      if (config) {
        const payloadJson = JSON.stringify(body.payload ?? {});
        const debit = estimateR2CommitDebit(
          blobs,
          payloadJson,
          responseJson,
          config.limits.maxAssumedBytesPerBlob,
        );
        const storageDeny = await recordReviewR2DebitBytes(state, config, debit, undefined);
        if (storageDeny) return storageDeny;
      }
    }
    if (!result.ok) {
      const status = result.code === "payload_conflict" ? 409 : 409;
      return Response.json({ error: result.code ?? "commit_conflict" }, { status });
    }
    return Response.json({ op_id: result.op_id, response: result.response });
  }

  if (path === "/operations/committed" && request.method === "GET") {
    const rejected = offsetRejected(url.searchParams.has("offset"));
    if (rejected) {
      return Response.json(rejected.body, { status: rejected.status });
    }
    const limit = parseCommittedLimit(url.searchParams.get("limit"));
    const afterCreated = url.searchParams.get("after_created_at") ?? "";
    const afterOp = url.searchParams.get("after_op_id") ?? "";
    const cur =
      afterCreated && afterOp
        ? await state.storage.sql.exec(
            `SELECT * FROM operations WHERE status = 'committed'
             AND (created_at > ? OR (created_at = ? AND op_id > ?))
             ORDER BY created_at ASC, op_id ASC LIMIT ?`,
            afterCreated,
            afterCreated,
            afterOp,
            limit,
          )
        : await state.storage.sql.exec(
            `SELECT * FROM operations WHERE status = 'committed'
             ORDER BY created_at ASC, op_id ASC LIMIT ?`,
            limit,
          );
    const items = [...cur];
    const next_cursor = committedNextCursor(items, limit);
    return Response.json({ items, next_cursor });
  }

  const opMatch = path.match(/^\/operations\/([^/]+)$/);
  if (opMatch && request.method === "GET") {
    const opId = opMatch[1];
    const cur = await state.storage.sql.exec("SELECT * FROM operations WHERE op_id = ?", opId);
    const rows = [...cur];
    return Response.json({ operation: rows[0] ?? null });
  }

  if (path === "/outbox/pending" && request.method === "GET") {
    const limit = Math.min(100, Number(url.searchParams.get("limit") || "100"));
    const cur = await state.storage.sql.exec(
      `SELECT o.* FROM operations o
       JOIN outbox x ON x.op_id = o.op_id
       WHERE x.dispatch_state = 'pending' AND o.status = 'committed'
       ORDER BY o.created_at LIMIT ?`,
      limit,
    );
    return Response.json({ items: [...cur] });
  }

  if (path === "/outbox/dispatch" && request.method === "POST") {
    const body = (await request.json()) as { op_id?: string };
    if (!body.op_id) {
      return Response.json({ error: "missing_op_id" }, { status: 400 });
    }
    await state.storage.sql.exec(
      `UPDATE outbox SET dispatch_state = 'dispatched', updated_at = ? WHERE op_id = ?`,
      nowIso(),
      body.op_id,
    );
    return Response.json({ ok: true });
  }

  return Response.json({ error: "not_found" }, { status: 404 });
}
