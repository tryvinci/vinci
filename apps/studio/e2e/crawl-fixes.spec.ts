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

  test("STU-02, 04, 22: Video sends its own start frame; Motion control has no Generate; no New (COREPRODUC-659)", async ({ page }) => {
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
    await expect(page.getByRole("button", { name: "New" })).toHaveCount(0); // it only cleared the form
  });

  test("COREPRODUC-659: a start frame shows while it uploads, and Generate waits for it", async ({ page }) => {
    let release = () => {};
    const held = new Promise<void>((done) => (release = done));
    await page.route("**/vinci-api/assets", async (route) => {
      if (route.request().method() === "POST") await held; // keep the upload in flight
      await route.continue();
    });
    await boot(page);
    await openPage(page, "Video");
    await page.getByTestId("video-prompt").fill("slow push-in");
    await page.getByTestId("video-panel").locator("input[type=file]").setInputFiles(PNG);
    await expect(page.getByTestId("video-ref-start-uploading")).toContainText("Uploading");
    await expect(page.getByTestId("video-generate")).toBeDisabled();
    await page.screenshot({ path: path.join(shots, "crawl_video_start_uploading.png") });
    release();
    await expect(page.getByTestId("video-ref-start")).toBeVisible();
    await expect(page.getByTestId("video-ref-start-uploading")).toHaveCount(0);
    await expect(page.getByTestId("video-generate")).toBeEnabled();
    await page.screenshot({ path: path.join(shots, "crawl_video_start_ready.png") });
  });

  test("COREPRODUC-659: Generate shows a bar that counts down to 90% over the model's average, then waits", async ({ page }) => {
    // History: two Mock MP4 runs of 4 s and 6 s, so the average is 5 s. The provider then takes 8 s.
    const t0 = Date.parse("2026-11-16T10:00:00Z");
    const past = (n: number, secs: number) => ({
      id: `hist-${n}`, state: "completed", inputs: { model_id: "mock:mp4:v1" }, outputs: [],
      created_at: new Date(t0).toISOString(), completed_at: new Date(t0 + secs * 1000).toISOString(),
    });
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() === "GET") {
        const body = (await (await route.fetch()).json()) as { runs?: unknown[] };
        return route.fulfill({ json: { ...body, runs: [...(body.runs || []), past(1, 4), past(2, 6)] } });
      }
      await new Promise((done) => setTimeout(done, 8000));
      return route.fulfill({ json: { id: "run-slow", state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
    });
    await boot(page);
    await openPage(page, "Video");
    await page.getByTestId("video-prompt").fill("slow push-in");
    await page.getByTestId("video-generate").click();
    const bar = page.getByTestId("video-feed-pending-progress");
    const pct = async () => Number(await bar.getByRole("progressbar").getAttribute("aria-valuenow"));
    await expect(bar).toContainText(/About [1-5]s left/);
    await expect.poll(pct).toBeGreaterThan(30);
    await page.screenshot({ path: path.join(shots, "crawl_video_progress.png") });
    await expect(bar).toContainText("Almost done…", { timeout: 6000 }); // 5 s in
    expect(await pct()).toBe(90);
    await page.waitForTimeout(1000);
    expect(await pct()).toBe(90); // it waits at 90%, it does not reach 100
    await page.screenshot({ path: path.join(shots, "crawl_video_progress_90.png") });
    await expect(bar).toHaveCount(0, { timeout: 10_000 }); // the run ended
  });

  test("COREPRODUC-659: a running canvas node shows the bar; a model with no history counts from its kind's default", async ({ page }) => {
    let release = () => {};
    const held = new Promise<void>((done) => (release = done));
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await held;
      await route.fulfill({ json: { id: "run-node", state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
    });
    await boot(page);
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await page.locator('[data-start="t2v"]').click();
    const gen = page.locator(".node[data-id]").first();
    await gen.locator("[data-node-prompt]").fill("a kite over the sea");
    await gen.getByTestId("node-run").click();
    const bar = gen.getByTestId("node-progress");
    await expect(bar).toContainText(/About (2m 00s|1m 5\ds) left/); // no Mock MP4 history: the 120 s video default
    await gen.screenshot({ path: path.join(shots, "canvas_node_progress.png") });
    release();
    await expect(bar).toHaveCount(0);
  });

  test("COREPRODUC-659: an effect run shows the bar under Generate", async ({ page }) => {
    let release = () => {};
    const held = new Promise<void>((done) => (release = done));
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await held;
      await route.continue();
    });
    await boot(page);
    await page.locator(`nav button[aria-label="Image"]`).hover();
    await page.getByRole("button", { name: "Upscale Still" }).first().click();
    const shell = page.getByTestId("effects-shell");
    await upload(page, shell.locator("input[type=file]").first(), PNG);
    await page.getByTestId("effects-generate").click();
    await expect(page.getByTestId("effects-progress")).toContainText(/left|Almost done/);
    await shell.screenshot({ path: path.join(shots, "effects_progress.png") });
    release();
    await expect(page.getByTestId("effects-progress")).toHaveCount(0);
  });

  test("COREPRODUC-665: a canvas result stays after a reload and after later runs elsewhere", async ({ page }) => {
    await boot(page);
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await page.locator('[data-start="t2v"]').click();
    const gen = page.locator(".node[data-id]").first();
    await gen.locator("[data-node-prompt]").fill("a kite over the sea");
    await gen.getByTestId("node-run").click();
    await expect(gen.locator(".thumb video")).toHaveCount(1, { timeout: 30_000 });
    // Leave the canvas: three stills on Image push the canvas run out of the newest three runs.
    await openPage(page, "Image");
    for (const n of [1, 2, 3]) {
      await page.getByTestId("image-prompt").fill(`still ${n}`);
      const done = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "POST");
      await page.getByTestId("image-generate").click();
      await done;
      await expect(page.getByTestId("image-generate")).toBeEnabled();
    }
    // Come back after the Studio reloads (another app.tryvinci.com page, then back to Studio).
    const booted = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "GET");
    await page.reload();
    await booted;
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await expect(page.locator(".node[data-id]").first().locator(".thumb video")).toHaveCount(1);
  });

  test("COREPRODUC-665: a canvas run still going at a reload shows its bar, then its result", async ({ page }) => {
    let release = () => {};
    const held = new Promise<void>((done) => (release = done));
    let started = false;
    let released = false;
    // The host answers POST /runs at once and the run keeps going on the server: model that.
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() === "POST") {
        const real = await route.fetch();
        const body = (await real.json()) as { id: string };
        started = true;
        return route.fulfill({ json: { ...body, state: "running", outputs: [], nodes: {} } });
      }
      const body = (await (await route.fetch()).json()) as { runs: { state: string; outputs?: string[]; nodes?: Record<string, unknown> }[] };
      const last = body.runs.at(-1);
      if (started && last && !released) Object.assign(last, { state: "running", outputs: [], nodes: Object.fromEntries(Object.keys(last.nodes || {}).map((k) => [k, { state: "running" }])) });
      return route.fulfill({ json: body });
    });
    await page.route("**/vinci-api/runs/*", async (route) => {
      await held;
      return route.continue();
    });
    await boot(page);
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await page.locator('[data-start="t2v"]').click();
    const gen = page.locator(".node[data-id]").first();
    await gen.locator("[data-node-prompt]").fill("a kite over the sea");
    await gen.getByTestId("node-run").click();
    await expect.poll(() => started).toBe(true);
    const booted = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "GET");
    await page.reload();
    await booted;
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    const node = page.locator(".node[data-id]").first();
    await expect(node.getByTestId("node-progress")).toBeVisible(); // the run is still going
    released = true;
    release();
    await expect(node.locator(".thumb video")).toHaveCount(1, { timeout: 15_000 });
    await expect(node.getByTestId("node-progress")).toHaveCount(0);
  });

  test("COREPRODUC-665: a canvas run that ends while you are on Image shows its result back on Canvas", async ({ page }) => {
    let release = () => {};
    const held = new Promise<void>((done) => (release = done));
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() === "POST") await held;
      return route.continue();
    });
    await boot(page);
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await page.locator('[data-start="t2v"]').click();
    await page.locator(".node[data-id]").first().locator("[data-node-prompt]").fill("a kite over the sea");
    const ended = page.waitForResponse((res) => res.url().endsWith("/vinci-api/runs") && res.request().method() === "POST");
    await page.locator(".node[data-id]").first().getByTestId("node-run").click();
    await openPage(page, "Image");
    release();
    await ended; // the run ended while Image was open
    await page.getByRole("button", { name: "Canvas", exact: true }).first().click();
    await expect(page.locator(".node[data-id]").first().locator(".thumb video")).toHaveCount(1);
  });

  test("COREPRODUC-666, 667: one-line model menu; input modes gray out with a reason; References sends no start frame", async ({ page }) => {
    // Rows as the host lists them: an end frame and open references only where the catalog has them.
    await page.route("**/vinci-api/models", async (route) => {
      const body = (await (await route.fetch()).json()) as { models: Record<string, unknown>[] };
      const mp4 = body.models.find((row) => row.id === "mock:mp4:v1") as { constraints?: Record<string, unknown> };
      const like = (id: string, name: string, extra: Record<string, unknown>, tier = "fast") => ({
        ...mp4, id, display_name: name, quality_tier: tier, constraints: { ...mp4.constraints, ...extra },
      });
      body.models.push(
        like("mock:seedance-2.5", "Seedance 2.5", { end_frame: true, max_references: 3, resolutions: ["480p", "1080p"] }, "quality"),
        like("mock:veo-3.1", "Veo 3.1", { end_frame: true, max_references: 0, resolutions: ["720p"] }, "quality"),
        like("mock:kling-2.6", "Kling 2.6 Standard", { end_frame: false, max_references: 0, resolutions: [] }),
        like("mock:wan-2.6", "Wan 2.6", { end_frame: false, max_references: 0 }),
      );
      const png = body.models.find((row) => row.id === "mock:png:v1") as Record<string, unknown>;
      for (const [id, name, tier] of [["mock:seedream", "Seedream 4.5", "quality"], ["mock:nano", "Nano Banana Pro", "quality"], ["mock:flux", "FLUX Dev", "fast"], ["mock:gpt", "GPT Image 1", "fast"]])
        body.models.push({ ...png, id, display_name: name, quality_tier: tier });
      await route.fulfill({ json: body });
    });
    const posted: Record<string, unknown>[] = [];
    await page.route("**/vinci-api/runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      posted.push((route.request().postDataJSON() as { inputs: Record<string, unknown> }).inputs);
      await route.fulfill({ json: { id: "run-refs", state: "completed", outputs: [], nodes: {}, estimate: { total: 0 } } });
    });
    await boot(page);
    await openPage(page, "Image");
    await page.getByTestId("image-model-chip").click();
    const picker = page.getByTestId("image-model-picker");
    await expect(picker.getByTestId("model-menu-group-FLUX")).toBeVisible(); // the same menu on Image
    await expect(picker).toHaveCSS("opacity", "1");
    await page.screenshot({ path: path.join(shots, "model_menu_image.png") });
    await page.keyboard.press("Escape");
    await openPage(page, "Video");
    await page.getByTestId("video-model-chip").click();
    const menu = page.getByTestId("video-preset-overlay");
    await expect(menu.getByRole("searchbox", { name: "Search models" })).toBeFocused();
    await expect(menu.getByText("Featured")).toBeVisible();
    await expect(menu.getByTestId("model-menu-group-Kling")).toBeVisible();
    await expect(menu.getByTestId("video-preset-card").filter({ hasText: "Seedance 2.5" })).toContainText("Refs");
    await expect(menu.locator("video, img")).toHaveCount(0); // no preview cards
    await expect(menu).toHaveCSS("opacity", "1"); // after its fade-in
    await page.screenshot({ path: path.join(shots, "model_menu_video.png") });
    await menu.getByTestId("model-menu-feature-References").click();
    await expect(menu.getByTestId("video-preset-card")).toHaveText([/Seedance 2\.5/]);
    await menu.getByTestId("video-preset-card").first().click();
    await expect(menu).toHaveCount(0);
    // Seedance takes all three modes.
    for (const mode of ["start", "start-end", "refs"]) await expect(page.getByTestId(`video-ref-mode-${mode}`)).toHaveAttribute("aria-disabled", "false");
    await page.getByTestId("video-ref-mode-refs").click();
    await expect(page.getByTestId("video-slot-reference")).toBeVisible();
    await expect(page.getByTestId("video-slot-start")).toHaveCount(0);
    await upload(page, page.getByTestId("video-panel").locator("input[type=file]"), PNG);
    await expect(page.getByTestId("video-ref-reference")).toHaveCSS("opacity", "1");
    await page.screenshot({ path: path.join(shots, "video_ref_modes_refs.png") });
    await page.getByTestId("video-prompt").fill("she walks into the kitchen");
    await page.getByTestId("video-generate").click();
    await expect.poll(() => posted.length).toBe(1);
    expect((posted[0].reference_urls as string[]).length).toBe(1);
    expect(posted[0].image ?? posted[0].first_frame_url).toBeUndefined(); // not a start frame
    // Kling 2.6 takes a start frame only: References moves to Start frame; the others gray out with a reason.
    await page.getByTestId("video-model-chip").click();
    await page.getByTestId("video-preset-card").filter({ hasText: "Kling 2.6" }).click();
    await expect(page.getByTestId("video-ref-mode-start")).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("video-ref-mode-refs")).toHaveAttribute("aria-disabled", "true");
    await page.getByTestId("video-ref-mode-start-end").click({ force: true }); // grayed out (aria-disabled), still says why
    await expect(page.getByTestId("video-ref-note")).toHaveText("Kling 2.6 Standard takes a start frame only, no end frame.");
    await expect(page.getByTestId("video-ref-mode-start")).toHaveAttribute("aria-checked", "true");
    await page.screenshot({ path: path.join(shots, "video_ref_modes_grayed.png") });
    // Start + End on Veo: each slot fills itself.
    await page.getByTestId("video-model-chip").click();
    await page.getByTestId("video-preset-card").filter({ hasText: "Veo 3.1" }).click();
    await page.getByTestId("video-ref-mode-start-end").click();
    await expect(page.getByTestId("video-slot-end")).toBeVisible();
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

