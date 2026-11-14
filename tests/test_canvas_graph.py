"""Studio canvas graph model (apps/studio/lib/canvas-graph.ts)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from vinci_daemon.app import create_app
from vinci_runtime.engine import Engine

from ts_module import run_ts

MODULE = "apps/studio/lib/canvas-graph.ts"
NAMES = [
    "addNode",
    "connect",
    "disconnect",
    "portsFor",
    "nodeRef",
    "toWorkflowNodes",
    "withAncestors",
    "runSet",
    "setParams",
    "removeNodes",
    "startHistory",
    "commit",
    "preview",
    "settle",
    "undo",
    "redo",
    "updateNode",
    "HISTORY_LIMIT",
    "duplicateNode",
    "fitView",
    "zoomAt",
    "ZOOM_MAX",
    "NODE_W",
    "NODE_H",
    "SHORTCUTS",
    "shortcutFor",
    "withKeys",
    "wheelZoomFactor",
    "searchCatalog",
    "buildAddMenu",
    "flattenAddMenu",
    "capabilityForModel",
    "kindFromMime",
    "nodeTypeOf",
    "ADD_CHIPS",
    "inputDefaults",
    "freeSpot",
    "wirePath",
    "curve",
    "portY",
    "outputOf",
    "NODE_CATALOG",
    "NODE_DEFAULTS",
    "runtimeGraph",
    "startParams",
    "blockedReason",
    "groupNodes",
    "ungroupNodes",
    "updateGroup",
    "groupOf",
    "groupBounds",
    "nodesInRect",
    "moveNodes",
    "estimateRun",
    "estimateScope",
    "scopeNodes",
    "instanceNodes",
    "isEdited",
    "inlineText",
    "unrunnableSource",
    "expandCounts",
]

# Shared fixture: a t2i still feeding nothing yet, plus an upscale and an i2v.
SETUP = """
const eq = (a, b, msg) => {
  const [x, y] = [JSON.stringify(a), JSON.stringify(b)];
  if (x !== y) throw new Error(`${msg}: ${x} !== ${y}`);
};
const gen = (id, capability, params) => ({ id, type: "generate", capability, params });
const still = { ...gen("still", "t2i", { prompt: "{{inputs.prompt}}" }), x: 1, y: 2 };
const up = gen("up", "upscale", { media: "{{inputs.media}}" });
const anim = gen("anim", "i2v", { image: "{{inputs.image}}" });
const base = { nodes: [still, up, anim], edges: [] };
const param = (g, id, key) => g.nodes.find((n) => n.id === id).params[key];
"""


def _check(body: str) -> None:
    result = run_ts(MODULE, NAMES, SETUP + body)
    assert result.returncode == 0, result.stderr or result.stdout


def test_connect_feeds_upstream_output_into_the_param() -> None:
    _check("""
const r = connect(base, "still", "up");
if (!r.ok) throw new Error(r.error);
eq(r.graph.edges, [{ src: "still", dst: "up", input_key: "media" }], "edge");
eq(param(r.graph, "up", "media"), nodeRef("still"), "media param");
eq(param(base, "up", "media"), "{{inputs.media}}", "input graph is not mutated");
const v = connect(base, "still", "anim");
if (!v.ok) throw new Error(v.error);
eq(param(v.graph, "anim", "image"), "{{nodes.still.output}}", "i2v reads image");
""")


def test_disconnect_restores_the_page_input() -> None:
    _check("""
const r = connect(base, "still", "up");
const g = disconnect(r.graph, "still", "up");
eq(g.edges, [], "edges");
eq(param(g, "up", "media"), "{{inputs.media}}", "media param");
eq(disconnect(base, "still", "up"), base, "no-op when not wired");
""")


def test_rewiring_keeps_dependencies_other_params_still_read() -> None:
    _check("""
const first = gen("first", "t2i", {});
const last = gen("last", "t2i", {});
const ref = nodeRef("first");
const motion = gen("motion", "i2v", { image: ref, first_frame_url: ref });
const wire = { src: "first", dst: "motion", input_key: "image" };
let g = { nodes: [first, last, motion], edges: [wire] };
g = connect(g, "last", "motion", "image").graph;
const order = g.edges.map((e) => `${e.src}>${e.dst}:${e.input_key || "-"}`).sort();
eq(order, ["first>motion:-", "last>motion:image"], "first stays upstream as a dependency");
const runs = [...withAncestors(g, ["motion"])].sort();
eq(runs, ["first", "last", "motion"], "both sources run");
const cut = disconnect(g, "first", "motion");
const reset = param(cut, "motion", "first_frame_url");
eq(reset, "{{inputs.first_frame_url}}", "deleting the wire resets it");
eq(cut.edges.map((e) => e.src), ["last"], "no dangling dependency");
const note = (n) => ({ ...n, params: { ...n.params, note: ref + " x" } });
const withNote = (n) => (n.id === "motion" ? note(n) : n);
const tpl = { ...g, nodes: g.nodes.map(withNote) };
eq(disconnect(tpl, "first", "motion").edges.length, 2, "an embedded reference keeps its edge");
const listed = (n) => ({ ...n, params: { ...n.params, image_urls: [ref, "x"] } });
const nested = { ...g, nodes: g.nodes.map((n) => (n.id === "motion" ? listed(n) : n)) };
const kept = disconnect(nested, "first", "motion");
eq(kept.edges.some((e) => e.src === "first"), true, "a reference inside a list keeps its edge");
eq(param(kept, "motion", "image_urls"), [ref, "x"], "and the list is left as is");
for (const variant of ["{{ nodes.first.output }}", "{{nodes.first.data.text}}"]) {
  const spaced = (n) => ({ ...n, params: { ...n.params, caption: variant } });
  const h = { ...g, nodes: g.nodes.map((n) => (n.id === "motion" ? spaced(n) : n)) };
  const out = disconnect(h, "first", "motion");
  const keeps = out.edges.some((e) => e.src === "first");
  eq(keeps, true, "runtime-valid reference keeps its edge: " + variant);
}
const lookalike = (n) => ({ ...n, params: { ...n.params, caption: "{{nodes.first2.output}}" } });
const other = { ...g, nodes: g.nodes.map((n) => (n.id === "motion" ? lookalike(n) : n)) };
const dropped = disconnect(other, "first", "motion").edges.some((e) => e.src === "first");
eq(dropped, false, "first2 is not first");
""")


def test_connect_rejects_bad_wires() -> None:
    _check("""
