// Vinci playground: a public page where anyone can make a few free images
// with no install, then get pointed at the full studio. Images run on
// Workers AI and are returned inline; nothing is stored.
import { renderPage } from "./page";

export interface Env {
  AI: Ai;
  QUOTA: KVNamespace;
  PER_VISITOR_DAILY?: string;
  GLOBAL_DAILY?: string;
  QUOTA_SALT?: string;
  TURNSTILE_SITE_KEY?: string;
  TURNSTILE_SECRET?: string;
}

export const IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell";
export const GUARD_MODEL = "@cf/meta/llama-guard-3-8b";
const MAX_PROMPT = 500;
const DAY_TTL = 60 * 60 * 48;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });

/** Hashes the visitor IP with a salt so raw IPs never reach storage. */
export async function visitorKey(ip: string, salt: string, day: string): Promise<string> {
  const data = new TextEncoder().encode(`${salt}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `v:${day}:${hex.slice(0, 32)}`;
}

/** Reads a counter from KV (missing means 0). */
async function count(kv: KVNamespace, key: string): Promise<number> {
  return Number((await kv.get(key)) || "0");
}

/**
 * Returns true when Llama Guard marks the prompt unsafe. Fails closed:
 * if the guard errors, the prompt is treated as unsafe.
 */
export async function isUnsafe(ai: Ai, prompt: string): Promise<boolean> {
  try {
    const out = (await ai.run(GUARD_MODEL as keyof AiModels, {
      messages: [{ role: "user", content: prompt }],
    } as never)) as { response?: unknown };
    const r = out?.response;
    if (r && typeof r === "object" && "safe" in r) return (r as { safe: boolean }).safe === false;
    if (typeof r === "string") return /unsafe/i.test(r);
    return true;
  } catch (err) {
    console.error("guard_error", String(err));
    return true;
  }
}

/** Verifies a Turnstile token when a secret is configured. */
async function turnstileOk(env: Env, token: string, ip: string): Promise<boolean> {
  if (!env.TURNSTILE_SECRET) return true;
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET);
  form.append("response", token);
  form.append("remoteip", ip);
  const res = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form });
  const data = (await res.json()) as { success?: boolean };
  return data.success === true;
}

/** POST /api/generate: quota, bot and safety checks, then one FLUX image. */
export async function generate(request: Request, env: Env, now = new Date()): Promise<Response> {
  let body: { prompt?: unknown; turnstile?: unknown };
  try {
    body = await request.json();
  } catch {
    return json({ error: "Send JSON with a prompt." }, 400);
  }
  const prompt = typeof body.prompt === "string" ? body.prompt.trim() : "";
  if (!prompt) return json({ error: "Write a prompt first." }, 400);
  if (prompt.length > MAX_PROMPT) return json({ error: `Keep the prompt under ${MAX_PROMPT} characters.` }, 400);

  const ip = request.headers.get("cf-connecting-ip") || "unknown";
  if (!(await turnstileOk(env, String(body.turnstile || ""), ip))) {
    return json({ error: "Please complete the check and try again." }, 403);
  }

  const day = now.toISOString().slice(0, 10);
  const perVisitor = Number(env.PER_VISITOR_DAILY || "3");
  const globalCap = Number(env.GLOBAL_DAILY || "20000");
  const vKey = await visitorKey(ip, env.QUOTA_SALT || "vinci", day);
  const gKey = `g:${day}`;
  const [used, usedAll] = await Promise.all([count(env.QUOTA, vKey), count(env.QUOTA, gKey)]);
  if (used >= perVisitor) {
    return json({ error: "That is today's free images. Run Vinci locally for unlimited takes on 90+ models.", remaining: 0 }, 429);
  }
  if (usedAll >= globalCap) {
    return json({ error: "The playground is at today's limit. Run Vinci locally to keep going.", remaining: 0 }, 429);
  }

  if (await isUnsafe(env.AI, prompt)) {
    console.log("prompt_blocked", { day });
    return json({ error: "That prompt is not allowed here. Try another idea." }, 422);
  }

  try {
    const out = (await env.AI.run(IMAGE_MODEL as keyof AiModels, { prompt, steps: 4 } as never)) as { image?: string };
    if (!out?.image) throw new Error("no image in response");
    // Count only successful images so errors do not use up a visitor's quota.
    await Promise.all([
      env.QUOTA.put(vKey, String(used + 1), { expirationTtl: DAY_TTL }),
      env.QUOTA.put(gKey, String(usedAll + 1), { expirationTtl: DAY_TTL }),
    ]);
    console.log("image_ok", { day, global: usedAll + 1 });
    return json({ image: `data:image/jpeg;base64,${out.image}`, remaining: perVisitor - used - 1, model: "FLUX.1 Schnell" });
  } catch (err) {
    console.error("image_error", String(err));
    return json({ error: "The model did not answer. Try again in a moment." }, 502);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/generate" && request.method === "POST") return generate(request, env);
    if (url.pathname === "/" && (request.method === "GET" || request.method === "HEAD")) {
      return new Response(renderPage({ turnstileSiteKey: env.TURNSTILE_SITE_KEY || "", perVisitor: Number(env.PER_VISITOR_DAILY || "3") }), {
        headers: { "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=300" },
      });
    }
    return new Response("Not found", { status: 404 });
  },
} satisfies ExportedHandler<Env>;
