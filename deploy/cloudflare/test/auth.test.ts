import assert from "node:assert/strict";
import { test } from "node:test";
import {
  authConfigured,
  bearerAuthorized,
  bridgeJournalAuthorized,
  mintSession,
  verifySession,
  type Env,
} from "../src/auth";

const env: Env = {
  VINCI_INSTANCE_SECRET: "x".repeat(16),
  VINCI_BRIDGE_TOKEN: "b".repeat(16),
  HOST: {} as DurableObjectNamespace,
};

test("authConfigured requires 16+ char secret", () => {
  assert.equal(authConfigured(env), true);
  assert.equal(authConfigured({ ...env, VINCI_INSTANCE_SECRET: "short" }), false);
});

test("session mint and verify with expiry", async () => {
  const token = await mintSession(env, 120);
  assert.ok(token.includes("."));
  assert.equal(await verifySession(env, token), true);
  assert.equal(await verifySession(env, "bad.token.here.now"), false);
});

test("bearer authorization", () => {
  const req = new Request("http://example/", {
    headers: { authorization: `Bearer ${"x".repeat(16)}` },
  });
  assert.equal(bearerAuthorized(req, env), true);
  assert.equal(bearerAuthorized(new Request("http://example/"), env), false);
});

test("bridge journal authorization", () => {
  const ok = new Request("http://example/__vinci/journal/acquire", {
    headers: { authorization: `Bearer ${"b".repeat(16)}` },
  });
  assert.equal(bridgeJournalAuthorized(ok, env), true);
  assert.equal(bridgeJournalAuthorized(new Request("http://example/"), env), false);
});
