import { defineConfig } from "@playwright/test";
import path from "node:path";

const here = __dirname;
const oss = path.resolve(here, "../..");
const artifacts = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  use: {
    baseURL: process.env.STUDIO_URL || "http://127.0.0.1:4311",
    viewport: { width: 1440, height: 900 },
    screenshot: "off",
  },
  outputDir: path.join(artifacts, "test-output"),
  reporter: [["list"]],
  webServer: {
    command: `bash ${path.join(here, "e2e/start-studio.sh")}`,
    url: "http://127.0.0.1:4311",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    cwd: oss,
  },
});