const mism = connect(base, "anim", "up");
if (mism.ok || !/cannot take video/.test(mism.error)) throw new Error("video->image: " + mism.error);
const videoToText = connect(base, "anim", "still");
if (videoToText.ok || !/cannot take video/.test(videoToText.error)) throw new Error("video->text: " + videoToText.error);
const noIn = connect(base, "up", "still");
if (noIn.ok) throw new Error("image cannot feed a text-only input");
const self = connect(base, "up", "up");
if (self.ok) throw new Error("self wire");
const up2 = { id: "up2", type: "generate", capability: "upscale", params: {} };
let g = { nodes: [still, up, up2], edges: [] };
g = connect(g, "up", "up2").graph;
const loop = connect(g, "up2", "up");
if (loop.ok || !/loop/.test(loop.error)) throw new Error("cycle: " + JSON.stringify(loop));
const unknown = { id: "x", type: "generate", capability: "transcribe", params: {} };
eq(portsFor(unknown), { inputs: [], output: null }, "unknown capability has no ports");
""")


def test_connect_replaces_the_source_of_a_taken_input() -> None:
    _check("""
const still2 = { id: "still2", type: "generate", capability: "t2i", params: {} };
let g = { nodes: [still, still2, up], edges: [] };
g = connect(g, "still", "up").graph;
const again = connect(g, "still", "up");
if (!again.ok || again.graph !== g) throw new Error("same wire is a no-op");
g = connect(g, "still2", "up").graph;
eq(g.edges, [{ src: "still2", dst: "up", input_key: "media" }], "one source per input");
eq(param(g, "up", "media"), nodeRef("still2"), "param follows the new source");
const stale = { nodes: [still, up], edges: [{ src: "still", dst: "up", input_key: "media" }] };
const fixed = connect(stale, "still", "up");
eq(param(fixed.graph, "up", "media"), nodeRef("still"), "redraw repairs a stale saved wire");
eq(fixed.graph.edges.length, 1, "no duplicate edge");
const upTpl = gen("up", "upscale", { media: nodeRef("still") });
const tpl = { nodes: [still, still2, upTpl], edges: [{ src: "still", dst: "up" }] };
const swapped = connect(tpl, "still2", "up");
const keyed = [{ src: "still2", dst: "up", input_key: "media" }];
eq(swapped.graph.edges, keyed, "unkeyed template edge replaced");
const runs = [...withAncestors(swapped.graph, ["up"])].sort();
eq(runs, ["still2", "up"], "old source no longer runs");
""")


def test_add_node_wires_only_when_types_fit() -> None:
    _check("""
const shot2 = { id: "shot2", type: "generate", capability: "t2i", params: {} };
const g1 = addNode({ nodes: [still], edges: [] }, shot2, "still");
eq(g1.edges, [], "t2i after t2i stays unwired");
eq(g1.nodes.map((n) => n.id), ["still", "shot2"], "node appended");
const g2 = addNode({ nodes: [still], edges: [] }, up, "still");
eq(g2.edges.length, 1, "upscale after t2i is wired");
""")


def test_ancestors_and_workflow_nodes() -> None:
    _check("""
let g = connect(base, "still", "up").graph;
g = connect(g, "up", "anim").graph;
eq([...withAncestors(g, ["anim"])].sort(), ["anim", "still", "up"], "closure");
eq([...withAncestors(g, ["still"])], ["still"], "roots stay alone");
const wf = toWorkflowNodes(setParams(g, "anim", { motion: "orbit" }).nodes);
const s = wf.find((n) => n.id === "still");
if ("x" in s || "y" in s) throw new Error("positions are canvas-only");
eq(s.params.camera, "{{inputs.camera}}", "unset shot params come from page inputs");
if ("duration" in s.params) throw new Error("stills get no duration");
const a = wf.find((n) => n.id === "anim");
eq(a.params.motion, "orbit", "set motion is kept");
eq(a.params.duration, "{{inputs.duration}}", "video duration from page inputs");
eq(a.params.image, "{{nodes.up.output}}", "wired input survives");
// A shot value cleared in the inspector ("") stays empty, so the page value cannot come back (COREPRODUC-525).
const cleared = toWorkflowNodes(setParams(g, "still", { lens: "", aspect_ratio: "" }).nodes).find((n) => n.id === "still");
eq(cleared.params.lens, "", "cleared lens stays empty");
eq(cleared.params.aspect_ratio, "{{inputs.aspect_ratio}}", "empty aspect still comes from the page");
""")



def test_remove_nodes_drops_wires_and_restores_downstream_inputs() -> None:
    _check("""
