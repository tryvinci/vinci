"""Canvas pages, comments, receipts, and the minimap (apps/studio/lib/canvas-board.ts)."""

from __future__ import annotations

from ts_module import run_ts

MODULE = "apps/studio/lib/canvas-board.ts"
NAMES = [
    "emptyProject",
    "readProjectFile",
    "writeActive",
    "addBoardPage",
    "renameBoardPage",
    "removeBoardPage",
    "activePage",
    "receiptCosts",
    "receiptTotal",
    "receiptAssets",
    "receiptNodes",
    "minimapWorld",
    "viewportFromMinimap",
    "MINIMAP_W",
    "MINIMAP_H",
]
SETUP = """
const eq = (a, b, msg) => {
  const [x, y] = [JSON.stringify(a), JSON.stringify(b)];
  if (x !== y) throw new Error(`${msg}: ${x} !== ${y}`);
};
"""


def _check(body: str) -> None:
    result = run_ts(MODULE, NAMES, SETUP + body)
    assert result.returncode == 0, result.stderr or result.stdout


def test_pages_and_comments_round_trip() -> None:
    """Pages persist in the project file. The last page cannot be removed."""
    _check("""
let project = emptyProject();
project = writeActive(
  project,
  { nodes: [{ id: "still", type: "generate" }], edges: [] },
  [{ id: "c1", x: 1, y: 2, text: "hold" }],
  { x: 3, y: 4, zoom: 1 },
);
project = addBoardPage(project, "page-2", "B");
project = writeActive(project, { nodes: [], edges: [] }, [], { x: 0, y: 0, zoom: 1 });
const back = readProjectFile(JSON.stringify(project));
eq(back.pages.map((p) => p.id), ["page-1", "page-2"], "two pages");
eq(back.pages[0].graph.nodes[0].id, "still", "first page kept its graph");
eq(back.pages[0].comments[0].text, "hold", "comment kept");
eq(activePage(back).id, "page-2", "the new page is active");
eq(removeBoardPage(back, "page-2").active, "page-1", "removing the active page opens the first");
const last = removeBoardPage(removeBoardPage(back, "page-2"), "page-1");
eq(last.pages.length, 1, "the last page stays");
eq(renameBoardPage(back, "page-2", "  ").pages[1].name, "B", "a blank rename is ignored");
eq(renameBoardPage(back, "page-2", "Alt").pages[1].name, "Alt", "rename");
eq(readProjectFile("nope"), null, "bad json");
eq(readProjectFile(JSON.stringify({ version: 1, pages: [] })), null, "no pages");
const moved = readProjectFile(JSON.stringify({ ...back, active: "missing" }));
eq(moved.active, "page-1", "unknown active falls back to the first page");
""")


def test_receipts_are_dollars_assets_and_nodes() -> None:
    _check("""
const runs = [
  {
    id: "r1",
    state: "completed",
    estimate: { total: 0.14 },
    outputs: ["a"],
    nodes: { still: { output: "a" }, up: { output: "b" } },
  },
  { id: "r2", estimate: { total: 0.5 }, outputs: [], nodes: { anim: { outputs: ["c"] } } },
];
eq(receiptTotal(runs), 0.64, "dollars, not credits");
eq(receiptCosts(runs).map((r) => r.dollars), [0.14, 0.5], "one row per receipt");
eq(receiptAssets(runs), [
  { runId: "r1", assetId: "a" },
  { runId: "r1", assetId: "b" },
  { runId: "r2", assetId: "c" },
], "outputs first, then node outputs, duplicates dropped");
eq(receiptNodes(runs).map((r) => [r.nodeId, r.assetId]), [["still", "a"], ["up", "b"], ["anim", "c"]], "nodes");
eq(receiptTotal([]), 0, "empty history");
eq(receiptAssets([]), [], "no assets");
eq(receiptNodes([]), [], "no nodes");
""")


def test_minimap_click_centers_without_changing_zoom() -> None:
    _check("""
const view = { x: 0, y: 0, zoom: 1 };
const world = minimapWorld([{ x: 0, y: 0 }], view, 800, 600);
const next = viewportFromMinimap(world, MINIMAP_W, MINIMAP_H, MINIMAP_W / 2, MINIMAP_H / 2, 800, 600, view.zoom);
const cx = world.x + world.w / 2;
const cy = world.y + world.h / 2;
eq(next.zoom, 1, "zoom stays");
eq(Math.round(next.x), Math.round(800 / 2 - cx), "click centers x");
eq(Math.round(next.y), Math.round(600 / 2 - cy), "click centers y");
""")
