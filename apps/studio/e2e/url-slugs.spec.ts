import { expect, test, type Page } from "@playwright/test";
import { cpSync, rmSync } from "node:fs";
import path from "node:path";

// COREPRODUC-698: each show, Shows section, shot page and page tab has its own URL, so a reload, Back
// and a shared link open the same place. Before, the URL named only the page (`#shows`).
const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";
const SAMPLE = path.resolve(__dirname, "../../../packages/olf/conformance/tidewatch");
const hash = (page: Page) => page.evaluate(() => decodeURIComponent(window.location.hash));

test.describe("URL slugs", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("vinci-onboard-v1", "done"));
  });

  test("a show, its sections and a shot page: reload, Back and an unknown show", async ({ page }) => {
    await page.goto("/");
    const sample = String((await (await page.request.post("/vinci-api/olf/sample")).json()).path);
    rmSync(sample, { recursive: true, force: true });
    cpSync(SAMPLE, sample, { recursive: true });
    await page.locator('nav button[aria-label="Shows"]').click();
    await page.getByTestId("shows-open-sample").click();
    await expect.poll(() => hash(page)).toMatch(/^#shows\/tidewatch-[0-9a-f]{8}\/storyboard\/e02$/);
    const show = (await hash(page)).split("/")[1];

    await page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]').click();
    await expect.poll(() => hash(page)).toBe(`#shows/${show}/shot/e02/s03/sh014`);
    await page.reload();
    await expect(page.getByRole("button", { name: "‹ Storyboard" })).toBeVisible(); // still the shot page
    await expect.poll(() => hash(page)).toBe(`#shows/${show}/shot/e02/s03/sh014`);
    await page.screenshot({ path: path.join(shots, "url_shot_page_reloaded.png") });

    await page.getByRole("button", { name: "‹ Storyboard" }).click();
    await page.getByTestId("shows-section-cut").click();
    await expect.poll(() => hash(page)).toBe(`#shows/${show}/cut/e02`);
    await page.goBack(); // Cut → Storyboard → the shot page, one step each
    await expect.poll(() => hash(page)).toBe(`#shows/${show}/storyboard/e02`);
    await page.goBack();
    await expect(page.getByRole("button", { name: "‹ Storyboard" })).toBeVisible();
    await page.goForward();
    await page.goForward();
    await expect(page.getByTestId("shows-tab-cut")).toHaveClass(/on/);

    // A renamed show keeps its link: only the 8 characters at the end pick the show.
    await page.goto(`/#shows/another-title-${show.slice(-8)}/cut/e02`);
    await expect(page.getByTestId("shows-tab-cut")).toHaveClass(/on/);
    await expect.poll(() => hash(page)).toBe(`#shows/${show}/cut/e02`);

    // A place the show does not have (a deleted bible entry) opens the show at its start, and says so.
    await page.goto(`/#shows/${show}/bible/char/nobody`);
    await expect(page.getByTestId("shows-notice")).toContainText("That place is not in this show.");
    await expect.poll(() => hash(page)).toBe(`#shows/${show}/storyboard/e02`);

    // The show list fails and the show is not in the recent ones: the link stays, to try again.
    await page.evaluate(() => localStorage.removeItem("vinci-shows-recent-v1"));
    await page.route(/\/vinci-api\/olf\/shows(\?.*)?$/, (route) => route.abort("failed")); // `?project=` since COREPRODUC-702
    await page.goto(`/#shows/${show}/cut/e02`);
    await page.reload();
    await expect(page.getByText("Could not load your shows, so this link did not open.")).toBeVisible();
    await expect.poll(() => hash(page)).toBe(`#shows/${show}/cut/e02`);
    await page.unroute(/\/vinci-api\/olf\/shows(\?.*)?$/);

    // A show that is not in this project: the open screen says so, and the URL is the page's own.
    await page.goto("/#shows/nobody-deadbeef/cut/e01");
    await expect(page.getByText("That show is not in this project.")).toBeVisible();
    await expect.poll(() => hash(page)).toBe("#shows");
    await page.screenshot({ path: path.join(shots, "url_unknown_show.png") });
  });

  test("page tabs: Video, Library and the Canvas timeline", async ({ page }) => {
    await page.goto("/#video");
    await page.getByTestId("video-tab-motion-control").click();
    await expect.poll(() => hash(page)).toBe("#video/motion-control");
    await page.reload();
    await expect(page.getByTestId("video-tab-motion-control")).toHaveClass(/on/);
    await page.goBack();
    await expect.poll(() => hash(page)).toBe("#video");
    await expect(page.getByTestId("video-tab-create")).toHaveClass(/on/);

    await page.goto("/#library/styles");
    await expect(page.getByTestId("library-tab-styles")).toHaveClass(/on/);
    await page.getByTestId("library-tab-elements").click();
    await expect.poll(() => hash(page)).toBe("#library/elements");
    await page.getByTestId("library-tab-characters").click();
    await expect.poll(() => hash(page)).toBe("#library"); // the first tab is the page itself
    await page.goto("/?page=library"); // a query names the page too, and a tab click still goes in the URL
    await page.getByTestId("library-tab-styles").click();
    await expect.poll(() => hash(page)).toBe("#library/styles");
    await page.reload();
    await expect(page.getByTestId("library-tab-styles")).toHaveClass(/on/);

    await page.goto("/#canvas/timeline");
    const views = page.getByRole("group", { name: "Canvas view" });
    await expect(views.getByRole("button", { name: "Timeline" })).toHaveClass(/on/);
    await views.getByRole("button", { name: "Canvas" }).click();
    await expect.poll(() => hash(page)).toBe("#canvas");
    await page.screenshot({ path: path.join(shots, "url_canvas.png") });
  });
});
