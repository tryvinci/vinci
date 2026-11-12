import { createContext, useContext } from "react";
import { OLF_API, type OlfBatchJob, type OlfPlan } from "../lib/shows";

/**
 * The OLF routes the daemon serves (from `/openapi.json`). A host serves fewer for now (Vinci
 * Platform has no cues, voices, previs or share yet), so the Shows pages hide those controls.
 * Every route counts as served until the list loads.
 */
export const OlfRoutes = createContext<(path: string) => boolean>(() => true);

export function useOlfRoute(path: string): boolean {
  return useContext(OlfRoutes)(path);
}

/** Runs this page polls now, so a reloaded show does not poll the same run twice. */
export const polling = new Set<string>();
const POLL_MS = 2000;
const wait = () => new Promise((done) => window.setTimeout(done, POLL_MS));

/**
 * Call the daemon's OLF routes. A 4xx carries the engine's own message, which is written for people.
 * A host answers a long step at once (HTTP 202) and runs it after: a render as a run (`run_id`), an
 * export as a job (`export_id`). This waits for its end, so callers get the finished answer either way.
 */
export async function olf<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(OLF_API + path, init);
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown; run_id?: string; export_id?: string };
  if (!res.ok) throw new Error(String(body.detail || res.statusText || "The request failed"));
  if (res.status === 202 && body.run_id) return { ...body, ...(await waitRun(body.run_id)) } as T;
  if (res.status === 202 && body.export_id) return (await waitExport(body.export_id)) as T;
  return body as T;
}

/**
 * Poll a host's render run (`GET /runs/{id}`) until it ends. Each poll moves the run on and
 * charges each finished step once, so a reload loses nothing.
 *
 * Returns:
 *   The takes the host recorded and the run's total.
 */
export async function waitRun(id: string): Promise<{ takes: string[]; total: number }> {
  polling.add(id);
  try {
    for (;;) {
      const res = await fetch(`${OLF_API.replace(/\/olf$/, "")}/runs/${encodeURIComponent(id)}`);
      const run = (await res.json().catch(() => ({}))) as {
        state?: string;
        error?: string;
        detail?: string;
        estimate?: { total?: number };
        olf?: { takes?: string[]; recorded?: boolean };
      };
      if (!res.ok) throw new Error(String(run.detail || res.statusText || "The render stopped"));
      // A Shows run ends when its takes are in the show too: a busy show records on a later poll.
      const recorded = !run.olf || run.olf.recorded;
      if (run.state === "completed" && recorded) return { takes: run.olf?.takes || [], total: run.estimate?.total || 0 };
      if ((run.state === "failed" || run.state === "cancelled") && recorded) throw new Error(run.error || `The render was ${run.state}`);
      await wait();
    }
  } finally {
    polling.delete(id);
  }
}

/** Poll a host's export job (`GET /olf/exports/{id}`) until its files are ready. */
async function waitExport(id: string): Promise<unknown> {
  for (;;) {
    await wait();
    const job = await olf<{ state: string; error?: string }>(`/exports/${encodeURIComponent(id)}`);
    if (job.state === "done") return job;
    if (job.state === "failed") throw new Error(job.error || "The export failed");
  }
}

export function send(method: string, body: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

/** An error as a notice: the engine's words, cut to 320 characters. */
export function message(err: unknown): string {
  const text = err instanceof Error ? err.message : String(err ?? "");
  return text.length > 320 ? `${text.slice(0, 317)}…` : text || "Something went wrong. Try again.";
}

/**
 * Run a batch's planned jobs one `POST /olf/render` each. A whole batch in one request outlived
 * the Studio proxy (15 min in dev, 5 min packaged) in the 2026-11-09 live test. Each job is bounded
 * by its planned price; a failed job is kept and the rest go on, but a higher price stops the run
 * (it needs a new confirm).
 *
 * Args:
 *   onStep: Called before each job (`done` jobs finished so far) and once at the end.
 */
export async function runJobs(
  path: string,
  jobs: readonly OlfBatchJob[],
  yes: boolean,
  onStep: (done: number, job: OlfBatchJob | null) => void | Promise<void>,
): Promise<{ takes: string[]; total: number; failed: { shot: string; error: string }[] }> {
  const out = { takes: [] as string[], total: 0, failed: [] as { shot: string; error: string }[] };
  for (const [done, job] of jobs.entries()) {
    await onStep(done, job);
    const body = { path, shot: job.shot, kind: job.kind || "keyframe", count: job.count || 1, yes, max_total: job.total ?? 0 };
    try {
      const made = await olf<OlfPlan>("/render", send("POST", body));
      out.takes.push(...(made.takes || []));
      out.total += made.total || 0;
    } catch (err) {
      const error = message(err);
      console.warn("[shows] batch job failed", { shot: job.shot, kind: job.kind, error });
      out.failed.push({ shot: job.shot, error });
      if (error.startsWith("the price changed")) break;
    }
  }
  await onStep(jobs.length, null);
  return out;
}
