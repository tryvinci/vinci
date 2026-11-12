"""Classification and picker filtering for the Studio capability registry."""

from __future__ import annotations

from ts_module import ROOT, run_ts

MODULE = "apps/studio/lib/model-capabilities.ts"
NAMES = [
    "classifyModel",
    "modelsFor",
    "defaultModelFor",
    "connectedProviderIds",
    "surfaceForPage",
    "withoutMockWhenConnected",
    "tieBreakAvailability",
    "modelsForNodeTypes",
    "isUnpriced",
    "PRICE_VARIES",
    "money",
    "setPriceUnit",
]
STUDIO = ROOT / "apps" / "studio" / "app" / "studio-client.tsx"


def _run(body: str):
    return run_ts(MODULE, NAMES, body)


def test_every_bundled_model_classifies() -> None:
    """Every catalog row gets a function. None of today's rows are text models."""
    script = r"""
const fs = await import("node:fs");
const path = await import("node:path");
const dir = "packages/core/vinci_core/catalogs";
const models = [];
for (const name of fs.readdirSync(dir)) {
  if (!name.endsWith(".json")) continue;
  const doc = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
  for (const row of doc.models) models.push(row);
}
if (models.length < 90) throw new Error("expected the bundled catalogs, got " + models.length);
const providers = new Set(models.map((row) => row.provider));
const expected = [
  "cloudflare", "elevenlabs", "fal", "google", "higgsfield",
  "magnific", "mock", "openai", "wavespeed",
];
for (const id of expected) {
  if (!providers.has(id)) throw new Error("missing provider " + id);
}
const unseen = [];
for (const row of models) {
  const info = classifyModel(row);
  if (!info.functions.length) unseen.push(row.id);
  // Text models are the t2t rows (OLF script drafts, COREPRODUC-548), and only those.
  if (info.functions.includes("text") !== (row.capabilities || []).includes("t2t")) throw new Error("text model drift: " + row.id);
  if (info.id !== row.id) throw new Error("id drift " + row.id);
  const aspects = JSON.stringify(row.constraints?.aspect_ratios || []);
  if (JSON.stringify(info.aspectRatios) !== aspects) throw new Error("aspect drift " + row.id);
  if (JSON.stringify(info.resolutions) !== JSON.stringify(row.constraints?.resolutions || [])) {
    throw new Error("resolution drift " + row.id);
  }
  const again = classifyModel(row);
  if (JSON.stringify(again) !== JSON.stringify(info)) {
    throw new Error("classify is not stable " + row.id);
  }
}
if (unseen.length) throw new Error("unclassified: " + unseen.join(", "));

const byId = Object.fromEntries(models.map((row) => [row.id, classifyModel(row)]));
const flf = models.filter((row) => byId[row.id].inputs.includes("end_frame")).map((row) => row.id);
if (flf.length !== 2 || !flf.every((id) => id.includes("flf"))) {
  throw new Error("end frame: " + flf.join(", "));
}
const masked = models.filter((row) => byId[row.id].inputs.includes("mask"));
if (masked.length) throw new Error("unexpected mask: " + masked.map((row) => row.id).join(", "));

const editOnly = byId["higgsfield:soul-reference:2026-09"];
if (!editOnly.functions.includes("image_edit") || editOnly.functions.includes("image_gen")) {
  throw new Error("soul reference functions " + editOnly.functions.join(","));
}
if (!editOnly.required.includes("references")) throw new Error("soul reference refs");

const upscaler = byId["magnific:upscaler-creative:2026-09"];
if (!upscaler.functions.includes("image_upscale") || upscaler.functions.includes("image_edit")) {
  throw new Error("creative upscaler leaked into edit: " + upscaler.functions.join(","));
}
const videoUp = byId["magnific:video-upscaler-precision:2026-09"];
if (!videoUp.functions.includes("video_upscale") || videoUp.functions.includes("image_upscale")) {
  throw new Error("video upscaler: " + videoUp.functions.join(","));
}
const seedvr = byId["fal:seedvr-upscale:2026-09"];
if (!seedvr.functions.includes("image_upscale")) throw new Error("seedvr still upscaler");

const both = byId["google:veo-3.1-lite:2026-08"];
if (!both.functions.includes("video_t2v") || !both.functions.includes("video_i2v")) {
  throw new Error("veo lite " + both.functions.join(","));
}
if (both.required.includes("start_frame")) throw new Error("t2v+i2v start frame is optional");
if (!both.inputs.includes("start_frame")) throw new Error("veo lite should accept a start frame");

const i2v = byId["fal:kling-2.6-pro-i2v:2026-09"];
if (!i2v.required.includes("start_frame") || !i2v.functions.includes("video_extend")) {
  throw new Error("i2v-only should require a start frame and extend");
}
const r2v = byId["higgsfield:veo-3.1-r2v:2026-09"];
if (!r2v.inputs.includes("references") || !r2v.required.includes("references")) {
  throw new Error("r2v references");
}
const popcorn = byId["higgsfield:popcorn-auto:2026-09"];
if (popcorn.maxReferences !== 8 || !popcorn.inputs.includes("references")) {
  throw new Error("popcorn refs " + popcorn.maxReferences);
}
const edit = byId["fal:nano-banana-pro-edit:2026-09"];
if (edit.maxReferences !== 4) throw new Error("edit max refs");

const talk = byId["wavespeed:infinitetalk:2026-08"];
if (!talk.functions.includes("lipsync") || !talk.required.includes("audio")) {
  throw new Error("infinitetalk audio");
}
const voice = byId["elevenlabs:flash-v2.5:2026-08"];
const ttsOk = voice.functions.includes("audio_tts")
  && !voice.inputs.includes("audio")
  && voice.required.includes("prompt");
if (!ttsOk) throw new Error("tts should take text, not an audio file");
const sts = byId["elevenlabs:speech-to-speech:2026-08"];
if (!sts.required.includes("audio") || sts.inputs.includes("prompt")) throw new Error("sts");
const heard = byId["wavespeed:seedance-2.0-turbo:2026-08"];
if (!heard.generatesAudio) throw new Error("seedance audio unit");
const silent = byId["wavespeed:kling-2.6-pro:2026-08"];
if (silent.generatesAudio) throw new Error("kling is not priced as audio");

const image = byId["openai:gpt-image-2:2026-04"];
const imageOk = !image.functions.includes("text")
  && image.functions.includes("image_gen")
  && image.functions.includes("image_edit");
if (!imageOk) throw new Error("gpt-image " + image.functions.join(","));
const chat = classifyModel({ id: "openai:gpt-4o:2026", provider: "openai", capabilities: [] });
if (!chat.functions.includes("text") || chat.functions.length !== 1) {
  throw new Error("gpt-4o " + chat.functions.join(","));
}
const named = classifyModel({ id: "openai:gpt-image-9", provider: "openai", capabilities: [] });
if (named.functions.includes("text")) throw new Error("gpt-image id is not a chat model");
const flagged = classifyModel({ id: "acme:writer", provider: "acme", capabilities: ["llm"] });
if (!flagged.functions.includes("text")) throw new Error("llm capability");
const inpaint = classifyModel({
  id: "fal:inpaint:2026",
  provider: "fal",
  display_name: "Inpaint",
  capabilities: ["i2i"],
});
if (!inpaint.inputs.includes("mask") || !inpaint.functions.includes("image_edit")) {
  throw new Error("mask");
}
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_models_for_filters_surface_and_provider() -> None:
    """Pickers keep compatible rows from connected providers and a sensible default."""
    script = r"""
