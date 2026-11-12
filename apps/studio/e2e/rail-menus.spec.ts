import { expect, test, type Page } from "@playwright/test";

// The rail's account menu and model picks. Bugs fixed on 2026-11-12 (reported in production):
// a clear scrim over the rail took the account menu's clicks, and the Image page replaced a model
// picked in the rail flyout (or picked on the page before a visit to another page) with its default.

async function openImage(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
  const booted = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "GET");
  await page.goto("/");
  await page.locator('nav button[aria-label="Image"]').click();
  await expect(page.getByTestId("image-page")).toBeVisible();
  await booted;
}

/** Demo connects only mock, which has one image model: add a second, a copy of Mock PNG. */
async function addSecondImageModel(page: Page) {
  await page.route(/\/vinci-api\/models(\?|$)/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const png = body.models.find((row: { id: string }) => row.id === "mock:png:v1");
    if (png) body.models.push({ ...png, id: "mock:png:b", display_name: "Mock Still B" });
    await route.fulfill({ response: res, json: body });
  });
}

/** The image model name, of the two, that the chip does not show. */
function other(chip: string): string {
  return chip.includes("Mock Still B") ? "Mock PNG" : "Mock Still B";
}

test.describe("Rail menus", () => {
  test("account menu items take clicks", async ({ page }) => {
    await openImage(page);
    // Open it from the keyboard: in `next dev` the Next.js dev indicator covers the account button.
    await page.locator(".rail-avatar button").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".avatar-menu")).toBeVisible();
    await page.locator(".avatar-menu").getByRole("menuitem", { name: "Connect" }).click();
    await expect(page.locator(".top h1")).toHaveText("Connect");
    await expect(page.locator(".avatar-menu")).toHaveCount(0);
  });

  test("a model picked in the Image flyout stays on the Image page", async ({ page }) => {
    await addSecondImageModel(page);
    await openImage(page);
    const chip = page.getByTestId("image-model-chip");
    const want = other((await chip.textContent()) || "");
    await page.locator('nav button[aria-label="Video"]').click();
    await expect(page.getByTestId("video-page")).toBeVisible();
    await page.locator('nav button[aria-label="Image"]').hover();
    const flyout = page.locator('.rail-entry:has(> button[aria-label="Image"]) .rail-flyout');
    await flyout.locator("button.flyout-row", { hasText: want }).click();
    await expect(page.getByTestId("image-page")).toBeVisible();
    await expect(chip).toContainText(want);
  });

  test("a model picked on the Image page stays after a visit to Video", async ({ page }) => {
    await addSecondImageModel(page);
    await openImage(page);
    const chip = page.getByTestId("image-model-chip");
    const want = other((await chip.textContent()) || "");
    await chip.click();
    await page.getByTestId("image-model-picker").getByRole("option", { name: new RegExp(want) }).click();
    await expect(chip).toContainText(want);
    await page.locator('nav button[aria-label="Video"]').click();
    await expect(page.getByTestId("video-page")).toBeVisible();
    await page.locator('nav button[aria-label="Image"]').click();
    await expect(page.getByTestId("image-page")).toBeVisible();
    await expect(chip).toContainText(want);
  });
});
