import { createHmac, timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

function launchNonce(): string {
  return process.env.VINCI_LAUNCH_NONCE || "";
}

function sessionSecret(): string {
  return process.env.VINCI_STUDIO_SESSION || "";
}

function bridgeSecret(): string {
  return process.env.VINCI_BRIDGE_TOKEN || "";
}

function safeEqual(a: string, b: string): boolean {
  if (!a || !b) return false;
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

/** Native shell proves Studio identity via bridge token before any session cookie exists in WK. */
export async function GET(request: NextRequest) {
  const nonce = launchNonce();
  const secret = sessionSecret();
  const expectedBridge = bridgeSecret();
  if (!nonce || !secret || !expectedBridge) {
    return NextResponse.json({ detail: "studio not configured" }, { status: 503 });
  }
  const bridge = request.headers.get("x-vinci-bridge-token") || "";
  if (!bridge || !safeEqual(bridge, expectedBridge)) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const proof = createHmac("sha256", secret).update(nonce).digest("hex");
  return NextResponse.json({
    ok: true,
    pid: process.pid,
    launch_nonce: nonce,
    proof,
  });
}
