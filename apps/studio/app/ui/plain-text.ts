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