const fs = await import("node:fs");
const path = await import("node:path");
const dir = "packages/core/vinci_core/catalogs";
const models = [];
for (const name of fs.readdirSync(dir)) {
  if (!name.endsWith(".json")) continue;
  const doc = JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
  for (const row of doc.models) models.push(row);
}
const before = models.map((row) => row.id).join("|");
const all = [...new Set(models.map((row) => row.provider))];

function ids(surface, providers, options) {
  return modelsFor(surface, providers, models, options).map((row) => row.id);
}
function caps(row) {
  return new Set(row.capabilities || []);
}

const image = modelsFor("image", ["openai", "mock"], models);
if (!image.length) throw new Error("openai image empty");
if (image.some((row) => row.provider !== "openai" && row.provider !== "mock")) {
  throw new Error("image leaked a provider");
}
if (image.some((row) => !caps(row).has("t2i"))) throw new Error("image row without t2i");
if (image.some((row) => row.provider === "higgsfield")) throw new Error("higgsfield without a key");
if (image.at(-1)?.provider !== "mock") throw new Error("mock should sort last");
if (models.map((row) => row.id).join("|") !== before) throw new Error("mutated catalog");

if (modelsFor("image", [], models).length) throw new Error("empty providers should show nothing");
if (modelsFor("nope", all, models).length) throw new Error("unknown surface");
if (modelsFor("effects", all, models).length) throw new Error("effects need a capability");
const effectTts = modelsFor("effects", all, models, { capability: "tts" });
if (!effectTts.length || effectTts.some((row) => !caps(row).has("tts"))) {
  throw new Error("effects tts");
}

