#!/usr/bin/env node
/** Supervise Next standalone server; forward signals; exit when parent PID dies. */
const { spawn } = require("node:child_process");
const path = require("node:path");

const parent = Number.parseInt(process.env.VINCI_PARENT_PID || "0", 10);
const serverJs = path.join(__dirname, "server.js");
const child = spawn(process.execPath, [serverJs], {
  cwd: __dirname,
  env: process.env,
  stdio: ["ignore", "pipe", "pipe"],
});

function pipe(stream, target) {
  stream.on("data", (chunk) => target.write(chunk));
}

pipe(child.stdout, process.stdout);
pipe(child.stderr, process.stderr);

function shutdownChild() {
  if (!child.killed) {
    child.kill("SIGTERM");
    setTimeout(() => {
      if (!child.killed) child.kill("SIGKILL");
    }, 4000).unref();
  }
}

for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) {
  process.on(sig, () => {
    shutdownChild();
  });
}

if (parent > 0) {
  const timer = setInterval(() => {
    try {
      process.kill(parent, 0);
    } catch {
      clearInterval(timer);
      shutdownChild();
    }
  }, 500);
  child.on("exit", () => clearInterval(timer));
}

child.on("exit", (code, signal) => {
  if (signal) {
    process.exit(1);
  }
  process.exit(code ?? 1);
});
