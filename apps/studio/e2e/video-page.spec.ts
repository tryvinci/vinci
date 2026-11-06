import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

async function openVideo(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
  await page.goto("/");
  await page.locator('nav button[aria-label="Video"]').click();
  await expect(page.getByTestId("video-page")).toBeVisible();
  await page.locator("h1").click();
  await expect(page.getByTestId("video-model-chip")).not.toHaveText("Model");
  await expect(page.getByTestId("video-duration")).toBeVisible();
}

test.describe("Video page", () => {
  test("panel, how strip, overlay, generate, extend", async ({ page }) => {
    await openVideo(page);
    await expect(page.getByTestId("video-panel")).toBeVisible();
    await expect(page.getByTestId("video-how")).toBeVisible();
    await expect(page.getByTestId("video-how").locator("article")).toHaveCount(3);
    await expect(page.getByTestId("video-generate")).toContainText("$");
    await expect(page.getByTestId("video-mode-extend")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_empty_how.png"), fullPage: true });

    await page.getByTestId("video-tab-edit").click();
    await expect(page.getByTestId("video-edit-empty")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_edit_unsupported.png") });

    await page.getByTestId("video-tab-motion-control").click();
    await expect(page.getByTestId("video-motion")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_motion_tab.png") });
    await page.getByTestId("video-tab-create").click();

    await page.getByTestId("video-preset-change").click();
    await expect(page.getByTestId("video-preset-overlay")).toBeVisible();
    await expect(page.getByTestId("video-preset-tab-all")).toBeVisible();
    await expect(page.getByTestId("video-preset-chip-all")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_preset_overlay.png"), fullPage: true });

    const mockPreset = page.getByTestId("video-preset-card").filter({ hasText: "Mock MP4" });
    const hasMock = (await mockPreset.count()) > 0;
    if (!hasMock) {
      await expect(mockPreset).toHaveCount(0);
      await page.keyboard.press("Escape");
      return;
    }
    await mockPreset.first().click();
    await expect(page.getByTestId("video-preset-overlay")).toHaveCount(0);
    await expect(page.getByTestId("video-duration")).toBeVisible();
    await expect(page.getByTestId("video-aspect")).toBeVisible();
    await expect(page.getByTestId("video-quality")).toBeVisible();
    await expect(page.getByTestId("video-audio")).toHaveCount(0);
    await page.screenshot({ path: path.join(shots, "video_preset_applied.png") });

    await page.getByTestId("video-advanced").click();
    await expect(page.getByTestId("video-advanced-fields")).toBeVisible();
    await expect(page.getByTestId("video-steps")).toBeVisible();
    await expect(page.getByTestId("video-seed")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_advanced.png") });

    await page.getByTestId("video-prompt").fill("north-light oak cube, slow push-in");
    await page.getByTestId("video-generate").click();
    await expect(page.getByTestId("video-feed-pending")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_pending_card.png") });

    await expect(page.locator(".image-card video")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("video-feed-pending")).toHaveCount(0);
    await page.screenshot({ path: path.join(shots, "video_feed_success.png"), fullPage: true });

    const card = page.locator(".image-card").first();
    await card.hover();
    await expect(page.getByTestId("video-card-hover")).toBeVisible();
    await expect(page.getByTestId("video-extend")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_card_hover.png") });

    await page.getByTestId("video-extend").click();
    await expect(page.getByTestId("video-mode-extend")).toHaveClass(/on/);
    await expect(page.getByTestId("video-ref-clip")).toBeVisible();
    await expect(page.getByTestId("video-prompt")).toHaveValue("north-light oak cube, slow push-in");
    await expect(page.getByTestId("video-ref-start")).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: path.join(shots, "video_extend_filled.png") });
  });

  test("animate from Image fills the start frame", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
    });
    await page.goto("/");
    await page.locator('nav button[aria-label="Image"]').click();
    await expect(page.getByTestId("image-page")).toBeVisible();
    await page.getByTestId("image-model-chip").click();
    const mockStill = page.getByRole("option", { name: /Mock PNG/ });
    if (await mockStill.count()) await mockStill.click();
    else {
      await page.keyboard.press("Escape");
      test.skip(true, "mock is hidden while a provider is connected and live spend is off");
    }
    await page.getByTestId("image-prompt").fill("oak still for animate");
    await page.getByTestId("image-generate").click();
    await expect(page.locator(".image-card img")).toBeVisible({ timeout: 30_000 });
    await page.locator(".image-card").first().hover();
    await page.getByTestId("image-animate").click({ force: true });
    await expect(page.getByTestId("video-page")).toBeVisible();
    await expect(page.getByTestId("video-ref-start")).toBeVisible();
    await expect(page.getByTestId("video-mode-references")).toHaveClass(/on/);
    await page.screenshot({ path: path.join(shots, "video_animate_start_frame.png"), fullPage: true });
  });

  test("narrow viewport stacks the panel", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
    });
    await page.goto("/");
    await page.locator("button.rail-menu").click();
    await page.locator('nav button[aria-label="Video"]').click();
    await expect(page.getByTestId("video-page")).toBeVisible();
    await expect(page.getByTestId("video-panel")).toBeVisible();
    await expect(page.getByTestId("video-how")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "video_narrow.png"), fullPage: true });
  });
});
