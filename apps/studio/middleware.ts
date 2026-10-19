import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { denyProxy } from "./lib/proxy-guard";

export function middleware(request: NextRequest) {
  if (!request.nextUrl.pathname.startsWith("/vinci-api/")) {
    return NextResponse.next();
  }
  if (process.env.VINCI_STUDIO_USE_REWRITE === "1") {
    return NextResponse.next();
  }
  const denied = denyProxy(request);
  if (denied) {
    return NextResponse.json({ detail: denied.detail }, { status: denied.status });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/vinci-api/:path*"],
};
