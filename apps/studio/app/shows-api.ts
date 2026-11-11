import { OLF_API, type OlfBatchJob, type OlfPlan } from "../lib/shows";

/** Call the daemon's OLF routes. A 4xx carries the engine's own message, which is written for people. */
export async function olf<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(OLF_API + path, init);
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) throw new Error(String(body.detail || res.statusText || "The request failed"));
  return body as T;
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
