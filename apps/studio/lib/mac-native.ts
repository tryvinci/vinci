/** macOS WKWebView bridge (`vinciNative` message handler). */

export function isMacNativeShell(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as Window & {
    __VINCI_MAC_NATIVE__?: boolean;
    webkit?: { messageHandlers?: { vinciNative?: { postMessage: (body: unknown) => void } } };
  };
  return Boolean(w.__VINCI_MAC_NATIVE__ || w.webkit?.messageHandlers?.vinciNative);
}

export function postMacNative(body: Record<string, unknown>): boolean {
  const handler = (
    window as Window & {
      webkit?: { messageHandlers?: { vinciNative?: { postMessage: (body: unknown) => void } } };
    }
  ).webkit?.messageHandlers?.vinciNative;
  if (!handler) return false;
  handler.postMessage(body);
  return true;
}

export function revealInFinder(mediaPath: string): boolean {
  return postMacNative({ action: "revealInFinder", path: mediaPath });
}

export function importToPhotos(mediaPath: string, album: string): boolean {
  return postMacNative({ action: "importToPhotos", path: mediaPath, album });
}

export type ExportedOutputRow = {
  asset_id: string;
  destination_kind: string;
  media_path: string;
  sidecar_path?: string;
  photos_album?: string;
};

/** When destination is Photos, ask the Mac shell to import staged files. */
export function autoImportPhotosExports(rows: ExportedOutputRow[] | undefined): void {
  if (!rows?.length || !isMacNativeShell()) return;
  for (const row of rows) {
    if (row.destination_kind !== "photos") continue;
    importToPhotos(row.media_path, row.photos_album || "Vinci");
  }
}
