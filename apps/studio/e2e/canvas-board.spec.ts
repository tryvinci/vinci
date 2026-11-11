import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const SHOT = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOT, `${name}.png`), fullPage: true });
}

function watchConsole(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("response", (res) => {
    if (res.status() < 400) return;
    if (!res.url().includes("/vinci-api/")) return;
    errors.push(`${res.status()} ${res.url()}`);
  });
  return errors;
}

async function issueBadge(page: Page) {
  return page.evaluate(() => {
    const portal = document.querySelector("nextjs-portal");
    const node = portal?.shadowRoot?.querySelector("[data-issues]");
    return (node?.textContent || "").trim();
  });
}

async function openCanvas(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
  // Boot sets models, then loads media (GET /runs). /skills can take ~2s, and a run started
  // before models load stops at "Models are still loading", which the canvas does not show.
  const booted = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "GET");
  await page.goto("/");
  await expect(page.locator("nav")).toBeVisible();
  await page.getByRole("button", { name: "Canvas" }).click();
  await expect(page.locator(".graph")).toBeVisible();
  await expect(page.getByTestId("edge-tools")).toBeVisible();
  await expect(page.getByTestId("canvas-pages")).toBeVisible();
  await expect(page.getByTestId("canvas-minimap")).toBeVisible();
  await booted;
}

async function addNode(page: Page, query: string, capability: string) {
  await page.getByTestId("canvas-tool-add").click();
  const menu = page.getByTestId("add-menu");
  await expect(menu).toBeVisible();
  await page.getByTestId("add-menu-search").fill(query);
  await menu.locator(`[data-add="node:${capability}"]`).click();
  await expect(menu).toHaveCount(0);
}

test("the first node opens above the dock on a short screen", async ({ page }) => {
  // From the board centre, the open node ran under the dock at 810 px (COREPRODUC-574).
  await page.setViewportSize({ width: 1440, height: 810 });
  await openCanvas(page);
  await page.locator('[data-start="t2i"]').click();
  const node = page.locator(".node[data-id]").first();
  await expect(node.getByTestId("node-model-chip")).toBeVisible();
  const box = await node.boundingBox();
  const dock = await page.locator(".canvas-bar").boundingBox();
  expect(box && dock && box.y + box.height <= dock.y).toBe(true);
  await node.getByTestId("node-model-chip").click(); // a real click: fails when the dock covers the pill
  await expect(node.locator(".node-pill-menu")).toBeVisible();
});

