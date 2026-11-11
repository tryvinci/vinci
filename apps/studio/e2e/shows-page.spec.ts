import { expect, test } from "@playwright/test";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const shots = process.env.PLAYWRIGHT_ARTIFACTS || "/opt/cursor/artifacts/playwright";
const SAMPLE = path.resolve(__dirname, "../../../packages/olf/conformance/tidewatch");

/**
 * Shows (OLF movie engine), laid out as the Claude Design editor and keyframes first: open the
 * sample show, open a shot from the storyboard, draw and approve a keyframe at $0 in demo mode,
 * render video from it, check the bible page, then see takes go stale after a bible edit on disk.
 * Each step saves a screenshot for the PR. The console must stay clean throughout.
 */
test.describe("Shows (OLF movie engine)", () => {
  test("storyboard, shot page, bible, stale, shots table", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("response", (res) => {
      if (res.status() >= 400 && res.url().includes("/vinci-api/")) errors.push(`${res.status()} ${res.url()}`);
    });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
      localStorage.removeItem("vinci-shows-recent-v1");
    });
    await page.goto("/");
    // Start each run from the pristine sample: the daemon copies it into its home only once.
    const sample = String((await (await page.request.post("/vinci-api/olf/sample")).json()).path);
    rmSync(sample, { recursive: true, force: true });
    cpSync(SAMPLE, sample, { recursive: true });
    await page.locator('nav button[aria-label="Shows"]').click();
    await expect(page.getByTestId("shows-open")).toContainText("Build the world once. Render every episode.");
    await expect(page.getByTestId("shows-open-sample")).toBeEnabled();
    await page.screenshot({ path: path.join(shots, "shows_open.png") });

    // Storyboard: the show's header sits in the Studio top bar; the cards are for review.
    await page.getByTestId("shows-open-sample").click();
    const crumb = page.locator(".top-crumb");
    await expect(crumb).toContainText("Tidewatch");
    await expect(crumb).toContainText("E02 · The Second Light");
    await expect(page.getByTestId("shot-card")).toHaveCount(3);
    await expect(page.getByTestId("shows-health")).toHaveText("Valid OLF v0.1");
    await expect(page.getByTestId("shows-season").first()).toContainText("Season 1 · First Light");
    await expect(page.getByTestId("shows-stats")).toContainText("Keyframes approved0 / 3");
    await expect(page.getByTestId("shows-scene")).toContainText("Mira Sol (winter, night outfit)");
    await page.screenshot({ path: path.join(shots, "shows_storyboard_new.png") });

    // Shot page: full width (no left panel); keyframes first, so video waits for an approved keyframe.
    const card = page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]');
    await card.click();
    const shot = page.getByTestId("shot-page");
    await expect(page.getByTestId("shows-nav")).toHaveCount(0);
    await expect(shot.getByTestId("render-hint")).toHaveText("Approve a keyframe first: video renders from the chosen keyframe.");
    await expect(shot.getByTestId("render-video")).toBeDisabled();
    await expect(shot.getByTestId("shot-cast")).toContainText("form: winter · from episode");
    await expect(shot.getByTestId("shot-cast")).toContainText("outfit: night · from scene");
    await page.screenshot({ path: path.join(shots, "shows_shot_empty.png") });

    await shot.getByTestId("render-keyframe").click();
    await expect(shot.getByTestId("strip-take")).toHaveCount(1, { timeout: 60_000 });
    await expect(page.getByTestId("shows-notice")).toContainText("Rendered kf1 for e02/s03/sh014");
    const details = shot.getByTestId("take-details");
    await expect(details).toContainText("Provenance · kf1");
    await expect(details).toContainText("QA palette"); // does the render keep the forms' colors?
    await details.getByRole("button", { name: "Approve" }).click(); // approving also chooses it
    await expect(shot.locator('[data-take="e02/s03/sh014/kf1"]')).toHaveClass(/chosen/);
    await expect(shot.getByTestId("render-hint")).toHaveText("Video animates from the chosen keyframe kf1.");
    await expect(shot.getByTestId("render-video")).toHaveText("Render video");
    await expect(shot.getByTestId("video-model")).toContainText("Mock MP4 · $0"); // design: the model menu
    await page.screenshot({ path: path.join(shots, "shows_shot_keyframe.png") });

    // A take picked in the strip gives way to the render's new take (live test, COREPRODUC-558).
    await shot.locator('[data-take="e02/s03/sh014/kf1"]').click();
    await shot.getByTestId("render-video").click();
    await expect(shot.getByTestId("strip-take")).toHaveCount(2, { timeout: 60_000 });
    await expect(page.getByTestId("shows-notice")).toContainText("Rendered v1 for e02/s03/sh014");
    await expect(details).toContainText("Provenance · v1");
    await expect(details).toContainText("From keyframe");
    await expect(shot.getByTestId("play-bar")).toBeVisible(); // the design's play bar, not native controls
    await details.getByRole("button", { name: "Approve" }).click();
    await expect(details.getByRole("button", { name: "Approved" })).toHaveAttribute("aria-pressed", "true");
    await expect(shot.getByTestId("render-video")).toHaveText("Re-render video");
    await page.screenshot({ path: path.join(shots, "shows_shot_video.png") });
    await shot.getByTestId("engine-details").locator("summary").click();
    await expect(shot.locator('[data-testid="engine-details"] .ref-row .ref-thumb')).toHaveCount(4);
    await page.locator(".shows-main").evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await page.screenshot({ path: path.join(shots, "shows_shot_engine.png") });

    await page.getByRole("button", { name: "‹ Storyboard" }).click();
    await expect(page.getByTestId("shows-stats")).toContainText("Keyframes approved1 / 3");
    const download = page.waitForEvent("download");
    await page.getByTestId("share").click(); // design: Share, the show folder as one .olf.zip
    expect((await download).suggestedFilename()).toBe("tidewatch.olf.zip");
    await expect(card).toContainText("kf1 · v1 approved");
    await page.screenshot({ path: path.join(shots, "shows_storyboard_approved.png") });

    // Bible: the character page shows its sheet, forms, links, license and edit impact.
    await page.getByTestId("shows-section-bible").click();
    const entry = page.locator('[data-testid="shows-entry"][data-entry="char/mira"]');
    await expect(entry.getByTestId("sheet-view")).toBeVisible();
    await expect(entry).toContainText("The whole sheet is the character reference."); // no crops
    await expect(entry.locator(".olf-ref-grid img.ref-thumb")).toHaveCount(2); // eyes and a texture: separate files
    const loaded = () => entry.locator(".olf-ref-grid img").evaluateAll((imgs) => imgs.every((img) => (img as HTMLImageElement).naturalWidth > 0));
    await expect.poll(loaded).toBe(true); // the daemon serves each separate detail file
    await expect(entry.getByTestId("entry-form")).toHaveCount(2);
    await expect(entry.getByTestId("entry-usage")).toHaveText("Used in 2 shots · 1 episode");
    await expect(entry.getByTestId("entry-impact")).toContainText("makes 2 takes stale");
    await expect(page.locator(".top-file")).toHaveText("bible/characters/mira/mira.yaml");
    await page.screenshot({ path: path.join(shots, "shows_bible_character.png") });

    // A bible edit on disk makes every take that shows Mira stale; select never does.
    const mira = path.join(sample, "bible/characters/mira/mira.yaml");
    writeFileSync(mira, readFileSync(mira, "utf8").replace("large tail.", "large white tail."));
    await page.getByRole("button", { name: "Reload" }).click();
    await page.getByTestId("shows-section-storyboard").click();
    await expect(card).toHaveAttribute("data-state", "stale");
    await expect(page.getByTestId("shows-stats")).toContainText("Stale takes2");
    await page.screenshot({ path: path.join(shots, "shows_storyboard_stale.png") });
    await card.click();
    // The banner says what changed (the take keeps its inputs view); See change shows the values.
    const banner = shot.getByTestId("stale-banner");
    await expect(banner).toContainText("Stale: char/mira (description) changed after v1 was rendered. Also stale: kf1.");
    await shot.getByTestId("see-change").click();
    await expect(shot.getByTestId("stale-diff")).toContainText("large white tail.");
    await expect(shot.getByTestId("render-box")).toContainText("kf1 is stale");
    await page.screenshot({ path: path.join(shots, "shows_shot_stale.png") });

    await page.getByRole("button", { name: "‹ Storyboard" }).click();
    await page.getByTestId("shows-section-shots").click();
    await expect(page.getByTestId("shots-row")).toHaveCount(3);
    await expect(page.getByTestId("shots-row").first()).toContainText("kf1 · v1 approved");
    await page.screenshot({ path: path.join(shots, "shows_shots_table.png") });

    // Cut and export (design screen 4): full width, the sections become tabs in the top bar.
    await page.getByTestId("shows-section-cut").click();
    await expect(page.getByTestId("shows-nav")).toHaveCount(0);
    await expect(page.getByTestId("shows-tab-cut")).toHaveClass(/on/);
    await expect(page.locator(".top-file")).toHaveText("episodes/e02/episode.yaml · cut");
    await expect(page.getByTestId("cut-empty")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "shows_cut_empty.png") });
    await page.getByTestId("cut-use-approved").click();
    await expect(page.getByTestId("cut-clip")).toHaveCount(1); // only sh014 has approved takes
    await expect(page.getByTestId("cut-clip")).toContainText("v1 · stale"); // stale since the bible edit
    await expect(page.getByTestId("cut-stale")).toContainText("1 clip in this cut is stale");
    await expect(page.getByTestId("cut-time")).toHaveText("0:00.0 / 0:04.0");
    await page.getByTestId("cut-out").fill("3");
    await page.getByTestId("cut-out").press("Enter");
    await expect(page.getByTestId("cut-time")).toHaveText("0:00.0 / 0:03.0");
    await page.getByTestId("cut-play").click();
    await expect(page.getByTestId("cut-time")).not.toHaveText("0:00.0 / 0:03.0"); // the clock runs
    await page.getByTestId("cut-play").click();
    await expect(page.getByTestId("cut-preview")).toContainText("You kept the key?"); // the subtitle line
    await page.screenshot({ path: path.join(shots, "shows_cut.png") });
    await page.getByTestId("cut-export-button").click();
    const files = page.getByTestId("cut-export-files");
    await expect(files).toContainText("exports/e02/e02-16x9.mp4", { timeout: 90_000 });
    await expect(files).toContainText("exports/e02/e02-9x16.mp4");
    await expect(page.getByTestId("shows-notice")).toContainText("Exported 3 files for e02");
    await page.screenshot({ path: path.join(shots, "shows_cut_exported.png") });
    // Sound off: no audio stream, and the lines are only subtitles that name the speaker.
    await page.getByTestId("cut-sound").uncheck();
    await page.getByTestId("cut-export-button").click();
    await expect(page.getByTestId("shows-notice")).toContainText("Exported 3 files for e02", { timeout: 90_000 });
    expect(errors).toEqual([]);
  });

  test("variations, dialogue and batch renders", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("response", (res) => {
      if (res.status() >= 400 && res.url().includes("/vinci-api/")) errors.push(`${res.status()} ${res.url()}`);
    });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
      localStorage.removeItem("vinci-shows-recent-v1");
    });
    await page.goto("/");
    const sample = String((await (await page.request.post("/vinci-api/olf/sample")).json()).path);
    rmSync(sample, { recursive: true, force: true });
    cpSync(SAMPLE, sample, { recursive: true });
    await page.locator('nav button[aria-label="Shows"]').click();
    await page.getByTestId("shows-open-sample").click();

    // Nothing is rendered yet, so both batches have no jobs.
    await expect(page.getByTestId("batch-stale")).toHaveText("Re-render 0 stale");
    await expect(page.getByTestId("batch-stale")).toBeDisabled();
    await expect(page.getByTestId("batch-animate")).toHaveText("Animate approved · est. $0");
    await expect(page.getByTestId("batch-animate")).toBeDisabled();

    // Variations: one render draws two keyframes, each its own take.
    await page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]').click();
    const shot = page.getByTestId("shot-page");
    await shot.getByTestId("draws-2").click();
    await expect(shot.getByTestId("render-keyframe")).toHaveText("2 new keyframes");
    await shot.getByTestId("render-keyframe").click();
    await expect(shot.getByTestId("strip-take")).toHaveCount(2, { timeout: 60_000 });
    await expect(page.getByTestId("shows-notice")).toContainText("Rendered kf1 and kf2 for e02/s03/sh014");
    await page.screenshot({ path: path.join(shots, "shows_shot_variations.png") });
    await shot.locator('[data-take="e02/s03/sh014/kf1"]').click();
    const details = shot.getByTestId("take-details");
    await expect(details).toContainText("Provenance · kf1");
    await details.getByRole("button", { name: "Approve" }).click();
    await expect(shot.locator('[data-take="e02/s03/sh014/kf1"]')).toHaveClass(/chosen/);

    // Dialogue: each line in its speaker's voice, as one audio take that plays over the picture.
    await expect(shot.getByTestId("dialogue-plan")).toContainText("mock:wav:v1 · $0");
    await shot.getByTestId("render-audio").click();
    await expect(shot.getByTestId("strip-take")).toHaveCount(3, { timeout: 60_000 });
    await expect(page.getByTestId("shows-notice")).toContainText("Rendered a1 for e02/s03/sh014");
    await shot.locator('[data-take="e02/s03/sh014/a1"]').click();
    await expect(details).toContainText("Provenance · a1");
    await expect(details).toContainText("mock:wav:v1");
    await expect(shot.getByTestId("take-audio")).toHaveAttribute("src", /a1\.wav/);
    await details.getByRole("button", { name: "Approve" }).click(); // chooses it: select.audio
    await expect(shot.locator('[data-take="e02/s03/sh014/a1"]')).toHaveClass(/chosen/);
    await expect(shot.getByTestId("render-audio")).toHaveText("Re-render dialogue");
    await page.screenshot({ path: path.join(shots, "shows_shot_dialogue.png") });

    // Animate approved: one request renders a video from each approved keyframe.
    await page.getByRole("button", { name: "‹ Storyboard" }).click();
    await expect(page.getByTestId("batch-animate")).toBeEnabled();
    await expect(page.getByTestId("batch-animate")).toHaveAttribute("title", "e02/s03/sh014 video: animate kf1");
    await page.screenshot({ path: path.join(shots, "shows_storyboard_batch.png") });
    await page.getByTestId("batch-animate").click();
    await expect(page.getByTestId("shows-notice")).toContainText("Rendered v1 for e02 · $0", { timeout: 60_000 });
    await expect(page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]')).toContainText("kf1 · v1");
    await expect(page.getByTestId("batch-animate")).toBeDisabled(); // v1 is a fresh video from kf1

    // A script edit on disk: the keyframe and the dialogue re-render; the video waits for a new keyframe.
    const scene = path.join(sample, "episodes/e02/scenes/s03.yaml");
    writeFileSync(
      scene,
      readFileSync(scene, "utf8").replace("toward the door.", "toward the open door.").replace('"You kept the key?"', '"You kept it?"'),
    );
    await page.getByRole("button", { name: "Reload" }).click();
    await expect(page.getByTestId("batch-stale")).toHaveText("Re-render 2 stale");
    await page.screenshot({ path: path.join(shots, "shows_storyboard_stale_batch.png") });
    await page.getByTestId("batch-stale").click();
    await expect(page.getByTestId("shows-notice")).toContainText("Rendered kf3 and a2 for e02 · $0", { timeout: 60_000 });
    await expect(page.getByTestId("batch-stale")).toHaveText("Re-render 0 stale");

    // Keep a stale take on purpose: the banner says what changed, and Keep makes the take fresh.
    await page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]').click();
    await expect(page.getByTestId("stale-banner")).toContainText("Stale: the shot's description and 1 more changed after v1 was rendered.");
    await page.getByTestId("see-change").click();
    await expect(page.getByTestId("stale-diff")).toContainText("toward the open door.");
    await page.screenshot({ path: path.join(shots, "shows_shot_stale_cause.png") });
    await page.getByTestId("keep-take").click();
    await expect(page.getByTestId("shows-notice")).toContainText("Kept v1");
    await expect(page.locator('[data-take="e02/s03/sh014/v1"]')).not.toHaveClass(/is-stale/);
    await page.getByRole("button", { name: "‹ Storyboard" }).click();

    // A second clip for the Cut: an approved keyframe of sh015 (set up through the API).
    const drawn = await page.request.post("/vinci-api/olf/render", { data: { path: sample, shot: "e02/s03/sh015", kind: "keyframe" } });
    expect(drawn.ok()).toBe(true);
    await page.request.patch("/vinci-api/olf/take", { data: { path: sample, take: "e02/s03/sh015/kf1", status: "approved" } });

    // Cut: "use approved takes" plays the approved, chosen dialogue (a1) as separate sound.
    await page.getByTestId("shows-section-cut").click();
    await page.getByTestId("cut-use-approved").click();
    await expect(page.getByTestId("cut-clip")).toHaveCount(2); // stills: no video is approved
    // A fade: the preview draws the second clip over the first, as the export does (COREPRODUC-542).
    await page.getByTestId("cut-clip").nth(1).click();
    await page.getByTestId("cut-transition-fade").click();
    await expect(page.getByTestId("cut-time")).toHaveText(/\/ 0:06\.0$/); // 4 s + 2.5 s - a 0.5 s overlap
    const ruler = await page.locator(".olf-ruler").boundingBox();
    if (!ruler) throw new Error("no ruler");
    await page.mouse.click(ruler.x + ruler.width * (3.75 / 6), ruler.y + ruler.height / 2);
    await expect(page.getByTestId("cut-preview")).toHaveAttribute("data-fade", /^0\.[3-7]\d$/);
    await page.screenshot({ path: path.join(shots, "shows_cut_fade.png") });
    await page.getByTestId("cut-clip").first().click();
    await expect(page.getByTestId("cut-dialogue")).toHaveText("a1 · Mira Sol · stale"); // a1 speaks the old line
    await expect(page.getByTestId("cut-audio")).toHaveValue("separate");
    await expect(page.getByTestId("cut-dialogue-audio")).toHaveAttribute("src", /a1\.wav/);
    await page.screenshot({ path: path.join(shots, "shows_cut_dialogue.png") });
    // Add music cue (COREPRODUC-551): a $0 demo cue at the playhead, then it plays in the export.
    await page.mouse.click(ruler.x + ruler.width * (1 / 6), ruler.y + ruler.height / 2);
    await page.getByTestId("cut-add-cue").click();
    await page.getByLabel("Cue description").fill("Slow piano, distant waves");
    await page.getByLabel("Cue length").fill("4");
    await page.getByTestId("cut-cue-add").click();
    await expect(page.getByTestId("shows-notice")).toContainText("Added e02/cue/slow-piano-distant at 0:01");
    await expect(page.getByTestId("cut-cue")).toHaveText("Slow piano, distant waves · a1 · vol 0.6 · ducked");
    await expect(page.getByTestId("cut-cue-audio")).toHaveAttribute("src", /slow-piano-distant%2Fa1\.wav/);
    await page.screenshot({ path: path.join(shots, "shows_cut_music.png") });
    // Also export OTIO and stems (COREPRODUC-544); C2PA signs when the daemon has c2pa-python.
    await page.getByTestId("cut-otio").check();
    await page.getByTestId("cut-export-button").click();
    const exported = page.getByTestId("cut-export-files");
    await expect(exported).toContainText("exports/e02/e02-16x9.mp4", { timeout: 90_000 });
    await expect(exported).toContainText("exports/e02/e02.otio");
    await expect(exported).toContainText("exports/e02/stems/e02-music.wav");
    await page.screenshot({ path: path.join(shots, "shows_cut_export_otio.png") });
    expect(errors).toEqual([]);
  });

  test("authoring: shot fields, new shots, scenes and episodes, sheet, form", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("response", (res) => {
      if (res.status() >= 400 && res.url().includes("/vinci-api/")) errors.push(`${res.status()} ${res.url()}`);
    });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
      localStorage.removeItem("vinci-shows-recent-v1");
    });
    await page.goto("/");
    const sample = String((await (await page.request.post("/vinci-api/olf/sample")).json()).path);
    rmSync(sample, { recursive: true, force: true });
    cpSync(SAMPLE, sample, { recursive: true });
    await page.locator('nav button[aria-label="Shows"]').click();
    await page.getByTestId("shows-open-sample").click();

    // + Add shot: a dashed card at the end of the scene opens a short form.
    await page.getByTestId("add-shot").first().click();
    const form = page.getByTestId("add-shot-form");
    await form.getByLabel("Shot description").fill("The door swings shut behind her.");
    await form.getByLabel("Length in seconds").fill("2.5");
    await form.locator("select").selectOption("wide");
    await page.screenshot({ path: path.join(shots, "shows_add_shot.png") });
    await form.getByRole("button", { name: "Add shot" }).click();
    await expect(page.getByTestId("shows-notice")).toContainText("Added sh020 to e02/s03");
    await expect(page.getByTestId("shot-card")).toHaveCount(4);

    // Shot fields: a select or the description writes one line of the scene file.
    await page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]').click();
    const shot = page.getByTestId("shot-page");
    await shot.getByTestId("shot-framing").selectOption("medium_close");
    await expect(shot.getByTestId("shot-framing")).toHaveValue("medium_close");
    await shot.getByTestId("shot-description").fill("Mira looks up: the door is open.");
    await shot.getByTestId("shot-description").blur();
    const scene = path.join(sample, "episodes/e02/scenes/s03.yaml");
    await expect.poll(() => readFileSync(scene, "utf8")).toContain('description: "Mira looks up: the door is open."');
    expect(readFileSync(scene, "utf8")).toContain("camera: { framing: medium_close, angle: eye_level, lens: 50mm, move: push_in }");
    await page.screenshot({ path: path.join(shots, "shows_shot_fields.png") });

    // + New episode, then its first scene and shot.
    await page.getByRole("button", { name: "‹ Storyboard" }).click();
    await page.getByTestId("new-episode").click();
    await page.getByLabel("Episode title").fill("The Third Light");
    await page.getByLabel("Episode title").press("Enter");
    await expect(page.locator(".top-crumb")).toContainText("E03 · The Third Light");
    await expect(page.getByTestId("add-scene-form")).toContainText("This episode has no scenes yet");
    await page.getByLabel("Scene heading").fill("EXT. CLIFF PATH - DUSK");
    await page.getByRole("button", { name: "Add scene" }).click();
    await expect(page.getByTestId("shows-scene")).toContainText("EXT. CLIFF PATH - DUSK");
    await page.getByTestId("add-shot").click();
    await page.getByTestId("add-shot-form").getByLabel("Shot description").fill("Mira climbs toward the lighthouse.");
    await page.getByTestId("add-shot-form").getByRole("button", { name: "Add shot" }).click();
    await expect(page.getByTestId("shot-card")).toHaveCount(1);
    await expect(page.getByTestId("shows-health")).toHaveText("Valid OLF v0.1");
    await page.screenshot({ path: path.join(shots, "shows_new_episode.png") });

    // Bible: Replace sheet keeps the file name (the character file does not change); + Form adds a look.
    await page.getByTestId("shows-section-bible").click();
    const sheet = page.locator('[data-testid="shows-entry"] .sheet-view img').first();
    const before = await sheet.getAttribute("src");
    await page.getByTestId("replace-sheet").locator("input[type=file]").setInputFiles(path.join(SAMPLE, "bible/characters/mira/forms/ember/front.png"));
    await expect(page.getByTestId("shows-notice")).toContainText("Replaced sheet.png. Takes that used the old sheet are stale.");
    await expect.poll(() => sheet.getAttribute("src")).not.toBe(before); // a new hash: the browser loads the new image
    await page.getByTestId("add-form").click();
    const panel = page.getByTestId("add-form-panel");
    await panel.getByLabel("Form name").fill("storm");
    await panel.getByLabel("Form description").fill("Grey hair, rain-dark tail.");
    await panel.getByLabel("Palette colors").fill("#555566, #223344");
    await panel.locator("input[type=file]").setInputFiles(path.join(SAMPLE, "bible/props/brass-key/ref.png"));
    await expect(panel).toContainText("Front view picked");
    await panel.getByRole("button", { name: "Add form" }).click();
    await expect(page.getByTestId("entry-form")).toHaveCount(3);
    await page.screenshot({ path: path.join(shots, "shows_bible_authoring.png") });

    // + Sheet: a second whole sheet gets its own tab; Replace sheet acts on the sheet shown.
    await page.getByTestId("add-sheet").locator("input[type=file]").setInputFiles(path.join(SAMPLE, "bible/locations/lighthouse/establishing.png"));
    await expect(page.getByTestId("sheet-tab")).toHaveCount(2);
    await expect(page.getByRole("tab", { name: "sheet-2.png" })).toHaveAttribute("aria-selected", "true");
    expect(readFileSync(path.join(sample, "bible/characters/mira/mira.yaml"), "utf8")).toContain("\nsheets: [sheet-2.png]\n");
    await page.getByTestId("replace-sheet").locator("input[type=file]").setInputFiles(path.join(SAMPLE, "bible/props/brass-key/ref.png"));
    await expect(page.getByTestId("shows-notice")).toContainText("Replaced sheet-2.png");
    await expect(page.getByTestId("add-region")).toHaveCount(0); // regions were dropped on 2026-11-09
    await page.screenshot({ path: path.join(shots, "shows_bible_sheets.png") });
    // Clone from sample (COREPRODUC-559): nothing is sent without a recording and consent.
    await page.getByTestId("voice-clone-open").click();
    const clone = page.getByTestId("voice-clone");
    await expect(clone.getByRole("textbox", { name: "Voice name" })).toHaveValue("Mira Sol's voice");
    await expect(clone.getByTestId("voice-clone-run")).toBeDisabled();
    const wav = Buffer.concat([Buffer.from("RIFF"), Buffer.alloc(60)]);
    await clone.locator("input[type=file]").setInputFiles({ name: "mira.wav", mimeType: "audio/wav", buffer: wav });
    await expect(clone).toContainText("mira.wav");
    await expect(clone.getByTestId("voice-clone-run")).toBeDisabled(); // no consent yet
    await clone.getByTestId("voice-clone-consent").check();
    await page.screenshot({ path: path.join(shots, "shows_voice_clone.png") });
    // Cancel drops the recording and the tick: reopened, the form asks for both again (review of #528).
    await clone.getByTestId("voice-clone-cancel").click();
    await page.getByTestId("voice-clone-open").click();
    await expect(clone).toContainText("Pick a recording (MP3, WAV, OGG or FLAC)");
    await expect(clone.getByTestId("voice-clone-consent")).not.toBeChecked();
    await expect(clone.getByTestId("voice-clone-run")).toBeDisabled();
    await page.screenshot({ path: path.join(shots, "shows_voice_clone_reopened.png") });
    await clone.locator("input[type=file]").setInputFiles({ name: "mira.wav", mimeType: "audio/wav", buffer: wav });
    await clone.getByTestId("voice-clone-consent").check();
    await clone.getByTestId("voice-clone-run").click();
    await expect(page.getByTestId("shows-notice")).toContainText("connect ElevenLabs to clone a voice"); // demo mode
    // That 400 is expected: its response and the browser's console line are the only errors.
    expect(errors.filter((line) => !/voice\/clone|status of 400/.test(line))).toEqual([]);
  });

  test("new show wizard and shot list from script", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
      localStorage.removeItem("vinci-shows-recent-v1");
    });
    await page.goto("/");
    await page.locator('nav button[aria-label="Shows"]').click();
    await page.getByTestId("shows-new").click();
    // Step 1, the show; step 2, the first character with its whole sheet.
    await page.getByTestId("setup-title").fill("Lamp Oil");
    await page.getByRole("radio", { name: "16:9" }).click();
    await page.getByTestId("setup-next").click();
    await page.getByTestId("setup-char-name").fill("Mira Sol");
    await page.getByLabel("Character description").fill("Lighthouse keeper and fox spirit.");
    await page.getByTestId("setup-sheet").locator("input[type=file]").setInputFiles(path.join(SAMPLE, "bible/characters/mira/sheet.png"));
    await expect(page.getByTestId("setup-sheet")).toContainText("Sheet picked");
    await expect(page.getByTestId("setup-voice")).toHaveText("Connect ElevenLabs to pick a voice. Demo speech has one voice.");
    await page.getByTestId("setup-next").click();
    // Step 3: Draft from idea on the demo text model, then the design's script and its shot list.
    await page.getByTestId("draft-idea").click();
    await page.getByLabel("Idea").fill("A fox spirit keeps the last lighthouse.");
    await page.getByRole("button", { name: "Draft", exact: true }).click();
    await expect(page.getByTestId("script-text")).toHaveValue(/EXT\. OPENING - DAY/);
    await expect(page.getByTestId("script-shot")).toHaveCount(2); // the preview is back
    // An agent CLI as the text model: e2e/fake-cli/claude stands in for Claude Code. It asks first.
    const menu = page.getByTestId("text-model");
    await expect(menu).toHaveValue("");
    await expect(menu.locator("option:checked")).toHaveText("Auto · Mock text");
    await menu.selectOption("claude_code:cli");
    await expect(menu.locator("option:checked")).toHaveText("Claude Code · your plan");
    await page.getByTestId("draft-idea").click();
    await page.getByLabel("Idea").fill("A fox spirit keeps the last lighthouse.");
    await page.getByRole("button", { name: "Draft", exact: true }).click();
    const ask = page.getByRole("alertdialog", { name: "Confirm spend" });
    await expect(ask).toContainText(
      "Write a draft with Claude Code? It runs on your own Claude Code sign-in and bills that account. Vinci adds no charge.",
    );
    await page.screenshot({ path: path.join(shots, "shows_text_model_cli.png") });
    await ask.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByTestId("script-text")).toHaveValue(/^EXT\. HARBOR - NIGHT\n\nA fox spirit keeps the last lighthouse\./);
    await expect(page.getByTestId("script-found")).toHaveText("1 scene · 1 character found");
    await menu.selectOption(""); // back to Auto (the demo text model) for the rest of the test
    const script = [
      "EXT. CLIFF PATH - DUSK",
      "Mira climbs toward the lighthouse. She stops and looks back\nat the village lights.",
      "INT. LAMP ROOM - NIGHT",
      "The brass lamp turns. A brass key, wrapped in cloth.",
      "MIRA\n(whisper)\nYou kept the key?",
    ].join("\n\n");
    await page.getByTestId("script-text").fill(script);
    await expect(page.getByTestId("script-shot")).toHaveCount(5);
    await expect(page.getByTestId("script-found")).toHaveText("2 scenes · 1 character found");
    await expect(page.getByTestId("script-box")).toContainText("Mira → char/mira");
    await expect(page.getByTestId("shows-setup")).toContainText("Mira whispers. “You kept the key?”"); // the line is not in the picture prompt
    await expect(page.getByTestId("script-new")).toContainText("New locations found: Cliff path and Lamp room.");
    await expect(page.getByTestId("shows-setup")).toContainText("2 keyframe options per shot · est. $0");
    await page.screenshot({ path: path.join(shots, "shows_new_show.png") });
    // Split with a model: the demo text model answers with tagged shots, parsed the same way.
    await page.getByTestId("split-model").click();
    await expect(page.getByTestId("script-text")).toHaveValue(/\[WS 24mm 2\.5s\] Mira climbs/);
    await expect(page.getByTestId("script-shot")).toHaveCount(5);
    await page.getByTestId("setup-create").click();
    await expect(page.getByTestId("shows-notice")).toContainText("Created Lamp Oil and drew 10 keyframes · $0");
    await expect(page.getByTestId("shot-card")).toHaveCount(5);
    await expect(page.getByTestId("shows-health")).toHaveText("Valid OLF v0.1");
    await page.screenshot({ path: path.join(shots, "shows_new_show_storyboard.png") });
    // Storyboard: Shot list from script adds a scene and its shots to the episode.
    await page.getByTestId("script-open").click();
    const panel = page.getByTestId("script-import");
    await panel.getByTestId("script-text").fill("INT. HALL - DAY\n\nRain falls on the glass.\n");
    await expect(panel.getByTestId("script-shot")).toHaveCount(1);
    await page.screenshot({ path: path.join(shots, "shows_script_import.png") });
    await page.getByTestId("script-add").click();
    await expect(page.getByTestId("shows-notice")).toContainText("Added e01/s03 to E01");
    await expect(page.getByTestId("shot-card")).toHaveCount(6);
    // The wizard's character has no forms yet: its bible page offers + Form (it crashed before, #525).
    await page.getByTestId("shows-section-bible").click();
    const made = page.locator('[data-testid="shows-entry"][data-entry="char/mira"]');
    await expect(made.getByTestId("add-form")).toBeVisible();
    await expect(made.getByTestId("entry-form")).toHaveCount(0);
    const art = made.getByTestId("sheet-view").locator("img");
    await expect.poll(() => art.evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0); // the sheet the wizard saved
    await page.screenshot({ path: path.join(shots, "shows_bible_new_character.png") });
    expect(errors).toEqual([]);
  });

  test("camerawork: a template, an engine move at $0, the bible page, a stale template", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("response", (res) => {
      if (res.status() >= 400 && res.url().includes("/vinci-api/")) errors.push(`${res.status()} ${res.url()}`);
    });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
      localStorage.removeItem("vinci-shows-recent-v1");
    });
    await page.goto("/");
    const sample = String((await (await page.request.post("/vinci-api/olf/sample")).json()).path);
    rmSync(sample, { recursive: true, force: true });
    cpSync(SAMPLE, sample, { recursive: true });
    await page.locator('nav button[aria-label="Shows"]').click();
    await page.getByTestId("shows-open-sample").click();

    // Lengths show as seconds+frames (24 frames a second), the notation of storyboards.
    const card = page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]');
    await expect(card).toContainText("4+00");
    await expect(page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh015"]')).toContainText("2+12");
    await card.click();
    const shot = page.getByTestId("shot-page");
    await shot.getByTestId("render-keyframe").click();
    await expect(shot.getByTestId("strip-take")).toHaveCount(1, { timeout: 60_000 });
    await shot.getByTestId("take-details").getByRole("button", { name: "Approve" }).click();
    await expect(shot.locator('[data-take="e02/s03/sh014/kf1"]')).toHaveClass(/chosen/); // approving also chooses it
    await expect(shot.getByTestId("video-model")).toContainText("Mock MP4 · $0"); // a model shot so far

    // The Camerawork menu: the show's own templates, then the library by family.
    const menu = shot.getByTestId("shot-camerawork");
    await expect(menu.locator('optgroup[label="In this show"] option')).toHaveText(["Slow push on an object · T.U. (jiwa) · Model · 2+00"]);
    await expect(menu.locator('optgroup[label="Library · Push"] option')).toHaveCount(5);
    await expect(menu.locator('option[value="anime/tu-to-eyes"]')).toHaveText("Track up to the eyes · T.U. · Engine $0 · 3+00");
    await page.screenshot({ path: path.join(shots, "shows_camerawork_before.png") });

    // A pick copies the template into the bible and fills the camera, the length and the render.
    await menu.selectOption("anime/tu-to-eyes");
    await expect(menu).toHaveValue("cam/tu-to-eyes");
    await expect(shot.getByTestId("camerawork-intent")).toContainText("Push from a close-up to the eyes for a realization or a decision.");
    await expect(shot.getByTestId("shot-length")).toHaveValue("3+00");
    await expect(shot.getByTestId("shot-move")).toHaveValue("push_in");
    await expect(shot.getByTestId("shot-render")).toHaveValue("engine");
    await expect(shot.getByTestId("shot-amount")).toHaveValue("0.35");
    await expect(shot.locator(".olf-field", { hasText: "Amount · template" })).toHaveCount(1); // the template fills it
    await expect(shot.getByTestId("engine-move")).toContainText("Engine move · $0. The frame moves over the chosen keyframe. No video model runs.");
    await expect(shot.getByTestId("video-model")).toHaveCount(0);
    await expect(shot.getByTestId("render-hint")).toHaveText("The engine moves the chosen keyframe kf1.");
    await expect(shot.getByTestId("render-note")).toContainText("this move enlarges it"); // the demo keyframe is small
    await page.screenshot({ path: path.join(shots, "shows_camerawork_engine.png") });

    // Render video: no confirm, no model, $0. The take is a normal video take.
    await shot.getByTestId("render-video").click();
    await expect(shot.getByTestId("strip-take")).toHaveCount(2, { timeout: 60_000 });
    const details = shot.getByTestId("take-details");
    await expect(details).toContainText("Provenance · v1");
    await expect(details).toContainText("local:ffmpeg:v1");
    await expect(details).toContainText("3.000s");
    await expect(shot.getByTestId("play-time")).toContainText("3.0s"); // the player has the take: 3+00
    await page.screenshot({ path: path.join(shots, "shows_camerawork_take.png") });

    // The bible page of the template: what the camera does, what it suits, and who uses it.
    await shot.getByTestId("camerawork-intent").getByRole("button", { name: "cam/tu-to-eyes" }).click();
    const entry = page.getByTestId("shows-entry");
    await expect(entry).toHaveAttribute("data-entry", "cam/tu-to-eyes");
    await expect(entry.locator("h1")).toHaveText("Track up to the eyes");
    await expect(entry.getByTestId("entry-usage")).toHaveText("Used in 1 shot · 1 episode");
    await expect(entry.getByTestId("camerawork-camera")).toContainText("Engine move · $0");
    await expect(entry.getByTestId("camerawork-source")).toContainText("A copy of anime/tu-to-eyes@1 from the camerawork library (CC0).");
    await expect(entry.getByTestId("entry-impact")).toHaveText(
      "Editing the camera, the prompt words or the avoid words makes 1 take stale. Credits and license edits do not.",
    );
    await expect(page.getByTestId("shows-bible-list")).toContainText("Camerawork");
    await expect(page.getByTestId("shows-bible-list")).toContainText("Slow push on an object"); // the sample's own template
    await page.screenshot({ path: path.join(shots, "shows_camerawork_bible.png") });

    // An edit to the template (on disk) makes the video of its shot stale, and the banner names it.
    const file = path.join(sample, "bible/camerawork/tu-to-eyes/tu-to-eyes.yaml");
    writeFileSync(file, readFileSync(file, "utf8").replace("ease: in_out", "ease: out"));
    await page.getByRole("button", { name: "Reload" }).click();
    await page.getByTestId("shows-section-storyboard").click();
    await card.click();
    await expect(shot.getByTestId("stale-banner")).toContainText("Stale: cam/tu-to-eyes (camera.ease) changed after v1 was rendered.");
    await expect(shot.locator('[data-take="e02/s03/sh014/kf1"]')).not.toHaveClass(/is-stale/); // the keyframe stays fresh
    await page.screenshot({ path: path.join(shots, "shows_camerawork_stale.png") });

    // A value typed on the shot wins over the template, and it goes in the shot's own line.
    await shot.getByTestId("shot-amount").fill("0.5");
    await shot.getByTestId("shot-amount").blur();
    await expect(shot.locator(".olf-field", { hasText: "Amount · template" })).toHaveCount(0);
    await expect(shot.getByTestId("shot-amount")).toHaveValue("0.5");
    expect(readFileSync(path.join(sample, "episodes/e02/scenes/s03.yaml"), "utf8")).toContain("template: cam/tu-to-eyes, amount: 0.5 }");

    // A model template on another shot keeps the model menu; its words go to the model.
    await page.locator(".top-shows").getByRole("button", { name: "Next shot" }).click();
    await expect(shot).toHaveAttribute("data-shot", "e02/s03/sh015");
    await shot.getByTestId("shot-camerawork").selectOption("anime/reaction-cu");
    await expect(shot.getByTestId("shot-camerawork")).toHaveValue("cam/reaction-cu");
    await expect(shot.getByTestId("shot-length")).toHaveValue("1+12");
    await expect(shot.getByTestId("video-model")).toContainText("Mock MP4 · $0");
    await page.screenshot({ path: path.join(shots, "shows_camerawork_model.png") });

    // Off again: the menu is blank, and the template's line is gone.
    await shot.getByTestId("shot-camerawork").selectOption("");
    await expect(shot.getByTestId("shot-camerawork")).toHaveValue("");
    await expect(shot.getByTestId("camerawork-intent")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("invalid show, wrong folder, engine off", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
      localStorage.removeItem("vinci-shows-recent-v1");
    });
    // A broken reference: the banner and the issues list explain it, and render stays off.
    const broken = path.join(mkdtempSync(path.join(os.tmpdir(), "olf-e2e-")), "tidewatch");
    cpSync(SAMPLE, broken, { recursive: true });
    const scene = path.join(broken, "episodes/e02/scenes/s03.yaml");
    writeFileSync(scene, readFileSync(scene, "utf8").replace("location: loc/lighthouse", "location: loc/attic"));
    await page.goto("/");
    await page.locator('nav button[aria-label="Shows"]').click();
    await page.getByTestId("shows-path").fill("/no/such/show");
    await page.getByRole("button", { name: "Open folder" }).click();
    await expect(page.getByTestId("shows-error")).toContainText("not an OLF project");
    await page.screenshot({ path: path.join(shots, "shows_wrong_folder.png") });

    await page.getByTestId("shows-path").fill(broken);
    await page.getByRole("button", { name: "Open folder" }).click();
    await expect(page.getByTestId("shows-health")).toHaveText("1 error");
    await expect(page.getByTestId("shows-banner")).toContainText("Render stays off");
    await page.screenshot({ path: path.join(shots, "shows_invalid.png") });
    // A shot that cannot resolve shows the engine's reason; the page asks for no plan (no 4xx/5xx).
    const asked: string[] = [];
    page.on("request", (req) => req.url().includes("/olf/shot") && asked.push(req.url()));
    await page.getByRole("button", { name: "Open shot e02/s03/sh014" }).click();
    await expect(page.getByTestId("render-box")).toContainText("unknown reference loc/attic");
    await expect(page.getByTestId("render-keyframe")).toBeDisabled();
    expect(asked).toEqual([]);
    await page.getByRole("button", { name: "Show issues" }).click();
    await expect(page.getByTestId("shows-issues")).toContainText("unknown reference loc/attic");
    await page.screenshot({ path: path.join(shots, "shows_issues.png") });

    // A daemon without vinci-olf lists no /olf routes: the page says so instead of failing.
    await page.route("**/vinci-api/openapi.json", (route) => route.fulfill({ json: { paths: {} } }));
    await page.reload();
    await page.locator('nav button[aria-label="Shows"]').click();
    await expect(page.getByTestId("shows-off")).toBeVisible();
    await page.screenshot({ path: path.join(shots, "shows_off.png") });
  });

  test("previs: pills for a shot with no keyframe, the e-conte sheet, the animatic, the 180° line", async ({ page }) => {
    test.setTimeout(180_000);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("response", (res) => {
      if (res.status() >= 400 && res.url().includes("/vinci-api/")) errors.push(`${res.status()} ${res.url()}`);
    });
    await page.addInitScript(() => {
      localStorage.setItem("vinci-onboard-v1", "done");
      localStorage.removeItem("vinci-shows-recent-v1");
    });
    await page.goto("/");
    const sample = String((await (await page.request.post("/vinci-api/olf/sample")).json()).path);
    rmSync(sample, { recursive: true, force: true });
    cpSync(SAMPLE, sample, { recursive: true });
    // A second character in the scene (Mira's sheet stands in for his), and on sh015 a layout that
    // puts Mira at the right of Tomas.
    const tomas = path.join(sample, "bible/characters/tomas");
    cpSync(path.join(sample, "bible/characters/mira/sheet.png"), path.join(tomas, "sheet.png"));
    writeFileSync(path.join(tomas, "tomas.yaml"), "id: char/tomas\nname: Tomas Hale\ndescription: A retired keeper.\nsheet: sheet.png\n");
    const scene = path.join(sample, "episodes/e02/scenes/s03.yaml");
    const swapped = "    layout: { start: [{ slot: a, x: 0.7 }, { slot: b, x: 0.3 }] }\n    forms: { char/mira: ember }";
    writeFileSync(
      scene,
      readFileSync(scene, "utf8").replace("characters: [char/mira]", "characters: [char/mira, char/tomas]").replace("    forms: { char/mira: ember }", swapped),
    );
    await page.locator('nav button[aria-label="Shows"]').click();
    await page.getByTestId("shows-open-sample").click();

    // A shot with no keyframe shows pills: who stands where, how large, and where they look.
    const card = page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh015"]');
    await expect(card.getByTestId("pill")).toHaveCount(2);
    await expect(card.locator('[data-testid="pill"][data-slot="a"]')).toHaveAttribute("data-facing", "left"); // she looks at him
    await expect(page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh016"]').getByTestId("pill")).toHaveCount(1); // Tomas: the insert takes Mira out
    await page.screenshot({ path: path.join(shots, "shows_previs_pills.png") });

    // The e-conte sheet: a PDF at $0, linked under the header and served by the daemon.
    await page.getByTestId("previs-sheet").click();
    const files = page.getByTestId("previs-files");
    await expect(files).toContainText("previs/e02/e02-sheet.pdf", { timeout: 60_000 });
    await expect(files.locator("a")).toHaveCount(2); // the PDF and its one PNG page
    const pdf = await page.request.get(String(await files.locator("a").first().getAttribute("href")));
    expect(pdf.status()).toBe(200);
    expect(pdf.headers()["content-type"]).toBe("application/pdf");
    await page.screenshot({ path: path.join(shots, "shows_previs_sheet.png") });

    // The animatic: one MP4 of the episode, from pills here (no shot has a picture yet).
    await page.getByTestId("previs-animatic").click();
    await expect(files).toHaveText("previs/e02/e02-animatic.mp4", { timeout: 90_000 });
    // The mock render: every shot from its pills, no sound, the lines as subtitles.
    await page.getByTestId("previs-mock").click();
    await expect(files).toHaveText("previs/e02/e02-mock.mp4", { timeout: 90_000 });
    await expect(page.getByTestId("shows-notice")).toContainText("Mock render for e02: 3 cuts");

    // A two-shot sets the 180° line: the layout of sh015 crosses it, and its shot page says so.
    await page.locator('[data-testid="shot-card"][data-shot="e02/s03/sh014"]').click();
    const shot = page.getByTestId("shot-page");
    await shot.getByTestId("shot-camerawork").selectOption("anime/two-shot-axis");
    await expect(shot.getByTestId("shot-camerawork")).toHaveValue("cam/two-shot-axis");
    await expect(shot.getByTestId("pill")).toHaveCount(2); // the template's pills: Mira left, Tomas right
    await page.locator(".top-shows").getByRole("button", { name: "Next shot" }).click();
    await expect(shot).toHaveAttribute("data-shot", "e02/s03/sh015");
    await expect(shot.getByTestId("shot-crosses")).toHaveText(
      "Crosses the 180° line: e02/s03/sh014 has Mira Sol at the left of Tomas Hale",
    );
    // Canvas: the shape of a drawing larger than the frame, for a pan or a tilt across it.
    await shot.getByTestId("shot-canvas").selectOption("21:9");
    await expect(shot.getByTestId("shot-canvas")).toHaveValue("21:9");
    expect(readFileSync(scene, "utf8")).toContain('canvas: "21:9"');
    await page.screenshot({ path: path.join(shots, "shows_previs_crosses.png") });
    expect(errors).toEqual([]);
  });

});
