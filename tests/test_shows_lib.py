"""Studio Shows page helpers (apps/studio/lib/shows.ts): takes, states, sheets, recent shows."""

from __future__ import annotations

from ts_module import run_ts

LIB = "apps/studio/lib/shows.ts"
NAMES = [
    "takesOf",
    "shownKeyframe",
    "shotState",
    "countTakes",
    "frames",
    "durationSeconds",
    "templateLabel",
    "cameraworkMenu",
    "price",
    "setShowsCredits",
    "parseRecent",
    "pushRecent",
    "folderName",
    "shortHash",
    "fileUrl",
    "episodeGroups",
    "seasonLabel",
    "framingShort",
    "episodeShots",
    "episodeOf",
    "neighbors",
    "runtimeText",
    "episodeStats",
    "chosenKeyframe",
    "takesSummary",
    "levelLabel",
    "entryName",
    "clockText",
    "clipAt",
    "timelineTicks",
    "clipLabel",
    "cueAt",
    "readyJobs",
    "andList",
    "spendText",
    "busyText",
    "dialogueLabel",
    "silentClips",
    "sheetsOf",
    "fadeAt",
    "scriptFound",
    "keyframeEstimate",
    "newEntries",
    "choiceLabel",
    "autoLabel",
    "textStepQuestion",
]
SHOW = """
const take = (id, kind, stale, file) => ({ id, kind, status: "draft", stale, file });
const show = {
  path: "/shows/tidewatch",
  shots: {
    "e02/s03/sh014": { id: "e02/s03/sh014", scene: "e02/s03", error: null, select: { keyframe: "kf1" },
      takes: ["e02/s03/sh014/kf1", "e02/s03/sh014/kf2", "e02/s03/sh014/v1"] },
    "e02/s03/sh015": { id: "e02/s03/sh015", scene: "e02/s03", error: null, takes: ["e02/s03/sh015/kf1"] },
    "e02/s03/sh016": { id: "e02/s03/sh016", scene: "e02/s03", error: null, takes: [] },
    "e02/s03/sh017": { id: "e02/s03/sh017", scene: "e02/s03", error: "unknown reference loc/attic", takes: [] },
  },
  takes: {
    "e02/s03/sh014/kf1": take("e02/s03/sh014/kf1", "keyframe", false, "takes/e02/s03/sh014/kf1.png"),
    "e02/s03/sh014/kf2": take("e02/s03/sh014/kf2", "keyframe", false, "takes/e02/s03/sh014/kf2.png"),
    "e02/s03/sh014/v1": take("e02/s03/sh014/v1", "video", true, "takes/e02/s03/sh014/v1.mp4"),
    "e02/s03/sh015/kf1": take("e02/s03/sh015/kf1", "keyframe", false, null),
  },
};
const eq = (a, b, what) => {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(what + ": " + JSON.stringify(a) + " != " + JSON.stringify(b));
};
"""


def _run(body: str) -> None:
    proc = run_ts(LIB, NAMES, SHOW + body)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_takes_and_states() -> None:
    _run(
        """
eq(takesOf(show, "e02/s03/sh014").map((t) => t.id.split("/").pop()), ["kf2", "kf1", "v1"], "keyframes first, newest first");
eq(shownKeyframe(show, "e02/s03/sh014").id, "e02/s03/sh014/kf1", "select.keyframe wins over the newest");
eq(shownKeyframe(show, "e02/s03/sh015").id, "e02/s03/sh015/kf1", "no select: the newest keyframe");
eq(shownKeyframe(show, "e02/s03/sh016"), undefined, "no takes");
eq(["e02/s03/sh014", "e02/s03/sh015", "e02/s03/sh016", "e02/s03/sh017"].map((id) => shotState(show, id)),
   ["stale", "fresh", "empty", "error"], "card states");
eq(countTakes(show, Object.keys(show.shots)), { shots: 4, takes: 4, stale: 1 }, "counts");
"""
    )


