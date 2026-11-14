import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

// Fixes for the 2026-11-13 production Studio crawl (COREPRODUC-638 to 642). Each test names its STU id.
const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";
const PNG = path.resolve(__dirname, "../../../packages/olf/conformance/tidewatch/bible/props/brass-key/ref.png");
const PNG2 = path.resolve(__dirname, "../../../packages/olf/conformance/tidewatch/bible/characters/mira/sheet.png");

async function boot(page: Page, hash = "") {
  await page.addInitScript(() => localStorage.setItem("vinci-onboard-v1", "done"));
  const booted = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "GET");
  await page.goto("/" + hash);
  await booted;
}

async function openPage(page: Page, name: "Image" | "Video") {
  await page.locator(`nav button[aria-label="${name}"]`).click();
  await expect(page.getByTestId(`${name.toLowerCase()}-page`)).toBeVisible();
}

/** Upload one file through an input and return the asset id the Studio got back. */
async function upload(page: Page, input: ReturnType<Page["locator"]>, file: string): Promise<string> {
  const answer = page.waitForResponse((res) => /\/vinci-api\/assets$/.test(res.url()) && res.request().method() === "POST");
  await input.setInputFiles(file);
  return ((await (await answer).json()) as { id: string }).id;
}

test.describe("Production crawl fixes", () => {
  test("STU-01, 11, 12, 23: an empty prompt keeps Generate off with a reason; Escape and names", async ({ page }) => {
    await boot(page);
    await openPage(page, "Image");
    await expect(page.getByTestId("image-generate")).toBeDisabled();
    await expect(page.getByTestId("image-blocked")).toHaveText("Describe the still first.");
    await page.screenshot({ path: path.join(shots, "crawl_image_empty_prompt.png") });
    await page.getByRole("textbox", { name: "Image prompt" }).fill("a brass key on oak");
    await expect(page.getByTestId("image-generate")).toBeEnabled();
    await expect(page.getByTestId("image-blocked")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Images per run: 1$/ })).toBeVisible();
    await page.getByTestId("image-model-chip").click();
    await expect(page.getByTestId("image-model-picker")).toBeVisible();
    await expect(page.getByTestId("model-price").first()).not.toHaveText("");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("image-model-picker")).toHaveCount(0);
    await expect(page.getByTestId("image-model-chip")).toBeFocused();

    await openPage(page, "Video");
    await page.getByRole("textbox", { name: "Video prompt" }).fill("");
    await expect(page.getByTestId("video-generate")).toBeDisabled();
    await expect(page.getByTestId("video-blocked")).toHaveText("Describe the shot first.");
  });

  test("STU-02, 04, 22: Video sends its own start frame; Motion control has no Generate; New clears", async ({ page }) => {
    const posted: Record<string, unknown>[] = [];
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      posted.push((route.request().postDataJSON() as { inputs: Record<string, unknown> }).inputs);
      await route.fulfill({ json: { id: "run-crawl", state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
    });
    await boot(page);
    await openPage(page, "Image");
    const refId = await upload(page, page.getByTestId("image-bar").locator("input[type=file]"), PNG);
    await openPage(page, "Video");
    const startId = await upload(page, page.getByTestId("video-panel").locator("input[type=file]"), PNG2);
    expect(startId).not.toBe(refId);
    await page.getByTestId("video-tab-motion-control").click();
    await expect(page.getByTestId("video-generate")).toHaveCount(0);
    await expect(page.getByTestId("video-motion-note")).toContainText("Go back to Create");
    await page.screenshot({ path: path.join(shots, "crawl_video_motion_note.png") });
    await page.getByTestId("video-tab-create").click();
    await page.getByTestId("video-prompt").fill("slow push-in");
    await page.getByTestId("video-generate").click();
    await expect.poll(() => posted.length).toBe(1);
    expect(posted[0].image).toBe(startId); // not the Image-page reference
    expect(posted[0].prompt).toBe("slow push-in");
    await page.getByRole("button", { name: "New" }).click();
    await expect(page.getByTestId("video-prompt")).toHaveValue("");
  });

  test("COREPRODUC-648: a text-only model takes no reference; Generate says why and names one that does", async ({ page }) => {
    // Demo has one image model (Mock PNG, takes references). Add a text-only copy named like FLUX Dev.
    await page.route("**/vinci-api/models", async (route) => {
      const res = await route.fetch();
      const body = (await res.json()) as { models: Record<string, unknown>[] };
      const png = body.models.find((row) => row.id === "mock:png:v1");
      body.models.push({ ...png, id: "mock:flux-dev:test", display_name: "FLUX Dev", capabilities: ["t2i"] });
      await route.fulfill({ response: res, json: body });
    });
    const posted: Record<string, unknown>[] = [];
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      posted.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({ json: { id: "run-648", state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
    });
    const pick = async (name: string) => {
      await page.getByTestId("image-model-chip").click();
      await page.getByTestId("image-model-picker").getByRole("option", { name: new RegExp(name) }).click();
      await expect(page.getByTestId("image-model-chip")).toHaveText(name);
    };
    await boot(page);
    await openPage(page, "Image");
    await page.getByRole("textbox", { name: "Image prompt" }).fill("a paper boat on a pond");

    // A text-only model: Add reference is off and says why.
    await pick("FLUX Dev");
    await expect(page.getByTestId("image-ref")).toBeDisabled();
    await expect(page.getByTestId("image-ref")).toHaveAttribute("aria-label", "FLUX Dev does not use references");
    await page.screenshot({ path: path.join(shots, "ref_flux_add_off.png") });

    // A model with References sends the reference.
    await pick("Mock PNG");
    await expect(page.getByTestId("image-ref")).toBeEnabled();
    const refId = await upload(page, page.getByTestId("image-bar").locator("input[type=file]"), PNG);
    await page.getByTestId("image-generate").click();
    await expect.poll(() => posted.length).toBe(1);
    expect((posted[0].inputs as Record<string, unknown>).image).toBe(refId);

    // Picking FLUX Dev with the reference set blocks Generate with a reason and a model that takes one.
    await pick("FLUX Dev");
    await expect(page.getByTestId("image-generate")).toBeDisabled();
    await expect(page.getByTestId("image-blocked")).toHaveText(
      "FLUX Dev does not use references. Remove the reference, or pick Mock PNG.",
    );
    await page.screenshot({ path: path.join(shots, "ref_flux_blocked.png") });
    await page.getByTestId("image-generate").click({ force: true });
    expect(posted.length).toBe(1); // nothing paid for a reference the model ignores

    // Removing the chip lets FLUX Dev run as text to image.
    await page.getByTitle("Remove reference").click();
    await expect(page.getByTestId("image-blocked")).toHaveCount(0);
    await page.getByTestId("image-generate").click();
    await expect.poll(() => posted.length).toBe(2);
    expect(posted[1].model_id).toBe("mock:flux-dev:test");
    expect((posted[1].inputs as Record<string, unknown>).image).toBeUndefined();
  });

  test("STU-10, 08: a wrong file type shows the server's reason, in full", async ({ page }) => {
    await page.route("**/vinci-api/assets", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ status: 415, json: { detail: "Upload an image, a video or an audio file." } })
        : route.continue(),
    );
    await boot(page);
    await openPage(page, "Image");
    await page.getByTestId("image-bar").locator("input[type=file]").setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hi") });
    await expect(page.locator(".top-log")).toHaveText("Upload an image, a video or an audio file.");
    expect(await page.locator(".top-log").evaluate((el) => getComputedStyle(el).whiteSpace)).toBe("normal");
  });

  test("STU-03, 06, 09, 21: a Text node feeds Image Gen; count makes copies; a refusal says why", async ({ page }) => {
    const bodies: { workflow?: { nodes: { id: string; params: Record<string, unknown> }[] } }[] = [];
    let refuse = false;
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      bodies.push(route.request().postDataJSON());
      if (refuse) return route.fulfill({ status: 403, json: { detail: "Studio generation is not available for free users. Please upgrade to a paid plan." } });
      await route.fulfill({ json: { id: `run-${bodies.length}`, state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
    });
    await boot(page);
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await expect(page.locator(".graph")).toBeVisible();
    await page.getByTestId("canvas-tool-add").click();
    await page.getByTestId("add-menu-search").fill("text");
    await page.getByTestId("add-menu").locator('[data-add="node:text"]').click();
    const text = page.locator(".node", { hasText: "Text" }).first();
    await text.locator("[data-node-prompt]").fill("a red fox at dusk");
    await text.locator(".port.out").click();
    await page.getByTestId("add-menu").locator('[data-add="node:t2i"]').click();
    const gen = page.locator(".node", { hasText: "Image Gen" });
    await expect(gen.locator("[data-node-prompt]")).toHaveAttribute("placeholder", /Using the wired text/);
    await gen.getByTestId("node-run").click();
    await expect.poll(() => bodies.length).toBe(1);
    const prompts = (bodies[0].workflow?.nodes || []).map((n) => String(n.params.prompt));
    expect(prompts.join()).not.toContain("{{nodes.");
    expect(prompts).toContain("a red fox at dusk");
    await page.screenshot({ path: path.join(shots, "crawl_canvas_text_node.png") });

    await gen.getByTestId("node-count").getByRole("button").last().click(); // count 2
    await gen.getByTestId("node-run").click();
    await expect.poll(() => bodies.length).toBe(2);
    const ids = (bodies[1].workflow?.nodes || []).map((n) => n.id);
    expect(ids.length).toBe(2);
    expect(new Set((bodies[1].workflow?.nodes || []).map((n) => n.params.seed)).size).toBe(2);
    // Each copy runs on the model its node shows (the model is pinned before the copies are made).
    const models = (bodies[1].workflow?.nodes || []).map((n) => (n as { model_id?: string }).model_id);
    expect(models[0]).toBeTruthy();
    expect(new Set(models).size).toBe(1);

    refuse = true;
    await gen.getByTestId("node-run").click();
    await expect(gen.locator(".node-sub")).toContainText("not available for free users");
    await page.screenshot({ path: path.join(shots, "crawl_canvas_refusal.png") });
  });

  test("COREPRODUC-649: a Video Gen node picks its duration; the run sends it and the price follows", async ({ page }) => {
    // Kling 2.6 Standard as the host lists it: 5 or 10 s, a price per length, no resolution.
    const kling = {
      id: "mock:kling-26-std",
      display_name: "Kling 2.6 Standard",
      provider: "mock",
      capabilities: ["t2v", "i2v"],
      available: true,
      status: "ready",
      pricing: { amount: 0.21, unit: "video", currency: "USD", clip_prices: { "5": 0.21, "10": 0.42 } },
      constraints: { aspect_ratios: ["16:9", "9:16", "1:1"], resolutions: [], durations: [5, 10], max_duration: 10 },
    };
    await page.route("**/vinci-api/models", async (route) => {
      const body = (await (await route.fetch()).json()) as { models: unknown[] };
      await route.fulfill({ json: { ...body, models: [...body.models, kling] } });
    });
    const bodies: { workflow?: { nodes: { model_id?: string; params: Record<string, unknown> }[] } }[] = [];
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      bodies.push(route.request().postDataJSON());
      await route.fulfill({ json: { id: `run-${bodies.length}`, state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
    });
    await boot(page);
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await page.locator('[data-start="t2v"]').click();
    const gen = page.locator(".node[data-id]").first();
    await gen.locator("[data-node-prompt]").fill("a kite over the sea");
    await gen.getByTestId("node-resolution-chip").click(); // a resolution picked on the first model…
    await gen.getByRole("option").last().click();
    await gen.getByTestId("node-model-chip").click();
    await gen.getByRole("option", { name: /Kling 2.6 Standard/ }).click();
    await expect(gen.getByTestId("node-resolution-chip")).toHaveCount(0); // no image sizes on a video model
    await expect(gen.getByTestId("node-duration-chip")).toHaveText("5s");
    await expect(gen.getByTestId("node-run")).toHaveAttribute("title", /0\.21/);
    await gen.getByTestId("node-duration-chip").click();
    await expect(gen.getByRole("option")).toHaveText(["5s", "10s"]);
    await gen.getByRole("option", { name: "10s" }).click();
    await expect(gen.getByTestId("node-run")).toHaveAttribute("title", /0\.42/);
    await gen.getByTestId("node-gear").click();
    await page.getByTestId("inspector-advanced").click();
    await expect(page.locator("#node-duration-pills button.on")).toHaveText("10s");
    await expect(page.locator("#node-resolution-pills")).toHaveCount(0);
    await page.screenshot({ path: path.join(shots, "canvas_video_duration.png") });
    await gen.getByTestId("node-run").click();
    await expect.poll(() => bodies.length).toBe(1);
    const node = (bodies[0].workflow?.nodes || [])[0];
    expect(node.model_id).toBe("mock:kling-26-std");
    expect(node.params.duration).toBe(10);
    expect(node.params.resolution).toBeUndefined(); // …is not sent to a model that lists none
  });

  // FLUX Dev and Hailuo 02 as the host lists them: FLUX has ratios but no resolution, Hailuo neither.
  for (const c of [
    { start: "t2i", id: "mock:flux-dev", name: "FLUX Dev", caps: ["t2i"], limits: { aspect_ratios: ["16:9", "9:16", "1:1"], resolutions: [] } },
    { start: "t2v", id: "mock:hailuo-02", name: "Hailuo 02", caps: ["t2v", "i2v"], limits: { aspect_ratios: [], resolutions: [], durations: [6, 10], max_duration: 10 } },
  ]) {
    test(`COREPRODUC-653: a ${c.name} node shows and sends only the aspect and resolution it lists`, async ({ page }) => {
      const model = { id: c.id, display_name: c.name, provider: "mock", capabilities: c.caps, available: true, status: "ready", pricing: { amount: 0.1, unit: "generation", currency: "USD" }, constraints: c.limits };
      await page.route("**/vinci-api/models", async (route) => {
        const body = (await (await route.fetch()).json()) as { models: unknown[] };
        await route.fulfill({ json: { ...body, models: [...body.models, model] } });
      });
      const bodies: { workflow?: { nodes: { model_id?: string; params: Record<string, unknown> }[] } }[] = [];
      await page.route("**/vinci-api/runs", async (route) => {
        if (route.request().method() !== "POST") return route.continue();
        bodies.push(route.request().postDataJSON());
        await route.fulfill({ json: { id: `run-${bodies.length}`, state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
      });
      await boot(page);
      await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
      await page.locator(`[data-start="${c.start}"]`).click();
      const gen = page.locator(".node[data-id]").first();
      await gen.locator("[data-node-prompt]").fill("a lighthouse at dusk");
      await gen.getByTestId("node-model-chip").click();
      await gen.getByRole("option", { name: new RegExp(c.name) }).click();
      await expect(gen.getByTestId("node-resolution-chip")).toHaveCount(0); // no made-up 1K/2K/4K
      await expect(gen.getByTestId("node-aspect-chip")).toHaveCount(c.limits.aspect_ratios.length ? 1 : 0); // no made-up 4:3
      await page.screenshot({ path: path.join(shots, `canvas_listed_controls_${c.start}.png`) });
      await gen.getByTestId("node-run").click();
      await expect.poll(() => bodies.length).toBe(1);
      const sent = (bodies[0].workflow?.nodes || []).find((n) => n.model_id === c.id);
      expect(sent?.params.resolution).toBeUndefined(); // the starter's "1K" is not sent
      if (c.limits.aspect_ratios.length) expect(sent?.params.aspect_ratio).toBe("16:9");
      else expect(sent?.params.aspect_ratio).toBeUndefined();
    });
  }
});

const HOST = {
  name: "Vinci Platform",
  currency: "credits",
  pages: ["image", "video", "canvas", "keys"],
  keys: ["wavespeed"],
  links: [{ title: "Dashboard", href: "/dashboard" }],
  home: { title: "Dashboard", href: "/dashboard" },
};

async function openHosted(page: Page, hash = "") {
  await page.addInitScript(() => localStorage.setItem("vinci-onboard-v1", "done"));
  await page.route(/\/vinci-api\/doctor(\?|$)/, async (route) => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), host: HOST } });
  });
  await page.goto("/" + hash);
}

