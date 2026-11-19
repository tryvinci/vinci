import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

// Studio projects (COREPRODUC-702): the tab's project is in the URL, its work stays in it, and a
// second window cannot overwrite its board.
const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

/** Open the Studio at `url` and wait for boot (GET /runs comes after the project is picked). */
async function boot(page: Page, url = "/") {
  await page.addInitScript(() => localStorage.setItem("vinci-onboard-v1", "done"));
  const booted = page.waitForResponse((res) => res.url().split("?")[0].endsWith("/vinci-api/runs") && res.request().method() === "GET");
  await page.goto("about:blank"); // a full load, even when only the hash differs
  await page.goto(url);
  await booted;
}

/** New project from the switcher; the Studio reloads in it. Returns its id (from the URL). */
async function newProject(page: Page, name: string): Promise<string> {
  await page.getByTestId("project-switch").click();
  await page.getByRole("menuitem", { name: "New project" }).click();
  await page.getByLabel("New project name").fill(name);
  const booted = page.waitForResponse((res) => res.url().includes("/vinci-api/runs?project=") && res.request().method() === "GET");
  await page.getByRole("button", { name: "Create" }).click();
  await booted;
  await expect(page.getByTestId("project-switch")).toHaveText(name);
  return new URL(page.url()).searchParams.get("project") || "";
}

test("each project keeps its own Image work, and the URL names the project", async ({ page }) => {
  await boot(page);
  await expect(page.getByTestId("project-switch")).toHaveText("My work");
  expect(new URL(page.url()).searchParams.get("project")).toBe("default"); // the pick is in the URL
  const id = await newProject(page, `Summer ads ${Date.now()}`);
  expect(id).toMatch(/^[0-9a-f]{32}$/);

  await page.locator('nav button[aria-label="Image"]').click();
  await page.getByTestId("image-prompt").fill("north-light oak cube");
  await page.getByTestId("image-generate").click();
  await expect(page.locator(".image-card img").first()).toBeVisible({ timeout: 30_000 });
  const mine = await page.locator(".image-card").count();
  await page.getByTestId("project-switch").click();
  await expect(page.getByRole("menu", { name: "Projects" })).toBeVisible();
  await page.screenshot({ path: path.join(shots, "projects_switcher_open.png") });

  // My work does not show the new project's still.
  const back = page.waitForResponse((res) => res.url().includes("/vinci-api/runs?project=default"));
  await page.getByRole("menu", { name: "Projects" }).getByRole("menuitem", { name: "My work" }).click();
  await back;
  await expect(page.getByTestId("image-page")).toBeVisible(); // the page stays: `#image` is kept
  const runs = (await (await page.request.get(`/vinci-api/runs?project=${id}`)).json()) as { runs: { inputs?: { prompt?: string } }[] };
  expect(runs.runs.map((run) => run.inputs?.prompt)).toEqual(["north-light oak cube"]);
  const others = (await (await page.request.get("/vinci-api/runs?project=default")).json()) as { runs: { inputs?: { prompt?: string } }[] };
  expect(others.runs.some((run) => run.inputs?.prompt === "north-light oak cube")).toBe(false);
  await page.screenshot({ path: path.join(shots, "projects_default_has_no_new_work.png"), fullPage: true });
  expect(mine).toBeGreaterThan(0);
});

test("a second window cannot overwrite the board", async ({ context }) => {
  const first = await context.newPage();
  await boot(first);
  const id = await newProject(first, `Board ${Date.now()}`);
  const url = `/?project=${id}#canvas`;
  const second = await context.newPage();
  await boot(second, url);
  await boot(first, url);

  // Window 1 adds a page; its save lands (board_rev 1).
  const saved = first.waitForResponse((res) => res.url().endsWith(`/projects/${id}/board`) && res.request().method() === "PUT");
  await first.getByTestId("page-add").click();
  expect((await saved).status()).toBe(200);

  // Window 2 still holds revision 0: its edit is refused, and it says so.
  const refused = second.waitForResponse((res) => res.url().endsWith(`/projects/${id}/board`) && res.request().method() === "PUT");
  await second.getByTestId("page-add").click();
  expect((await refused).status()).toBe(409);
  await expect(second.getByTestId("board-conflict")).toContainText("This board changed in another window");
  await second.getByTestId("page-add").click(); // a later message does not hide the warning
  await expect(second.getByTestId("board-conflict")).toBeVisible();
  await second.screenshot({ path: path.join(shots, "projects_board_stale.png") });

  // A reload of window 2 shows window 1's board.
  await boot(second, url);
  await expect(second.getByTestId("page-tab")).toHaveCount(2);
});

test("each project lists only its own shows, and Shows has the switcher", async ({ page }) => {
  await boot(page, "/?project=default#shows");
  await expect(page.getByTestId("project-switch")).toHaveText("My work"); // on the open screen
  const id = await newProject(page, `Series ${Date.now()}`);
  expect(new URL(page.url()).hash).toBe("#shows");

  // The sample opens as this project's own copy; with a show open, the header has no switcher.
  await page.getByTestId("shows-open-sample").click();
  await expect(page.getByTestId("shows-health")).toBeVisible();
  await expect(page.getByTestId("project-switch")).toHaveCount(0);
  await page.getByRole("button", { name: "Close show" }).click();
  // New show joins the tab's project too.
  await page.getByTestId("shows-new").click();
  await page.getByTestId("setup-title").fill(`Pilot ${id.slice(0, 6)}`);
  await page.getByRole("button", { name: "Skip to an empty project" }).click();
  await expect(page.getByTestId("shows-health")).toBeVisible();
  await page.getByRole("button", { name: "Close show" }).click();
  const grid = page.getByTestId("shows-grid");
  await expect(grid.locator(".show-card")).toHaveCount(2);
  await page.screenshot({ path: path.join(shots, "projects_shows_own_list.png") });

  // The project's show is not in My work, and My work's shows are not in the project.
  const listed = async (project: string) =>
    ((await (await page.request.get(`/vinci-api/olf/shows?project=${project}`)).json()) as { shows: { path: string }[] }).shows.map((row) => row.path);
  const mine = await listed(id);
  expect(mine).toHaveLength(2);
  expect(mine.some((row) => row.endsWith(`tidewatch-${id.slice(0, 8)}`))).toBe(true);
  const others = await listed("default");
  expect(mine.filter((row) => others.includes(row))).toEqual([]);

  await page.getByTestId("project-switch").click();
  const back = page.waitForResponse((res) => res.url().includes("/vinci-api/olf/shows?project=default"));
  await page.getByRole("menu", { name: "Projects" }).getByRole("menuitem", { name: "My work" }).click();
  await back;
  await expect(page.getByTestId("project-switch")).toHaveText("My work");
  await expect(page.getByTestId("shows-health")).toHaveCount(0); // the project's show does not open here by itself
  await expect(page.locator(".show-card", { hasText: id.slice(0, 6) })).toHaveCount(0);
  await page.screenshot({ path: path.join(shots, "projects_shows_my_work.png") });
});
