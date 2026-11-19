import { uploadForm } from "./projects";

/**
 * Uploads (COREPRODUC-710): one way to send a file to the Studio's server. The server states its
 * limits in `GET /doctor` (`limits`), so a file it would refuse is refused here, before the bytes
 * leave the browser, with the real number. An error page that is not JSON (a proxy's 413) still
 * becomes a sentence.
 */
export type UploadLimits = { upload_bytes?: number | null; import_bytes?: number | null };

let limits: UploadLimits = {};

/** What a host takes per request until it states its limits: Cloud Run refuses bodies over 32 MiB. */
export const HOST_REQUEST_BYTES = 30 * 1024 * 1024;

/** Set from `limits` in `GET /doctor`, as `setPriceUnit` does for the price unit. */
export function setUploadLimits(next?: UploadLimits | null): void {
  limits = next || {};
}

/** A size for people: `850 KB`, `40 MB`, `2.0 GB` (decimal units, as the servers count). */
export function sizeText(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

/** Why the server would refuse this file (`kind`: a Studio upload or a show import), or "". */
export function tooLarge(name: string, size: number, kind: "upload" | "import"): string {
  const cap = kind === "import" ? limits.import_bytes : limits.upload_bytes;
  return cap && size > cap ? `${name} is ${sizeText(size)}; this server takes files up to ${sizeText(cap)}.` : "";
}

/** The reason in an error answer: the server's `detail`, else plain words (never an HTML page). */
export async function errorText(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (detail) return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch {
    // not JSON: a proxy's page, or plain text
  }
  if (res.status === 413) return "The file is larger than this server takes.";
  if (text && !text.trimStart().startsWith("<")) return text.slice(0, 320);
  return res.statusText || `The request failed (HTTP ${res.status}).`;
}

/** Send a file to `POST /assets` with the tab's project: the stored asset, or an Error with the reason. */
export async function uploadFile<T = { id: string }>(api: string, file: File): Promise<T> {
  const refused = tooLarge(file.name, file.size, "upload");
  if (refused) throw new Error(refused);
  const res = await fetch(`${api}/assets`, { method: "POST", body: uploadForm(file) });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as T;
}
