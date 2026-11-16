/**
 * The progress bar of a generation (COREPRODUC-659). Providers send no progress, so the bar is a
 * fake countdown: it fills to 90% over the model's average run time, then waits at 90% until the
 * run ends. The average comes from the user's own finished runs of that model, else a default by kind.
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
 * Seconds a model's runs take: the mean of its newest finished runs, else the default for its kind.
 *
 * Args:
 *   runs: `/runs` rows, any order.
 *   modelId: The model about to run.
 *   kind: The model's kind, for the default.
 */
export function averageSeconds(runs: readonly TimedRun[], modelId: string, kind = "image"): number {
  const times = runs
    .filter((run) => run.state === "completed" && modelId && runModel(run) === modelId)
    .map((run) => ({ end: Date.parse(run.completed_at || ""), start: Date.parse(run.started_at || run.created_at || "") }))
    .filter(({ end, start }) => end - start >= 1000 && end - start <= 3_600_000) // a lost clock is no average
    .sort((a, b) => b.end - a.end)
    .slice(0, RECENT)
    .map(({ end, start }) => (end - start) / 1000);
  if (!times.length) return DEFAULT_SECONDS[kind] ?? DEFAULT_SECONDS.image!;
  return Math.round(times.reduce((sum, t) => sum + t, 0) / times.length);
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
