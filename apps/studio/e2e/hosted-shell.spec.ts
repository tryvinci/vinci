import { expect, test, type Page } from "@playwright/test";

// The Studio inside a host (Vinci Platform): the doctor's host block names the pages it serves. Bugs fixed
// on 2026-11-12 (live UI check on app.tryvinci.com): a 401 at start showed the local Studio, All tools had
// empty tabs, the canvas offered starters no model could run, the access pill opened a menu at the far side,
// and image cards had a button that copied a vinci:// link.

const HOST = {
  name: "Vinci Platform",
  currency: "credits",
  pages: ["image", "video", "canvas", "keys"],
  links: [{ title: "Dashboard", href: "/dashboard" }],
  home: { title: "Dashboard", href: "/dashboard" },
};

/** Serve the demo daemon as a host: its doctor gets the host block, and the voice model is gone. */
async function openHosted(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
  await page.route(/\/vinci-api\/doctor(\?|$)/, async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), host: HOST } });
  });
  await page.route(/\/vinci-api\/models(\?|$)/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.models = body.models.filter((row: { id: string }) => row.id !== "mock:wav:v1");
    await route.fulfill({ response: res, json: body });
  });
  await page.goto("/");
  await expect(page.getByTestId("image-page")).toBeVisible();
}

test.describe("Hosted shell", () => {
  test("a 401 at start shows the session notice, not the local Studio", async ({ page }) => {
    await page.route(/\/vinci-api\/init$/, (route) =>
      route.fulfill({ status: 401, json: { detail: "Your session ended. Sign in again." } }),
    );
    await page.goto("/");
    await expect(page.getByTestId("session-ended")).toContainText("Your session ended");
    await expect(page.getByRole("button", { name: "Sign in again" })).toBeVisible();
    await expect(page.locator("nav#studio-rail")).toHaveCount(0);
  });

  test("All tools shows only tabs with tools the host serves", async ({ page }) => {
    await openHosted(page);
    await page.getByRole("button", { name: "All tools" }).click();
    const tabs = (await page.locator(".all-tools-tabs button").allTextContents()).map((tab) => tab.trim());
    expect(tabs).toContain("Image");
    for (const empty of ["Audio", "Edit", "Library", "Templates"]) expect(tabs).not.toContain(empty);
  });

  test("the canvas offers only runnable starters, and its access pill opens Connect", async ({ page }) => {
    await openHosted(page);
    await page.locator('nav button[aria-label="Canvas"]').click();
    await expect(page.locator('.first-node-card[data-start="t2i"]')).toBeVisible();
    await expect(page.locator('.first-node-card[data-start="tts"]')).toHaveCount(0);
    await page.locator("button.access-pill").click();
    await expect(page.locator(".top h1")).toHaveText("Connect");
    await expect(page.locator(".avatar-menu")).toHaveCount(0);
  });
});
