import assert from "node:assert/strict";
import { test } from "node:test";
import worker, { GUARD_MODEL, IMAGE_MODEL, generate, type Env } from "../src/index.ts";

/** In-memory KV good enough for quota tests. */
function fakeKV() {
  const m = new Map<string, string>();
  return { map: m, get: async (k: string) => m.get(k) ?? null, put: async (k: string, v: string) => void m.set(k, v) } as unknown as KVNamespace & { map: Map<string, string> };
}

function fakeAI(opts: { unsafe?: boolean; guardThrows?: boolean; imageThrows?: boolean } = {}) {
  const calls: string[] = [];
  const ai = {
    calls,
    run: async (model: string) => {
      calls.push(model);
      if (model === GUARD_MODEL) {
        if (opts.guardThrows) throw new Error("guard down");
        return { response: { safe: !opts.unsafe, categories: opts.unsafe ? ["S1"] : [] } };
      }
      if (model === IMAGE_MODEL) {
        if (opts.imageThrows) throw new Error("capacity");
        return { image: "AAAA" };
      }
      throw new Error("unexpected model " + model);
    },
  };
  return ai as unknown as Ai & { calls: string[] };
}

const env = (over: Partial<Env> = {}): Env => ({ AI: fakeAI(), QUOTA: fakeKV(), PER_VISITOR_DAILY: "2", GLOBAL_DAILY: "100", QUOTA_SALT: "s", ...over });
const req = (body: unknown, ip = "1.2.3.4") =>
  new Request("https://x/api/generate", { method: "POST", headers: { "content-type": "application/json", "cf-connecting-ip": ip }, body: JSON.stringify(body) });

test("makes an image and counts it", async () => {
  const e = env();
  const res = await generate(req({ prompt: "a red cube" }), e);
  assert.equal(res.status, 200);
  const data = (await res.json()) as { image: string; remaining: number };
  assert.match(data.image, /^data:image\/jpeg;base64,AAAA$/);
  assert.equal(data.remaining, 1);
  // Raw IP never reaches storage.
  assert.ok(![...(e.QUOTA as unknown as { map: Map<string, string> }).map.keys()].some((k) => k.includes("1.2.3.4")));
});

test("stops a visitor at the daily limit but not others", async () => {
  const e = env();
  for (let i = 0; i < 2; i++) assert.equal((await generate(req({ prompt: "x" }), e)).status, 200);
  assert.equal((await generate(req({ prompt: "x" }), e)).status, 429);
  assert.equal((await generate(req({ prompt: "x" }, "5.6.7.8"), e)).status, 200);
});

test("stops everyone at the global limit", async () => {
  const e = env({ GLOBAL_DAILY: "1", PER_VISITOR_DAILY: "5" });
  assert.equal((await generate(req({ prompt: "x" }), e)).status, 200);
  assert.equal((await generate(req({ prompt: "x" }, "9.9.9.9"), e)).status, 429);
});

test("blocks unsafe prompts without calling the image model or using quota", async () => {
  const ai = fakeAI({ unsafe: true });
  const e = env({ AI: ai });
  assert.equal((await generate(req({ prompt: "bad" }), e)).status, 422);
  assert.deepEqual(ai.calls, [GUARD_MODEL]);
  assert.equal((e.QUOTA as unknown as { map: Map<string, string> }).map.size, 0);
});

test("fails closed when the guard errors", async () => {
  const e = env({ AI: fakeAI({ guardThrows: true }) });
  assert.equal((await generate(req({ prompt: "x" }), e)).status, 422);
});

test("model errors return 502 and do not use quota", async () => {
  const e = env({ AI: fakeAI({ imageThrows: true }) });
  assert.equal((await generate(req({ prompt: "x" }), e)).status, 502);
  assert.equal((e.QUOTA as unknown as { map: Map<string, string> }).map.size, 0);
});

test("rejects empty, long, and non-JSON prompts", async () => {
  const e = env();
  assert.equal((await generate(req({ prompt: "  " }), e)).status, 400);
  assert.equal((await generate(req({ prompt: "a".repeat(501) }), e)).status, 400);
  const bad = new Request("https://x/api/generate", { method: "POST", body: "nope" });
  assert.equal((await generate(bad, e)).status, 400);
});

test("serves the page and 404s elsewhere", async () => {
  const e = env();
  const page = await worker.fetch(new Request("https://x/"), e);
  assert.equal(page.status, 200);
  const html = await page.text();
  assert.match(html, /github\.com\/tryvinci\/vinci/);
  assert.ok(!html.includes("class=\"cf-turnstile\""), "no Turnstile widget without a site key");
  assert.ok(!/—/.test(html), "no em dashes in copy");
  assert.equal((await worker.fetch(new Request("https://x/nope"), e)).status, 404);
});
