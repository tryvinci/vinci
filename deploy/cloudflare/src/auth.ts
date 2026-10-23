const SESSION_COOKIE = "vinci_session";
const CSRF_COOKIE = "vinci_csrf";
const SESSION_VERSION = "v2";
const DEFAULT_SESSION_TTL_SEC = 60 * 60 * 24 * 14;

export function instanceSecret(env: Env): string {
  return (env.VINCI_INSTANCE_SECRET || "").trim();
}

export function bridgeToken(env: Env): string {
  return (env.VINCI_BRIDGE_TOKEN || "").trim();
}

/** Container → DO journal routes (bridge token only). */
export function bridgeJournalAuthorized(request: Request, env: Env): boolean {
  const bridge = bridgeToken(env);
  if (!bridge || bridge.length < 16) return false;
  const auth = request.headers.get("authorization") || "";
  return auth === `Bearer ${bridge}`;
}

export function authConfigured(env: Env): boolean {
  return instanceSecret(env).length >= 16;
}

async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function mintSession(env: Env, ttlSeconds = DEFAULT_SESSION_TTL_SEC): Promise<string> {
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const nonce = crypto.randomUUID();
  const payload = `${SESSION_VERSION}.${exp}.${nonce}`;
  const sig = await hmacHex(instanceSecret(env), payload);
  return `${payload}.${sig}`;
}

export async function verifySession(env: Env, cookie: string | null): Promise<boolean> {
  const secret = instanceSecret(env);
  if (!secret || !cookie) return false;
  const parts = cookie.split(".");
  if (parts.length !== 4) return false;
  const [ver, expRaw, nonce, sig] = parts;
  if (ver !== SESSION_VERSION) return false;
  const exp = Number(expRaw);
  if (!Number.isFinite(exp) || exp < Math.floor(Date.now() / 1000)) return false;
  const payload = `${ver}.${expRaw}.${nonce}`;
  const expected = await hmacHex(secret, payload);
  return sig === expected;
}

export function mintCsrfToken(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export function readCookie(request: Request, name: string): string | null {
  const raw = request.headers.get("cookie") || "";
  for (const part of raw.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

export function bearerAuthorized(request: Request, env: Env): boolean {
  const secret = instanceSecret(env);
  if (!secret) return false;
  const auth = request.headers.get("authorization") || "";
  return auth === `Bearer ${secret}`;
}

export async function authorized(request: Request, env: Env): Promise<boolean> {
  if (!authConfigured(env)) return false;
  if (bearerAuthorized(request, env)) return true;
  const cookie = readCookie(request, SESSION_COOKIE);
  return await verifySession(env, cookie);
}

export function secureCookie(name: string, value: string, maxAgeSeconds: number): string {
  return `${name}=${encodeURIComponent(value)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${maxAgeSeconds}`;
}

export function sessionCookie(value: string, maxAgeSeconds: number): string {
  return secureCookie(SESSION_COOKIE, value, maxAgeSeconds);
}

export function csrfCookie(value: string): string {
  return secureCookie(CSRF_COOKIE, value, 3600);
}

export function csrfOk(request: Request): boolean {
  const expected = readCookie(request, CSRF_COOKIE);
  if (!expected) return false;
  const header = request.headers.get("x-vinci-csrf") || "";
  const form = header;
  return header.length > 0 && header === expected;
}

export function sameOriginOk(request: Request): boolean {
  const host = request.headers.get("host");
  if (!host) return false;
  const origin = request.headers.get("origin");
  if (origin) {
    try {
      return new URL(origin).host === host;
    } catch {
      return false;
    }
  }
  const referer = request.headers.get("referer");
  if (referer) {
    try {
      return new URL(referer).host === host;
    } catch {
      return false;
    }
  }
  return false;
}

export function loginPage(csrf: string, error?: string): string {
  const err = error ? `<p class="err">${error}</p>` : "";
  return `<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Vinci sign in</title><style>body{font-family:system-ui;background:#09090b;color:#fafafa;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}form{background:#18181b;padding:2rem;border-radius:12px;width:min(360px,92vw)}input{width:100%;padding:.75rem;border-radius:8px;border:1px solid #3f3f46;background:#09090b;color:inherit}button{margin-top:1rem;width:100%;padding:.75rem;border:0;border-radius:8px;background:#e4e4e7;color:#09090b;font-weight:600}.err{color:#f87171}</style></head><body><form method="post" action="/_auth/login"><h1>Vinci self-host</h1><p>Enter your instance secret to open Studio.</p>${err}<input type="hidden" name="csrf" value="${csrf}"/><label>Instance secret<input name="secret" type="password" autocomplete="current-password" required minlength="16"/></label><button type="submit">Continue</button></form></body></html>`;
}

export interface Env {
  VINCI_INSTANCE_SECRET?: string;
  VINCI_BRIDGE_TOKEN?: string;
  HOST: DurableObjectNamespace;
  VINCI_CONTAINER_IDLE_MS?: string;
  VINCI_R2_BUCKET?: string;
  VINCI_R2_ACCOUNT_ID?: string;
  VINCI_R2_ACCESS_KEY_ID?: string;
  VINCI_R2_SECRET_ACCESS_KEY?: string;
  VINCI_ALLOW_LIVE_SPEND?: string;
  VINCI_DO_JOURNAL_BASE?: string;
  /** Review cost envelope (default off). Requires VINCI_REVIEW_EXPIRES_AT when "1". */
  VINCI_REVIEW_MODE?: string;
  VINCI_REVIEW_EXPIRES_AT?: string;
  VINCI_REVIEW_MAX_REQUESTS?: string;
  VINCI_REVIEW_MAX_PROXY_WALL_MS?: string;
  VINCI_REVIEW_MAX_CONTAINER_AWAKE_MS?: string;
  VINCI_REVIEW_MAX_R2_DEBIT_BYTES?: string;
  VINCI_REVIEW_MAX_BODY_BYTES?: string;
  VINCI_REVIEW_MAX_CONCURRENT_PROXY?: string;
  VINCI_REVIEW_MAX_SINGLE_PROXY_MS?: string;
  VINCI_REVIEW_MAX_ASSUMED_BYTES_PER_BLOB?: string;
}