const extend = modelsFor("video_extend", ["higgsfield"], models, { requireInputs: ["end_frame"] });
if (extend.length !== 2 || extend.some((row) => !row.id.includes("flf"))) {
  throw new Error("end frame filter " + extend.map((row) => row.id).join(","));
}
const i2vOnly = models.filter((row) => caps(row).has("i2v"));
if (ids("video_extend", all).length !== i2vOnly.length) {
  throw new Error("extend should be every i2v model");
}
const t2i = models.filter((row) => caps(row).has("t2i"));
if (ids("image", all).length !== t2i.length) throw new Error("image count");
const t2t = models.filter((row) => caps(row).has("t2t"));
if (!t2t.length || ids("text", all).length !== t2t.length) throw new Error("text surface lists the t2t models");
// The canvas Assistant ("An LLM that writes text") lists the text models.
if (ids("canvas", all, { capability: "assistant" }).length !== t2t.length) {
  throw new Error("assistant lists the t2t models");
}
const nodeImage = modelsFor("canvas", all, models, { capability: "t2i" });
if (nodeImage.some((row) => !caps(row).has("t2i"))) throw new Error("canvas t2i");
if (!nodeImage.some((row) => caps(row).has("i2i"))) {
  throw new Error("combo image models stay on t2i nodes");
}

const sunset = {
  id: "openai:old:2020",
  provider: "openai",
  capabilities: ["t2i"],
  status: "sunset",
  quality_tier: "quality",
  pricing: { amount: 0, unit: "image" },
};
const deprecated = { ...sunset, id: "openai:old:2021", status: "deprecated" };
const withOld = [...models, sunset, deprecated];
if (modelsFor("image", ["openai"], withOld).some((row) => row.id.startsWith("openai:old"))) {
  throw new Error("sunset should be hidden");
}
const kept = modelsFor("image", ["openai"], withOld, { activeOnly: false });
if (!kept.some((row) => row.status === "sunset")) throw new Error("activeOnly false keeps sunset");

const live = defaultModelFor("image", ["openai", "fal", "mock"], models);
if (!live || live.provider === "mock") throw new Error("default should be a connected provider");
if (live.quality_tier !== "quality") throw new Error("default should be quality when one exists");
const qualityPrices = models
  .filter((row) => (row.provider === "openai" || row.provider === "fal"))
  .filter((row) => caps(row).has("t2i") && row.quality_tier === "quality" && !isUnpriced(row))
  .map((row) => row.pricing.amount);
if (isUnpriced(live) || live.pricing.amount > Math.min(...qualityPrices)) {
  throw new Error("default should be the cheapest priced quality row");
}

const up = defaultModelFor("upscale", all, models);
if (!up || !classifyModel(up).functions.includes("image_upscale")) {
  throw new Error("upscale default is a still");
}
const stillIds = ids("upscale", all);
if (stillIds.includes("mock:mp4:v1")) throw new Error("clip mock on the still upscale page");
if (!stillIds.includes("wavespeed:seedvr2:2026-08")) throw new Error("seedvr2 missing from still");
const clipIds = ids("video_upscale", all);
if (!clipIds.includes("mock:mp4:v1")) throw new Error("mock mp4 should be a clip upscaler");
if (clipIds.includes("wavespeed:seedvr2:2026-08")) throw new Error("still seedvr2 on clip upscale");
const voice = defaultModelFor("speak", all, models);
if (!voice || !classifyModel(voice).functions.includes("audio_tts")) {
  throw new Error("speak default is TTS");
}
const clip = defaultModelFor("video", all, models);
if (!clip || !classifyModel(clip).functions.includes("video_t2v")) {
  throw new Error("video default should run from a prompt");
}
const local = defaultModelFor("video", ["mock"], models);
if (!local || local.provider !== "mock") throw new Error("demo video default is mock");