test.describe("Production crawl fixes on a host", () => {
  test("STU-07: reload and Back keep the page and the prompt", async ({ page }) => {
    await openHosted(page, "#video");
    await expect(page.getByTestId("video-page")).toBeVisible();
    await page.getByTestId("video-prompt").fill("a lighthouse at dusk");
    await page.reload();
    await expect(page.getByTestId("video-page")).toBeVisible();
    await expect(page.getByTestId("video-prompt")).toHaveValue("a lighthouse at dusk");
    await page.locator('nav button[aria-label="Canvas"]').click();
    await expect(page).toHaveURL(/#canvas$/);
    await page.goBack();
    await expect(page.getByTestId("video-page")).toBeVisible();
  });

  test("STU-13: Escape gives focus back to All tools", async ({ page }) => {
    await openHosted(page);
    await expect(page.getByTestId("image-page")).toBeVisible();
    await page.getByRole("button", { name: "All tools" }).click();
    await expect(page.getByTestId("all-tools-popover")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("all-tools-popover")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "All tools" })).toBeFocused();
  });

  test("STU-16: a network failure on Connect is an error, in plain words", async ({ page }) => {
    await page.route("**/vinci-api/providers", (route) => (route.request().method() === "POST" ? route.abort("failed") : route.continue()));
    await openHosted(page, "#keys");
    await expect(page.getByTestId("host-keys")).toBeVisible();
    const field = page.locator("input[type=password]").first();
    await field.fill("ws-test-key-0000000000000000");
    await page.getByRole("button", { name: /^Save .* key$/ }).first().click();
    const log = page.getByTestId("host-keys-log");
    await expect(log).toHaveText("Could not reach Vinci. Check your connection, then try again.");
    await expect(log).toHaveClass(/error/);
    await expect(log).toHaveAttribute("role", "alert");
    await page.screenshot({ path: path.join(shots, "crawl_connect_network_error.png") });
  });
});

