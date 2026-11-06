import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const SHOT = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOT, `${name}.png`), fullPage: true });
}

async function openCanvas(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(page.locator("#onboard")).toHaveCount(0);
  await page.getByRole("button", { name: "Canvas" }).click();
  await expect(page.getByTestId("choose-first-node")).toBeVisible();
}

test.describe("Canvas v2 typed ports and add popover", () => {
  test("empty, add popover, click-output-to-add, keyboard", async ({ page }) => {
    await openCanvas(page);
    await shot(page, "01-empty-first-node");

    await page.keyboard.press("n");
    const menu = page.getByTestId("add-menu");
    await expect(menu).toBeVisible();
    await expect(menu.locator(".add-sec", { hasText: "Media" })).toBeVisible();
    await expect(menu.locator(".add-sec", { hasText: "Nodes" })).toBeVisible();
    await expect(menu.locator(".add-sec", { hasText: "Models" })).toBeVisible();
    await expect(page.getByTestId("add-chip-image")).toBeVisible();
    await shot(page, "02-add-popover-open");

    await page.getByTestId("add-chip-image").click();
    await expect(menu.locator('[data-add="node:t2i"]')).toBeVisible();
    await expect(menu.locator('[data-add="node:t2v"]')).toHaveCount(0);
    await shot(page, "03-add-popover-image-chip");

    await page.getByTestId("add-chip-3d").click();
    await expect(menu.getByText("Nothing matches. Clear the filter or try another word.")).toBeVisible();
    await shot(page, "04-add-popover-3d-empty");

    await page.getByTestId("add-chip-3d").click();
    await page.getByTestId("add-menu-search").fill("upscaler");
    await expect(menu.locator('[data-add="node:upscale"]')).toBeVisible();
    await shot(page, "05-add-popover-search");

    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);

    await page.keyboard.press("n");
    await expect(menu).toBeVisible();
    await page.getByTestId("add-menu-search").fill("");
    await page.getByTestId("add-chip-image").click();
    await menu.locator('[data-add="node:t2i"]').click();
    await expect(page.locator(".node").first()).toBeVisible();
    const modelPill = page.getByTestId("node-model-chip");
    await expect(modelPill).toHaveAttribute("aria-haspopup", "listbox");
    await modelPill.focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("listbox", { name: "Model" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox", { name: "Model" })).toHaveCount(0);
    await expect(page.locator('.port.out[data-kind="image"]')).toBeVisible();
    await expect(page.locator('.port.in[data-kind="text"]')).toBeVisible();
    await shot(page, "06-image-gen-typed-ports");

    await page.locator('.port.out[data-kind="image"]').click();
    await expect(menu).toBeVisible();
    await expect(menu.locator('[data-add="node:upscale"]')).toBeVisible();
    await expect(menu.locator('[data-add="node:t2i"]')).toHaveCount(0);
    await shot(page, "07-click-output-compatible");

    await menu.locator('[data-add="node:upscale"]').click();
    await expect(page.locator(".node")).toHaveCount(2);
    await expect(page.locator("path.wire:not(.ghost)")).toHaveCount(1);
    await shot(page, "08-wired-upscaler");

    await page.keyboard.press("n");
    await expect(menu).toBeVisible();
    await page.getByTestId("add-menu-search").fill("video gen");
    await expect(menu.locator('[data-add="node:t2v"]')).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator(".node")).toHaveCount(3);
    await page.locator('.port.out[data-kind="video"]').click();
    await page.locator('.port.in[data-kind="text"]').first().click();
    await expect(page.locator("path.wire:not(.ghost)")).toHaveCount(1);
    await shot(page, "09-video-out-to-text-in-rejected");
  });
});
