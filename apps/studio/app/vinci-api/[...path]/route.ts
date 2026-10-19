import { NextRequest, NextResponse } from "next/server";
import { PROXY_HEADER_ALLOWLIST, denyProxy } from "../../../lib/proxy-guard";

export const runtime = "nodejs";

const daemonBase = () => (process.env.VINCI_DAEMON_URL || "http://127.0.0.1:4310").replace(/\/$/, "");
const bridgeToken = () => process.env.VINCI_BRIDGE_TOKEN || "";

async function proxy(req: NextRequest, pathSegments: string[]): Promise<NextResponse> {
  try {
  const rewrite = process.env.VINCI_STUDIO_USE_REWRITE === "1";
  const denied = rewrite ? null : denyProxy(req);
  if (denied) {
    return NextResponse.json({ detail: denied.detail }, { status: denied.status });
  }
  const path = pathSegments.map((p) => encodeURIComponent(p)).join("/");
  const target = `${daemonBase()}/${path}${req.nextUrl.search}`;
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (!PROXY_HEADER_ALLOWLIST.has(lower)) return;
    headers.set(key, value);
  });
  const token = bridgeToken();
  if (!token && !rewrite) {
    return NextResponse.json({ detail: "daemon bridge not configured" }, { status: 503 });
  }
  if (token) headers.set("authorization", `Bearer ${token}`);
  const init: RequestInit & { duplex?: "half" } = {
    method: req.method,
    headers,
    redirect: "manual",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = req.body;
    init.duplex = "half";
  }
  const upstream = await fetch(target, init);
  const outHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (lower === "transfer-encoding" || lower === "content-encoding" || lower === "content-length") {
      return;
    }
    outHeaders.set(key, value);
  });
  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: outHeaders,
  });
  } catch {
    return NextResponse.json({ detail: "proxy unavailable" }, { status: 503 });
  }
}

type RouteCtx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function POST(req: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function PATCH(req: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function PUT(req: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function DELETE(req: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
