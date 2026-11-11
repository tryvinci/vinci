"""Studio shell: one format rail, All tools, and Ctrl+K.

The rail is Explore / Image / Video / Canvas / Shows / Library, with Features|Models
flyouts and the Skills, Find, Cost, Connect footer. All tools and Ctrl+K
index those same entries. Home, Assets, Edit, and the avatar pages stay in
that index; they are not a second rail.
"""

from __future__ import annotations

from ts_module import ROOT, run_ts

SHELL = ROOT / "apps" / "studio" / "lib" / "studio-shell.ts"
CLIENT = ROOT / "apps" / "studio" / "app" / "studio-client.tsx"


def _run(body: str) -> None:
    names = [
        "LEGACY_PAGES",
        "RAIL_GROUPS",
        "RAIL_FOOTER",
        "FLYOUT_FEATURES",
        "OFF_RAIL_TOOLS",
        "TOOLS",
        "AVATAR_MENU",
        "TOOL_CATEGORIES",
        "filterTools",
        "visibleCategories",
        "pinTool",
        "unpinTool",
        "togglePin",
        "sidebarPins",
        "parsePinned",
        "serializePinned",
        "parseCollapsed",
        "railItemOn",
        "railPageIds",
        "commandSearch",
        "moveCommandIndex",
        "pickCommandHit",
        "isCommandHotkey",
        "reachablePages",
        "editTools",
    ]
    result = run_ts("apps/studio/lib/studio-shell.ts", names, body)
    assert result.returncode == 0, result.stderr or result.stdout


def test_format_rail_is_the_only_rail() -> None:
    _run(
        """
const groups = RAIL_GROUPS.map((group) => (group.label || "") + ":" + group.items.map((row) => row.id).join("+")).join("|");
if (groups !== ":explore|Formats:image+video|Workflows:canvas+shows+library") {
  throw new Error("rail groups: " + groups);
}
if (RAIL_GROUPS[1].items[0].flyout !== "image" || RAIL_GROUPS[1].items[1].flyout !== "video") {
  throw new Error("Image and Video open flyouts");
}
const features = FLYOUT_FEATURES.image.map((row) => row.id).join(",") + "/" + FLYOUT_FEATURES.video.map((row) => row.id).join(",");
if (features !== "image,upscale,adapts/video,speak") throw new Error("flyout features: " + features);
if (RAIL_FOOTER.map((row) => row.id).join(",") !== "skills,find,cost,keys") {
  throw new Error("footer");
}
const onRail = new Set(railPageIds());
for (const id of ["explore", "image", "upscale", "adapts", "video", "speak", "canvas", "shows", "library", "skills", "find", "cost", "keys"]) {
  if (!onRail.has(id)) throw new Error(id + " left the rail");
}
for (const id of ["home", "assets", "edit", "agent", "space", "collab"]) {
  if (onRail.has(id)) throw new Error(id + " must not grow a second rail");
  if (!OFF_RAIL_TOOLS.some((row) => row.page === id)) throw new Error(id + " dropped from the index");
}
const indexed = new Set(TOOLS.map((row) => row.page));
for (const id of onRail) {
  if (!indexed.has(id)) throw new Error("All tools missed rail page " + id);
}
if (!railItemOn(RAIL_GROUPS[1].items[0], "upscale")) throw new Error("Image flyout covers upscale");
if (!railItemOn(RAIL_GROUPS[1].items[1], "speak")) throw new Error("Video flyout covers speak");
if (railItemOn(RAIL_GROUPS[1].items[0], "video")) throw new Error("Image is not Video");
"""
    )


def test_popover_filters_as_you_type_and_pins() -> None:
    _run(
        """
const typed = filterTools("upsc");
if (typed.length !== 1 || typed[0].id !== "upscale") throw new Error("type filter");
const tab = filterTools("", "edit").map((row) => row.id).join(",");
if (!tab.includes("upscale") || !tab.includes("adapts")) throw new Error("edit tab");
if (filterTools("zzzz-nope").length !== 0) throw new Error("empty miss");
if (!visibleCategories("upsc").includes("edit") || visibleCategories("upsc").includes("video")) {
  throw new Error("tabs should hide empty categories");
}
const pinned = pinTool([], "upscale");
if (pinned.join() !== "upscale") throw new Error("pin");
if (pinTool(pinned, "upscale").join() !== "upscale") throw new Error("pin is idempotent");
if (pinTool([], "image").length !== 0) throw new Error("core tools are not pinable");
if (sidebarPins(["upscale", "image", "missing"])[0]?.id !== "upscale") throw new Error("sidebar pins");
if (unpinTool(pinned, "upscale").length !== 0) throw new Error("unpin");
if (togglePin([], "adapts").join() !== "adapts") throw new Error("toggle on");
if (togglePin(["adapts"], "adapts").length !== 0) throw new Error("toggle off");
if (parsePinned('["skills","cost"]').join() !== "skills,cost") throw new Error("parse pin");
if (parsePinned("nope").length !== 0) throw new Error("bad pin json");
if (serializePinned(["keys", "image"]) !== '["keys"]') throw new Error("serialize drops core");
if (parseCollapsed("1") !== true || parseCollapsed("0") !== false) throw new Error("collapse");
"""
    )