let g = connect(base, "still", "up").graph;
g = connect(g, "up", "anim").graph;
const r = removeNodes(g, ["up"]);
eq(r.nodes.map((n) => n.id), ["still", "anim"], "node gone");
eq(r.edges, [], "both wires gone");
eq(param(r, "anim", "image"), "{{inputs.image}}", "downstream falls back to page input");
if (removeNodes(g, ["nope"]) !== g) throw new Error("unknown id returns the same graph");
const refs = {
  refs: [nodeRef("still"), "keep"],
  cfg: { src: "{{ nodes.still.outputs }}" },
  note: "a {{nodes.still.data}} b",
  seed: "{{nodes.still.output}}",
  tabbed: ["{{\tnodes.still.output}}"],
};
const withRefs = (n) => ({ ...n, params: { ...n.params, ...refs } });
const nested = (n) => (n.id === "up" ? withRefs(n) : n);
const ng = { ...g, nodes: g.nodes.map(nested) };
const gone = removeNodes(ng, ["still"]);
const dangling = gone.edges.filter((e) => e.src === "still" || e.dst === "still");
eq(dangling, [], "no edge points at a deleted node, even for nested references");
if (JSON.stringify(gone.nodes).includes("nodes.still")) throw new Error("deleted node still named");
eq(param(gone, "up", "refs"), ["keep"], "list reference dropped, literal kept");
eq(param(gone, "up", "cfg"), { src: "" }, "nested object reference cleared");
eq(param(gone, "up", "note"), "a  b", "embedded reference cut out");
eq(param(gone, "up", "seed"), "{{inputs.seed}}", "whole-param reference -> page input");
const upOf = (graph) => graph.nodes.find((n) => n.id === "up");
if (upOf(removeNodes(g, ["anim"])) !== upOf(g)) throw new Error("survivor identity lost");
""")


def test_history_undo_redo_round_trip() -> None:
    _check("""
let h = startHistory(base);
const wired = connect(base, "still", "up").graph;
h = commit(h, wired);
h = commit(h, removeNodes(wired, ["anim"]));
eq([h.past.length, h.future.length], [2, 0], "two steps");
h = undo(h);
if (h.present !== wired) throw new Error("undo returns the exact prior graph");
h = undo(h);
if (h.present !== base) throw new Error("second undo reaches the start");
eq(undo(h), h, "undo at the start is a no-op");
h = redo(h);
if (h.present !== wired) throw new Error("redo");
h = commit(h, base);
eq(h.future.length, 0, "a new edit clears redo");
eq(commit(h, h.present), h, "unchanged graph is not recorded");
""")


def test_history_drag_is_one_step_and_capped() -> None:
    _check("""
let h = startHistory(base);
const start = h.present;
for (let i = 1; i <= 30; i++) h = preview(h, updateNode(h.present, "still", { x: i, y: i }));
eq(h.past.length, 0, "drag frames are not recorded");
h = settle(h, start);
eq(h.past.length, 1, "drag lands as one step");
eq(h.present.nodes[0].x, 30, "final position kept");
if (undo(h).present !== start) throw new Error("undo restores the pre-drag graph");
eq(settle(startHistory(base), base).past.length, 0, "a click without a move records nothing");
let back = commit(startHistory(base), connect(base, "still", "up").graph);
back = undo(back);
const before = back.present;
back = preview(back, updateNode(back.present, "still", { x: 99 }));
back = preview(back, updateNode(back.present, "still", { x: 1 }));
back = settle(back, before);
eq(back.future.length, 1, "dragging back to the start keeps redo");
if (back.present !== before) throw new Error("and keeps the original graph object");
let big = startHistory(base);
for (let i = 0; i < HISTORY_LIMIT + 25; i++) {
  big = commit(big, setParams(big.present, "still", { prompt: "take " + i }));
}
eq(big.past.length, HISTORY_LIMIT, "history is capped");
eq(isEdited(startHistory(base)), false, "fresh history is not edited");
let all = big;
while (all.past.length) all = undo(all);
eq(isEdited(all), true, "a trimmed history stays edited after undoing everything");
const once = commit(startHistory(base), removeNodes(base, ["up"]));
eq(isEdited(undo(once)), false, "undo back to load");
let layout = commit(startHistory(base), moveNodes(base, { still: { x: 0, y: 0 } }, 300, 40));
layout = commit(layout, groupNodes(layout.present, ["still", "up"], "g1"));
eq(isEdited(layout), false, "moving and grouping nodes is layout, not a run edit");
const tuned = commit(layout, setParams(layout.present, "up", { scale: "2x" }));
eq(isEdited(tuned), true, "a param edit is");
""")



def test_duplicate_copies_beside_without_wires() -> None:
    _check("""
let g = connect(base, "still", "up").graph;
g = duplicateNode(g, "up", "up-copy");
const copy = g.nodes.find((n) => n.id === "up-copy");
eq([copy.capability, copy.x, copy.y], ["upscale", 24, 24], "copy sits beside");
eq(copy.params.media, "{{inputs.media}}", "wired input is not copied");
eq(g.edges.length, 1, "no new wire");
eq(duplicateNode(g, "nope", "x"), g, "unknown id is a no-op");
const frames = {
  first_frame_url: nodeRef("still"),
  last_frame_url: "{{ nodes.up.output }}",
  image_urls: [nodeRef("still")],
  extra: ["keep", "{{\tnodes.still.output}}"],
};
const withFrames = (n) => (n.id === "anim" ? { ...n, params: { ...n.params, ...frames } } : n);
const fl = { ...base, nodes: base.nodes.map(withFrames) };
const dup = duplicateNode(fl, "anim", "anim-copy").nodes.find((n) => n.id === "anim-copy");
const left = JSON.stringify(dup.params);
if (left.includes("nodes.")) throw new Error("copy still names a node: " + left);
const resets = [dup.params.first_frame_url, dup.params.last_frame_url, dup.params.image_urls];
const pageInputs = ["{{inputs.first_frame_url}}", "{{inputs.last_frame_url}}", []];
eq(resets, pageInputs, "every ref resets");
eq(dup.params.extra, ["keep"], "a tab inside the braces is still a reference");
const lone = { refs: ["{{\tnodes.still.output}}"] };
const swap = (n) => (n.id === "anim" ? Object.assign({}, n, { params: lone }) : n);
const tg = { ...base, nodes: base.nodes.map(swap) };
eq(duplicateNode(tg, "anim", "c").nodes.at(-1).params.refs, [], "a lone tabbed ref is found");
eq(param(removeNodes(tg, ["still"]), "anim", "refs"), [], "removeNodes finds it too");
const reader = { id: "c", params: { image: "{{nodes.a b.output}}" } };
const spaced = { nodes: [{ id: "a b" }, reader], edges: [] };
const sc = duplicateNode(spaced, "c", "c2").nodes.at(-1);
eq(sc.params.image, "{{inputs.image}}", "an id with a space is a reference too");
const trail = { id: "d", params: { image: "{{nodes.a .output}}" } };
const trailed = { nodes: [{ id: "a " }, trail], edges: [] };
const tc = duplicateNode(trailed, "d", "d2").nodes.at(-1);
eq(tc.params.image, "{{inputs.image}}", "a space before the dot stays in the id");
""")


def test_zoom_keeps_the_cursor_point_and_clamps() -> None:
    _check("""
