import { expect, test, type Page } from "@playwright/test";

/**
 * Fail the run when a Studio surface logs a console error, throws, or
 * raises the Next.js dev "N Issue" badge.
 *
 * The badge lives in the `nextjs-portal` shadow root (`[data-issues]`).
 * A missing `/library` route used to 404 on Image and Video; Chromium
 * reports that as a console error and the overlay can stick for the rest
 * of the session. Seen once on the integration screenshots (Nov 2026).
 */
test.describe("console stays clean", () => {
  test("Image, Video, Canvas, Effects, Assets", async ({ page }) => {
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

    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
    });
    await page.goto("/");
    await expect(page.locator("nav")).toBeVisible();

    await openRail(page, "Image");
    await expect(page.getByTestId("image-page")).toBeVisible();
    await settle(page, errors, "Image");

    await openRail(page, "Video");
    await expect(page.getByTestId("video-page")).toBeVisible();
    await expect(page.getByTestId("video-how").locator("article")).toHaveCount(3);
    await settle(page, errors, "Video");

    await openRail(page, "Canvas");
    await expect(page.locator(".graph")).toBeVisible();
    await settle(page, errors, "Canvas");

    await page.locator(`nav button[aria-label="Image"]`).hover();
    await page.getByRole("button", { name: "Upscale Still" }).click();
    await expect(page.getByTestId("effects-shell")).toBeVisible();
    await settle(page, errors, "Effects");

    await page.keyboard.press("Control+k");
    await expect(page.getByTestId("command-box")).toBeVisible();
    await page.getByLabel("Search tools, assets, projects").fill("Assets");
    await page.getByRole("button", { name: /^Assets/ }).first().click();
    await expect(page.getByTestId("assets-page")).toBeVisible();
    await settle(page, errors, "Assets");
  });
});

async function openRail(page: Page, label: string) {
  await page.evaluate((name) => {
    const btn = document.querySelector(`nav button[aria-label="${name}"]`);
    if (!(btn instanceof HTMLElement)) throw new Error(`missing rail ${name}`);
    btn.click();
  }, label);
}

/** Let the page's effects finish, then assert no new errors and no issue badge. */
async function settle(page: Page, errors: string[], name: string) {
  await page.waitForTimeout(600);
  const badge = await page.evaluate(() => {
    const portal = document.querySelector("nextjs-portal");
    const node = portal?.shadowRoot?.querySelector("[data-issues]");
    return (node?.textContent || "").trim();
  });
  expect(badge, `${name} Next issue badge`).toBe("");
  expect(errors, name).toEqual([]);
}
