#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { networkInterfaces } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DAEMON = process.env.VINCI_DAEMON_URL || "http://127.0.0.1:4310";
const PORT = process.env.VINCI_DAEMON_PORT || "4310";
const STUDIO_PORT = process.env.VINCI_STUDIO_PORT || "4311";

function usage(): never {
  console.log(`vinci — open-source generative media runtime

Usage:
  vinci init [--demo]
  vinci doctor
  vinci providers add <name> [--from-env NAME] [--from-file PATH] [--extra-from-env NAME] [--extra-from-file PATH] [--url URL] [--account-id ID] [--label NAME] [--authorize-url URL]
  vinci providers list|test|remove <name>
  vinci models [--capability t2i] [--max-price 0.10]
  vinci run <skill|workflow.yaml> [--input JSON] [--max-cost N] [--prefer cheapest]
  vinci jobs [list|get <id>|approve <runId>|cancel <runId>|logs <runId>]
  vinci skills search|inspect|list|add <query|dir>
  vinci cost [report --by skill|provider|day]
  vinci catalog refresh
  vinci find <query>
  vinci sheets sync
  vinci mcp print-config
  vinci studio [--lan] [--host HOST] [--port PORT] [--html] [--no-open]
`);
  process.exit(1);
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  if (!cmd || cmd === "-h" || cmd === "--help") usage();

  if (cmd === "mcp" && argv[1] === "print-config") {
    process.stdout.write(
      JSON.stringify({ mcpServers: { vinci: { url: `${DAEMON}/mcp` } } }, null, 2) + "\n",
    );
    return;
  }

  if (cmd === "studio") {
    await runStudio(argv);
    return;
  }

  await ensureDaemon();

  if (cmd === "init") {
    print(await post("/init", { demo: argv.includes("--demo") }));
    return;
  }
  if (cmd === "doctor") {
    print(await get("/doctor"));
    return;
  }
  if (cmd === "providers") {
    const sub = argv[1];
    if (sub === "add") {
      const fromFile = flag(argv, "--from-file");
      const extraFile = flag(argv, "--extra-from-file");
      const secret = fromFile ? readFileSync(fromFile, "utf8").trim() : undefined;
      const extraSecret = extraFile ? readFileSync(extraFile, "utf8").trim() : undefined;
      print(
        await post("/providers", {
          id: argv[2],
          from_env: flag(argv, "--from-env"),
          secret,
          extra_from_env: flag(argv, "--extra-from-env"),
          extra_secret: extraSecret,
          url: flag(argv, "--url"),
          account_id: flag(argv, "--account-id"),
          label: flag(argv, "--label"),
          authorize_url: flag(argv, "--authorize-url"),
        }),
      );
      return;
    }
    if (sub === "remove") {
      print(await del(`/providers/${argv[2]}`));
      return;
    }
    if (sub === "test") {
      const all = (await get("/providers")) as Record<string, unknown>;
      const name = argv[2];
      print(name ? (all[name] ?? { error: "unknown provider", id: name }) : all);
      return;
    }
    print(await get("/providers"));
    return;
  }
  if (cmd === "models") {
    const q = new URLSearchParams();
    const capability = flag(argv, "--capability");
    const maxPrice = flag(argv, "--max-price");
    if (capability) q.set("capability", capability);
    if (maxPrice) q.set("max_price", maxPrice);
    print(await get(`/models?${q.toString()}`));
    return;
  }
  if (cmd === "run") {
    const target = argv[1];
    if (!target) usage();
    const inputRaw = flag(argv, "--input") || "{}";
    let inputs: unknown;
    try {
      inputs = JSON.parse(inputRaw);
    } catch {
      inputs = { prompt: inputRaw };
    }
    const maxCost = flag(argv, "--max-cost");
    const prefer = flag(argv, "--prefer");
    const body: Record<string, unknown> = { inputs, preference: prefer || undefined };
    if (isWorkflowFile(target)) body.workflow_path = resolve(target);
    else body.skill = target;
    if (maxCost) body.max_cost = Number(maxCost);
    const run = (await post("/runs", body)) as {
      id?: string;
      state?: string;
      awaiting_reason?: string;
      estimate?: { total?: number; nodes?: { model_id: string }[] };
      asset_uris?: string[];
      job_uris?: string[];
      receipt_uris?: string[];
    };
    const model = run.estimate?.nodes?.[0]?.model_id;
    const total = run.estimate?.total;
    if (model !== undefined) {
      console.log(`this run ≈ $${total ?? 0} via ${model}`);
    }
    for (const uri of run.asset_uris || []) console.log(uri);
    for (const uri of run.job_uris || []) console.log(uri);
    for (const uri of run.receipt_uris || []) console.log(uri);
    if (run.state === "awaiting_approval") {
      const reason = run.awaiting_reason ? `: ${run.awaiting_reason}` : "";
      console.log(`awaiting approval${reason}`);
      console.log(`vinci jobs approve ${run.id ?? "<runId>"}`);
    }
    print(run);
    return;
  }
  if (cmd === "jobs") {
    const sub = argv[1] || "list";
    if (sub === "get") print(await get(`/jobs/${argv[2]}`));
    else if (sub === "approve") print(await post(`/runs/${argv[2]}/approve`, {}));
    else if (sub === "cancel") print(await post(`/runs/${argv[2]}/cancel`, {}));
    else if (sub === "logs") print(await get(`/events?run_id=${argv[2]}`));
    else print(await get("/jobs"));
    return;
  }
  if (cmd === "skills") {
    const sub = argv[1] || "list";
    if (sub === "add") {
      const dir = argv[2];
      if (!dir) usage();
      print(await post("/skills/install", { path: dir }));
      return;
    }
    if (sub === "search") {
      print(await get(`/skills?q=${encodeURIComponent(argv.slice(2).join(" "))}`));
      return;
    }
    if (sub === "inspect") {
      print(await get(`/skills?q=${encodeURIComponent(argv[2] || "")}`));
      return;
    }
    print(await get("/skills"));
    return;
  }
  if (cmd === "cost") {
    print(await get(`/cost/report?by=${encodeURIComponent(flag(argv, "--by") || "provider")}`));
    return;
  }
  if (cmd === "catalog" && argv[1] === "refresh") {
    print(await post("/catalog/refresh", {}));
    return;
  }
  if (cmd === "find") {
    const q = argv.slice(1).join(" ");
    print(await get(`/find?q=${encodeURIComponent(q)}`));
    return;
  }
  if (cmd === "sheets") {
    if (argv[1] !== "sync") usage();
    const res = await fetch(DAEMON + "/integrations/gsheet/sync", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    const body = (await res.json()) as { detail?: string };
    if (!res.ok) {
      console.error(typeof body.detail === "string" ? body.detail : JSON.stringify(body));
      process.exit(1);
    }
    print(body);
    return;
  }
  usage();
}

async function runStudio(argv: string[]): Promise<void> {
  const lan = argv.includes("--lan");
  const noOpen = argv.includes("--no-open");
  const htmlOnly = argv.includes("--html");
  const port = flag(argv, "--port") || PORT;
  const host = lan ? "0.0.0.0" : flag(argv, "--host") || "127.0.0.1";
  const openHost = host === "0.0.0.0" ? "127.0.0.1" : host;
  const base = process.env.VINCI_DAEMON_URL || `http://${openHost}:${port}`;
  await ensureDaemon({ host, port, url: base });
  const htmlUrl = `${base.replace(/\/$/, "")}/studio`;
  const tsUrl = `http://${openHost}:${STUDIO_PORT}`;
  let studioUrl = htmlUrl;
  if (!htmlOnly) {
    const tsUp = await ensureStudioTs(base, STUDIO_PORT);
    if (tsUp) studioUrl = tsUrl;
  }
  console.log(`Vinci Studio → ${studioUrl}`);
  console.log(`Vinci Studio (HTML) → ${htmlUrl}`);
  if (lan || host === "0.0.0.0") {
    for (const lanUrl of lanStudioUrls(port)) console.log(`Vinci Studio (LAN) → ${lanUrl}`);
    if (!htmlOnly) {
      for (const lanUrl of lanStudioUrls(STUDIO_PORT)) {
        console.log(`Vinci Studio (LAN TS) → ${lanUrl.replace(/\/studio$/, "")}`);
      }
    }
    console.log("Phone/Mac apps load TypeScript Studio on :4311 when it is up; HTML /studio is the fallback. Keys stay on the daemon host.");
  }
  if (noOpen) return;
  openBrowser(studioUrl);
}

async function ensureStudioTs(daemonUrl: string, port: string): Promise<boolean> {
  const tsUrl = `http://127.0.0.1:${port}`;
  if (await pageUp(tsUrl)) return true;
  const here = dirname(fileURLToPath(import.meta.url));
  const studioDir = resolve(here, "../../studio");
  if (!existsSync(resolve(studioDir, "package.json"))) return false;
  const child = spawn("npx", ["next", "dev", "-p", port], {
    cwd: studioDir,
    detached: true,
    stdio: "ignore",
    env: { ...process.env, VINCI_DAEMON_URL: daemonUrl, PORT: port },
  });
  child.unref();
  for (let i = 0; i < 40; i++) {
    await delay(200);
    if (await pageUp(tsUrl)) return true;
  }
  return false;
}

async function pageUp(url: string): Promise<boolean> {
  try {
    const res = await fetch(url);
    return res.ok;
  } catch {
    return false;
  }
}

function flag(argv: string[], name: string): string | undefined {
  const i = argv.indexOf(name);
  if (i >= 0) return argv[i + 1];
  const prefix = `${name}=`;
  const hit = argv.find((a) => a.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : undefined;
}

function isWorkflowFile(value: string): boolean {
  return value.endsWith(".yaml") || value.endsWith(".yml");
}

async function get(path: string): Promise<unknown> {
  const res = await fetch(DAEMON + path);
  return res.json();
}

async function post(path: string, body: unknown): Promise<unknown> {
  const res = await fetch(DAEMON + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function del(path: string): Promise<unknown> {
  const res = await fetch(DAEMON + path, { method: "DELETE" });
  return res.json();
}

function print(value: unknown): void {
  process.stdout.write(JSON.stringify(value, null, 2) + "\n");
}

async function ensureDaemon(opts?: { host?: string; port?: string; url?: string }): Promise<void> {
  const url = opts?.url || DAEMON;
  if (await healthy(url)) return;
  const host = opts?.host || "127.0.0.1";
  const port = opts?.port || PORT;
  const child = spawn("python3", ["-m", "vinci_daemon", "--host", host, "--port", port], {
    detached: true,
    stdio: "ignore",
    env: process.env,
  });
  child.unref();
  for (let i = 0; i < 40; i++) {
    await delay(150);
    if (await healthy(url)) return;
  }
  throw new Error(`daemon did not start at ${url}`);
}

async function healthy(url: string = DAEMON): Promise<boolean> {
  try {
    const res = await fetch(`${url}/healthz`);
    return res.ok;
  } catch {
    return false;
  }
}

function openBrowser(url: string): void {
  const opener =
    process.platform === "darwin" ? "open" : process.platform === "win32" ? "cmd" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
  try {
    spawn(opener, args, { detached: true, stdio: "ignore" }).unref();
  } catch {
    console.log("Open that URL in a browser if the OS opener is missing.");
  }
}

function lanStudioUrls(port: string): string[] {
  const out: string[] = [];
  for (const rows of Object.values(networkInterfaces())) {
    for (const row of rows || []) {
      if (row.internal) continue;
      const family = String(row.family);
      if (family === "IPv4" || family === "4") {
        out.push(`http://${row.address}:${port}/studio`);
      }
    }
  }
  return out;
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

void main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  console.error(message);
  process.exit(1);
});
