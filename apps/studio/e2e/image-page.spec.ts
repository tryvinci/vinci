import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fakeRuns } from "./fake-runs";

const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";

async function openImage(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("vinci-onboard-v1", "done");
  });
  // Boot sets models, then loads media (GET /runs). /skills can take ~2s, so wait before the picker opens.
  const booted = page.waitForResponse((res) => res.url().split("?")[0].endsWith("/vinci-api/runs") && res.request().method() === "GET");
  // An empty project: other specs leave runs in My work on the shared daemon, and this test checks the empty feed.
  const { id } = (await (await page.request.post("/vinci-api/projects", { data: { name: "e2e Image page" } })).json()) as { id: string };
  await page.goto(`/?project=${id}`);
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

  test("Generate stays on while an image run goes; one top-bar line (COREPRODUC-791, 792)", async ({ page }) => {
    // Fake runs that go on until the test ends them, so the first run is still going when Generate is clicked again.
    const runs = await fakeRuns(page);
    await openImage(page);
    await page.getByTestId("image-model-chip").click();
    const mock = page.getByRole("option", { name: /Mock PNG/ });
    test.skip((await mock.count()) === 0, "a connected provider hides mock");
    await mock.click();

    const generate = page.getByTestId("image-generate");
    await page.getByTestId("image-prompt").fill("north-light oak cube");
    await generate.click();
    await expect(page.getByTestId("image-feed-pending")).toHaveCount(1);
    await expect(generate).toBeEnabled();
    await expect(generate).toContainText("Generate");
    await page.screenshot({ path: path.join(shots, "image_parallel_first_running.png") });

    await page.getByTestId("image-prompt").fill("south-light walnut sphere");
    await generate.click();
    await expect(page.getByTestId("image-feed-pending")).toHaveCount(2);
    await expect.poll(() => runs.posts).toBe(2);
    await expect(generate).toBeEnabled();
    await page.screenshot({ path: path.join(shots, "image_parallel_two_running.png") });

    // The first job ends: the top bar still says "Generating…" while the second goes (COREPRODUC-792).
    const log = page.locator(".top-log[role=status]");
    runs.end(1);
    await expect(page.getByTestId("image-feed-pending")).toHaveCount(1);
    await expect(log).toHaveText("Generating…");
    await page.screenshot({ path: path.join(shots, "image_parallel_first_ended.png") });
    runs.end(2);
    await expect(page.getByTestId("image-feed-pending")).toHaveCount(0);
    await expect(log).toHaveText("Your still is in the feed.");
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
