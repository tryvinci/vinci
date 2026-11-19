import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

// COREPRODUC-729: a click on an Image or Video card opens the full-screen viewer (as Higgsfield does).
// Delete is soft, with Undo on the card. Recreate fills the prompt bar. Screenshots go to PLAYWRIGHT_ARTIFACTS.
const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

async function boot(page: Page, hash: string) {
  await page.addInitScript(() => localStorage.setItem("vinci-onboard-v1", "done"));
  const booted = page.waitForResponse((res) => res.url().includes("/vinci-api/runs") && res.request().method() === "GET");
  await page.goto("/" + hash);
  await booted;
}

const log = (page: Page) => page.locator(".top-log");
const viewer = (page: Page) => page.getByTestId("media-viewer");
const prompt = (page: Page) => page.getByTestId("media-viewer-prompt");

/** Click the picture of a card, away from its buttons. */
async function openCard(page: Page, feed: string, index = 0) {
  const card = page.locator(`[data-testid="${feed}"] .image-card:not(.pending):not(.failed):not(.deleted)`).nth(index);
  await card.hover();
  const box = await card.boundingBox();
  if (!box) throw new Error("no card");
  await page.mouse.click(box.x + box.width / 2, box.y + 24);
  await expect(viewer(page)).toBeVisible();
}

test.describe("COREPRODUC-729 media viewer", () => {
  test("Image: open, step, Esc, Recreate, delete with Undo", async ({ page }) => {
    await boot(page, "#image");
    const box = page.getByRole("textbox", { name: "Image prompt" });
    // New prompts each run: a repeat hits the run cache and keeps the older card's place in the feed.
    const tag = Date.now().toString(36);
    const key = `a brass key on oak ${tag}`;
    const kettle = `a copper kettle at dawn ${tag}`;
    for (const text of [key, kettle]) {
      await box.fill(text);
      await page.getByTestId("image-generate").click();
      await expect(log(page)).toHaveText("Your still is in the feed.", { timeout: 60_000 });
    }

    await openCard(page, "image-feed");
    await expect(prompt(page)).toHaveText(kettle);
    await expect(page.getByTestId("media-viewer-close")).toBeFocused();
    await expect(viewer(page).locator("dl")).toContainText("Size");
    await expect(page.getByTestId("media-viewer-primary")).toHaveText("Animate");
    await expect(viewer(page).getByRole("button", { name: "Copy file link" })).toBeVisible(); // local daemon only
    await page.screenshot({ path: path.join(shots, "c729_image_viewer.png") });
    await page.keyboard.press("ArrowRight");
    await expect(prompt(page)).toHaveText(key);
    await page.keyboard.press("ArrowLeft");
    await expect(prompt(page)).toHaveText(kettle);
    await viewer(page).getByRole("button", { name: "Hide details" }).click();
    await expect(page.getByTestId("media-viewer-prompt")).toHaveCount(0);
    await page.screenshot({ path: path.join(shots, "c729_image_viewer_wide.png") });
    await viewer(page).getByRole("button", { name: "Show details" }).click();
    // Tab stays inside: back past the first stop (Hide details) wraps to the last (Delete).
    await page.getByTestId("media-viewer-close").focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByTestId("media-viewer-delete")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(viewer(page)).toHaveCount(0);
    // Focus goes back to the card that opened it.
    await expect(page.locator('[data-testid="image-feed"] .image-card').first().getByTestId("image-card-open")).toBeFocused();

    // Recreate: the prompt goes back in the box, and the viewer closes so the box is in view.
    await box.fill("");
    await openCard(page, "image-feed");
    await page.getByTestId("media-viewer-recreate").click();
    await expect(viewer(page)).toHaveCount(0);
    await expect(box).toHaveValue(kettle);
    await expect(log(page)).toHaveText("Recreate filled the prompt and the settings. Press Generate to make it again.");

    // Delete from the card's hover row, then Undo on its tile.
    const first = page.locator('[data-testid="image-feed"] .image-card').first();
    await first.hover();
    await first.getByTestId("feed-delete").click();
    await expect(first).toHaveClass(/deleted/);
    await expect(log(page)).toHaveText("Deleted. Undo is on its card.");
    await page.screenshot({ path: path.join(shots, "c729_image_deleted_tile.png") });
    await first.getByRole("button", { name: "Undo" }).click();
    await expect(log(page)).toHaveText("Restored.");
    await expect(first).not.toHaveClass(/deleted/);

    // Delete from the viewer: it moves to the next card. After a reload the deleted still is gone.
    await openCard(page, "image-feed");
    await page.getByTestId("media-viewer-delete").click();
    await expect(prompt(page)).toHaveText(key);
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("feed-card-deleted")).toHaveCount(1);
    // The card that opened the viewer is deleted: focus goes to its Undo.
    await expect(page.getByTestId("feed-card-deleted").getByRole("button", { name: "Undo" })).toBeFocused();
    await boot(page, "#image");
    await openCard(page, "image-feed");
    await expect(prompt(page)).toHaveText(key);
  });

  test("Video: the clip plays in the viewer; Extend, Recreate and Delete are there", async ({ page }) => {
    await boot(page, "#video");
    const clip = `a lighthouse at dusk, slow pan ${Date.now().toString(36)}`;
    await page.getByTestId("video-prompt").fill(clip);
    await page.getByTestId("video-generate").click();
    await expect(page.locator('[data-testid="video-feed"] .image-card video').first()).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("video-feed-pending")).toHaveCount(0);
    await page.getByTestId("video-prompt").fill("");

    await openCard(page, "video-feed");
    await expect(prompt(page)).toHaveText(clip);
    await expect(viewer(page).locator("video")).toBeVisible();
    await expect(page.getByTestId("media-viewer-primary")).toHaveText("Extend");
    await expect(page.getByTestId("media-viewer-delete")).toBeVisible();
    await expect(viewer(page).locator("dl")).toContainText("Length");
    await page.screenshot({ path: path.join(shots, "c729_video_viewer.png") });

    await page.getByTestId("media-viewer-recreate").click();
    await expect(viewer(page)).toHaveCount(0);
    await expect(page.getByTestId("video-prompt")).toHaveValue(clip);
  });
});