def test_command_box_opens_tool_or_asset() -> None:
    _run(
        """
if (!isCommandHotkey({ key: "k", ctrlKey: true })) throw new Error("ctrl+k");
if (!isCommandHotkey({ key: "K", metaKey: true })) throw new Error("cmd+k");
if (isCommandHotkey({ key: "k" })) throw new Error("plain k");
const tools = commandSearch("");
if (!tools.some((row) => row.id === "image") || tools.some((row) => row.kind !== "tool")) {
  throw new Error("empty command lists tools");
}
const hits = commandSearch("still", {
  assets: [{ id: "still-1", kind: "image", uri: "vinci://assets/still-1" }],
  projects: [{ id: "cinema-still", title: "Cinema still", blurb: "oak cube", page: "canvas" }],
});
if (!hits.some((row) => row.kind === "tool" && row.id === "upscale")) throw new Error("tool hit");
if (!hits.some((row) => row.kind === "asset" && row.id === "still-1")) throw new Error("asset hit");
if (!hits.some((row) => row.kind === "project" && row.id === "cinema-still")) throw new Error("project hit");
const onlyAsset = commandSearch("sha-cube", {
  assets: [{ id: "sha-cube", kind: "image" }],
  projects: [{ id: "cinema-still", title: "Cinema still" }],
});
const picked = pickCommandHit(onlyAsset, 0);
if (!picked || picked.kind !== "asset" || picked.page !== "assets") throw new Error("enter asset");
if (moveCommandIndex(0, 1, 3) !== 1 || moveCommandIndex(0, -1, 3) !== 2) throw new Error("arrows");
if (pickCommandHit([], 0) !== null) throw new Error("empty pick");
"""
    )


def test_no_page_lost() -> None:
    _run(
        """
const pages = new Set(reachablePages());
for (const id of LEGACY_PAGES) {
  if (!pages.has(id)) throw new Error("lost page " + id);
}
for (const id of ["home", "assets", "edit"]) {
  if (!pages.has(id)) throw new Error("missing new page " + id);
}
const menu = new Set(AVATAR_MENU.map((row) => row.page));
for (const id of ["keys", "cost", "agent", "space", "collab", "find"]) {
  if (!menu.has(id)) throw new Error("avatar missing " + id);
}
if (editTools().map((row) => row.id).join() !== "upscale,adapts") throw new Error("edit index");
const models = commandSearch("flux", {
  models: [{ id: "flux", title: "Flux", blurb: "wavespeed", page: "image", flyout: "image" }],
});
if (!models.some((row) => row.kind === "model" && row.id === "flux" && row.page === "image")) {
  throw new Error("command indexes flyout models");
}
"""
    )


def test_studio_client_wires_shell() -> None:
    """The TS Studio uses the shell module; old pages stay as renderers."""
    body = CLIENT.read_text(encoding="utf-8")
    assert 'from "../lib/studio-shell"' in body
    assert 'data-testid="all-tools-popover"' in body
    assert 'data-testid="command-box"' in body
    assert 'data-testid="studio-sidebar"' in body
    assert "isCommandHotkey" in body
    assert "RAIL_GROUPS" in body
    assert "FLYOUT_FEATURES" in body
    assert 'className="rail-flyout"' in body
    assert "SIDEBAR_CORE" not in body
    assert "RAIL_FOOTER.map" in body
    assert "All tools" in body
    assert 'page === "home"' in body
    assert 'page === "assets"' in body
    assert 'page === "edit"' in body
    for needle in (
        'page === "agent"',
        'page === "space"',
        'page === "collab"',
        'page === "keys"',
        'page === "skills"',
        'page === "find"',
        'page === "cost"',
        'page === "explore"',
        "Supercomputer",
        "Collab",
        "Talking scenes open Video",
    ):
        assert needle in body
    assert SHELL.is_file()
