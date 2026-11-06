const LEAK = /vinci:\/\/|\bsha256\b|\breceipt\b|\bdaemon\b|\bCAS\b/i;

/** User-facing error. Hides internals. Says what to do next. */
export function plainError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  const trimmed = raw.trim();
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