const v = zoomAt({ x: 100, y: 50, zoom: 1 }, 2, 300, 250);
const gx = (300 - 100) / 1, gy = (250 - 50) / 1;
eq([gx * v.zoom + v.x, gy * v.zoom + v.y], [300, 250], "point under cursor stays put");
eq(zoomAt(v, 99, 0, 0).zoom, ZOOM_MAX, "zoom is clamped");
const notch = wheelZoomFactor(-100, 0, false);
if (notch < 1.1 || notch > 1.2) throw new Error("one mouse notch is ~15%: " + notch);
eq(wheelZoomFactor(100, 0, false) * notch, 1, "in and out cancel");
const boosted = wheelZoomFactor(-5, 0, true) > wheelZoomFactor(-5, 0, false);
if (!boosted) throw new Error("pinch is boosted");
eq(wheelZoomFactor(-100, 0, true), notch, "Ctrl + mouse notch is not boosted");
eq(wheelZoomFactor(-3, 1, true), wheelZoomFactor(-3, 1, false), "line deltas are not boosted");
""")


def test_fit_view_centres_all_nodes_without_blowing_up() -> None:
    _check("""
const nodes = [{ id: "a", x: 0, y: 0 }, { id: "b", x: 1000, y: 600 }];
const v = fitView(nodes, 800, 500, 40);
const right = (1000 + NODE_W) * v.zoom + v.x;
const bottom = (600 + NODE_H) * v.zoom + v.y;
const inside = v.x >= 39.9 && v.y >= 39.9 && right <= 760.1 && bottom <= 460.1;
if (!inside) throw new Error("not inside: " + JSON.stringify(v));
eq(fitView([{ id: "a", x: 10, y: 10 }], 800, 500).zoom, 1, "a lone node stays at 100%");
const tall = fitView(nodes, 800, 500, 40, new Map([["b", 400]]));
if ((600 + 400) * tall.zoom + tall.y > 460.1) throw new Error("tall card overflows the fit");
const odd = fitView([{ id: "constructor", x: 0, y: 0 }], 800, 500, 40, new Map());
if (!Number.isFinite(odd.y)) throw new Error("prototype-named id must fall back to NODE_H");
eq(fitView([], 800, 500), { x: 0, y: 0, zoom: 1 }, "empty canvas goes home");
""")


def test_shortcut_table_has_unique_bindings_and_resolves_keys() -> None:
    _check("""
const seen = new Set();
for (const s of SHORTCUTS) {
  if (!s.label || !s.keys) throw new Error("missing text: " + s.id);
  for (const m of s.match) {
    const k = `${m.key}|${!!m.mod}|${!!m.shift}`;
    if (seen.has(k)) throw new Error("duplicate binding " + k);
    seen.add(k);
  }
}
eq(shortcutFor({ key: "z", metaKey: true }), "undo", "cmd z");
eq(shortcutFor({ key: "Z", metaKey: true, shiftKey: true }), "redo", "cmd shift z");
eq(shortcutFor({ key: "z", ctrlKey: true }), "undo", "ctrl counts as mod");
eq(shortcutFor({ key: "Backspace" }), "delete", "backspace");
eq(shortcutFor({ key: "d" }), "fit", "plain d");
eq(shortcutFor({ key: "d", metaKey: true }), "duplicate", "cmd d");
eq(shortcutFor({ key: "+", metaKey: true, shiftKey: true }), "zoomIn", "cmd plus");
eq(shortcutFor({ key: "?", shiftKey: true }), "help", "question mark");
eq(shortcutFor({ key: "z", altKey: true, metaKey: true }), null, "alt combos never match");
eq(shortcutFor({ key: "q" }), null, "unbound key");
eq(withKeys("undo"), "Undo (⌘Z)", "tooltip text");
""")



def test_add_menu_search_and_port_filter() -> None:
    _check("""
