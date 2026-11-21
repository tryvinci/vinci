/**
 * Ask the daemon which routes exist without requesting a missing one.
 *
 * Image and Video used to GET `/library` and treat 404 as "the index is not
 * shipped yet". The browser logs that 404 as a console error, and the Next.js
 * dev overlay turns console errors into the "1 Issue" badge. Seen on the
 * Studio integration capture (Video, then every later page in that session).
 * OpenAPI is a 200 document, so the probe does not fail the console.
 *
 * Args:
 *   apiBase: Studio proxy prefix, usually `/vinci-api`.
 * Returns:
 *   Path names from `/openapi.json`. Empty when the spec cannot be read; a network or 5xx failure
 *   is not cached, so the next call asks again.
 */
let specPromise: Promise<Set<string>> | null = null;

/**
 * Fetch `/openapi.json` path names and reject on network or 5xx failure (clearing the cache so
 * the next call retries). Callers that need to distinguish a failed probe from a missing route
 * use this; `daemonPaths` catches and returns an empty set.
 */
export function daemonPathsStrict(apiBase: string): Promise<Set<string>> {
  if (!specPromise) {
    specPromise = fetch(`${apiBase}/openapi.json`)
      .then(async (res) => {
        if (res.status >= 500) throw new Error(`openapi ${res.status}`); // daemon down: try again later
        if (!res.ok) return new Set<string>();
        const body = (await res.json()) as { paths?: Record<string, unknown> };
        return new Set(Object.keys(body.paths || {}));
      })
      .catch((err) => {
        console.warn("[daemon-routes] /openapi.json failed; next call retries", err);
        specPromise = null;
        throw err;
      });
  }
  return specPromise;
}

export function daemonPaths(apiBase: string): Promise<Set<string>> {
  return daemonPathsStrict(apiBase).catch(() => new Set<string>());
}

/**
 * True when the daemon lists `path` (with or without a trailing slash).
 *
 * Args:
 *   apiBase: Studio proxy prefix.
 *   path: Route path such as `/library`.
 */
export async function daemonHasPath(apiBase: string, path: string): Promise<boolean> {
  const paths = await daemonPaths(apiBase);
  return paths.has(path) || paths.has(`${path}/`);
}
