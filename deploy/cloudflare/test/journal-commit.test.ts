import assert from "node:assert/strict";
import { test } from "node:test";
import { handleJournal } from "../src/journal";

type OpRow = {
  op_id: string;
  generation: number;
  fence_token: string;
  kind: string;
  path: string;
  blob_keys_json: string;
  payload_json: string;
  payload_digest: string;
  response_json: string;
  status: string;
  created_at: string;
  committed_at: string | null;
};

function makeState() {
  const writer = {
    generation: 0,
    fence_token: "fence-1",
    writer_id: "do",
    lease_until: new Date(Date.now() + 120_000).toISOString(),
    released: 0,
    etag: "etag-w",
  };
  const ops = new Map<string, OpRow>();

  async function digestPayload(payload: Record<string, unknown>): Promise<string> {
    const raw = JSON.stringify(payload, Object.keys(payload).sort());
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  const sql = {
    exec<T>(query: string, ...binds: unknown[]) {
      const q = query.replace(/\s+/g, " ").trim();
      if (q.startsWith("CREATE TABLE")) {
        return [] as T[];
      }
      if (q.startsWith("SELECT generation, fence_token") && q.includes("writer_lease")) {
        return [writer] as T[];
      }
      if (q.startsWith("SELECT op_id, kind, path, payload_digest, payload_json")) {
        const opId = String(binds[0]);
        const row = ops.get(opId);
        return row ? [row] : ([] as T[]);
      }
      if (q.startsWith("UPDATE operations SET payload_json")) {
        const [payloadJson, payloadDigest, responseJson, committedAt, opId] = binds as string[];
        const row = ops.get(String(opId));
        if (!row || row.status !== "pending") {
          return { rowsWritten: 0 };
        }
        row.payload_json = payloadJson;
        row.payload_digest = payloadDigest;
        row.response_json = responseJson;
        row.status = "committed";
        row.committed_at = committedAt;
        return { rowsWritten: 1 };
      }
      if (q.startsWith("UPDATE operations SET response_json")) {
        const [responseJson, committedAt, opId, payloadDigest] = binds as string[];
        const row = ops.get(String(opId));
        if (!row || row.status !== "pending" || row.payload_digest !== payloadDigest) {
          return { rowsWritten: 0 };
        }
        row.response_json = responseJson;
        row.status = "committed";
        row.committed_at = committedAt;
        return { rowsWritten: 1 };
      }
      if (q.startsWith("INSERT INTO operations")) {
        const [
          opId,
          generation,
          fenceToken,
          kind,
          path,
          blobKeysJson,
          payloadJson,
          payloadDigest,
          responseJson,
          created,
          committedAt,
        ] = binds as (string | number)[];
        ops.set(String(opId), {
          op_id: String(opId),
          generation: Number(generation),
          fence_token: String(fenceToken),
          kind: String(kind),
          path: String(path),
          blob_keys_json: String(blobKeysJson),
          payload_json: String(payloadJson),
          payload_digest: String(payloadDigest),
          response_json: String(responseJson),
          status: committedAt ? "committed" : "pending",
          created_at: String(created),
          committed_at: committedAt ? String(committedAt) : null,
        });
        return { rowsWritten: 1 };
      }
      if (q.startsWith("INSERT INTO outbox")) {
        return { rowsWritten: 1 };
      }
      if (q.startsWith("UPDATE writer_lease SET etag")) {
        return { rowsWritten: 1 };
      }
      throw new Error(`unmocked sql: ${q.slice(0, 80)}`);
    },
  };

  const state = {
    storage: {
      sql,
      transaction: async <T>(fn: () => Promise<T>) => fn(),
    },
  };

  return { state, ops, digestPayload, writer };
}

test("commit allows pending submit_intent to upgrade provider_job_ref", async () => {
  const { state, ops, digestPayload, writer } = makeState();
  const intentPayload = {
    run_id: "r1",
    node_id: "adapt:0",
    job_id: "j1",
    model_id: "m1",
    provider: "openai",
    provider_job_ref: "",
    idempotency_key: "k1",
    submit_intent: true,
  };
  const intentDigest = await digestPayload(intentPayload);
  ops.set("op:inflight", {
    op_id: "op:inflight",
    generation: 0,
    fence_token: writer.fence_token,
    kind: "provider_inflight",
    path: "/x",
    blob_keys_json: "[]",
    payload_json: JSON.stringify(intentPayload),
    payload_digest: intentDigest,
    response_json: "{}",
    status: "pending",
    created_at: new Date().toISOString(),
    committed_at: null,
  });

  const committedPayload = { ...intentPayload, provider_job_ref: "ref-abc" };
  delete (committedPayload as { submit_intent?: boolean }).submit_intent;

  const res = await handleJournal(
    new Request("http://do/__vinci/journal/commit", {
      method: "POST",
      body: JSON.stringify({
        fence_token: writer.fence_token,
        op_id: "op:inflight",
        kind: "provider_inflight",
        path: "/x",
        blob_keys: [],
        payload: committedPayload,
        response: committedPayload,
      }),
    }),
    state as DurableObjectState,
  );
  assert.equal(res.status, 200);
  const row = ops.get("op:inflight");
  assert.equal(row?.status, "committed");
  assert.equal(JSON.parse(row?.payload_json ?? "{}").provider_job_ref, "ref-abc");
});

test("commit rejects digest change without submit_intent upgrade", async () => {
  const { state, ops, digestPayload, writer } = makeState();
  const intentPayload = {
    run_id: "r1",
    node_id: "n0",
    job_id: "j1",
    provider_job_ref: "",
  };
  const intentDigest = await digestPayload(intentPayload);
  ops.set("op:plain", {
    op_id: "op:plain",
    generation: 0,
    fence_token: writer.fence_token,
    kind: "provider_inflight",
    path: "/x",
    blob_keys_json: "[]",
    payload_json: JSON.stringify(intentPayload),
    payload_digest: intentDigest,
    response_json: "{}",
    status: "pending",
    created_at: new Date().toISOString(),
    committed_at: null,
  });

  const res = await handleJournal(
    new Request("http://do/__vinci/journal/commit", {
      method: "POST",
      body: JSON.stringify({
        fence_token: writer.fence_token,
        op_id: "op:plain",
        kind: "provider_inflight",
        path: "/x",
        blob_keys: [],
        payload: { ...intentPayload, provider_job_ref: "ref-abc" },
        response: { ok: true },
      }),
    }),
    state as DurableObjectState,
  );
  assert.equal(res.status, 409);
  const body = (await res.json()) as { error?: string };
  assert.equal(body.error, "payload_conflict");
});

const INTENT_BASE = {
  run_id: "parent",
  node_id: "adapt:0",
  job_id: "j1",
  model_id: "m1",
  provider: "openai",
  provider_job_ref: "",
  idempotency_key: "k1",
  submit_intent: true,
};

const INFLIGHT_PATH = "/runs/parent/nodes/adapt:0/provider_inflight";

async function seedPendingIntent(
  ops: Map<string, OpRow>,
  writer: { fence_token: string },
  digestPayload: (p: Record<string, unknown>) => Promise<string>,
  opId: string,
  payload: Record<string, unknown>,
  kind: string,
  path: string,
) {
  const digest = await digestPayload(payload);
  ops.set(opId, {
    op_id: opId,
    generation: 0,
    fence_token: writer.fence_token,
    kind,
    path,
    blob_keys_json: "[]",
    payload_json: JSON.stringify(payload),
    payload_digest: digest,
    response_json: "{}",
    status: "pending",
    created_at: new Date().toISOString(),
    committed_at: null,
  });
}

async function commitInflight(
  state: DurableObjectState,
  writer: { fence_token: string },
  opId: string,
  payload: Record<string, unknown>,
  kind: string,
  path: string,
) {
  return handleJournal(
    new Request("http://do/__vinci/journal/commit", {
      method: "POST",
      body: JSON.stringify({
        fence_token: writer.fence_token,
        op_id: opId,
        kind,
        path,
        blob_keys: [],
        payload,
        response: payload,
      }),
    }),
    state,
  );
}

for (const [field, value] of [
  ["run_id", "other-run"],
  ["node_id", "other-node"],
  ["job_id", "other-job"],
  ["model_id", "other-model"],
  ["provider", "other-provider"],
  ["idempotency_key", "other-key"],
] as const) {
  test(`commit rejects submit_intent upgrade when ${field} mutates`, async () => {
    const { state, ops, digestPayload, writer } = makeState();
    const opId = `op:mut-${field}`;
    const intent = { ...INTENT_BASE };
    await seedPendingIntent(
      ops,
      writer,
      digestPayload,
      opId,
      intent,
      "provider_inflight",
      INFLIGHT_PATH,
    );
    const mutated = { ...intent, [field]: value, provider_job_ref: "ref-ok" };
    delete (mutated as { submit_intent?: boolean }).submit_intent;
    const res = await commitInflight(
      state as DurableObjectState,
      writer,
      opId,
      mutated,
      "provider_inflight",
      INFLIGHT_PATH,
    );
    assert.equal(res.status, 409);
    const body = (await res.json()) as { error?: string };
    assert.equal(body.error, "payload_conflict");
  });
}

test("commit rejects submit_intent upgrade when kind mutates", async () => {
  const { state, ops, digestPayload, writer } = makeState();
  const opId = "op:mut-kind";
  await seedPendingIntent(
    ops,
    writer,
    digestPayload,
    opId,
    { ...INTENT_BASE },
    "provider_inflight",
    INFLIGHT_PATH,
  );
  const committed = { ...INTENT_BASE, provider_job_ref: "ref-ok" };
  delete (committed as { submit_intent?: boolean }).submit_intent;
  const res = await commitInflight(
    state as DurableObjectState,
    writer,
    opId,
    committed,
    "other_kind",
    INFLIGHT_PATH,
  );
  assert.equal(res.status, 409);
});

test("commit rejects submit_intent upgrade when path mutates", async () => {
  const { state, ops, digestPayload, writer } = makeState();
  const opId = "op:mut-path";
  await seedPendingIntent(
    ops,
    writer,
    digestPayload,
    opId,
    { ...INTENT_BASE },
    "provider_inflight",
    INFLIGHT_PATH,
  );
  const committed = { ...INTENT_BASE, provider_job_ref: "ref-ok" };
  delete (committed as { submit_intent?: boolean }).submit_intent;
  const res = await commitInflight(
    state as DurableObjectState,
    writer,
    opId,
    committed,
    "provider_inflight",
    "/other/path",
  );
  assert.equal(res.status, 409);
});
