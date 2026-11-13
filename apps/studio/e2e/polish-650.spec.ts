import { expect, test, type Page } from "@playwright/test";
import { cpSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

// COREPRODUC-650: 15 small Studio issues from the 2026-11-13 production crawl, confirmed 2026-11-14.
// Each test names its finding id. Screenshots go to PLAYWRIGHT_ARTIFACTS for the PR.
const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";
const OSS = path.resolve(__dirname, "../../..");
const SAMPLE = path.join(OSS, "packages/olf/conformance/tidewatch");
const PNG = path.join(SAMPLE, "bible/props/brass-key/ref.png");
const MP4 = path.join(OSS, "packages/provider-sdk/vinci_provider_sdk/fixtures/mock.mp4");

async function boot(page: Page, hash = "") {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
    localStorage.removeItem("vinci-shows-recent-v1");
  });
  const booted = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "GET");
  await page.goto("/" + hash);
  await booted;
}

/** Hold each upload for `ms`, so the "Uploading …" line can be seen (a host takes about 4 s). */
async function slowUploads(page: Page, ms = 800) {
  await page.route("**/vinci-api/assets", async (route) => {
    if (route.request().method() === "POST") await new Promise((done) => setTimeout(done, ms));
    await route.continue();
  });
}

const log = (page: Page) => page.locator(".top-log");

test.describe("COREPRODUC-650 Studio polish", () => {
  test("image-12, image-14, paid-8: All tools tabs, upload status, a picture opens full size", async ({ page, context }) => {
    await slowUploads(page);
    await boot(page, "#image");
    await page.getByRole("button", { name: "All tools" }).click();
    const tabs = page.locator(".all-tools-tabs");
    await expect(tabs).toBeVisible();
    // The labels fit: the row is not squeezed below its buttons (it was 13 px).
    const row = await tabs.boundingBox();
    const tab = await tabs.locator("button").first().boundingBox();
    expect(row && tab && row.height >= tab.height && row.height >= 20).toBe(true);
    await page.screenshot({ path: path.join(shots, "p650_image12_tabs.png") });
    await page.keyboard.press("Escape");

    await page.getByTestId("image-bar").locator("input[type=file]").setInputFiles(PNG);
    await expect(log(page)).toHaveText("Uploading ref.png…");
    await page.screenshot({ path: path.join(shots, "p650_image14_uploading.png") });
    await expect(log(page)).toHaveText("Reference added.");
    await page.getByTitle("Remove reference").click();
    await expect(log(page)).toHaveText("Reference removed.");

    await page.getByRole("textbox", { name: "Image prompt" }).fill("a brass key on oak");
    await page.getByTestId("image-generate").click();
    await expect(log(page)).toHaveText("Your still is in the feed.", { timeout: 60_000 });
    const card = page.locator(".image-card:not(.pending)").first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    await card.hover();
    const open = card.getByTestId("image-card-open");
    await expect(open).toHaveAttribute("target", "_blank");
    await page.screenshot({ path: path.join(shots, "p650_paid8_hover.png") });
    const popup = context.waitForEvent("page");
    const box = await card.boundingBox();
    if (!box) throw new Error("no card");
    await page.mouse.click(box.x + box.width / 2, box.y + 30); // the picture, away from the buttons
    const full = await popup;
    expect(full.url()).toMatch(/\/vinci-api\/assets\/[^/]+\/file$/);
    await full.screenshot({ path: path.join(shots, "p650_paid8_full.png") });
    await full.close();
  });

  test("video-8, video-9, video-12: clip notices, removes, Advanced hints", async ({ page }) => {
    await slowUploads(page);
    await boot(page, "#video");
    await expect(page.getByTestId("video-page")).toBeVisible();
    await page.getByTestId("video-panel").locator("input[type=file]").setInputFiles(MP4);
    await expect(log(page)).toHaveText("Uploading mock.mp4…");
    await expect(log(page)).toHaveText("Clip added. Switched to Extend Video: the new clip continues it.");
    await page.screenshot({ path: path.join(shots, "p650_video9_clip.png") });
    await page.getByRole("button", { name: "Remove Clip" }).click();
    await expect(log(page)).toHaveText("Clip removed.");
    await page.screenshot({ path: path.join(shots, "p650_video8_removed.png") });

    await page.getByTestId("video-advanced").click();
    await expect(page.getByTestId("video-steps")).toHaveAttribute("placeholder", "Model default");
    await expect(page.getByTestId("video-seed")).toHaveAttribute("placeholder", "Random");
    await page.screenshot({ path: path.join(shots, "p650_video12_advanced.png") });
  });

  test("canvas-7, canvas-8: one row of node chips; undo clears the delete notice", async ({ page }) => {
    // A long model name, as Kling 2.6 Standard on a host (a copy of the mock video row; nothing runs).
    await page.route(/\/vinci-api\/models(\?|$)/, async (route) => {
      type Row = { id: string; display_name: string; constraints: Record<string, unknown> };
      const data = (await (await route.fetch()).json()) as Row[] | { models: Row[] };
      const rows = Array.isArray(data) ? data : data.models;
      const mp4 = rows.find((row) => row.id === "mock:mp4:v1");
      if (mp4) rows.unshift({ ...mp4, id: "mock:mp4:kling", display_name: "Kling 2.6 Standard", constraints: { ...mp4.constraints, resolutions: ["1K", "2K"] } });
      await route.fulfill({ json: data });
    });
    await boot(page, "#canvas");
    await expect(page.locator(".graph")).toBeVisible();
    await page.getByTestId("canvas-tool-add").click();
    await page.getByTestId("add-menu-search").fill("video");
    await page.getByTestId("add-menu").locator('[data-add="node:t2v"]').click();
    const node = page.locator(".node", { hasText: "Video Gen" }).first();
    await node.getByTestId("node-model-chip").click();
    await node.getByRole("option", { name: /Kling 2\.6 Standard/ }).click();
    // One row: every chip's middle on one line (16:9 and 1K wrapped to a second row before).
    const mids = await node.locator(".node-pills > *").evaluateAll((els) => els.map((el) => {
      const r = el.getBoundingClientRect();
      return r.top + r.height / 2;
    }));
    expect(mids.length).toBeGreaterThanOrEqual(4); // count, model, aspect, resolution
    expect(Math.max(...mids) - Math.min(...mids)).toBeLessThan(2);
    await expect(node.getByTestId("node-model-chip")).toHaveAttribute("title", /Kling 2\.6 Standard/);
    await page.screenshot({ path: path.join(shots, "p650_canvas7_row.png") });

    await node.getByText("Video Gen", { exact: true }).click();
    await page.keyboard.press("Delete");
    await expect(log(page)).toHaveText("Deleted. Undo with ⌘Z.");
    await page.keyboard.press("ControlOrMeta+z");
    await expect(page.locator(".node", { hasText: "Video Gen" })).toHaveCount(1);
    await expect(page.getByText("Deleted. Undo with ⌘Z.")).toHaveCount(0);
    await page.screenshot({ path: path.join(shots, "p650_canvas8_undo.png") });
  });

  test("shell-12, shows-11, shows-14, shows-16: Shows copy, Cut and sheet buttons, keyframe prompt", async ({ page }) => {
    test.setTimeout(120_000);
    await boot(page);
    const sample = String((await (await page.request.post("/vinci-api/olf/sample")).json()).path);
    rmSync(sample, { recursive: true, force: true });
    cpSync(SAMPLE, sample, { recursive: true });
    // Mira with no sheet: the sheet button adds one.
    const mira = path.join(sample, "bible/characters/mira/mira.yaml");
    writeFileSync(mira, readFileSync(mira, "utf8").replace(/^sheet: .*\n/m, ""));
    // A priced keyframe, as on a host: the render asks first.
    await page.route(/\/vinci-api\/olf\/shot\?/, async (route) => {
      const body = await (await route.fetch()).json();
      body.plans.keyframe.total = 2;
      await route.fulfill({ json: body });
    });

    await page.locator('nav button[aria-label="Shows"]').click();
    const start = page.getByTestId("shows-open");
    await expect(start).toContainText("Shows");
    await expect(start).not.toContainText("OLF v0.1");
    await expect(start).not.toContainText("Movie engine");
    await page.screenshot({ path: path.join(shots, "p650_shell12_start.png") });

    await page.getByTestId("shows-open-sample").click();
    await expect(page.getByTestId("shot-card")).toHaveCount(3);
    await page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]').click();
    await page.getByTestId("shot-page").getByTestId("render-keyframe").click();
    const ask = page.getByRole("alertdialog", { name: "Confirm spend" });
    await expect(ask).toContainText("this keyframe");
    await expect(ask).not.toContainText("this render");
    await page.screenshot({ path: path.join(shots, "p650_shows16_prompt.png") });
    await ask.getByRole("button", { name: "Cancel" }).click();
    await page.getByRole("button", { name: "‹ Storyboard" }).click();

    await page.getByTestId("shows-section-cut").click();
    const use = page.getByTestId("cut-use-approved");
    await expect(use).toBeDisabled(); // nothing approved yet: the server would answer 400
    await expect(use).toHaveAttribute("title", "Approve a keyframe or a video first.");
    await expect(page.getByTestId("cut-approved-hint")).toHaveText("Approve a keyframe or a video first.");
    await page.screenshot({ path: path.join(shots, "p650_shows11_cut.png") });

    await page.getByTestId("shows-tab-bible").click(); // the Cut screen puts the sections in the top bar
    await expect(page.getByTestId("replace-sheet")).toHaveText("Add a sheet");
    await page.screenshot({ path: path.join(shots, "p650_shows14_sheet.png") });
  });
});

