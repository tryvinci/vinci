import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

const SEED = [
  { id: "soldier", name: "Soldier", kind: "character", refs: ["seed-soldier"] },
  { id: "room", name: "Room", kind: "location", refs: ["seed-room"] },
  { id: "logo", name: "Logo", kind: "brand", refs: ["seed-logo"] },
];

async function boot(page: Page, seed = true) {
  await page.addInitScript(
    ({ seed, rows }) => {
      localStorage.setItem("vinci-onboard-v1", "done");
      if (seed) localStorage.setItem("vinci-library-v1", JSON.stringify(rows));
    },
    { seed, rows: SEED },
  );
  await page.goto("/");
}

test.describe("Library and @mentions", () => {
  test("library tabs, empty create, seeded grid", async ({ page }) => {
    await boot(page, false);
    await page.locator('nav button[aria-label="Library"]').click();
    await expect(page.getByTestId("library-page")).toBeVisible();
    await expect(page.getByTestId("library-tab-characters")).toBeVisible();
    await expect(page.getByTestId("library-empty")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "library_characters_empty.png"), fullPage: true });

    await page.getByTestId("library-create-submit").click();
    await expect(page.getByTestId("library-create-error")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "library_create_error.png") });

    await page.getByTestId("library-name").fill("Soldier");
    await page.locator('input[aria-label="Add images"]').setInputFiles({
      name: "soldier.png",
      mimeType: "image/png",
      buffer: PNG,
    });
    await expect(page.locator(".library-ref")).toHaveCount(1);
    await page.getByTestId("library-create-submit").click();
    await expect(page.getByTestId("library-grid")).toContainText("Soldier");
    await page.screenshot({ path: path.join(shots, "library_character_created.png"), fullPage: true });

    for (const tab of ["elements", "styles", "locations", "brand-kit"] as const) {
      await page.getByTestId(`library-tab-${tab}`).click();
      await expect(page.getByTestId("library-empty")).toBeVisible();
    }
    await page.screenshot({ path: path.join(shots, "library_brand_kit_empty.png") });

    await page.getByTestId("library-tab-templates").click();
    await expect(page.getByTestId("library-templates")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "library_templates.png"), fullPage: true });

    await page.getByTestId("library-tab-flows").click();
    await expect(page.getByTestId("library-empty")).toContainText("No flows yet");
    await page.screenshot({ path: path.join(shots, "library_flows_empty.png") });
  });

  test("same @ list on Image, Video, and canvas", async ({ page }) => {
    await boot(page, true);
    await page.locator('nav button[aria-label="Image"]').click();
    await expect(page.getByTestId("image-bar")).toBeVisible();
    await page.getByTestId("image-elements").click();
    const imageList = page.getByTestId("image-mention");
    await expect(imageList).toBeVisible();
    await expect(imageList).toContainText("Soldier");
    await expect(imageList).toContainText("Room");
    await expect(imageList).not.toContainText("Logo");
    await page.screenshot({ path: path.join(shots, "image_mention_popover.png") });
    await imageList.getByRole("option", { name: /Soldier/ }).click();
    await expect(page.getByTestId("image-prompt")).toHaveValue(/@Soldier/);
    await page.screenshot({ path: path.join(shots, "image_mention_inserted.png") });

    await page.locator('nav button[aria-label="Video"]').click();
    const createVideo = page.getByRole("button", { name: "Create Video" });
    if ((await createVideo.count()) > 0) await createVideo.click();
    await expect(page.getByTestId("video-panel")).toBeVisible();
    await page.locator("h1").click();
    await page.getByTestId("video-prompt").fill("");
    await page.getByTestId("video-prompt").pressSequentially("@");
    const videoList = page.getByTestId("video-mention");
    await expect(videoList).toBeVisible();
    await expect(videoList).toContainText("Soldier");
    await expect(videoList).toContainText("Room");
    await expect(videoList).not.toContainText("Logo");
    await page.screenshot({ path: path.join(shots, "video_mention_popover.png") });

    await page.locator('nav button[aria-label="Canvas"]').click();
    await page.keyboard.press("n");
    const menu = page.getByTestId("add-menu");
    await expect(menu).toBeVisible();
    await page.getByTestId("add-chip-image").click();
    await menu.locator('[data-add="node:t2i"]').click();
    const prompt = page.locator(".node-prompt").first();
    await prompt.click();
    await prompt.fill("");
    await prompt.pressSequentially("@");
    const canvasList = page.getByTestId("canvas-mention");
    await expect(canvasList).toBeVisible();
    await expect(canvasList).toContainText("Soldier");
    await expect(canvasList).toContainText("Room");
    await expect(canvasList).not.toContainText("Logo");
    await page.screenshot({ path: path.join(shots, "canvas_mention_popover.png") });
  });

  test("narrow library drawer still reaches Library", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await boot(page, true);
    await page.locator("button.rail-menu").click();
    await page.locator('nav button[aria-label="Library"]').click();
    await expect(page.getByTestId("library-page")).toBeVisible();
    await expect(page.getByTestId("library-grid")).toContainText("Soldier");
    await page.screenshot({ path: path.join(shots, "library_narrow.png"), fullPage: true });
  });
});
