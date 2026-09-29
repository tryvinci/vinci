import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  outputFileTracingRoot: dir,
  async rewrites() {
    const daemon = process.env.VINCI_DAEMON_URL || "http://127.0.0.1:4310";
    return [{ source: "/vinci-api/:path*", destination: `${daemon}/:path*` }];
  },
};

export default nextConfig;