test.describe("COREPRODUC-650 on a host", () => {
  test("shell-10, shell-15: Connect cards stay in one row with the rail open; provider links", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("vinci-onboard-v1", "done"));
    await page.route(/\/vinci-api\/doctor(\?|$)/, async (route) => {
      const res = await route.fetch();
      const host = {
        name: "Vinci Platform",
        currency: "credits",
        pages: ["image", "video", "canvas", "keys"],
        keys: ["wavespeed", "mcp_higgsfield", "mcp_magnific"],
        links: [],
        home: { title: "Dashboard", href: "/dashboard" },
      };
      await route.fulfill({ response: res, json: { ...(await res.json()), host } });
    });
    await page.goto("/#keys");
    const cards = page.locator(".host-key-list > .connect-sheet");
    await expect(cards).toHaveCount(3);
    await expect(page.getByRole("link", { name: "Get a Wavespeed key" })).toHaveAttribute("href", "https://wavespeed.ai/accesskey");
    await expect(page.getByRole("link", { name: "Higgsfield docs" })).toHaveAttribute("href", "https://docs.higgsfield.ai");
    await expect(page.getByRole("link", { name: "Magnific docs" })).toHaveAttribute("href", "https://docs.magnific.com/introduction");
    const rows = async () => new Set(await cards.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)))).size;
    expect(await rows()).toBe(1);
    await page.screenshot({ path: path.join(shots, "p650_shell10_closed.png") });
    await page.locator("nav.rail").hover();
    await page.waitForTimeout(400); // the rail opens in 160 ms
    expect(await rows()).toBe(1); // it was 2 + 1
    await page.screenshot({ path: path.join(shots, "p650_shell10_open.png") });
  });
});