test("selection scopes, pages, history, minimap", async ({ page }) => {
  const errors = watchConsole(page);
  // Demo hides mock and leaves live spend off, so a page-model target refuses to start.
  // Report the models as usable. POST /runs is still fulfilled here and never reaches a provider.
  await page.route("**/vinci-api/models", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as { models?: { available?: boolean }[] };
    for (const row of body.models || []) row.available = true;
    await route.fulfill({ json: body });
  });
  await page.route("**/vinci-api/doctor", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as { live_spend?: boolean };
    body.live_spend = true;
    await route.fulfill({ json: body });
  });
  const posted: string[][] = [];
  await page.route("**/vinci-api/runs", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    const payload = route.request().postDataJSON() as { workflow?: { nodes?: { capability?: string }[] } };
    posted.push((payload.workflow?.nodes || []).map((node) => node.capability || "").sort());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: `run-board-${posted.length}`,
        state: "completed",
        outputs: [],
        nodes: {},
        estimate: { total: 0 },
      }),
    });
  });
  await openCanvas(page);
  await expect(page.locator(".canvas-bar")).toBeVisible();
  await expect(page.getByTestId("page-tab")).toHaveCount(1);
  await shot(page, "board-01-empty-chrome");

  await addNode(page, "image gen", "t2i");
  await expect(page.locator(".node")).toHaveCount(1);
  await page.locator(".node", { hasText: "Image Gen" }).locator("[data-node-prompt]").fill("oak cube");
  await page.locator(".port.out").click();
  const menu = page.getByTestId("add-menu");
  await expect(menu.locator('[data-add="node:upscale"]')).toBeVisible();
  await menu.locator('[data-add="node:upscale"]').click();
  await expect(page.locator(".node")).toHaveCount(2);
  await addNode(page, "video gen", "t2v");
  await expect(page.locator(".node")).toHaveCount(3);
  await page.locator(".node", { hasText: "Video Gen" }).locator("[data-node-prompt]").fill("a slow pan");

  await page.locator(".node", { hasText: "Upscaler" }).click({ position: { x: 160, y: 24 } });
  const bar = page.getByTestId("selection-bar");
  await expect(bar).toBeVisible();
  const costFirst = await page.getByTestId("selection-run").evaluate((el) => el.firstElementChild?.getAttribute("data-testid"));
  expect(costFirst).toBe("selection-cost");
  await expect(page.getByTestId("selection-cost")).not.toHaveText("");
  await shot(page, "board-02-selection-cost");

  await page.getByTestId("selection-scope-menu").click();
  const scope = page.getByTestId("scope-menu");
  await expect(scope).toBeVisible();
  await expect(scope.locator("select")).toHaveCount(0);
  await expect(scope.locator('[data-scope="upstream"] span').first()).toBeVisible();
  await shot(page, "board-03-scope-menu");

  await scope.locator('[data-scope="upstream"]').click();
  const run = page.getByTestId("selection-run");
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toEqual(["t2i", "upscale"]);
  await expect(run).toBeEnabled();

  await page.getByTestId("selection-scope-menu").click();
  await page.locator('[data-scope="node"]').click();
  await expect(page.getByTestId("selection-scope")).toHaveText("This node only");
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBe(2);
  expect(posted[1]).toEqual(["upscale"]);
  await expect(run).toBeEnabled();

  await page.getByTestId("selection-scope-menu").click();
  await page.locator('[data-scope="page"]').click();
  await expect(page.getByTestId("selection-scope")).toHaveText("Whole page");
  await expect(run).toBeEnabled();
  await run.click();
  await expect.poll(() => posted.length).toBe(3);
  expect(posted[2]).toEqual(["t2i", "t2v", "upscale"]);
  await expect(run).toBeEnabled();

  await page.getByTestId("selection-edge").click();
  const edge = page.getByTestId("edge-menu");
  await expect(edge).toBeVisible();
  await expect(edge.locator("select")).toHaveCount(0);
  await shot(page, "board-04-edge-menu");
  await edge.locator('[data-edge-style="curve"]').click();
  await expect.poll(async () => page.locator("path.wire").first().getAttribute("d")).toContain("C");

  await page.getByTestId("canvas-tool-history").click();
  await expect(page.getByTestId("history-cost")).toContainText("No receipts yet.");
  await page.getByTestId("history-tab-assets").click();
  await expect(page.getByTestId("history-assets")).toContainText("No assets yet.");
  await page.getByTestId("history-tab-nodes").click();
  await expect(page.getByTestId("history-nodes")).toContainText("No nodes yet.");
  await shot(page, "board-05-history");
  await page.getByLabel("Close history").click();

  await page.getByTestId("page-add").click();
  await expect(page.getByTestId("page-tab")).toHaveCount(2);
  await page.getByTestId("page-tab").nth(1).dblclick();
  const name = page.getByLabel("Page name");
  await name.fill("Alt");
  await name.press("Enter");
  await expect(page.getByTestId("page-tab").nth(1)).toHaveText("Alt");
  await shot(page, "board-06-pages");
  await page.getByTestId("page-tab").nth(0).click();
  await expect(page.locator(".node")).toHaveCount(3);
  await page.getByTestId("page-tab").nth(1).click();
  await expect(page.locator(".node")).toHaveCount(0);

  await page.keyboard.press("c");
  await page.locator(".graph").click({ position: { x: 480, y: 96 } });
  await expect(page.getByTestId("board-comment")).toBeVisible();
  await page.getByLabel("Edit comment").click();
  const comment = page.getByLabel("Comment text");
  await comment.fill("keep this");
  await comment.blur();
  await expect(page.getByTestId("board-comment")).toContainText("keep this");
  await shot(page, "board-07-comment");

  await page.reload();
  await page.getByRole("button", { name: "Canvas" }).click();
  await expect(page.getByTestId("page-tab")).toHaveCount(2);
  await expect(page.getByTestId("page-tab").nth(1)).toHaveText("Alt");
  await expect(page.getByTestId("board-comment")).toContainText("keep this");
  await shot(page, "board-08-reloaded");

  await page.getByTestId("canvas-zoom").click();
  const zoom = page.getByTestId("zoom-menu");
  await expect(zoom).toBeVisible();
  await expect(zoom.locator("select")).toHaveCount(0);
  await expect(page.getByTestId("canvas-pages").locator("select")).toHaveCount(0);
  await expect(page.getByTestId("selection-bar").locator("select")).toHaveCount(0);
  await shot(page, "board-09-zoom-menu");
  await zoom.getByRole("menuitem", { name: "Zoom out" }).click();
  await expect(page.getByTestId("canvas-zoom")).not.toHaveText("100%");
  await page.keyboard.press("d");
  await page.keyboard.press("f");
  await page.keyboard.press("Meta+0");
  await expect(page.getByTestId("canvas-zoom")).toHaveText("100%");

  await page.getByTestId("page-tab").nth(0).click();
  await page.locator(".node", { hasText: "Image Gen" }).click({ position: { x: 160, y: 24 } });
  await page.getByTestId("selection-instance").click();
  await expect(page.locator(".node-instance")).toBeVisible();
  await shot(page, "board-10-instance");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByTestId("edge-tools")).toBeVisible();
  await expect(page.getByTestId("canvas-pages")).toBeVisible();
  await expect(page.getByTestId("canvas-minimap")).toBeVisible();
  const pagesBox = await page.getByTestId("canvas-pages").boundingBox();
  const mapBox = await page.getByTestId("canvas-minimap").boundingBox();
  const dockBox = await page.locator(".canvas-bar").boundingBox();
  const overlaps = (
    a: { x: number; y: number; width: number; height: number },
    b: { x: number; y: number; width: number; height: number },
  ) => a.x < b.x + b.width - 1 && a.x + a.width > b.x + 1 && a.y < b.y + b.height - 1 && a.y + a.height > b.y + 1;
  expect(pagesBox && mapBox && !overlaps(pagesBox, mapBox)).toBeTruthy();
  expect(pagesBox && dockBox && !overlaps(pagesBox, dockBox)).toBeTruthy();
  expect(mapBox && dockBox && !overlaps(mapBox, dockBox)).toBeTruthy();
  await shot(page, "board-11-narrow");

  const badge = await issueBadge(page);
  const detail = await page.evaluate(() => {
    const portal = document.querySelector("nextjs-portal");
    return (portal?.shadowRoot?.textContent || "").replace(/\s+/g, " ").slice(0, 1500);
  });
  expect(badge, detail || errors.join("\n")).toBe("");
  expect(errors).toEqual([]);
});
