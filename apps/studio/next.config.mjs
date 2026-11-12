import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));

// `npm run build:static` writes plain files to out/ for a host that serves this Studio (Vinci
// Platform) under VINCI_STUDIO_BASE_PATH and answers /vinci-api itself. pageExtensions drops the
// .ts files that need a Node server (middleware.ts, the route.ts proxies). "js" stays because
// Next.js builds its own not-found page from a .js file.
const basePath = process.env.VINCI_STUDIO_BASE_PATH || "";
const staticExport = {
  output: "export",
  basePath,
  env: { NEXT_PUBLIC_VINCI_STUDIO_BASE_PATH: basePath },
  pageExtensions: ["tsx", "js"],
  outputFileTracingRoot: path.join(dir, "../.."),
};

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(dir, "../.."),
  // POST /runs blocks until a live job ends. The rewrite proxy default (30 s) turned every video into a 500.
  experimental: { proxyTimeout: 15 * 60 * 1000 },
  async rewrites() {
    // Dev-only fallback; production Mac bundle uses app/vinci-api/[...path]/route.ts
    if (process.env.VINCI_STUDIO_USE_REWRITE === "1") {
      const daemon = process.env.VINCI_DAEMON_URL || "http://127.0.0.1:4310";
      return [{ source: "/vinci-api/:path*", destination: `${daemon}/:path*` }];
    }
    return [];
  },
};

export default process.env.VINCI_STUDIO_EXPORT === "1" ? staticExport : nextConfig;