const idsOpen = connectedProviderIds(undefined);
if (idsOpen.join() !== "mock") throw new Error("loading doctor is mock only");
const saved = connectedProviderIds({
  OpenAI: { configured: true },
  higgsfield: { configured: false, available: false },
  fal: { available: true },
  mock: { configured: false },
});
const connectedOk = saved[0] === "mock" && saved.includes("OpenAI") && saved.includes("fal");
if (!connectedOk || saved.includes("higgsfield")) throw new Error("connected " + saved.join(","));
if (surfaceForPage("image") !== "image" || surfaceForPage("explore") !== "canvas") {
  throw new Error("page surface");
}
if (modelsFor("image", ["OpenAI"], models).some((row) => row.provider !== "openai")) {
  throw new Error("provider match is case-insensitive");
}
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_mock_hides_only_when_a_provider_is_connected() -> None:
    """availabilityRank is a tiebreak after mock, role, quality, and price."""
    script = """
const rows = [
  { id: "slow", provider: "fal", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 2 } },
  { id: "fast", provider: "openai", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 2 } },
  { id: "cheap", provider: "google", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 0.1 } },
  { id: "mock:png:v1", provider: "mock", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 0 } },
];
const listed = modelsFor("image", ["fal", "openai", "google", "mock"], rows);
const hidden = withoutMockWhenConnected(listed, ["openai", "mock"]).map((row) => row.id);
if (hidden.includes("mock:png:v1")) throw new Error("mock leaked: " + hidden);
if (hidden[0] !== "cheap") throw new Error("price still leads: " + hidden);
const pair = [
  { id: "aaa", provider: "fal", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 2 } },
  { id: "fast", provider: "openai", capabilities: ["t2i"], quality_tier: "fast", pricing: { amount: 2 } },
];
const byId = modelsFor("image", ["fal", "openai"], pair).map((row) => row.id).join();
if (byId !== "aaa,fast") throw new Error("id order before the tiebreak: " + byId);
const tied = tieBreakAvailability("image", pair, (row) => (row.id === "fast" ? 0 : 3));
if (tied.map((row) => row.id).join() !== "fast,aaa") throw new Error("tiebreak: " + tied.map((row) => row.id));
const demo = withoutMockWhenConnected(listed, ["mock"]).map((row) => row.provider);
if (!demo.includes("mock")) throw new Error("demo drops mock");
const nodes = modelsForNodeTypes(["mock"], rows).map((row) => row.id);
if (!nodes.includes("mock:png:v1")) throw new Error("node types missed t2i");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_unpriced_models_rank_last_and_mock_stays_free() -> None:
    """Amount 0 on a live provider is "unknown", not free (COREPRODUC-529)."""
    script = """
const row = (id, provider, amount, unit) => ({
  id, provider, capabilities: ["t2i"], quality_tier: "quality", pricing: { amount, unit },
});
const rows = [
  row("openai:tokens", "openai", 0, "token"),
  row("fal:priced", "fal", 0.04, "image"),
  row("mock:png:v1", "mock", 0, "image"),
];
if (!isUnpriced(rows[0]) || isUnpriced(rows[1]) || isUnpriced(rows[2])) throw new Error("isUnpriced");
if (!isUnpriced({ provider: "openai" })) throw new Error("no pricing is unpriced");
const live = modelsFor("image", ["openai", "fal"], rows).map((r) => r.id).join();
if (live !== "fal:priced,openai:tokens") throw new Error("priced first: " + live);
const only = modelsFor("image", ["openai"], rows).map((r) => r.id).join();
if (only !== "openai:tokens") throw new Error("an unpriced model still lists alone: " + only);
if (defaultModelFor("image", ["openai", "fal"], rows).id !== "fal:priced") throw new Error("live default");
if (defaultModelFor("image", ["mock"], rows).id !== "mock:png:v1") throw new Error("demo default is mock");
if (PRICE_VARIES !== "price varies") throw new Error("copy");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_money_uses_the_host_price_unit() -> None:
    """USD by default; a host that bills in credits (Vinci Platform, COREPRODUC-585) shows credits."""
    script = """
const want = (got, exp) => { if (got !== exp) throw new Error(got + " != " + exp); };
want(money(0.16), "$0.160");
want(money(0), "$0");
want(money(undefined), "$0");
want(money(0.0004), "$0.0004");
setPriceUnit("credits");
want(money(2), "2 credits");
want(money(1), "1 credit");
want(money(0), "0 credits");
want(money(14.5), "14.5 credits");
// A row's own currency wins: a model on the user's own key is in USD on a credits host (COREPRODUC-613).
want(money(0.9, "USD"), "$0.900");
want(money(2, "credits"), "2 credits");
setPriceUnit(undefined);
want(money(0.33), "$0.330");
want(money(3, "credits"), "3 credits");
// A sign-in connector prices in the provider's own credits (COREPRODUC-614).
want(money(4, "Higgsfield credits"), "4 Higgsfield credits");
want(money(1, "Magnific credits"), "1 Magnific credit");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_own_key_models_rank_after_the_hosts_models() -> None:
    """On a credits host, a model on the user's own key (USD) is listed after the host's models and is
    not the default by a smaller number: 0.04 dollars and 2 credits do not compare (COREPRODUC-613)."""
    script = """
