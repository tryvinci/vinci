import type { DurableObjectState } from "@cloudflare/workers-types";
import { bridgeJournalAuthorized, bridgeToken, type Env } from "./auth";
import { normalizeDoJournalBase } from "./journal-base";
import { handleJournal } from "./journal";
import {
  acquireReviewProxySlot,
  applyReviewExpiry,
  beginContainerAwakeSession,
  handleReviewMaintenanceAlarm,
  handleReviewTeardown,
  parseReviewConfig,
  recordReviewProxyWallMs,
  releaseReviewProxySlot,
  reviewBodyLimitBytes,
  tickContainerAwakeMs,
} from "./review-budget";

const MAX_BODY_BYTES = 32 * 1024 * 1024;

type ComputeContainer = {
  running: boolean;
  start: (opts: { env: Record<string, string>; enableInternet?: boolean }) => Promise<void>;
  getTcpPort: (port: number) => { fetch: (url: string, init?: RequestInit) => Promise<Response> };
  setInactivityTimeout?: (ms: number) => Promise<void>;
  destroy?: () => Promise<void>;
};

function idleMs(env: { VINCI_CONTAINER_IDLE_MS?: string }): number {
  const raw = Number(env.VINCI_CONTAINER_IDLE_MS || "120000");
  if (!Number.isFinite(raw)) return 120_000;
  return Math.min(21_600_000, Math.max(1, raw));
}

function containerEnv(env: Env): Record<string, string> {
  return {
    VINCI_BRIDGE_TOKEN: bridgeToken(env),
    VINCI_SELFHOST: "1",
    VINCI_HOME: "/data/.vinci",
    VINCI_CAS_BACKEND: "r2",
    VINCI_R2_BUCKET: env.VINCI_R2_BUCKET || "",
    VINCI_R2_ACCOUNT_ID: env.VINCI_R2_ACCOUNT_ID || "",
    VINCI_R2_ACCESS_KEY_ID: env.VINCI_R2_ACCESS_KEY_ID || "",
    VINCI_R2_SECRET_ACCESS_KEY: env.VINCI_R2_SECRET_ACCESS_KEY || "",
    VINCI_ALLOW_LIVE_SPEND: env.VINCI_ALLOW_LIVE_SPEND || "0",
    VINCI_DURABLE_JOURNAL: "do",
    VINCI_DO_JOURNAL_BASE: normalizeDoJournalBase(env.VINCI_DO_JOURNAL_BASE || ""),
    VINCI_HOME_SNAPSHOT_ROLE: "compact",
  };
}

async function waitReady(container: ComputeContainer, port = 8080): Promise<boolean> {
  for (let i = 0; i < 30; i++) {
    try {
      const res = await container.getTcpPort(port).fetch("http://container/healthz");
      if (res.ok) return true;
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

async function prepare(
  container: ComputeContainer,
  env: Env,
  reviewConfig: ReturnType<typeof parseReviewConfig>,
  state: DurableObjectState,
): Promise<boolean> {
  const waking = !container.running;
  if (waking) {
    await container.start({ enableInternet: true, env: containerEnv(env) });
    if (reviewConfig) {
      await beginContainerAwakeSession(state, reviewConfig);
    }
  }
  if (container.setInactivityTimeout) {
    await container.setInactivityTimeout(idleMs(env));
  }
  const ready = await waitReady(container);
  if (reviewConfig && ready) {
    const deny = await tickContainerAwakeMs(state, reviewConfig, container);
    if (deny) return false;
  }
  return ready;
}

async function readBodyLimited(request: Request, maxBytes: number): Promise<ArrayBuffer | undefined> {
  if (request.method === "GET" || request.method === "HEAD") return undefined;
  const reader = request.body?.getReader();
  if (!reader) return undefined;
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > maxBytes) {
      throw new Error("body_too_large");
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out.buffer;
}

async function proxyWithTimeout(
  container: ComputeContainer,
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const port = container.getTcpPort(8080);
  if (timeoutMs <= 0) return port.fetch(url, init);
  return Promise.race([
    port.fetch(url, init),
    new Promise<Response>((_, reject) => {
      setTimeout(() => reject(new Error("proxy_timeout")), timeoutMs);
    }),
  ]);
}

export class VinciHost {
  constructor(
    private readonly state: DurableObjectState,
    private readonly env: Env,
  ) {}

  private container(): ComputeContainer | undefined {
    const value: unknown = this.state.container;
    return value as ComputeContainer | undefined;
  }

  async alarm(): Promise<void> {
    await handleReviewMaintenanceAlarm(this.state, this.env, this.container());
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/__vinci/review/teardown" && request.method === "POST") {
      if (!bridgeJournalAuthorized(request, this.env)) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      return handleReviewTeardown(this.state, this.env, this.container());
    }

    if (url.pathname.startsWith("/__vinci/journal/")) {
      if (!bridgeJournalAuthorized(request, this.env)) {
        return Response.json({ error: "unauthorized" }, { status: 401 });
      }
      const reviewConfig = parseReviewConfig(this.env);
      if (reviewConfig) {
        const expired = await applyReviewExpiry(this.state, reviewConfig, this.container());
        if (expired) {
          return Response.json({ error: "review_expired" }, { status: 503 });
        }
      }
      return handleJournal(request, this.state, this.env);
    }

    const container = this.container();
    if (!container) {
      return Response.json({ error: "container_unwired" }, { status: 503 });
    }

    const reviewConfig = parseReviewConfig(this.env);
    const bodyLimit = reviewBodyLimitBytes(this.env, MAX_BODY_BYTES);

    if (reviewConfig) {
      const deny = await acquireReviewProxySlot(this.state, reviewConfig, container);
      if (deny) return deny;
    }

    try {
      const ready = await prepare(container, this.env, reviewConfig, this.state);
      if (!ready) {
        return Response.json({ error: "container_not_ready" }, { status: 503 });
      }

      url.protocol = "http:";
      url.host = "container";
      url.port = "";
      const headers = new Headers(request.headers);
      const bridge = bridgeToken(this.env);
      if (bridge) headers.set("authorization", `Bearer ${bridge}`);
      let body: ArrayBuffer | undefined;
      try {
        body = await readBodyLimited(request, bodyLimit);
      } catch {
        return Response.json({ error: "body_too_large" }, { status: 413 });
      }
      const init: RequestInit = {
        method: request.method,
        headers,
        body,
        redirect: "manual",
      };
      const timeoutMs = reviewConfig?.limits.maxSingleProxyMs ?? 0;
      const started = Date.now();
      let upstream: Response;
      try {
        upstream = await proxyWithTimeout(container, url.toString(), init, timeoutMs);
      } catch (err) {
        if (err instanceof Error && err.message === "proxy_timeout") {
          return Response.json({ error: "proxy_timeout" }, { status: 504 });
        }
        throw err;
      }
      if (reviewConfig) {
        const wallDeny = await recordReviewProxyWallMs(
          this.state,
          reviewConfig,
          Date.now() - started,
          container,
        );
        if (wallDeny) return wallDeny;
        const awakeDeny = await tickContainerAwakeMs(this.state, reviewConfig, container);
        if (awakeDeny) return awakeDeny;
      }
      return upstream;
    } finally {
      if (reviewConfig) {
        await releaseReviewProxySlot(this.state);
      }
    }
  }
}
