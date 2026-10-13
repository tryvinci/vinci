/** Normalize worker origin → DO journal HTTP API base (parity with journal_payload.py). */

export const DO_JOURNAL_PATH_SUFFIX = "/__vinci/journal";

export function normalizeDoJournalBase(base: string): string {
  const raw = base.trim().replace(/\/+$/, "");
  if (!raw) {
    return "";
  }
  if (raw.endsWith(DO_JOURNAL_PATH_SUFFIX)) {
    return raw;
  }
  return `${raw}${DO_JOURNAL_PATH_SUFFIX}`;
}
