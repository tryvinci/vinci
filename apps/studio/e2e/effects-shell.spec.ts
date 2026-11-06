import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

async function skipOnboard(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
}

async function openFlyoutFeature(page: Page, railLabel: string, featureName: string) {
  await page.locator(`nav button[aria-label="${railLabel}"]`).hover();
  await page.getByRole("button", { name: featureName }).click();
  await page.locator(".main").hover();
}

test.describe("Effects shell", () => {
  test("upscale still preset, gallery overlay, history empty", async ({ page }) => {
    await skipOnboard(page);
    await page.goto("/");
    await openFlyoutFeature(page, "Image", "Upscale Still");
    await expect(page.getByTestId("effects-shell")).toBeVisible();
    await expect(page.getByTestId("effects-preset-card")).toBeVisible();
    await expect(page.getByTestId("effects-history-empty")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "effects_upscale_empty.png"), fullPage: true });

    await page.getByTestId("effects-change").click();
    await expect(page.getByTestId("effects-gallery-overlay")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "effects_gallery_overlay.png"), fullPage: true });
    await page.getByRole("button", { name: "Close" }).click();
  });

  test("speak talking photo generate", async ({ page }) => {
    await skipOnboard(page);
    await page.goto("/");
    await openFlyoutFeature(page, "Video", "Talking Head");
    await expect(page.getByTestId("effects-shell")).toHaveAttribute("data-app", "talking-photo");
    await page.screenshot({ path: path.join(shots, "effects_speak_form.png"), fullPage: true });
  });

  test("adapts embeds batch panel", async ({ page }) => {
    await skipOnboard(page);
    await page.goto("/");
    await openFlyoutFeature(page, "Image", "Adapts");
    await expect(page.getByTestId("effects-adapts-panel")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "effects_adapts_panel.png"), fullPage: true });
  });

  test("narrow viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await skipOnboard(page);
    await page.goto("/");
    await page.locator("button.rail-menu").click();
    await openFlyoutFeature(page, "Image", "Upscale Still");
    await expect(page.getByTestId("effects-shell")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "effects_upscale_narrow.png"), fullPage: true });
  });
});
