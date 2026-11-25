import { expect, test, type Page } from "@playwright/test";

// The Studio inside a host (Vinci Platform): the doctor's host block names the pages it serves. Bugs fixed
// on 2026-11-12 (live UI check on app.tryvinci.com): a 401 at start showed the local Studio, All tools had
// empty tabs, the canvas offered starters no model could run, the access pill opened a menu at the far side,
// and image cards had a button that copied a vinci:// link. On 2026-11-13 (COREPRODUC-629): the account
// menu showed only the host name, not the signed-in user, and had no Sign out.

const HOST = {
  name: "Vinci Platform",
  currency: "credits",
  pages: ["image", "video", "canvas", "keys"],
  links: [{ title: "Dashboard", href: "/dashboard" }],
  home: { title: "Dashboard", href: "/dashboard" },
};

/** Serve the demo daemon as a host: its doctor gets the host block, and the voice model is gone. */
async function openHosted(page: Page, host: object = HOST) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
  await page.route(/\/vinci-api\/doctor(\?|$)/, async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), host } });
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

  test("the account menu shows the host's signed-in user and a Sign out link", async ({ page }) => {
    const photo = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" fill="#e85"/></svg>');
    await openHosted(page, {
      ...HOST,
      links: [...HOST.links, { title: "Sign out", href: "/sign-out" }],
      user: { name: "Ada Lovelace", email: "ada@example.com", image: photo },
    });
    const account = page.getByRole("button", { name: "Account menu" });
    await expect(account.locator(".rail-label")).toHaveText("Ada Lovelace");
    await expect(account.locator(".rail-label")).toHaveAttribute("title", "ada@example.com");
    await expect.poll(() => account.locator(".avatar-face img").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    // Keyboard, not a click: in `next dev` the Next.js dev indicator covers the bottom-left account button.
    await account.focus();
    await page.keyboard.press("Enter");
    const signOut = page.getByRole("menuitem", { name: "Sign out" });
    await expect(signOut).toHaveAttribute("href", "/sign-out");
    await expect(signOut).toHaveAttribute("target", "_top");
  });

  // Bug fixed (first occurrence 2026-11-19, user report): before /doctor answered, the rail showed every
  // local page (Explore, Library, Skills, Find, Cost report), the title "Home" and the account "Local" for a moment.
  test("before /doctor answers, the rail shows no page the host may not serve", async ({ page }) => {
    let release = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    let asked = () => {};
    const doctorAsked = new Promise<void>((resolve) => (asked = resolve));
    await page.addInitScript(() => localStorage.setItem("vinci-onboard-v1", "done"));
    await page.route(/\/vinci-api\/doctor(\?|$)/, async (route) => {
      asked();
      await held;
      const res = await route.fetch();
      await route.fulfill({ response: res, json: { ...(await res.json()), host: HOST } });
    });
    await page.goto("/");
    await doctorAsked;
    const rail = page.locator("nav#studio-rail");
    await expect(rail).toBeVisible();
    for (const name of ["Explore", "Image", "Library", "Skills", "Find", "Cost report"]) {
      await expect(rail.locator(`button[aria-label="${name}"]`)).toHaveCount(0);
    }
    await expect(page.locator(".top h1")).toHaveText("");
    await expect(rail.getByRole("button", { name: "Account menu" }).locator(".rail-label")).toHaveText("");
    release();
    await expect(rail.locator('button[aria-label="Image"]')).toBeVisible();
    await expect(page.locator(".top h1")).toHaveText("Image");
    for (const name of ["Explore", "Library", "Skills", "Find", "Cost report"]) {
      await expect(rail.locator(`button[aria-label="${name}"]`)).toHaveCount(0);
    }
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

  // Bug fixed (first occurrence 2026-11-13, 1 report, phone screenshot): each flyout in the phone drawer
  // was a glass card with a "Features" heading on its edge, and "Create Image" repeated "Image".
  test("on a phone the drawer has no flyout cards and no repeated rows", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openHosted(page);
    await page.locator(".rail-menu").click();
    const drawer = page.locator("nav#studio-rail");
    await expect(drawer.getByRole("button", { name: "Video" })).toBeVisible();
    await expect(drawer.locator(".rail-flyout-h:visible")).toHaveCount(0);
    await expect(drawer.locator(".flyout-row:visible")).toHaveCount(0);
    await expect(drawer.locator(".rail-flyout").first()).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  });

  // COREPRODUC-777: Connect shows a "Connect an agent" card with the page origin's /mcp, no key step.
  test("Connect shows the agent setup with this origin's /mcp", async ({ page, context, baseURL }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await openHosted(page, { ...HOST, keys: ["wavespeed"] });
    await page.locator(".rail-avatar button").focus();
    await page.keyboard.press("Enter");
    await page.locator(".avatar-menu").getByRole("menuitem", { name: "Connect" }).click();
    const card = page.getByTestId("agent-connect");
    const url = `${new URL(baseURL || "").origin}/mcp`;
    await expect(card.locator('[data-agent="Claude Code"] pre')).toHaveText(`claude mcp add --transport http vinci ${url}`);
    await expect(card.locator('[data-agent="claude.ai"] pre')).toHaveText(url);
    await expect(card).toContainText("no key");
    await card.locator('[data-agent="Cursor"]').getByRole("button", { name: "Copy" }).click();
    await expect(card.getByRole("status")).toHaveText("Copied the Cursor setup.");
    expect(JSON.parse(await page.evaluate(() => navigator.clipboard.readText()))).toEqual({ mcpServers: { vinci: { url } } });
  });
});