const caps = (rows) => rows.map((r) => r.capability);
eq(caps(searchCatalog("")), NODE_CATALOG.map((r) => r.capability), "empty query keeps menu order");
eq(caps(searchCatalog("", "image")), ["upscale", "i2i", "i2v"], "image output: only image inputs");
eq(caps(searchCatalog("", "video")), ["lipsync"], "video output");
eq(caps(searchCatalog("", "audio")), ["lipsync"], "audio output");
eq(caps(searchCatalog("", "text")), ["t2i", "t2v", "i2i", "tts", "i2v", "assistant"], "text output");
eq(caps(searchCatalog("up")), ["upscale", "media"], "label prefix beats a blurb hit");
eq(caps(searchCatalog("edit")), ["i2i"], "word prefix");
eq(caps(searchCatalog("im"))[0], "t2i", "label prefix beats word prefix");
eq(caps(searchCatalog("clip", "image")), ["i2v"], "query and kind combine");
eq(caps(searchCatalog("", null, "utilities")), ["media", "text", "list", "assistant", "note"], "utilities chip");
eq(searchCatalog("zzz"), [], "no match");
eq(portsFor({ id: "n", type: "transform", capability: "note" }).output, null, "note has no ports");
for (const row of NODE_CATALOG.filter((r) => r.capability !== "note")) {
  if (outputOf(row.capability) == null && row.capability !== "media") throw new Error("catalog row without ports: " + row.capability);
}
eq(kindFromMime("video/mp4"), "video", "mime");
eq(nodeTypeOf("text"), "transform", "canvas-only text");
eq(nodeTypeOf("t2i"), "generate", "image gen");
""")


def test_new_nodes_get_inputs_and_free_spots() -> None:
    _check("""
eq(inputDefaults("upscale"), { media: "{{inputs.media}}" }, "upscale reads media");
const two = { video: "{{inputs.video}}", audio: "{{inputs.audio}}" };
eq(inputDefaults("lipsync"), two, "two inputs");
eq(inputDefaults("t2i"), { prompt: "{{inputs.prompt}}" }, "t2i prompt is a text port");
const g = { nodes: [{ id: "a", x: 100, y: 100 }, { id: "b", x: 124, y: 124 }], edges: [] };
eq(freeSpot(g, 100, 100), { x: 100 + NODE_W + 40, y: 100 }, "next free card slot to the right");
const step = NODE_W + 40;
const cards = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => ({ id: "r" + i, x: i * step, y: 0 }));
const row = { nodes: cards, edges: [] };
eq(freeSpot(row, 0, 0), { x: 0, y: NODE_H + 40 }, "a full row spills below");
eq(freeSpot(g, 800, 100), { x: 800, y: 100 }, "free spot kept");
const cell = (i) => ({ id: "c" + i, x: (i % 9) * step, y: Math.floor(i / 9) * (NODE_H + 40) });
const grid = [...Array(81).keys()].map(cell);
const spot = freeSpot({ nodes: grid, edges: [] }, 0, 0);
const near = (n) => Math.abs(n.x - spot.x) < NODE_W + 16 && Math.abs(n.y - spot.y) < NODE_H + 16;
if (grid.some(near)) throw new Error("full grid still overlaps: " + JSON.stringify(spot));
""")


def test_wires_enter_the_right_input_port() -> None:
    _check("""
const v = { id: "v", type: "generate", capability: "t2v", x: 0, y: 0 };
const ls = { id: "ls", type: "generate", capability: "lipsync", x: 400, y: 0 };
    const end = (d) => [...d.matchAll(/-?\\d+(?:\\.\\d+)?/g)].slice(-2).map((m) => Number(m[0]));
    eq(end(wirePath(v, ls, "video")), [400, portY(0)], "first input");
    eq(end(wirePath(v, ls, "audio")), [400, portY(1)], "second input sits lower");
    eq(end(wirePath(v, ls)), [400, portY(0)], "unknown key falls back to the first input");
""")



def test_new_node_params_come_from_page_and_capability_defaults() -> None:
    _check("""
const still16 = { prompt: "oak cube", aspect_ratio: "16:9", resolution: "1K", count: 1, num_images: 1 };
eq(startParams("t2i", { prompt: "  oak cube " }), still16, "t2i");
eq(startParams("t2i", { aspect_ratio: "9:16" }).aspect_ratio, "9:16", "page aspect wins");
eq(startParams("upscale", { prompt: "x" }), { media: "{{inputs.media}}" }, "upscale has no prompt");
const v = startParams("i2v", { duration: "8" });
eq([v.duration, v.image, v.prompt], [8, "{{inputs.image}}", ""], "i2v");
eq(startParams("t2v", { duration: "" }).duration, 5, "duration falls back to the default");
for (const row of NODE_CATALOG) {
  if (!NODE_DEFAULTS[row.capability]) throw new Error("no defaults for " + row.capability);
}
""")


def test_blocked_reason_names_what_is_missing() -> None:
    _check("""
const t2i = gen("t2i-1", "t2i", startParams("t2i", {}));
eq(blockedReason(t2i, {}), "Add a prompt, then run.", "empty prompt");
const typed = setParams({ nodes: [t2i], edges: [] }, "t2i-1", { prompt: "cube" }).nodes[0];
eq(blockedReason(typed, {}), null, "typed");
const tpl = gen("tpl", "t2i", { prompt: "{{inputs.prompt}}" });
eq(blockedReason(tpl, { prompt: true }), null, "template prompt read from the page");
eq(blockedReason(tpl, {}), "Add a prompt, then run.", "page prompt missing");
const upN = gen("up", "upscale", startParams("upscale", {}));
eq(blockedReason(upN, {}), "Connect image first.", "unwired upscale");
eq(blockedReason(upN, { media: true }), null, "page still feeds it");
const wired = connect({ nodes: [still, upN], edges: [] }, "still", "up").graph;
eq(blockedReason(wired.nodes[1], {}), null, "wired upscale");
const ls = gen("ls", "lipsync", startParams("lipsync", {}));
eq(blockedReason(ls, { video: true }), "Connect audio first.", "second input");
const animWired = gen("anim", "i2v", { image: "{{nodes.still.output}}" });
eq(blockedReason(animWired, {}), null, "i2v prompt optional");
""")



def test_group_and_ungroup_keep_one_group_per_node() -> None:
    _check("""
