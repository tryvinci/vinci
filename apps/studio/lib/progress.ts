/**
 * The progress bar of a generation (COREPRODUC-659). Providers send no progress, so the bar is a
 * fake countdown: it fills to 90% over the model's average run time, then waits at 90% until the
 * run ends. The estimate is the median of the user's own finished runs of that model, else a default by
 * kind and provider.
 */

/** A run as `/runs` gives it: the fields the average needs. */
export type TimedRun = {
  state?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  inputs?: { model_id?: unknown };
  workflow?: { nodes?: { model_id?: string }[] };
};

/** A generation in flight: when it started (ms) and the seconds it should take. */
export type RunClock = { startedAt: number; seconds: number };

export const CAP = 90; // the bar waits here until the run ends
const RECENT = 20; // newest finished runs in the average
const DEFAULT_SECONDS: Record<string, number> = { image: 20, video: 120, audio: 30, text: 15 };
// Sign-in providers are slower (COREPRODUC-687, prod 2026-11-18): Magnific and Higgsfield images took
// 38-79 s (Wavespeed 16-22 s) and Magnific kling-30 video 634 s. Their ids name them ("mcp_magnific:…").
const SIGN_IN_SECONDS: Record<string, number> = { image: 60, video: 600 };
const SIGN_IN = /(^|_)(magnific|higgsfield):/;

/** Seconds a model with no history takes: by kind, longer on a sign-in provider. */
export function defaultSeconds(modelId: string, kind = "image"): number {
  const own = SIGN_IN.test(modelId) ? SIGN_IN_SECONDS[kind] : undefined;
  return own ?? DEFAULT_SECONDS[kind] ?? DEFAULT_SECONDS.image!;
}

/** The model of a run: its `model_id` input, else the one model its nodes name. */
export function runModel(run: TimedRun): string {
  if (typeof run.inputs?.model_id === "string" && run.inputs.model_id) return run.inputs.model_id;
  const ids = new Set((run.workflow?.nodes || []).map((n) => n.model_id).filter(Boolean));
  return ids.size === 1 ? [...ids][0]! : "";
}

/** image, video, audio or text, from a model's capabilities. */
export function modelKind(capabilities: readonly string[] = []): string {
  if (capabilities.some((c) => /(^|2)v$|video|extend|flf|lipsync/.test(c))) return "video";
  if (capabilities.some((c) => /tts|music|sfx|audio|speech|voice/.test(c))) return "audio";
  if (capabilities.some((c) => c === "t2t")) return "text";
  return "image";
}

/**
 * Seconds a model's runs take: the median of its newest finished runs, else `defaultSeconds`.
 *
 * Bug fixed (first seen in prod logs 2026-11-18, 1 user report 2026-11-26, COREPRODUC-687): the mean let
 * one slow run (a 5.5 min Magnific card among 28-44 s ones) set the next bar to minutes.
 *
 * Args:
 *   runs: `/runs` rows, any order.
 *   modelId: The model about to run.
 *   kind: The model's kind, for the default.
 *
 * Returns:
 *   Whole seconds, at least 1.
 */
export function averageSeconds(runs: readonly TimedRun[], modelId: string, kind = "image"): number {
  const times = runs
    .filter((run) => run.state === "completed" && modelId && runModel(run) === modelId)
    .map((run) => ({ end: Date.parse(run.completed_at || ""), start: Date.parse(run.started_at || run.created_at || "") }))
    .filter(({ end, start }) => end - start >= 1000 && end - start <= 3_600_000) // a lost clock is no average
    .sort((a, b) => b.end - a.end)
    .slice(0, RECENT)
    .map(({ end, start }) => (end - start) / 1000)
    .sort((a, b) => a - b);
  if (!times.length) return defaultSeconds(modelId, kind);
  const mid = times.length >> 1;
  return Math.round(times.length % 2 ? times[mid]! : (times[mid - 1]! + times[mid]!) / 2);
}

/** Percent done (0 to 90) and whole seconds left, `elapsedMs` into a run of `seconds`. */
export function fakeProgress(elapsedMs: number, seconds: number): { pct: number; left: number } {
  const total = Math.max(1, seconds) * 1000;
  const elapsed = Math.max(0, elapsedMs);
  return { pct: Math.min(CAP, (CAP * elapsed) / total), left: Math.max(0, Math.ceil((total - elapsed) / 1000)) };
}

/** The line under the bar: "About 12s left", "About 1m 05s left", then "Almost done…" at 90%. */
export function progressLabel(left: number): string {
  if (left <= 0) return "Almost done…";
  const m = Math.floor(left / 60);
  const s = left % 60;
  return `About ${m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`} left`;
}
