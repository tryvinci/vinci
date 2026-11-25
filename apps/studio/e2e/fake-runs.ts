import type { Page } from "@playwright/test";

/**
 * Fake runs that stay "running" until the test ends them, so two Generates overlap. No model is called.
 *
 * Args:
 *   page: The page whose POST /runs and GET /runs/fake-* answers are faked. Other /runs calls reach the daemon.
 * Returns:
 *   `posts`: how many runs were posted (fake-1, fake-2, …); `end(n)`: fake-n answers "completed" from now on.
 */
export async function fakeRuns(page: Page) {
  const ended = new Set<string>();
  const runs = { posts: 0, end: (n: number) => void ended.add(`fake-${n}`) };
  await page.route("**/vinci-api/runs", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    runs.posts += 1;
    return route.fulfill({ json: { id: `fake-${runs.posts}`, state: "running", created_at: new Date().toISOString() } });
  });
  await page.route("**/vinci-api/runs/fake-*", (route) => {
    const id = route.request().url().split("/").pop() || "";
    return route.fulfill({ json: { id, state: ended.has(id) ? "completed" : "running", outputs: [] } });
  });
  return runs;
}