def test_text_helpers() -> None:
    _run(
        """
eq([frames(4), frames("2.5"), frames("4s"), frames(3.5), frames("0+18"), frames(10 / 24), frames(undefined)],
   ["4+00", "2+12", "4+00", "3+12", "0+18", "0+10", ""], "a length as seconds+frames");
eq([durationSeconds("3+12"), durationSeconds("0+06"), durationSeconds("4s"), durationSeconds(2.5), durationSeconds("x")],
   [3.5, 0.25, 4, 2.5, 0], "seconds of each form");
eq([price(0), price(0.42), price(undefined), price(0.0024)], ["$0", "$0.42", "$0", "$0.0024"], "price");
setShowsCredits(true);  // a host that bills in credits (COREPRODUC-588)
eq([price(0), price(1), price(11)], ["0 credits", "1 credit", "11 credits"], "price in credits");
setShowsCredits(false);
eq(shortHash("sha256:" + "a".repeat(56) + "12345678"), "sha256:aaaaaaaa…12345678", "short hash");
eq(fileUrl("/my shows/t", "takes/e02/s03/sh014/kf1.png"),
   "/vinci-api/olf/file?path=%2Fmy%20shows%2Ft&rel=takes%2Fe02%2Fs03%2Fsh014%2Fkf1.png", "file url");
"""
    )


def test_recent_shows() -> None:
    _run(
        """
eq(parseRecent("not json"), [], "bad json");
eq(parseRecent(JSON.stringify(["/a", 3, "", "/b"])), ["/a", "/b"], "strings only");
let rows = [];
for (const path of ["/1", "/2", "/3", "/4", "/5", "/6", "/7", "/2"]) rows = pushRecent(rows, path);
eq(rows, ["/2", "/7", "/6", "/5", "/4", "/3"], "newest first, no duplicates, at most 6");
eq([folderName("/Users/me/shows/tidewatch/"), folderName("C:\\\\shows\\\\demo")], ["tidewatch", "demo"], "folder name");
"""
    )


def test_season_groups() -> None:
    _run(
        """
const ep = (id) => ({ id, title: id.toUpperCase(), scenes: [] });
const tv = {
  seasons: [
    { id: "season/02", title: "Ember Tide", episodes: ["e04", "e03"] },
    { id: "season/01", title: "First Light", episodes: ["e01", "e99"] },
    { id: "season/03", episodes: [] },
  ],
  episodes: [ep("e01"), ep("e02"), ep("e03"), ep("e04")],
};
const groups = episodeGroups(tv).map((g) => [g.season ? seasonLabel(g.season) : "none", g.episodes.map((e) => e.id)]);
eq(groups, [["Season 2 · Ember Tide", ["e04", "e03"]], ["Season 1 · First Light", ["e01"]], ["none", ["e02"]]],
   "season order kept, missing and empty dropped, loose episodes last");
eq(episodeGroups({ seasons: [], episodes: [ep("e01")] }).map((g) => g.season), [null], "no seasons: one group");
eq(seasonLabel({ id: "season/03", episodes: [] }), "Season 3", "no title");
"""
    )


def test_storyboard_helpers() -> None:
    _run(
        """
const ids = Object.keys(show.shots);
const episode = { id: "e02", scenes: [{ id: "e02/s03", shots: ids }] };
show.episodes = [episode];
eq([framingShort({ framing: "close_up", lens: "50mm" }), framingShort({ framing: "dutch" }), framingShort(undefined)],
   ["CU · 50mm", "Dutch", "Shot"], "card framing label");
eq([episodeShots(episode).length, episodeOf(show, "e02/s03/sh015").id, episodeOf(show, "e09/s01/sh001")], [4, "e02", undefined], "episode of a shot");
eq(neighbors(episode, "e02/s03/sh014"), { next: "e02/s03/sh015" }, "first shot: no previous");
eq(neighbors(episode, "e02/s03/sh017"), { prev: "e02/s03/sh016" }, "last shot: no next");
eq([runtimeText(52), runtimeText(125.4)], ["0:52", "2:05"], "runtime");
show.shots["e02/s03/sh014"].duration = "4s";
show.shots["e02/s03/sh015"].duration = 2.5;
eq(episodeStats(show, episode), { shots: 4, approved: 0, stale: 1, runtime: 6.5 }, "stats before approval");
show.takes["e02/s03/sh014/kf1"].status = "approved";
eq(episodeStats(show, episode).approved, 1, "a shot with an approved keyframe");
eq([chosenKeyframe(show, "e02/s03/sh014").id, chosenKeyframe(show, "e02/s03/sh015")],
   ["e02/s03/sh014/kf1", undefined], "only select.keyframe is chosen; the newest is not");
eq(ids.map((id) => takesSummary(show, id)), ["kf1 · v1", "1 keyframe", "No takes yet", "No takes yet"], "card footer");
show.takes["e02/s03/sh014/v1"].status = "approved";
eq(takesSummary(show, "e02/s03/sh014"), "kf1 · v1 approved", "approved video");
eq([levelLabel("episode"), levelLabel(undefined)], ["from episode", "default"], "origin label");
const named = (id, data = {}) => entryName({ id, data, files: {}, used_in: [] });
eq([named("prop/brass-key"), named("voice/mira"), named("char/mira", { name: "Mira Sol" })],
   ["Brass key", "Mira's voice", "Mira Sol"], "entry names");
"""
    )


