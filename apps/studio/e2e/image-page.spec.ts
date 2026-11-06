import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

async function openImage(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
  // Boot sets models, then loads media (GET /runs). /skills can take ~2s, so wait before the picker opens.
  const booted = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "GET");
  await page.goto("/");
  await page.locator('nav button[aria-label="Image"]').click();
  await expect(page.getByTestId("image-page")).toBeVisible();
  await booted;
}

test.describe("Image page", () => {
  test("feed, prompt bar, model chips, generate, animate", async ({ page }) => {
    await openImage(page);
    await expect(page.getByTestId("image-bar")).toBeVisible();
    await expect(page.getByTestId("image-how")).toBeVisible();
    await expect(page.getByTestId("image-generate")).toContainText("$");
    await page.screenshot({ path: path.join(shots, "image_empty_how.png"), fullPage: true });

    await page.getByTestId("image-model-chip").click();
    await expect(page.getByTestId("image-model-picker")).toBeVisible();
    // Featured lists quality-tier models only. Demo connects mock alone (fast tier), so only "All" shows.
    await expect(page.getByRole("heading", { name: "All" })).toBeVisible();
    await page.screenshot({ path: path.join(shots, "image_model_picker.png") });

    const mock = page.getByRole("option", { name: /Mock PNG/ });
    const hasMock = (await mock.count()) > 0;
    if (hasMock) {
      await mock.click();
      await expect(page.getByTestId("image-quality")).toHaveCount(0);
      await expect(page.getByTestId("image-aspect")).toBeVisible();
      await expect(page.getByTestId("image-resolution")).toBeVisible();
      await page.screenshot({ path: path.join(shots, "image_mock_hides_quality.png") });
      // Keyed rows (GPT Image 2 quality chip) are not listed beside mock; tests/test_image_page.py covers them.
    } else {
      // A connected provider hides mock. The keyed default still exposes its chips.
      await expect(page.locator(".image-picker-row", { hasText: /Mock/i })).toHaveCount(0);
      await page.keyboard.press("Escape");
    }

    if (!hasMock) return;

    await page.getByTestId("image-prompt").fill("north-light oak cube");
    await page.getByTestId("image-generate").click();
    await expect(page.getByTestId("image-feed-pending")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "image_pending_card.png") });

    await expect(page.locator(".image-card img")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("image-feed-pending")).toHaveCount(0);
    await page.screenshot({ path: path.join(shots, "image_feed_success.png"), fullPage: true });

    const card = page.locator(".image-card").first();
    await card.hover();
    await expect(page.getByTestId("image-card-hover")).toBeVisible();
    await expect(page.getByRole("button", { name: "Use as reference" })).toBeVisible();
    await page.screenshot({ path: path.join(shots, "image_card_hover.png") });

    await page.getByTestId("image-animate").click();
    await expect(page.getByTestId("video-page")).toBeVisible();
    await expect(page.getByTestId("video-ref-start")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "image_animate_video.png"), fullPage: true });
  });

  test("narrow viewport keeps the bar", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
    });
    await page.goto("/");
    await page.locator("button.rail-menu").click();
    await page.locator('nav button[aria-label="Image"]').click();
    await expect(page.getByTestId("image-page")).toBeVisible();
    await expect(page.getByTestId("image-bar")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "image_narrow.png"), fullPage: true });
  });
});