let g = groupNodes(base, ["still", "up"], "g1");
const g1 = { id: "g1", name: "Group", color: "teal", nodeIds: ["still", "up"] };
eq(g.groups, [g1], "grouped");
eq(groupNodes(base, ["still"], "solo"), base, "one node is not a group");
eq(groupNodes(base, ["still", "ghost"], "x"), base, "unknown ids are ignored");
g = groupNodes(g, ["up", "anim"], "g2");
const members = g.groups.map((x) => [x.id, x.nodeIds]);
eq(members, [["g1", ["still"]], ["g2", ["up", "anim"]]], "up moved groups");
eq(g.groups[1].color, "amber", "next colour");
eq(groupOf(g, ["anim", "up"]).id, "g2", "exact member set finds the group");
eq(groupOf(g, ["anim"]), undefined, "partial set is not the group");
g = updateGroup(g, "g2", { name: "Hero shots", color: "violet" });
eq([g.groups[1].name, g.groups[1].color], ["Hero shots", "violet"], "rename and recolour");
eq(groupNodes(g, ["anim", "up"], "g3"), g, "regrouping a group keeps its name and colour");
const u = ungroupNodes(g, ["anim"]);
eq(u.groups.map((x) => x.id), ["g1"], "ungroup the group holding anim");
eq(u.nodes.length, 3, "nodes stay");
eq(ungroupNodes(u, ["anim"]), u, "no-op when not grouped");
""")


def test_groups_survive_edits_and_are_pruned_on_delete() -> None:
    _check("""
let g = groupNodes(base, ["still", "up"], "g1");
g = connect(g, "still", "up").graph;
eq(g.groups.length, 1, "connect keeps groups");
g = removeNodes(g, ["up"]);
eq(g.groups[0].nodeIds, ["still"], "deleted member leaves the group");
eq(removeNodes(g, ["still"]).groups, [], "empty groups are dropped");
let h = startHistory(base);
h = commit(h, groupNodes(base, ["still", "up"], "g1"));
eq(undo(h).present.groups, undefined, "grouping is undoable");
""")


def test_frame_bounds_marquee_and_multi_move() -> None:
    _check("""
const at = (id, x, y) => ({ id, x, y });
const nodes = [at("a", 100, 100), at("b", 400, 300), at("c", 900, 900)];
const g = groupNodes({ nodes, edges: [] }, ["a", "b"], "g");
const b = groupBounds(g, g.groups[0]);
eq([b.x, b.y, b.w], [80, 52, 400 + NODE_W + 20 - 80], "frame wraps members with a title bar");
eq(b.y + b.h, 300 + NODE_H + 20, "frame bottom");
eq(nodesInRect(g, { x: 0, y: 0, w: 450, h: 350 }), ["a", "b"], "marquee hits overlapping cards");
eq(nodesInRect(g, { x: 0, y: 0, w: 50, h: 50 }), [], "empty marquee");
const moved = moveNodes(g, { a: { x: 100, y: 100 }, b: { x: 400, y: 300 } }, 10.4, -20);
const spots = moved.nodes.map((n) => [n.x, n.y]);
eq(spots, [[110, 80], [410, 280], [900, 900]], "selection moves together");
""")



def test_run_estimate_covers_upstream_and_flags_unpriced() -> None:
    _check("""
let g = connect(base, "still", "up").graph;
g = connect(g, "up", "anim").graph;
const prices = { still: 0.04, up: 0.1, anim: null };
const price = (n) => prices[n.id];
const upRun = estimateRun(g, ["up"], price);
eq(upRun, { nodes: 2, total: 0.14, unpriced: 0 }, "upscale pulls in its still");
eq(estimateRun(g, ["up"], price, true), { nodes: 1, total: 0.1, unpriced: 0 }, "solo prices only the clicked node");
eq([...runSet(g, ["up"])].sort(), ["still", "up"], "default run includes ancestors");
eq([...runSet(g, ["up"], true)], ["up"], "card run is this node only");
eq(estimateRun(g, ["anim"], price).unpriced, 1, "unknown price is counted, not guessed");
eq(estimateRun(g, ["still"], price).nodes, 1, "a root runs alone");
const withMedia = { ...g, nodes: [...g.nodes, { id: "cut", type: "media", params: {} }] };
eq(estimateRun(withMedia, ["cut"], price).nodes, 0, "media ops are not priced generate jobs");
eq(shortcutFor({ key: "Enter", metaKey: true }), "runSelection", "cmd enter");
eq(shortcutFor({ key: "Enter", metaKey: true, shiftKey: true }), "runAll", "cmd shift enter");
""")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VINCI_HOME", str(tmp_path))
    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path)
    engine.init_home(demo=True)
    return TestClient(create_app(engine))


def test_canvas_wire_reaches_the_downstream_job(client: TestClient) -> None:
    """A wire drawn with `connect` must hand the upstream asset to the downstream job.

    Regression: Studio wrote `{{inputs.media}}` on wired nodes, so the job got media=''.
    """
    built = run_ts(
        MODULE,
        NAMES,
        SETUP
        + """
const edit = gen("edit", "i2i", { prompt: "{{inputs.prompt}}", media: "{{inputs.media}}" });
const r = connect({ nodes: [still, edit], edges: [] }, "still", "edit");
if (!r.ok) throw new Error(r.error);
const nodes = toWorkflowNodes(r.graph.nodes).map((n) => ({ ...n, model_id: "mock:png:v1" }));
console.log(JSON.stringify({ nodes, edges: r.graph.edges }));
""",
    )
    assert built.returncode == 0, built.stderr
    graph = json.loads(built.stdout)
    res = client.post(
        "/runs",
        json={
            "inputs": {"prompt": "oak cube"},
            "workflow": {"id": "canvas", "version": "1.0.0", **graph},
        },
    )
    assert res.status_code == 200, res.text
    run = res.json()
    assert run["state"] == "completed", run
    still_out = run["nodes"]["still"]["output"]
    job = client.get(f"/jobs/{run['nodes']['edit']['job_id']}").json()
    assert job["inputs"]["media"] == still_out


def test_click_output_inserts_a_wired_upscaler() -> None:
    """Acceptance: Image Gen output + Upscaler creates a wired Upscaler."""
    _check("""