const hosted = { id: "bytedance/seedream-v4.5", provider: "vinci", capabilities: ["t2i"], quality_tier: "quality", status: "ready", pricing: { amount: 2, unit: "image", currency: "credits" } };
const ownKey = { id: "higgsfield:soul-standard:2026-09", provider: "higgsfield", capabilities: ["t2i"], quality_tier: "quality", status: "ready", pricing: { amount: 0.04, unit: "image", currency: "USD" } };
setPriceUnit("credits");
const picked = defaultModelFor("image", ["vinci", "higgsfield"], [ownKey, hosted]);
if (picked.id !== hosted.id) throw new Error("host default should stay the host model, got " + picked.id);
const order = modelsFor("image", ["vinci", "higgsfield"], [ownKey, hosted]).map((row) => row.id);
if (order.join() !== [hosted.id, ownKey.id].join()) throw new Error("order " + order.join());
// With a Wavespeed key every row is in USD: the prices compare again.
const hostedOnKey = { ...hosted, pricing: { amount: 0.05, unit: "image", currency: "USD" } };
if (defaultModelFor("image", ["vinci", "higgsfield"], [hostedOnKey, ownKey]).id !== ownKey.id) throw new Error("USD rows compare by price");
setPriceUnit(undefined);
// Higgsfield credits (a sign-in connector, COREPRODUC-614) do not compare with dollars either.
const signIn = { id: "mcp_higgsfield:seedream_v4_5", provider: "mcp_higgsfield", capabilities: ["t2i"], quality_tier: "quality", status: "ready", pricing: { amount: 1, unit: "generation", currency: "Higgsfield credits" } };
const local = { id: "wavespeed:seedream-4.5:2026-08", provider: "wavespeed", capabilities: ["t2i"], quality_tier: "quality", status: "ready", pricing: { amount: 0.04, unit: "image", currency: "USD" } };
if (defaultModelFor("image", ["wavespeed", "mcp_higgsfield"], [signIn, local]).id !== local.id) throw new Error("the USD row should be the default");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_studio_pickers_call_the_registry() -> None:
    """The TypeScript Studio delegates picker membership to modelsFor."""
    text = STUDIO.read_text(encoding="utf-8")
    assert 'from "../lib/model-capabilities"' in text
    assert "modelsFor(" in text
    assert "connectedProviderIds(" in text
    assert "surfaceForPage(page)" in text
    assert "setModels(modelBody.models || [])" in text
    assert 'models.filter((m) => m.provider !== "mock")' not in text
    assert "withoutMockWhenConnected(" in text
    assert "tieBreakAvailability(" in text
    assert "rankSurface(" in text
    image = (ROOT / "apps" / "studio" / "app" / "image-page.tsx").read_text(encoding="utf-8")
    video = (ROOT / "apps" / "studio" / "app" / "video-page.tsx").read_text(encoding="utf-8")
    effects = (ROOT / "apps" / "studio" / "app" / "effect-shell.tsx").read_text(encoding="utf-8")
    assert "isUnpriced(row) ? PRICE_VARIES" in text  # picker rows: no "$0" for unpriced models
    assert "row && !isUnpriced(row)" in text  # canvas estimate: unpriced counts as not estimated
    assert "selected && isUnpriced(selected) ? PRICE_VARIES" in image
    assert "imageModels(models, connected, availability)" in image
    assert "videoModels(models, connected, availability)" in video
    assert "appModelChoices(" in effects
    assert "resolveAppModel(" in effects
    html_path = ROOT / "apps" / "daemon" / "vinci_daemon" / "studio.html"
    html = html_path.read_text(encoding="utf-8")
    assert "model-capabilities" not in html
