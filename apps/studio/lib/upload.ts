import { currentProject, uploadForm } from "./projects";

/**
 * Uploads (COREPRODUC-710): one way to send a file to the Studio's server. The server states its
 * limits in `GET /doctor` (`limits`), so a file it would refuse is refused here, before the bytes
 * leave the browser, with the real number. An error page that is not JSON (a proxy's 413) still
 * becomes a sentence.
 */
export type UploadLimits = { upload_bytes?: number | null; import_bytes?: number | null; direct?: boolean };

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

/** Whether the server takes files straight to storage (`limits.direct`: `POST /uploads`). */
export function directUploads(): boolean {
  return Boolean(limits.direct);
}

/**
 * Send a file straight to the host's storage (COREPRODUC-710): `POST /uploads` opens a session, the
 * file goes to its URL in pieces (after a network or storage failure it asks storage what it keeps and goes
 * on from there, up to 3 times in a row), and
 * `POST /uploads/{id}/complete` finishes it.
 *
 * Args:
 *   api: The Studio API base (`/vinci-api`).
 *   file: The file.
 *   kind: `asset` (a media file) or `import` (a `.volf` package: the answer is an import job).
 *   onProgress: Hears the share sent so far, 0 to 1.
 *
 * Returns:
 *   The complete answer: the asset, or `{export_id}` of the import job.
 */
export async function sendDirect<T>(api: string, file: File, kind: "asset" | "import", onProgress?: (share: number) => void): Promise<T> {
  const start = await fetch(`${api}/uploads`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: file.name, size: file.size, mime: file.type, kind, project_id: currentProject() }),
  });
  if (!start.ok) throw new Error(await errorText(start));
  const { id, url, chunk_bytes: chunk } = (await start.json()) as { id: string; url: string; chunk_bytes: number };
  const total = file.size;
  let at = 0;
  const ask = () => fetch(url, { method: "PUT", headers: { "content-range": `bytes */${total}` } }).catch(() => null);
  // A 308 says more to send; Range is what storage keeps, none yet when it is absent (the bucket's CORS exposes it).
  const kept = (res: Response) => Number(res.headers.get("range")?.split("-")[1] ?? -1) + 1;
  for (let misses = 0; at < total || total === 0; ) {
    const end = Math.min(at + chunk, total);
    const range = total ? `bytes ${at}-${end - 1}/${total}` : "bytes */0";
    let res = await fetch(url, { method: "PUT", headers: { "content-range": range }, body: total ? file.slice(at, end) : undefined }).catch(() => null);
    if (res?.ok) break; // storage has the whole file
    if (!res || res.status >= 500 || res.status === 408 || res.status === 429) {
      // The network or storage had a hiccup: wait, ask storage what it keeps, and go on from there.
      if (++misses > 3) throw new Error(`The upload of ${file.name} stopped (${res ? `HTTP ${res.status}` : "no connection"}). Try again.`);
      console.warn("[upload] piece failed: asking storage what it has", { name: file.name, at, status: res?.status, misses });
      await new Promise((done) => setTimeout(done, 500 * 2 ** misses));
      res = await ask();
      if (res?.ok) break;
      if (res?.status === 308) {
        const next = kept(res);
        if (next > at) misses = 0; // storage kept the piece; only its answer was lost
        at = next;
      }
      onProgress?.(total ? at / total : 0);
      continue;
    }
    if (res.status !== 308) throw new Error(`Storage refused ${file.name} (HTTP ${res.status}). Try again.`);
    const next = kept(res);
    if (next > at) misses = 0; // a hiccup now and then over a long upload is fine
    else if (++misses > 3) throw new Error(`The upload of ${file.name} does not move on. Try again.`);
    at = next;
    onProgress?.(total ? at / total : 0);
  }
  onProgress?.(1);
  const done = await fetch(`${api}/uploads/${encodeURIComponent(id)}/complete`, { method: "POST" });
  if (!done.ok) throw new Error(await errorText(done));
  return (await done.json()) as T;
}

/**
 * Send a file to the server with the tab's project: the stored asset, or an Error with the reason.
 * Straight to storage when the server takes that (`limits.direct`), else in `POST /assets`.
 */
export async function uploadFile<T = { id: string }>(api: string, file: File, onProgress?: (share: number) => void): Promise<T> {
  const refused = tooLarge(file.name, file.size, "upload");
  if (refused) throw new Error(refused);
  if (directUploads()) return sendDirect<T>(api, file, "asset", onProgress);
  const res = await fetch(`${api}/assets`, { method: "POST", body: uploadForm(file) });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as T;
}