const shot = { ...gen("shot", "t2i", startParams("t2i", { prompt: "oak" })), x: 0, y: 0 };
const upNode = { ...gen("up", "upscale", startParams("upscale", {})), x: NODE_W + 80, y: 0 };
const g = addNode({ nodes: [shot], edges: [] }, upNode, "shot");
eq(g.edges, [{ src: "shot", dst: "up", input_key: "media" }], "wired");
eq(param(g, "up", "media"), nodeRef("shot"), "upscaler reads the still");
""")


def test_add_popover_groups_chips_and_providers() -> None:
    """Magnific add popover: chips, Media / Nodes / providers with counts / Flows."""
    _check("""
eq(ADD_CHIPS.map((c) => c.id), ["image", "video", "audio", "3d", "utilities", "flows", "templates", "library"], "chips");
const models = [
  { id: "a", display_name: "Soul", provider: "higgsfield", capabilities: ["t2i"] },
  { id: "b", display_name: "Kling", provider: "higgsfield", capabilities: ["t2v"] },
  { id: "c", display_name: "Flux", provider: "fal", capabilities: ["t2i"] },
];
const templates = [{ id: "long-video", title: "Long video", blurb: "A storyboard" }];
const open = buildAddMenu("", { models, templates });
eq(open.map((s) => s.id), ["media", "nodes", "providers", "flows"], "sections");
eq(open[0].rows.map((r) => r.pick.capability), ["media"], "media section");
eq(open[1].rows.some((r) => r.pick.capability === "t2i"), true, "image gen in nodes");
const vendors = open[2].rows.map((r) => `${r.vendor}:${r.vendorCount}`);
eq(vendors, ["higgsfield:2", "higgsfield:2", "fal:1"], "vendor counts");
eq(open[3].rows.map((r) => r.pick.templateId), ["long-video"], "flows");
const fromImage = flattenAddMenu(buildAddMenu("", { takes: "image", models, templates }));
eq(fromImage.map((r) => r.pick.capability || r.pick.kind), ["upscale", "i2i", "i2v"], "click image output");
eq(flattenAddMenu(buildAddMenu("", { chip: "3d", models, templates })), [], "3d empty");
eq(flattenAddMenu(buildAddMenu("", { chip: "library", models, templates })), [], "library empty");
eq(capabilityForModel(["t2v", "t2i"]), "t2i", "catalog order");
eq(capabilityForModel(["t2v"], "image"), null, "video model cannot take an image");
eq(flattenAddMenu(buildAddMenu("upscaler")).map((r) => r.pick.capability), ["upscale"], "search");
const runnable = (cap) => !["upscale", "tts", "lipsync", "assistant"].includes(cap);
const hosted = flattenAddMenu(buildAddMenu("", { models, templates, canAdd: runnable })).map((r) => r.pick.capability);
eq(["upscale", "tts", "lipsync", "assistant"].filter((cap) => hosted.includes(cap)), [], "a host hides nodes no model runs");
eq(["media", "t2i", "text", "note"].every((cap) => hosted.includes(cap)), true, "runnable and model-free nodes stay");
const textNode = { id: "copy", type: "transform", capability: "text", params: { prompt: "hi" } };
const mixed = { nodes: [still, textNode], edges: [] };
eq(runtimeGraph(mixed).nodes.map((n) => n.id), ["still"], "text stays off the runtime");
""")


def test_wires_are_orthogonal_with_rounded_corners() -> None:
    _check("""
const d = curve(0, 10, 200, 80);
if (d.includes(" C") || / C[0-9]/.test(d)) throw new Error("bezier leftover: " + d);
if (!d.includes(" Q")) throw new Error("needs rounded corners: " + d);
    eq(d.slice(0, 2), "M0", "starts at the output");
    const nums = (s) => [...s.matchAll(/-?\\d+(?:\\.\\d+)?/g)].map((m) => Number(m[0]));
    eq(nums(d).slice(-2), [200, 80], "ends at the input");
    const flat = curve(0, 10, 120, 10);
    eq(flat, "M0 10 L120 10", "level wire is a line");
    const a = { id: "v", type: "generate", capability: "t2v", x: 0, y: 0 };
    const b = { id: "ls", type: "generate", capability: "lipsync", x: 400, y: 0 };
    eq(nums(wirePath(a, b, "video")).slice(-2), [400, portY(0)], "first input");
""")


def test_up_to_here_excludes_downstream() -> None:
    """Toolbar scope: up to here is the node and what feeds it, never what follows."""
    _check("""
let g = connect(base, "still", "up").graph;
g = connect(g, "up", "anim").graph;
const prices = { still: 0.04, up: 0.1, anim: 0.5 };
const price = (n) => prices[n.id];
eq(scopeNodes(g, ["up"], "upstream").sort(), ["still", "up"], "up to here");
eq(estimateScope(g, ["up"], price, "upstream"), { nodes: 2, total: 0.14, unpriced: 0 }, "anim stays out of the total");
eq(scopeNodes(g, ["up"], "node"), ["up"], "this node only");
eq(scopeNodes(g, ["up"], "page").sort(), ["anim", "still", "up"], "whole page");
eq([...runSet(g, ["up"])].sort(), ["still", "up"], "card run still includes ancestors");
eq([...runSet(g, ["up"], true)], ["up"], "solo stays this node only");
""")


def test_instances_follow_the_source_until_it_is_deleted() -> None:
    _check("""
