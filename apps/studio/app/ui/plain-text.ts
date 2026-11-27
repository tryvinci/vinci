import { money } from "../../lib/model-capabilities";

const LEAK = /vinci:\/\/|\bsha256\b|\breceipt\b|\bdaemon\b|\bCAS\b/i;

const NETWORK = /^(Failed to fetch|NetworkError|Load failed|Network request failed)/i;

/** The `detail` of a JSON error body (FastAPI), when it is plain text. */
function jsonDetail(text: string): string {
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : text;
  } catch {
    return text;
  }
}

/**
 * User-facing error. Hides internals. Says what to do next. Bugs fixed (first occurrence, 2026-11-13
 * production crawl, COREPRODUC-642): a raw `{"detail": …}` body (a 415 for a .txt upload) showed the
 * generic message, and a network failure showed "Failed to fetch".
 */
export function plainError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  let trimmed = raw.trim();
  if (trimmed.startsWith("{")) trimmed = jsonDetail(trimmed).trim();
  if (NETWORK.test(trimmed)) return "Could not reach Vinci. Check your connection, then try again.";
  if (
    !trimmed ||
    LEAK.test(trimmed) ||
    trimmed.length > 180 ||
    trimmed.startsWith("{") ||
    trimmed.startsWith("<") ||
    trimmed.startsWith("[")
  ) {
    return "Something went wrong. Try again. If this model needs a key, open Connect.";
  }
  return trimmed;
}

/** The one next step for a refused or failed run: add Vinci credits, take a paid plan, or open Connect. */
export type RunAction = "credits" | "upgrade" | "connect";
/** A refused or failed run: the reason in plain words, and the button that fixes it, if any. */
export type RunProblem = { text: string; action?: RunAction };

/**
 * A refused or failed run as a reason and a next step (COREPRODUC-692). The server's reason is
 * already plain; the HTTP status that `api()` attaches, else the reason's words, picks the button.
 * On a host, 402 means not enough Vinci credits and 403 the free plan; the local daemon sends neither
 * for a run. A provider refusal, a sign-in or a key is fixed in Connect.
 *
 * Args:
 *   err: An `api()` error (with `status`), or a failed run's `error` text.
 * Returns:
 *   The reason (as `plainError` gives it) and the action, if one fits.
 */
export function runProblem(err: unknown): RunProblem {
  const text = plainError(err);
  const status = (err as { status?: number } | null)?.status;
  // The server's own reason, not the shown text: "connection" (network) and the generic fallback
  // ("…open Connect") are no sign of a provider problem.
  const reason = err instanceof Error ? err.message : String(err ?? "");
  const action: RunAction | undefined =
    status === 402
      ? "credits"
      : status === 403
        ? "upgrade"
        : /\bconnect\b|\bsign in\b|key was removed|refused the request/i.test(reason)
          ? "connect"
          : undefined;
  return action ? { text, action } : { text };
}
/** Why a run waits, from the runtime's `awaiting_reason` (`should_await_approval`), in plain words. */
const LIMITS: [RegExp, string][] = [
  [/exceeds --max-cost (-?[\d.]+)/, "your max cost"],
  [/would exceed monthly cap (-?[\d.]+)/, "your monthly cap"],
  [/exceeds require_approval_over (-?[\d.]+)/, "your approval limit"],
];

/**
 * Why a run waits for the person's approval (COREPRODUC-786): "$0.080 is over your max cost of $0.010".
 * Before, the Studio stopped at `awaiting_approval` with the generic "Something went wrong" text,
 * and only the CLI could approve the run.
 *
 * Args:
 *   run: A run in `awaiting_approval`: its `estimate.total` (USD) and `awaiting_reason`.
 * Returns:
 *   The price and the limit it is over (only the price for a reason it does not know).
 */
export function approvalReason(run: { estimate?: { total?: number }; awaiting_reason?: unknown }): string {
  const reason = typeof run.awaiting_reason === "string" ? run.awaiting_reason : "";
  const hit = LIMITS.map(([re, name]) => [reason.match(re), name] as const).find(([m]) => m);
  const over = hit?.[0] ? ` is over ${hit[1]} of ${money(Number(hit[0][1]))}` : "";
  return `${money(run.estimate?.total)}${over}`;
}