def test_cut_helpers() -> None:
    _run(
        """
const clip = (index, take, start, length, extra = {}) => ({
  index, take, shot: take.split("/").slice(0, 3).join("/"), kind: take.includes("/kf") ? "keyframe" : "video",
  file: "x.mp4", in: 0.2, out: 0.2 + length, length, start, transition: "cut", audio: "own", stale: false,
  missing: false, dialogue: [], ...extra,
});
const cut = {
  episode: "e02", duration: 6.0, stale: 1, missing: 0, audio: [],
  clips: [
    clip(0, "e02/s03/sh014/v1", 0, 4, { dialogue: [{ line: "You kept the key?" }, { line: "I did." }], stale: true }),
    clip(1, "e02/s03/sh015/kf1", 3.5, 2.5, { transition: "fade" }),
  ],
};
eq([clockText(21.43), clockText(0), clockText(65.05)], ["0:21.4", "0:00.0", "1:05.1"], "clock text");
eq(clipAt(cut, 1).clip.index, 0, "first clip");
eq(clipAt(cut, 1).offset, 1.2, "the take second includes the in point");
eq(clipAt(cut, 3.7).clip.index, 1, "inside a fade, the later clip wins");
eq(clipAt({ ...cut, clips: [] }, 1), null, "no clips");
eq(timelineTicks(52), [0, 10, 20, 30, 40, 52], "design ruler: every 10 s, then the end");
eq(timelineTicks(6), [0, 1, 2, 3, 4, 5, 6], "a short cut: every second");
eq([clipLabel(cut.clips[0]), clipLabel(cut.clips[1])],
   [{ shot: "s03/sh014", take: "v1 · stale" }, { shot: "s03/sh015", take: "kf only · fade" }], "block words");
eq([cueAt(cut, 1), cueAt(cut, 3), cueAt(cut, 5)], ["You kept the key?", "I did.", ""], "subtitles share the clip");
const speech = { take: "e02/s03/sh014/a1", file: "takes/e02/s03/sh014/a1.wav", length: 1.1 };
const withBible = { ...show, bible: { character: [{ id: "char/mira", data: { name: "Mira Sol" } }], location: [], prop: [], voice: [] } };
const spoken = clip(0, "e02/s03/sh014/v1", 0, 4, { audio: "separate", dialogue_take: speech,
  dialogue: [{ speaker: "char/mira", line: "You kept the key?" }, { speaker: "char/mira", line: "All this time." }] });
eq(dialogueLabel(withBible, spoken), "a1 · Mira Sol", "design words: the take, then who speaks (once)");
eq(dialogueLabel(withBible, { ...spoken, dialogue_take: null }), "no dialogue take · Mira Sol", "no take chosen");
eq(dialogueLabel(withBible, { ...spoken, dialogue_take: { ...speech, stale: true } }), "a1 · Mira Sol · stale", "an old line");
eq(silentClips({ ...cut, clips: [spoken, { ...spoken, index: 1, dialogue_take: null }, cut.clips[1]] }).map((c) => c.index),
   [1], "separate audio needs a chosen dialogue take with a file");
"""
    )