let g = instanceNodes({ nodes: [still], edges: [] }, ["still"], ["copy"]);
eq(g.nodes.find((n) => n.id === "copy").instanceOf, "still", "linked to the source");
g = setParams(g, "copy", { prompt: "oak" });
eq(param(g, "still", "prompt"), "oak", "an instance edit writes through");
g = setParams(g, "still", { prompt: "pine" });
eq(param(g, "copy", "prompt"), "pine", "a source edit copies onto the instance");
const dup = duplicateNode(g, "copy", "dup");
eq(dup.nodes.find((n) => n.id === "dup").instanceOf, undefined, "duplicate is not linked");
const gone = removeNodes(g, ["still"]);
eq(gone.nodes.find((n) => n.id === "copy").instanceOf, undefined, "deleting the source detaches the copy");
eq(toWorkflowNodes(g.nodes).every((n) => n.instanceOf == null), true, "instanceOf stays off /runs");
""")


def test_edge_style_is_canvas_only() -> None:
    _check("""
const curved = connect(base, "still", "up", "media", "curve");
eq(curved.graph.edges[0].style, "curve", "curve is stored");
const round = connect(base, "still", "up", "media", "rounded");
eq(round.graph.edges[0].style, undefined, "rounded is omitted");
eq(runtimeGraph(curved.graph).edges[0].style, undefined, "style is stripped before /runs");
const a = curved.graph.nodes.find((n) => n.id === "still");
const b = { ...curved.graph.nodes.find((n) => n.id === "up"), x: 400, y: 80 };
if (!wirePath(a, b, "media", "curve").includes(" C")) throw new Error("curve path");
const straight = wirePath(a, b, "media", "straight");
if (!straight.includes("L") || straight.includes("C") || straight.includes("Q")) throw new Error("straight path " + straight);
eq(shortcutFor({ key: "c" }), "comment", "c places a comment");
eq(shortcutFor({ key: "d" }), "fit", "plain d still fits");
""")


def test_text_nodes_are_inlined_before_a_run() -> None:
    """COREPRODUC-640: a Text node wired into Image Gen failed ("needs the output of text-…")."""
    _check("""
const text = { id: "text-1", type: "transform", capability: "text", params: { prompt: "a red fox" } };
const img = gen("img", "t2i", { prompt: "{{inputs.prompt}}" });
let g = connect({ nodes: [text, img], edges: [] }, "text-1", "img").graph;
eq(param(g, "img", "prompt"), nodeRef("text-1"), "wire into an empty prompt");
const filled = inlineText(g);
eq(param(filled, "img", "prompt"), "a red fox", "text is in the prompt");
eq(runtimeGraph(filled).nodes.map((n) => n.id), ["img"], "the Text node stays off the runtime");
eq(param(g, "img", "prompt"), nodeRef("text-1"), "the canvas keeps the wire");
eq(unrunnableSource(filled, ["img"]), null, "nothing left to run on the canvas");
const ask = { id: "ask", type: "transform", capability: "assistant", params: { prompt: "write" } };
const g2 = { nodes: [ask, gen("v", "t2i", { prompt: nodeRef("ask") })], edges: [{ src: "ask", dst: "v" }] };
eq(unrunnableSource(inlineText(g2), ["v"])?.id, "ask", "an Assistant cannot feed a run yet");
""")


def test_text_wire_keeps_the_typed_prompt() -> None:
    """COREPRODUC-642 (STU-21): wiring a Text node replaced the prompt typed in Image Gen."""
    _check("""
const text = { id: "t", type: "transform", capability: "text", params: { prompt: "at dusk" } };
const img = gen("img", "t2i", { prompt: "a lighthouse" });
let g = connect({ nodes: [text, img], edges: [] }, "t", "img").graph;
eq(param(g, "img", "prompt"), "a lighthouse\\n" + nodeRef("t"), "typed text stays, wire after it");
eq(connect(g, "t", "img").graph, g, "same wire again is a no-op");
eq(param(inlineText(g), "img", "prompt"), "a lighthouse\\nat dusk", "the run reads both");
const cut = disconnect(g, "t", "img");
eq(param(cut, "img", "prompt"), "a lighthouse", "unwire keeps the typed text");
eq(cut.edges, [], "no edge left");
const made = addNode({ nodes: [text], edges: [] }, gen("new", "t2i", { prompt: "seeded page prompt" }), "t");
eq(param(made, "new", "prompt"), nodeRef("t"), "a node made from the Text output takes the wire alone");
""")


def test_count_expands_into_seeded_copies() -> None:
    """COREPRODUC-642 (STU-06): count 2 sent one job, gave 1 picture and showed the price of 1."""
    _check("""
const src = gen("src", "t2i", { prompt: "p" });
const two = gen("two", "i2v", { image: nodeRef("src"), count: 2, num_images: 2 });
const out = expandCounts({ nodes: [src, two], edges: [{ src: "src", dst: "two", input_key: "image" }] }, 100);
eq(out.nodes.map((n) => n.id), ["src", "two", "two-copy2"], "one node per output");
eq(out.nodes.slice(1).map((n) => n.params.seed), [100, 101], "own seeds");
eq(out.nodes[1].params.count, undefined, "count is gone");
eq(out.nodes[2].params.num_images, undefined, "num_images is gone");
eq(out.edges.map((e) => e.dst), ["two", "two-copy2"], "copies keep their inputs");
const seeded = expandCounts({ nodes: [gen("s", "t2i", { seed: 7, count: 2 })], edges: [] }, 100);
eq(seeded.nodes.map((n) => n.params.seed), [7, 8], "a set seed counts up");
const one = gen("one", "t2i", { count: 1 });
eq(expandCounts({ nodes: [one], edges: [] }, 1).nodes[0], one, "count 1 is unchanged");
""")
