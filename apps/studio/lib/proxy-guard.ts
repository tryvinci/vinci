import type { NextRequest } from "next/server";

export const STUDIO_SESSION_COOKIE = "vinci_studio_session";

function sessionSecret(): string {
  return process.env.VINCI_STUDIO_SESSION || "";
}

export function studioHostExpected(): string {
  return process.env.VINCI_STUDIO_HOST || "";
}

export function studioOriginExpected(): string {
  return process.env.VINCI_STUDIO_ORIGIN || "";
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export function denyProxy(request: NextRequest): { status: number; detail: string } | null {
  const expectedHost = studioHostExpected();
  if (!expectedHost) {
    return { status: 503, detail: "studio host not configured" };
  }
  const secret = sessionSecret();
  if (!secret) {
    return { status: 503, detail: "studio session not configured" };
  }
  const cookie = request.cookies.get(STUDIO_SESSION_COOKIE)?.value || "";
  if (!cookie || !safeEqual(cookie, secret)) {
    return { status: 401, detail: "unauthorized" };
  }
  const host = request.headers.get("host") || "";
  if (host !== expectedHost) {
    return { status: 403, detail: "forbidden host" };
  }
  const method = request.method.toUpperCase();
  if (method !== "GET" && method !== "HEAD") {
    const origin = request.headers.get("origin") || "";
    const allowed = studioOriginExpected();
    if (!allowed || origin !== allowed) {
      return { status: 403, detail: "forbidden origin" };
    }
  }
  return null;
}

export const PROXY_HEADER_ALLOWLIST = new Set([
  "accept",
  "accept-language",
  "content-type",
  "content-length",
  "x-vinci-operation-id",
  "range",
  "if-none-match",
  "if-modified-since",
]);