def test_batch_and_render_words() -> None:
    _run(
        """
const batch = { mode: "stale", total: 0.42, unpriced: [], takes: [], jobs: [
  { shot: "e02/s03/sh014", kind: "keyframe", why: "kf1 is stale", total: 0.21 },
  { shot: "e02/s03/sh014", kind: "audio", why: "a1 is stale", total: 0.21 },
  { shot: "e02/s03/sh017", kind: null, error: "unknown reference loc/attic" },
] };
eq(readyJobs(batch).map((job) => job.kind), ["keyframe", "audio"], "a job with an error does not run");
eq(readyJobs(null), [], "no batch yet");
eq([andList(["kf1"]), andList(["kf1", "kf2"]), andList(["kf1", "kf2", "a1"]), andList([])],
   ["kf1", "kf1 and kf2", "kf1, kf2 and a1", ""], "lists in words");
eq(spendText(0.42, [], "2 renders"), "Spend $0.42 on 2 renders?", "a paid batch");
eq(spendText(0, ["openai:img"], "this render"), "Spend $0 on this render? openai:img has no flat price.", "unpriced");
eq(spendText(0, ["a", "b"], "3 keyframes"), "Spend $0 on 3 keyframes? a, b have no flat price.", "two unpriced");
eq([busyText("video"), busyText("audio"), busyText("keyframe")],
   ["Rendering video…", "Speaking dialogue…", "Drawing keyframe…"], "card words while rendering");
"""
    )


def test_sheets() -> None:
    _run(
        """
const mira = { id: "char/mira", files: { "sheet.png": "c/sheet.png", "sheet-2.png": "c/sheet-2.png" }, data: {
  sheet: "sheet.png", sheets: ["sheet-2.png", "x.png", { image: "old.png" }] } };
eq(sheetsOf(mira), [{ image: "sheet.png", file: "c/sheet.png" }, { image: "sheet-2.png", file: "c/sheet-2.png" },
   { image: "x.png", file: undefined }], "the primary sheet first, then whole files; bad rows are skipped");
eq(sheetsOf({ id: "char/x", files: {}, data: {} }), [], "no sheet yet");
"""
    )


def test_preview_fades() -> None:
    _run(
        """
const at = (index, start, length, extra = {}) => ({ index, take: `e02/s03/sh01${index}/v1`, shot: "x", kind: "video",
  file: "x.mp4", in: 0, out: length, length, start, transition: "cut", audio: "own", dialogue_take: null,
  stale: false, missing: false, dialogue: [], ...extra });
const faded = { episode: "e02", duration: 7.5, stale: 0, missing: 0, audio: [],
  clips: [at(0, 0, 4), at(1, 3.5, 4, { transition: "fade", in: 1 })] };
eq(fadeAt(faded, 3.0), null, "before the fade: one clip");
const half = fadeAt(faded, 3.75);
eq([half.from.clip.index, half.to.clip.index, half.mix], [0, 1, 0.5], "half way: both clips, half mixed");
eq([half.from.offset, half.to.offset], [3.75, 1.25], "each clip at its own time in its take");
eq(fadeAt(faded, 4.0), null, "after the fade");
eq(fadeAt({ ...faded, clips: [at(0, 0, 4), at(1, 4, 4)] }, 4.1), null, "a cut has no fade");
"""
    )


def test_script_preview_words() -> None:
    _run(
        """
const view = { scenes: [{ shots: [{}, {}] }, { shots: [{}] }], shots: 3, runtime: 9,
  characters: [{ name: "Mira Sol", id: "char/mira", new: false }, { name: "Guard", id: "char/guard", new: true }],
  locations: [{ name: "Cliff path", id: "loc/cliff-path", new: true }],
  keyframe: { model: "mock:png:v1", amount: 0.04, unpriced: false } };
eq(scriptFound(view), "2 scenes · 2 characters found", "found");
eq(scriptFound(null), "No scenes yet", "empty");
eq(keyframeEstimate(view), { text: "2 keyframe options per shot · est. $0.24", total: 0.24, unpriced: false }, "price");
eq(keyframeEstimate({ ...view, keyframe: { model: "openai:img", amount: 0, unpriced: true } }).text,
   "2 keyframe options per shot · openai:img has no flat price", "no flat price");
const entries = newEntries(view);
eq([entries.places, entries.people], [["Cliff path"], ["Guard"]], "new entries");
eq(entries.notes[0], "New location found: Cliff path. We will add it to the bible with a text description. You can upload reference images later.", "design notice");
eq(entries.notes[1].startsWith("New character found: Guard."), true, "a new character needs a sheet");
"""
    )


