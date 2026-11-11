#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, networkInterfaces } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DAEMON = process.env.VINCI_DAEMON_URL || "http://127.0.0.1:4310";
const PORT = process.env.VINCI_DAEMON_PORT || "4310";
const STUDIO_PORT = process.env.VINCI_STUDIO_PORT || "4311";
// The servers this CLI starts, one JSON file each ({pid, url}), for `vinci stop`. Same home as the
// daemon (vinci_core.paths.default_home).
const HOME = process.env.VINCI_HOME ? resolve(process.env.VINCI_HOME.replace(/^~(?=$|\/)/, homedir())) : join(homedir(), ".vinci");
const RUN_DIR = join(HOME, "run");
type Server = "daemon" | "studio";

function usage(): never {
  console.log(`vinci — open-source generative media runtime

Usage:
  vinci init [--demo]
  vinci doctor
  vinci providers add <name> [--from-env NAME] [--from-file PATH] [--extra-from-env NAME] [--extra-from-file PATH] [--url URL] [--account-id ID] [--label NAME] [--authorize-url URL]
  vinci providers connect <higgsfield|magnific|url>
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
  vinci stop [--force]   (stop the daemon and Studio that vinci started; --force also kills a busy daemon)
  vinci olf validate|resolve <shot>|status|render <shot>|review <take>|select <shot> [-C PROJECT]   (OLF movie engine)
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

  if (cmd === "stop") {
    process.exitCode = await runStop(argv.includes("--force"));
    return;
  }

  if (cmd === "olf") {
    // OLF movie engine (packages/olf): Python, local runtime, no daemon. Exit code passes through.
    const child = spawn("python3", ["-m", "vinci_olf", ...argv.slice(1)], { stdio: "inherit" });
    child.on("error", (err) => {
      // No python3 on PATH: one line instead of an unhandled 'error' event and a stack trace.
      process.stderr.write(`vinci olf: cannot start python3 (${err.message}). Install Python 3.11 or newer, then run make install.\n`);
      process.exit(2);
    });
    child.on("exit", (code) => process.exit(code ?? 1));
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
    if (sub === "connect") {
      const target = argv[2];
      if (!target) usage();
      const presets: Record<string, { id: string; label: string }> = {
        higgsfield: { id: "mcp_higgsfield", label: "Higgsfield" },
        magnific: { id: "mcp_magnific", label: "Magnific" },
      };
      const preset = presets[target];
      const id = preset?.id || flag(argv, "--id") || "mcp";
      print(
        await post("/providers", {
          id,
          url: preset ? undefined : target,
          label: preset?.label || flag(argv, "--label"),
        }),
      );
      const started = (await post(`/providers/${encodeURIComponent(id)}/oauth`, {})) as {
        mode?: string;
        authorize_url?: string;
        hint?: string;
      };
      print(started);
      if (started.mode === "oauth" && started.authorize_url) {
        console.log(started.authorize_url);
        for (let i = 0; i < 60; i += 1) {
          await delay(1000);
          const rows = (await get("/providers")) as Record<string, { auth_state?: string }>;
          if (rows[id]?.auth_state === "connected") {
            console.log(`${id} connected`);
            return;
          }
        }
        console.log("still waiting for sign-in");
      }
      return;
    }
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

/**
 * Start the daemon and open Studio: the TypeScript Studio on :4311 when it can start, else the
 * deprecated daemon HTML page at /studio (with a warning naming the fix).
 *
 * Args (argv flags): --lan binds 0.0.0.0 and prints LAN URLs; --no-open skips the browser;
 * --html forces the HTML page; --port / --host override the daemon address.
 */
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
  console.log(`Vinci Studio (HTML, deprecated) → ${htmlUrl}`);
  if (studioUrl === htmlUrl) {
    const fix = htmlOnly
      ? "Drop --html"
      : "Install Node 20+ and run from a clone with apps/studio";
    console.warn(
      `Warning: the HTML Studio at /studio is deprecated and gets no new features. ${fix} to use the TypeScript Studio on :${STUDIO_PORT}.`,
    );
  }
  if (lan || host === "0.0.0.0") {
    for (const lanUrl of lanStudioUrls(port)) console.log(`Vinci Studio (LAN) → ${lanUrl}`);
    if (studioUrl === tsUrl) {
      for (const lanUrl of lanStudioUrls(STUDIO_PORT)) {
        console.log(`Vinci Studio (LAN TS) → ${lanUrl.replace(/\/studio$/, "")}`);
      }
    }
    console.log(`Phone/Mac apps load TypeScript Studio on :${STUDIO_PORT} when it is up; the deprecated HTML /studio is the fallback. Keys stay on the daemon host.`);
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
    env: {
      ...process.env,
      VINCI_DAEMON_URL: daemonUrl,
      VINCI_STUDIO_USE_REWRITE: "1",
      PORT: port,
    },
  });
  child.unref();
  remember("studio", child.pid, tsUrl);
  for (let i = 0; i < 40; i++) {
    await delay(200);
    if (await pageUp(tsUrl)) return true;
  }
  return false;
}

/** Record a server this CLI started, so `vinci stop` can find it. A failure only warns. */
function remember(name: Server, pid: number | undefined, url: string): void {
  if (!pid) return;
  try {
    mkdirSync(RUN_DIR, { recursive: true });
    writeFileSync(join(RUN_DIR, `${name}.json`), JSON.stringify({ pid, url }) + "\n");
  } catch (err) {
    console.warn(`vinci: cannot record the ${name} in ${RUN_DIR} (${String(err)}); vinci stop will not find it`);
  }
}

/**
 * Stop the Studio and the daemon that `vinci` started (`$VINCI_HOME/run/*.json`). Each gets SIGTERM
 * to its process group (`npx next dev` has children), only while its server still answers, so a
 * pid that the OS gave to another program is never signalled. The Studio gets SIGKILL after 10 s;
 * the daemon only with `force`, because SIGTERM waits for open requests and a job can be paid.
 *
 * Returns:
 *   The exit code: 1 when a recorded server is still up, else 0.
 */
async function runStop(force: boolean): Promise<number> {
  let code = 0;
  let said = false;
  for (const name of ["studio", "daemon"] as Server[]) {
    const file = join(RUN_DIR, `${name}.json`);
    if (!existsSync(file)) continue;
    said = true;
    let rec: { pid?: number; url?: string } = {};
    try {
      rec = JSON.parse(readFileSync(file, "utf8")) as typeof rec;
    } catch {
      // a broken record: drop it below
    }
    const probe = rec.url && (name === "daemon" ? `${rec.url.replace(/\/$/, "")}/healthz` : rec.url);
    if (!rec.pid || !probe || !(await pageUp(probe))) {
      console.log(`${name}: not running (removed the old record)`);
      rmSync(file, { force: true });
      continue;
    }
    signal(rec.pid, "SIGTERM");
    let down = await stopsAnswering(probe, 10_000);
    if (!down && (name === "studio" || force)) {
      signal(rec.pid, "SIGKILL");
      down = await stopsAnswering(probe, 5_000);
    }
    if (down) {
      console.log(`stopped ${name} (pid ${rec.pid}, ${rec.url})`);
      rmSync(file, { force: true });
    } else {
      console.log(`${name} (pid ${rec.pid}, ${rec.url}) is still finishing open requests, such as a running job. Run vinci stop --force to kill it.`);
      code = 1;
    }
  }
  // A server that answers with no record was started some other way (make dev, another terminal).
  const daemonUrl = DAEMON.replace(/\/$/, "");
  for (const [name, probe, url] of [
    ["daemon", `${daemonUrl}/healthz`, daemonUrl],
    ["studio", `http://127.0.0.1:${STUDIO_PORT}`, `http://127.0.0.1:${STUDIO_PORT}`],
  ] as const) {
    if (!existsSync(join(RUN_DIR, `${name}.json`)) && (await pageUp(probe))) {
      console.log(`${name} at ${url} was not started by vinci: stop it where it runs (Ctrl+C there).`);
      said = true;
    }
  }
  if (!said) console.log("nothing to stop: vinci started no daemon or Studio that is still running");
  return code;
}

/** Send `sig` to the process group of `pid` (POSIX), or end its process tree (Windows). */
function signal(pid: number, sig: NodeJS.Signals): void {
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(pid), "/t", ...(sig === "SIGKILL" ? ["/f"] : [])], { stdio: "ignore" });
    return;
  }
  try {
    process.kill(-pid, sig); // a detached child leads its own process group
  } catch {
    try {
      process.kill(pid, sig);
    } catch {
      // already gone
    }
  }
}

/** Wait up to `ms` for `url` to stop answering. */
async function stopsAnswering(url: string, ms: number): Promise<boolean> {
  for (let waited = 0; waited < ms; waited += 250) {
    if (!(await pageUp(url))) return true;
    await delay(250);
  }
  return !(await pageUp(url));
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
  remember("daemon", child.pid, url);
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
