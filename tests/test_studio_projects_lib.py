"""Studio projects in the Studio (COREPRODUC-702): apps/studio/lib/projects.ts.

The tab's project comes from the URL, then the project opened last, then the default one; every
feed read and every new run and upload carries it.
"""

from __future__ import annotations

from ts_module import run_ts

NAMES = [
    "pickProject",
    "projectFromSearch",
    "projectHref",
    "withProject",
    "runBody",
    "uploadForm",
    "filterProjects",
    "setCurrentProject",
    "currentProject",
    "projectKey",
]
SETUP = """
function eq(got, want, what) {
  if (JSON.stringify(got) !== JSON.stringify(want)) throw new Error(what + ": " + JSON.stringify(got));
}
const p = (id, extra = {}) => ({ id, name: id, default: false, board_rev: 0, archived_at: null, updated_at: "2026-11-18", ...extra });
const mine = p("default", { name: "My work", default: true, updated_at: "2026-11-01" });
const ads = p("ads", { name: "Summer ads", updated_at: "2026-11-17" });
const old = p("old", { name: "Old reel", archived_at: "2026-11-02" });
const all = [mine, ads, old];
"""


def _check(body: str) -> None:
    result = run_ts("apps/studio/lib/projects.ts", NAMES, SETUP + body)
    assert result.returncode == 0, result.stderr or result.stdout


def test_the_url_project_wins_then_the_last_then_the_default() -> None:
    _check("""
eq(pickProject(all, "ads", "default").id, "ads", "the URL's project");
eq(pickProject(all, "", "ads").id, "ads", "no URL: the project opened last");
eq(pickProject(all, "nope", "").id, "default", "unknown: the default project");
eq(pickProject(all, "old", "old").id, "default", "an archived project does not open");
eq(pickProject([], "", ""), null, "no projects");
eq(projectFromSearch("?page=video&project=ads"), "ads", "query value");
eq(projectFromSearch(""), "", "none");
""")


def test_the_project_goes_in_the_url_and_keeps_the_page() -> None:
    _check("""
eq(projectHref("https://app.test/studio#canvas/timeline", "ads"), "https://app.test/studio?project=ads#canvas/timeline", "added");
eq(projectHref("https://app.test/studio?project=old&x=1#image", "ads"), "https://app.test/studio?project=ads&x=1#image", "replaced");
""")


def test_reads_and_new_work_carry_the_project_only_when_projects_are_on() -> None:
    _check("""
setCurrentProject(null);
eq(withProject("/runs"), "/runs", "off: unchanged");
eq(runBody({ skill: "s" }), { skill: "s" }, "off: no project_id");
eq(uploadForm(new Blob(["x"])).has("project_id"), false, "off: no form field");
setCurrentProject("a b");
eq(currentProject(), "a b", "current");
eq(withProject("/runs"), "/runs?project=a%20b", "first query value");
eq(withProject("/library?tool=image"), "/library?tool=image&project=a%20b", "added to a query");
eq(runBody({ skill: "s" }), { skill: "s", project_id: "a b" }, "run body");
eq(uploadForm(new Blob(["x"]), "x.png").get("project_id"), "a b", "upload form");
""")


def test_the_switcher_lists_open_projects_last_changed_first() -> None:
    _check("""
eq(filterProjects(all, "").map((row) => row.id), ["ads", "default"], "no archived, newest first");
eq(filterProjects(all, "summer ADS").map((row) => row.id), ["ads"], "every word, any case");
eq(filterProjects(all, "reel"), [], "archived stays out of a search");
""")


def test_each_named_project_keeps_its_own_browser_storage() -> None:
    _check("""
setCurrentProject(null);
eq(projectKey("k"), "k", "off: the plain key");
setCurrentProject("mine", true);
eq(projectKey("k"), "k", "My work: the plain key, so what it kept before projects stays");
setCurrentProject("ads");
eq(projectKey("k"), "k:ads", "a named project: its own key");
""")
