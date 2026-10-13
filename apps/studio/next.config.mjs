import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));
/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: dir,
  async rewrites() {
    // Dev-only fallback; production Mac bundle uses app/vinci-api/[...path]/route.ts
    if (process.env.VINCI_STUDIO_USE_REWRITE === "1") {
      const daemon = process.env.VINCI_DAEMON_URL || "http://127.0.0.1:4310";
      return [{ source: "/vinci-api/:path*", destination: `${daemon}/:path*` }];
    }
    return [];
  },
};

export default nextConfig;