def test_model_menu_words() -> None:
    """Model menus and the question before a text step: an agent CLI bills its own sign-in."""
    _run(
        """
const cli = { id: "claude_code:cli", name: "Claude Code", provider: "claude_code", amount: 0, currency: "PLAN", unpriced: true };
const luna = { id: "openai:gpt-6-luna:2026-11", name: "GPT-6 Luna", provider: "openai", amount: 0, currency: "USD", unpriced: true };
const mock = { id: "mock:llm:v1", name: "Mock text", provider: "mock", amount: 0, currency: "USD", unpriced: false };
eq([cli, luna, mock].map(choiceLabel), ["Claude Code · your plan", "GPT-6 Luna · price varies", "Mock text · $0"], "rows");
eq([autoLabel("mock:llm:v1", [mock]), autoLabel("mock:mp4:v1", [mock]), autoLabel(undefined, [])],
   ["Auto · Mock text", "Auto · mock:mp4:v1", "Auto"], "auto row");
const ask = (model, unpriced) => ({ plan: [{ node: "t2t", model, amount: 0 }], total: 0, unpriced });
eq(textStepQuestion(ask("claude_code:cli", ["claude_code:cli"]), [mock, cli], "a draft"),
   "Write a draft with Claude Code? It runs on your own Claude Code sign-in and bills that account. Vinci adds no charge.", "cli");
eq(textStepQuestion(ask("codex:cli", ["codex:cli"]), [{ ...cli, id: "codex:cli", name: "Codex", tools: true }], "a shot list"),
   "Write a shot list with Codex? It runs on your own Codex sign-in and bills that account. Vinci adds no charge. It can use its own tools, such as reading your files: use it only with scripts you trust.", "cli with tools");
eq(textStepQuestion(ask(luna.id, [luna.id]), [cli, luna], "a shot list"),
   "Spend $0 on a shot list from openai:gpt-6-luna:2026-11? openai:gpt-6-luna:2026-11 has no flat price.", "token-billed");
"""
    )


def test_camerawork_menu() -> None:
    """COREPRODUC-564: the Camerawork menu of a shot, and the label of each template."""
    _run(
        """
const tu = { id: "anime/tu-to-eyes", version: 1, family: "push", name: "Track up to the eyes", notation: "T.U.",
  camera: { move: "push_in", render: "engine" }, timing: { default: "3+00" } };
const talk = { id: "anime/kuchipaku-hold", version: 1, family: "dialogue", name: "Held pose, mouth only", notation: "Kuchipaku",
  camera: { move: "static", render: "model" }, timing: { default: "dialogue" } };
const slow = { id: "anime/tu-slow", version: 1, family: "push", name: "Slow track up", camera: { render: "engine" }, timing: { default: "4+00" } };
eq([tu, talk, { id: "cam/own" }].map(templateLabel),
   ["Track up to the eyes · T.U. · Engine $0 · 3+00", "Held pose, mouth only · Kuchipaku · Model · dialogue", "cam/own · Model"], "labels");
const none = { bible: {} };
eq(cameraworkMenu(none, [tu, talk, slow]).map((g) => [g.label, g.rows.map((r) => r.value)]),
   [["Library · Push", ["anime/tu-to-eyes", "anime/tu-slow"]], ["Library · Dialogue", ["anime/kuchipaku-hold"]]], "the library by family");
const mine = { bible: { camerawork: [
  { id: "cam/tu-to-eyes", data: { ...tu, id: "cam/tu-to-eyes", source: "anime/tu-to-eyes@1" } },
  { id: "cam/key-insert", data: { id: "cam/key-insert", name: "Slow push on an object", timing: { default: "2+00" } } },
] } };
eq(cameraworkMenu(mine, [tu, talk]).map((g) => [g.label, g.rows.map((r) => r.value)]),
   [["In this show", ["cam/tu-to-eyes", "cam/key-insert"]], ["Library · Dialogue", ["anime/kuchipaku-hold"]]], "a copy is listed one time, as the show's");
eq(cameraworkMenu(mine, []).length, 1, "an older daemon has no library: the show's own templates stay");
"""
    )
