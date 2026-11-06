"""Library + @mentions. Acceptance: same list on Image/Video/canvas; chosen refs go out."""

from __future__ import annotations

from ts_module import ROOT, run_ts

MODULE = "apps/studio/lib/library.ts"
NAMES = [
    "CUSTOM_TABS",
    "LIBRARY_TABS",
    "MENTION_KINDS",
    "REF_TABS",
    "asCastRow",
    "asLibraryItem",
    "createLibraryItem",
    "filterMentions",
    "insertMention",
    "itemsForTab",
    "kindFromLegacy",
    "mentionOpen",
    "mentionRefs",
    "mentionRole",
    "mentionableItems",
    "mentionedItems",
    "parseLibraryStore",
    "providerMentionInputs",
    "serializeLibraryStore",
    "tabKind",
    "upsertLibraryItem",
]


def _run(body: str):
    return run_ts(MODULE, NAMES, body)


def test_tabs_match_magnific_not_invented() -> None:
    script = """
if (REF_TABS.map((r) => r.id).join() !== "characters,elements,styles,locations,brand-kit") {
  throw new Error("ref tabs " + REF_TABS.map((r) => r.id));
}
if (CUSTOM_TABS.map((r) => r.id).join() !== "templates,flows") throw new Error("custom tabs");
if (LIBRARY_TABS.includes("color")) throw new Error("do not invent Color");
if (MENTION_KINDS.join() !== "character,element,style,location") throw new Error("mention kinds");
if (tabKind("characters") !== "character" || tabKind("flows") !== null) throw new Error("tab kind");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_create_is_name_plus_one_to_eight_images() -> None:
    script = """
const empty = createLibraryItem({ name: "", kind: "character", refs: ["a"] });
if (empty.ok) throw new Error("nameless");
const none = createLibraryItem({ name: "Soldier", kind: "character", refs: [] });
if (none.ok) throw new Error("no refs");
const too = createLibraryItem({ name: "Soldier", kind: "character", refs: ["1","2","3","4","5","6","7","8","9"] });
if (!too.ok || too.item.refs.length !== 8) throw new Error("cap 8");
const ok = createLibraryItem({ name: " Soldier ", kind: "character", refs: ["a", "a", "b"] });
if (!ok.ok || ok.item.name !== "Soldier" || ok.item.refs.join() !== "a,b") throw new Error("dedupe");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_legacy_prop_becomes_element_and_mentions_filter() -> None:
    script = """
if (kindFromLegacy("prop") !== "element") throw new Error("prop");
const item = asLibraryItem({ name: "Vase", assetId: "v1", kind: "prop" });
if (item.kind !== "element" || item.refs.join() !== "v1") throw new Error(JSON.stringify(item));
const brand = asLibraryItem({ name: "Logo", refs: ["l1"], kind: "brand" });
const rows = mentionableItems([item, brand, asLibraryItem({ name: "Soldier", refs: ["s1","s2"], kind: "character" })]);
if (rows.map((r) => r.name).join() !== "Vase,Soldier") throw new Error("brand leaked " + rows.map((r) => r.name));
if (!mentionOpen("hello @so", 8)) throw new Error("open");
if (mentionOpen("hello @so there", 15)) throw new Error("closed");
const next = insertMention("hello @so", 8, "Soldier");
if (next.text !== "hello @Soldier") throw new Error(next.text);
    const hits = filterMentions(rows, "hello @so", 9);
    if (hits.map((r) => r.name).join() !== "Soldier") throw new Error("filter " + hits.map((r) => r.name));
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_chosen_character_refs_go_to_provider_request() -> None:
    script = """
const items = [
  asLibraryItem({ name: "Soldier", refs: ["s1", "s2"], kind: "character" }),
  asLibraryItem({ name: "Room", refs: ["r1"], kind: "location" }),
  asLibraryItem({ name: "Unused", refs: ["u1"], kind: "character" }),
];
const refs = mentionRefs("a portrait of @Soldier in @Room", items, ["extra"]);
if (refs.join() !== "extra,s1,s2,r1") throw new Error("refs " + refs);
const unused = mentionRefs("no one", items, []);
if (unused.length) throw new Error("all-cast leak " + unused);
const soul = asLibraryItem({ name: "Hero", refs: ["h1"], kind: "character", soulId: "soul-9" });
const mapped = providerMentionInputs("@Hero", [soul], { id: "higgsfield:soul-character:2026-09", provider: "higgsfield" });
if (mapped.image_urls.join() !== "h1" || mapped.soul_id !== "soul-9") throw new Error(JSON.stringify(mapped));
const mock = providerMentionInputs("@Hero", [soul], { id: "mock:png:v1", provider: "mock" });
if (mock.soul_id) throw new Error("invented soul on mock");
if (mentionRole("style") !== "style" || mentionRole("character") !== "character") throw new Error("role");
const listed = mentionedItems("@Soldier @missing", items);
if (listed.map((r) => r.name).join() !== "Soldier") throw new Error("mentioned");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_store_roundtrip_and_upsert() -> None:
    script = """
const a = asLibraryItem({ name: "Soldier", refs: ["s1"], kind: "character" });
const raw = serializeLibraryStore([a]);
const back = parseLibraryStore(raw);
if (back[0].name !== "Soldier" || back[0].refs.join() !== "s1") throw new Error("store");
if (parseLibraryStore("nope").length) throw new Error("bad json");
const next = upsertLibraryItem(back, asLibraryItem({ name: "Soldier", refs: ["s2"], kind: "character" }));
if (next.length !== 1 || next[0].refs.join() !== "s2") throw new Error("upsert");
if (itemsForTab(next, "characters").length !== 1) throw new Error("tab");
if (itemsForTab(next, "styles").length) throw new Error("other tab");
const row = asCastRow(next[0]);
if (row.assetId !== "s2" || row.kind !== "character") throw new Error("cast row");
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_studio_wires_shared_popover_and_library_page() -> None:
    client = (ROOT / "apps" / "studio" / "app" / "studio-client.tsx").read_text(encoding="utf-8")
    assert "LibraryPage" in client
    assert "providerMentionInputs" in client
    assert "withMentionRefs" in client
    assert "PromptMention" in client
    bar = (ROOT / "apps" / "studio" / "app" / "image-prompt-bar.tsx").read_text(encoding="utf-8")
    assert "image-elements" in bar
    panel = (ROOT / "apps" / "studio" / "app" / "video-panel.tsx").read_text(encoding="utf-8")
    assert "PromptMention" in panel
    card = (ROOT / "apps" / "studio" / "app" / "canvas-node-card.tsx").read_text(encoding="utf-8")
    assert "PromptMention" in card
    assert "canvas-mention" in card
    page = (ROOT / "apps" / "studio" / "app" / "library-page.tsx").read_text(encoding="utf-8")
    assert "library-tab-${row.id}" in page
    assert "References" in page and "Custom" in page
    lib = (ROOT / "apps" / "studio" / "lib" / "library.ts").read_text(encoding="utf-8")
    assert "Add 1 to 8 images." in lib
    assert "Characters" in lib and "Brand kit" in lib
    assert "Templates" in lib and "Flows" in lib
    for tab in ("characters", "elements", "styles", "locations", "brand-kit", "templates", "flows"):
        assert f'"{tab}"' in lib
