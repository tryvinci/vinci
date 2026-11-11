"""OLF v0.1 engine tests: conformance sample, merge and hash rules, validation, demo render."""

from __future__ import annotations

import re
import shutil
import struct
from pathlib import Path
from typing import Any

import pytest
from vinci_olf import OlfError, canonical, inputs_hash, load, merge, resolve, stale, validate
from vinci_olf.project import read

SAMPLE = Path(__file__).resolve().parents[1] / "conformance" / "tidewatch"
EXPECTED = read(SAMPLE.parent / "tidewatch.expected.yaml")
MIRA = "bible/characters/mira/mira.yaml"
SCENE = "episodes/e02/scenes/s03.yaml"


@pytest.fixture
def show(tmp_path: Path) -> Path:
    """A writable copy of the conformance sample."""
    return Path(shutil.copytree(SAMPLE, tmp_path / "show"))


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_conformance_sample_validates_and_resolves_as_expected() -> None:
    p = load(SAMPLE)
    assert [str(i) for i in validate(p)] == []
    assert sorted(EXPECTED) == sorted(k for k in p.docs if p.kind(k) == "shot")
    for shot_id, want in EXPECTED.items():
        view = resolve(p, shot_id)
        assert view == want["resolved"], shot_id
        assert {k: inputs_hash(view, k) for k in want["inputs_hash"]} == want["inputs_hash"], (
            shot_id
        )


def test_merge_rules() -> None:
    assert merge({"a": 1, "m": {"x": 1, "y": 2}}, {"a": 2, "m": {"y": 3}}) == {
        "a": 2,
        "m": {"x": 1, "y": 3},
    }
    assert merge({"l": [1, 2]}, {"l": [3]}) == {"l": [3]}  # lists replace
    assert merge({"l": ["a", "b"]}, {"l": {"$append": ["c", "a"], "$remove": ["b"]}}) == {
        "l": ["a", "c"]
    }
    assert merge({}, {"l": {"$append": ["x"]}}) == {"l": ["x"]}  # an op with nothing above


def test_canonical_json_matches_rfc8785_vectors() -> None:
    vectors = {  # RFC 8785 Appendix B: IEEE-754 bits -> text
        "0000000000000000": "0",
        "8000000000000000": "0",
        "0000000000000001": "5e-324",
        "7fefffffffffffff": "1.7976931348623157e+308",
        "4340000000000000": "9007199254740992",
        "4430000000000000": "295147905179352830000",
        "44b52d02c7e14af5": "9.999999999999997e+22",
        "44b52d02c7e14af6": "1e+23",
        "3eb0c6f7a0b5ed8d": "0.000001",
        "3eb0c6f7a0b5ed8c": "9.999999999999997e-7",
        "41b3de4355555553": "333333333.3333332",
        "444b1ae4d6e2ef50": "1e+21",
        "444b1ae4d6e2ef4f": "999999999999999900000",
    }
    for bits, text in vectors.items():
        assert canonical(struct.unpack(">d", bytes.fromhex(bits))[0]) == text
    # Keys sort by UTF-16 code units, so U+20AC comes before U+1F600 (a surrogate pair).
    assert (
        canonical({"\U0001f600": 2, "€": 1, "b": [4.0, True, None]})
        == '{"b":[4,true,null],"€":1,"😀":2}'
    )


def test_yaml_12_reads_aspect_as_text(tmp_path: Path) -> None:
    path = tmp_path / "x.yaml"
    path.write_text("aspect: 16:9\nloop: no\n", encoding="utf-8")
    assert read(path) == {"aspect": "16:9", "loop": "no"}  # PyYAML (YAML 1.1) gives 969 and False


def test_hash_rules(show: Path) -> None:
    def hashes() -> dict[str, str]:
        view = resolve(load(show), "e02/s03/sh014")
        return {k: inputs_hash(view, k) for k in ("keyframe", "video", "audio")}

    before = hashes()
    edit(show / SCENE, "duration: 4s", "duration: 4.0s")  # same duration, other spelling
    edit(show / MIRA, 'owner: "@creator" }', 'owner: "@other" }')  # credits never render
    edit(
        show / SCENE,
        "first_frame: keyframe      #",
        "first_frame: keyframe\n    select: { keyframe: kf9 }  #",
    )
    assert hashes() == before
    edit(show / SCENE, "move: push_in }", "move: static }")
    after = hashes()
    assert after["keyframe"] == before["keyframe"] and after["video"] != before["video"]
    edit(show / SCENE, "delivery: whisper", "delivery: shout")
    assert hashes()["audio"] != before["audio"]


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    [
        (SCENE, "location: loc/lighthouse", "location: loc/attic", "unknown reference loc/attic"),
        (SCENE, "lens: 50mm", "lens: 40mm", "lens 40mm is not in style.lenses"),
        (
            SCENE,
            "outfits: { char/mira: night }",
            "outfits: { char/mira: gala }",
            "has no outfit named 'gala'",
        ),
        (
            "bible/style.yaml",
            "references: [asset/2f58f14c",
            "references: [asset/2f58f1, asset/2f58f14c",
            "full 64-character",
        ),
        (
            MIRA,
            "textures: [textures/snowflake.png]",
            "textures: [../../../../escape.png]",
            "outside the project",
        ),
        (MIRA, "eyes: details/eyes.png", "eyes: sheet.png#eyes", "not a crop"),
        (SCENE, "delivery: whisper", "delivery: whisper, extra: 1", "Additional properties"),
    ],
)
def test_validate_reports_errors(show: Path, path: str, old: str, new: str, message: str) -> None:
    edit(show / path, old, new)
    errors = [str(i) for i in validate(load(show)) if i.level == "error"]
    assert any(message in e for e in errors), errors


def _demo_engine(tmp_path: Path, monkeypatch: Any) -> Any:
    """A Vinci runtime in demo mode: mock models only, $0, no live spend."""
    from vinci_runtime.engine import Engine

    monkeypatch.delenv("VINCI_ALLOW_LIVE_SPEND", raising=False)
    engine = Engine(tmp_path / "home")
    engine.init_home(demo=True)
    return engine


def test_demo_render_writes_takes_and_tracks_staleness(
    show: Path, tmp_path: Path, monkeypatch: Any
) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("the mock video model runs ffmpeg")
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    plan = render(load(show), "e02/s03/sh014", engine=engine, dry_run=True)
    assert [r["model"] for r in plan["plan"]] == ["mock:png:v1", "mock:mp4:v1"] and plan[
        "takes"
    ] == []
    assert not (show / "takes").exists()  # a dry run stages, runs and writes nothing
    result = render(load(show), "e02/s03/sh014", engine=engine)
    assert result["takes"] == ["e02/s03/sh014/kf1", "e02/s03/sh014/v1"] and result["total"] == 0
    p = load(show)
    video = p.docs["e02/s03/sh014/v1"].data
    assert video["inputs"] == {"first_frame": "e02/s03/sh014/kf1"} and video["status"] == "draft"
    assert (
        video["provenance"]["model"] == "mock:mp4:v1" and video["provenance"]["cost"]["amount"] == 0
    )
    sheet = EXPECTED["e02/s03/sh014"]["resolved"]["characters"][0]["sheet"]
    assert p.docs["e02/s03/sh014/kf1"].data["inputs"]["references"][0] == sheet  # the whole sheet
    assert [
        str(i) for i in validate(p) if i.level == "error"
    ] == []  # takes and lock entries are valid
    assert not stale(p, "e02/s03/sh014/kf1") and not stale(p, "e02/s03/sh014/v1")
    from vinci_olf.api import summary

    bible = summary(p)["bible"]
    mira = bible["character"][0]
    # The render locked the sheet, so its license comes from the lock file now.
    assert mira["impact"] == 2 and mira["license"]["owner"] == "@creator"
    assert bible["voice"][0]["impact"] == 1  # a voice is in video and audio hashes only
    edit(show / SCENE, "move: push_in }", "move: static }")
    p = load(show)
    assert not stale(p, "e02/s03/sh014/kf1") and stale(p, "e02/s03/sh014/v1")
    edit(show / MIRA, "large tail.", "large white tail.")
    assert stale(load(show), "e02/s03/sh014/kf1")


def test_paid_render_stops_without_yes(show: Path, monkeypatch: Any) -> None:
    from types import SimpleNamespace

    import vinci_core.cost
    from vinci_olf.render import render

    price = SimpleNamespace(amount=0.42)
    priced = SimpleNamespace(id="paid:model", provider="wavespeed", pricing=price)
    row = {"node_id": "video", "model": priced, "estimate": SimpleNamespace(amount=0.42)}
    monkeypatch.setattr(vinci_core.cost, "plan_workflow", lambda *a, **k: [row])
    engine = SimpleNamespace(
        config=SimpleNamespace(preference=None),
        routing_providers=lambda: {"wavespeed"},
        catalog=lambda: None,
        start_run=lambda *a, **k: pytest.fail("a paid render must not start without --yes"),
    )
    # A storyboard control is not staged, so the fake engine needs no CAS.
    edit(
        show / SCENE,
        "first_frame: keyframe      #",
        "storyboard: ../../../bible/props/brass-key/ref.png  #",
    )
    with pytest.raises(OlfError, match=r"costs \$0.42.*--yes"):
        render(load(show), "e02/s03/sh014", engine=engine)
    # A confirm sends the price a person saw: a plan above it stops (PR-Agent on #523).
    with pytest.raises(
        OlfError, match=r"price changed: this render costs \$0.42, more than the \$0.40"
    ):
        render(load(show), "e02/s03/sh014", engine=engine, yes=True, max_total=0.4)
    # A live model at $0 bills per token: it needs --yes too (CodeRabbit on #517). Mock stays free.
    free = SimpleNamespace(amount=0)
    row["model"] = SimpleNamespace(id="openai:img", provider="openai", pricing=free)
    row["estimate"] = SimpleNamespace(amount=0)
    with pytest.raises(OlfError, match=r"openai:img with no flat price.*--yes"):
        render(load(show), "e02/s03/sh014", engine=engine)


def test_edits_change_one_line(show: Path) -> None:
    from vinci_olf.edit import set_select, set_take

    takes = show / "takes/e02/s03"
    for take, kind in (("sh014/kf1", "keyframe"), ("sh014/v1", "video"), ("sh016/kf1", "keyframe")):
        (takes / take).parent.mkdir(parents=True, exist_ok=True)
        (takes / f"{take}.yaml").write_text(
            f"id: e02/s03/{take}\nkind: {kind}\nstatus: draft\noutput: asset/{'0' * 64}\n"
            "provenance:\n  provider: mock\n  model: m\n  created: '2026-11-08T00:00:00Z'\n",
            encoding="utf-8",
        )
    scene, split = show / SCENE, show / "episodes/e02/scenes/s03/sh016.yaml"
    before = {path: path.read_text(encoding="utf-8") for path in (scene, split)}
    assert set_select(load(show), "e02/s03/sh014", keyframe="kf1", video="v1") == {
        "keyframe": "kf1",
        "video": "v1",
    }
    assert set_select(load(show), "e02/s03/sh016", keyframe="kf1") == {"keyframe": "kf1"}
    for path, text in before.items():
        added = set(path.read_text(encoding="utf-8").splitlines()) - set(text.splitlines())
        assert len(path.read_text(encoding="utf-8").splitlines()) == len(text.splitlines()) + 1, (
            path
        )
        assert all("select: { keyframe: kf1" in line for line in added), added
    assert resolve(load(show), "e02/s03/sh014")["select"] == {"keyframe": "kf1", "video": "v1"}
    set_select(load(show), "e02/s03/sh014", keyframe=None, video=None)
    set_select(load(show), "e02/s03/sh016", keyframe=None)
    assert {path: path.read_text(encoding="utf-8") for path in before} == before  # byte for byte
    take = set_take(
        load(show), "e02/s03/sh014/v1", status="approved", notes="Good: slight flicker."
    )
    assert (take["status"], take["notes"]) == ("approved", "Good: slight flicker.")
    for bad in ({"video": "v9"}, {"keyframe": "v1"}, {"take": "kf1"}):
        with pytest.raises(OlfError):
            set_select(load(show), "e02/s03/sh014", **bad)
    with pytest.raises(OlfError, match="status must be one of"):
        set_take(load(show), "e02/s03/sh014/v1", status="great")


def test_api_views() -> None:
    from vinci_olf.api import shot_detail, summary

    view = summary(load(SAMPLE))
    assert view["issues"] == [] and view["title"] == "Tidewatch"
    assert view["episodes"][0]["scenes"][0]["shots"] == [
        "e02/s03/sh014",
        "e02/s03/sh015",
        "e02/s03/sh016",
    ]
    mira = next(row for row in view["bible"]["character"] if row["id"] == "char/mira")
    assert mira["used_in"] == ["e02/s03/sh014", "e02/s03/sh015"]  # sh016 removes her
    assert mira["files"]["details/eyes.png"] == "bible/characters/mira/details/eyes.png"
    assert mira["file"] == "bible/characters/mira/mira.yaml" and mira["forms_usage"] == {
        "winter": 1,
        "ember": 1,
    }
    assert mira["impact"] == 0 and mira["license"] is None  # no takes yet, nothing locked yet
    assert view["style"]["file"] == "bible/style.yaml"
    # The scene line: the episode sets the form, the scene's outfit beats the season's.
    looks = view["episodes"][0]["scenes"][0]["looks"]
    assert looks == {"char/mira": {"form": "winter", "outfit": "night"}}
    detail = shot_detail(load(SAMPLE), "e02/s03/sh014")
    assert detail["references"][0] == {  # winter has no front view: the whole sheet
        "asset": detail["resolved"]["characters"][0]["sheet"],
        "file": "bible/characters/mira/sheet.png",
    }
    assert detail["hashes"]["video"] is None  # waits for a selected keyframe
    origins = detail["origins"]
    assert origins["forms"] == {"char/mira": "episode"}
    assert origins["outfits"] == {"char/mira": "scene"}
    assert (origins["style"], origins["location"], origins["camera"]) == ("season", "scene", "shot")
    assert detail["hashes"]["keyframe"] == EXPECTED["e02/s03/sh014"]["inputs_hash"]["keyframe"]
    assert detail["prompts"]["video"].endswith('Mira Sol (whisper) says: "You kept the key?".')


def test_season_level(show: Path) -> None:
    def look(shot: str = "e02/s03/sh014") -> tuple[str, str]:
        view = resolve(load(show), shot)
        return view["style"]["look"]["grain"], view["characters"][0]["outfit"]["name"]

    assert look() == (
        "medium",
        "night",
    )  # the season sets grain; the scene's outfit beats the season's
    season = show / "seasons/01.yaml"
    edit(season, "episodes: [e02]", "episodes: [e01]")
    errors = [str(i) for i in validate(load(show)) if i.level == "error"]
    assert any("episode e01 is missing" in e for e in errors), errors
    edit(season, "episodes: [e01]", "episodes: []")
    assert look() == ("light", "night")  # no season lists e02: no season level
    edit(season, "episodes: []", "episodes: [e02]")
    (show / "seasons/02.yaml").write_text("id: season/02\nepisodes: [e02]\n", encoding="utf-8")
    errors = [str(i) for i in validate(load(show)) if i.level == "error"]
    assert any("e02 is also in season/01" in e for e in errors), errors


def test_malformed_files_are_issues_not_crashes(show: Path) -> None:
    from vinci_olf.api import summary
    from vinci_olf.render import render

    # Found by PR-Agent on #517: the extra rules assumed shapes the schema had already rejected.
    edit(show / "episodes/e02/episode.yaml", "forms: { char/mira: winter }", "forms: winter")
    edit(show / "episodes/e02/episode.yaml", "scenes: [e02/s03]", "scenes: [e02/s03]\ncut: [x]")
    edit(show / "seasons/01.yaml", "episodes: [e02]", "episodes: 2")
    view = summary(load(show))
    errors = {i["message"] for i in view["issues"] if i["level"] == "error"}
    assert {
        "forms: 'winter' is not of type 'object'",
        "cut.0: 'x' is not of type 'object'",
        "episodes: 2 is not of type 'array'",
    } <= errors
    assert view["shots"]["e02/s03/sh014"]["error"] == "fix the errors on the issues page"
    with pytest.raises(OlfError, match="kind must be keyframe, video or audio"):
        render(load(show), "e02/s03/sh014", kind="music", dry_run=True)


def test_untrusted_files_cannot_crash_or_escape(show: Path, tmp_path: Path) -> None:
    # Found by CodeRabbit on #517: a project can come from someone you do not trust. (Its crop
    # findings went away with sheet crops on 2026-11-09.)
    edit(show / MIRA, "  ember:", "  style:")  # a form named like the style document
    validate(load(show))  # raised TypeError (unhashable dict)
    # Billion laughs: each anchor lists the one before it ten times (10**8 values at h).
    levels = zip("abcdefg", "bcdefgh", strict=True)
    bomb = "a: &a [x, x, x, x, x, x, x, x, x, x]\n" + "".join(
        f"{c}: &{c} [{', '.join([f'*{b}'] * 10)}]\n" for b, c in levels
    )
    (show / "bible/props/bell/bell.yaml").write_text(bomb, encoding="utf-8")
    (show / "assets/lock.yaml").write_text("asset/x: [unclosed\n", encoding="utf-8")
    problems = load(show).problems
    assert any("bell.yaml: cannot read: more than 100000 values" in x for x in problems)
    assert any("lock.yaml: cannot read" in x for x in problems)
    (show / "project.yaml").write_text("spec: [olf/0.1\n", encoding="utf-8")
    with pytest.raises(OlfError, match="project.yaml: cannot read"):
        load(show)


def _take(show: Path, take_id: str, kind: str, status: str = "approved") -> None:
    """Write a minimal take file (no asset): enough for the cut, which only names takes."""
    path = show / "takes" / f"{take_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"id: {take_id}\nkind: {kind}\nstatus: {status}\noutput: asset/{'0' * 64}\n",
        encoding="utf-8",
    )


def test_cut_edits_and_timeline(show: Path) -> None:
    from vinci_olf.cut import cut_view, use_approved
    from vinci_olf.edit import set_clip

    episode = show / "episodes/e02/episode.yaml"
    before = episode.read_text(encoding="utf-8")
    with pytest.raises(OlfError, match="no approved takes yet"):
        use_approved(load(show), "e02")
    _take(show, "e02/s03/sh014/v1", "video")
    _take(show, "e02/s03/sh014/v2", "video", status="rejected")
    _take(show, "e02/s03/sh015/kf1", "keyframe")  # no approved video: the still goes in the cut
    rows = use_approved(load(show), "e02")
    assert rows == [{"take": "e02/s03/sh014/v1"}, {"take": "e02/s03/sh015/kf1"}]
    after = episode.read_text(encoding="utf-8")
    assert after.startswith(before) and after.endswith(
        "cut:\n  - { take: e02/s03/sh014/v1 }\n  - { take: e02/s03/sh015/kf1 }\n"
    )  # only the cut block is new
    set_clip(load(show), "e02", 1, transition="fade", out=2)
    assert "  - { take: e02/s03/sh015/kf1, out: 2s, transition: fade }\n" in episode.read_text(
        encoding="utf-8"
    )
    view = cut_view(load(show), "e02")
    first, second = view["clips"]
    assert (first["kind"], first["length"], first["start"]) == ("video", 4.0, 0.0)  # the shot's 4s
    assert (second["kind"], second["start"], second["transition"]) == (
        "keyframe",
        3.5,
        "fade",
    )  # 0.5s overlap
    assert view["duration"] == 5.5 and first["dialogue"][0]["line"] == "You kept the key?"
    assert view["file"] == "episodes/e02/episode.yaml" and view["format"] == {
        "resolution": "1920x1080",
        "fps": 24,
    }
    set_clip(load(show), "e02", 1, transition=None)  # back to the default cut
    assert cut_view(load(show), "e02")["clips"][1]["start"] == 4.0
    with pytest.raises(OlfError, match="no clip 3"):
        set_clip(load(show), "e02", 2, out=1)


def test_export_cut(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("export runs ffmpeg")
    from vinci_media import probe
    from vinci_olf.cut import use_approved
    from vinci_olf.edit import set_take
    from vinci_olf.export import check_licenses, export
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    render(load(show), "e02/s03/sh014", engine=engine)
    set_take(load(show), "e02/s03/sh014/v1", status="approved")
    use_approved(load(show), "e02")
    result = export(load(show), "e02")
    assert result["files"] == [
        "exports/e02/e02.srt",
        "exports/e02/e02-16x9.mp4",
        "exports/e02/e02-9x16.mp4",
    ]
    wide, tall = probe(show / result["files"][1]), probe(show / result["files"][2])
    assert (wide["width"], wide["height"], tall["width"], tall["height"]) == (
        1920,
        1080,
        1080,
        1920,
    )
    assert abs(wide["duration"] - 4.0) < 0.3 and result["subtitles"] == 1
    assert (
        "00:00:00,000 --> 00:00:04,000\nYou kept the key?"
        in (show / "exports/e02/e02.srt").read_text()
    )
    # No sound: the file has no audio stream, and a subtitle names its speaker.
    from vinci_media import has_audio

    assert has_audio(show / result["files"][1])
    silent = export(load(show), "e02", aspects=("16:9",), sound=False)["files"]
    assert not has_audio(show / silent[1])
    assert (
        "00:00:00,000 --> 00:00:04,000\nMira: You kept the key?" in (show / silent[0]).read_text()
    )
    lock = show / "assets/lock.yaml"  # a no-derivatives license stops the export
    lock.write_text(
        lock.read_text().replace("all-rights-reserved", "CC-BY-ND-4.0"), encoding="utf-8"
    )
    p = load(show)
    from vinci_olf.cut import cut_view

    assert any(
        "forbids derivatives" in problem for problem in check_licenses(p, cut_view(p, "e02"))
    )
    with pytest.raises(OlfError, match="export stopped by licenses"):
        export(p, "e02", aspects=("16:9",))


def test_api_groups_seasons() -> None:
    from vinci_olf.api import summary

    view = summary(load(SAMPLE))
    assert view["seasons"] == [
        {
            "id": "season/01",
            "title": "First Light",
            "synopsis": "Mira takes over the lamp and learns what the light keeps away.",
            "episodes": ["e02"],
        }
    ]
    assert view["episodes"][0]["season"] == "season/01"


def test_dialogue_audio_take(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg joins the dialogue lines")
    from vinci_media import probe
    from vinci_olf.render import LINE_GAP, render

    engine = _demo_engine(tmp_path, monkeypatch)
    shot, takes = "e02/s03/sh014", show / "takes/e02/s03/sh014"
    # extensions.<provider> of the planned model become parameters; core params still win.
    edit(
        show / "bible/voices/mira/mira.yaml",
        "  elevenlabs:",
        '  mock: { voice_id: mira-low, prompt: "not the line", num_images: 4 }\n  elevenlabs:',
    )
    result = render(load(show), shot, kind="audio", engine=engine)
    assert result["takes"] == [f"{shot}/a1"] and result["plan"][0]["model"] == "mock:wav:v1"
    assert result["plan"][0]["extensions"] == ["voice_id"]  # shown with the price
    p = load(show)
    take = p.docs[f"{shot}/a1"].data
    assert take["kind"] == "audio" and take["provenance"]["prompt"] == "You kept the key?"
    assert take["inputs_hash"] == inputs_hash(resolve(p, shot), "audio")
    assert (takes / "a1.wav").read_bytes()[8:12] == b"WAVE"  # mock:wav:v1 speaks a real WAV
    sent = next(job.inputs for job in engine.store.list_jobs() if job.model_id == "mock:wav:v1")
    assert sent["voice_id"] == "mira-low" and sent["prompt"] == "You kept the key?"
    assert "num_images" not in sent  # an output count is the engine's (SPEC.md rule 4)
    # Two lines make one take: the lines in order, with a short gap between them.
    edit(
        show / SCENE,
        "delivery: whisper }",
        'delivery: whisper }\n      - { speaker: char/mira, line: "All this time." }',
    )
    assert render(load(show), shot, kind="audio", engine=engine)["takes"] == [f"{shot}/a2"]
    p = load(show)
    assert p.docs[f"{shot}/a2"].data["provenance"]["prompt"] == "You kept the key?\nAll this time."
    one, two = (probe(takes / f"{name}.wav")["duration"] for name in ("a1", "a2"))
    assert two > one + LINE_GAP and stale(p, f"{shot}/a1") and not stale(p, f"{shot}/a2")
    assert [str(i) for i in validate(p) if i.level == "error"] == []
    with pytest.raises(OlfError, match="e02/s03/sh015 has no dialogue"):
        render(p, "e02/s03/sh015", kind="audio", dry_run=True, engine=engine)


def test_batch_renders(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("the mock video model runs ffmpeg")
    import vinci_olf.batch
    from vinci_olf.batch import jobs, render_batch
    from vinci_olf.edit import set_select, set_take
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    shot = "e02/s03/sh014"
    render(load(show), shot, kind="keyframe", engine=engine)
    render(load(show), shot, kind="audio", engine=engine)
    assert jobs(load(show), "e02", "stale") == jobs(load(show), "e02", "animate") == []
    set_take(load(show), f"{shot}/kf1", status="approved")
    set_select(load(show), shot, keyframe="kf1")
    plan = render_batch(load(show), "e02", mode="animate", dry_run=True, engine=engine)
    assert [(j["shot"], j["kind"], j["why"]) for j in plan["jobs"]] == [
        (shot, "video", "animate kf1")
    ]
    assert render_batch(load(show), "e02", mode="animate", engine=engine)["takes"] == [f"{shot}/v1"]
    assert jobs(load(show), "e02", "animate") == []  # v1 is a fresh video from kf1
    # The edit makes kf1, v1 and a1 stale. v1 waits: its new keyframe needs a person's choice.
    edit(show / SCENE, "toward the door.", "toward the open door.")
    edit(show / SCENE, 'line: "You kept the key?"', 'line: "You kept it?"')
    todo = [(j["kind"], j["why"]) for j in jobs(load(show), "e02", "stale")]
    assert todo == [("keyframe", "kf1 is stale"), ("audio", "a1 is stale")]
    with monkeypatch.context() as m:  # one price check for the whole batch
        fake = {"plan": [], "total": 0.21, "unpriced": [], "takes": []}
        m.setattr(
            vinci_olf.batch,
            "render",
            lambda *a, dry_run=False, **k: fake if dry_run else pytest.fail("ran without --yes"),
        )
        with pytest.raises(OlfError, match=r"costs \$0.42 for 2 renders.*--yes"):
            render_batch(load(show), "e02", mode="stale", engine=engine)
        # The Studio sends the total it confirmed; a batch that grew since then stops.
        with pytest.raises(OlfError, match=r"price changed: this batch costs \$0.42"):
            render_batch(load(show), "e02", mode="stale", yes=True, max_total=0.3, engine=engine)
    result = render_batch(load(show), "e02", mode="stale", engine=engine)
    assert result["takes"] == [f"{shot}/kf2", f"{shot}/a2"] and result["total"] == 0
    assert jobs(load(show), "e02", "stale") == []  # kf2 and a2 are fresh and wait for a choice
    with pytest.raises(OlfError, match="mode must be one of stale, animate"):
        jobs(load(show), "e02", "all")


def test_keyframe_variations(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    shot = "e02/s03/sh014"
    plan = render(load(show), shot, kind="keyframe", count=3, dry_run=True, engine=engine)
    assert [row["node"] for row in plan["plan"]] == ["keyframe", "keyframe2", "keyframe3"]
    result = render(load(show), shot, kind="keyframe", count=2, engine=engine)
    assert result["takes"] == [f"{shot}/kf1", f"{shot}/kf2"]
    p = load(show)
    one, two = (p.docs[f"{shot}/kf{n}"].data for n in (1, 2))
    assert one["output"] != two["output"]  # each variation is its own generation
    assert one["inputs_hash"] == two["inputs_hash"] and not stale(p, f"{shot}/kf2")
    with pytest.raises(OlfError, match="count must be 1 to 4"):
        render(p, shot, kind="video", count=2, dry_run=True, engine=engine)


def _loudness(path: Path, start: float, length: float) -> float:
    """Mean volume in dB of a part of a file's sound (ffmpeg volumedetect; silence is -91)."""
    import re
    import subprocess

    cmd = ["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", str(path)]
    proc = subprocess.run(
        [*cmd, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True
    )
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", proc.stderr)[1])  # type: ignore[index]


def test_export_with_separate_dialogue(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("export runs ffmpeg")
    from vinci_olf.cut import cut_view, use_approved
    from vinci_olf.edit import set_clip, set_select, set_take
    from vinci_olf.export import export
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    shot = "e02/s03/sh014"
    render(load(show), shot, engine=engine)  # kf1 and v1 (the mock video has no sound)
    render(load(show), shot, kind="audio", engine=engine)  # a1: about 1.1 s of speech
    set_take(load(show), f"{shot}/v1", status="approved")
    use_approved(load(show), "e02")
    set_clip(load(show), "e02", 0, audio="separate")
    with pytest.raises(OlfError, match="audio is separate, but the shot has no chosen dialogue"):
        export(load(show), "e02", aspects=("16:9",))
    # An approved, chosen dialogue take: "use approved takes" plays it as separate sound.
    set_take(load(show), f"{shot}/a1", status="approved")
    set_select(load(show), shot, audio="a1")
    assert use_approved(load(show), "e02") == [{"take": f"{shot}/v1", "audio": "separate"}]
    speech = cut_view(load(show), "e02")["clips"][0]["dialogue_take"]
    assert speech["take"] == f"{shot}/a1" and speech["length"] == 1.1 and speech["stale"] is False
    result = export(load(show), "e02", aspects=("16:9",), subtitles=False)
    wide = show / result["files"][0]
    # The dialogue plays from the start of the clip, then the clip's 4 s end in silence.
    assert _loudness(wide, 0.1, 0.8) > -40 > _loudness(wide, 2.0, 1.5)


def test_fit_duration() -> None:
    from types import SimpleNamespace

    from vinci_core.cost import fit_duration

    kling = SimpleNamespace(durations=[5.0, 10.0], max_duration=10)  # 5 or 10 s (API docs)
    assert [fit_duration(s, kling) for s in (2.5, 4, 5, 7.2, 12)] == [5, 5, 5, 10, 10]
    capped = SimpleNamespace(durations=[], max_duration=8)  # any length up to 8 s
    assert [fit_duration(s, capped) for s in (2.5, 8, 12)] == [3, 8, 8]
    assert fit_duration(4.2, None) == 5  # no constraints: the shot length, rounded up
    halves = SimpleNamespace(durations=[2.5, 5.5], max_duration=None)  # kept as listed (#539)
    assert [fit_duration(s, halves) for s in (2, 2.5, 3, 9)] == [2.5, 2.5, 5.5, 5.5]


def test_render_fits_the_model_duration(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("the mock video model runs ffmpeg")
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    edit(show / SCENE, "duration: 2.5s", "duration: 12s")  # sh015, longer than mock:mp4:v1 takes
    render(load(show), "e02/s03/sh015", engine=engine)
    sent = next(job.inputs for job in engine.store.list_jobs() if job.model_id == "mock:mp4:v1")
    take = load(show).docs["e02/s03/sh015/v1"].data
    assert sent["duration"] == 8 and take["duration"] == "8.0s"  # capped; the real length recorded


def test_cut_and_export_refuse_untrusted_shapes_and_paths(show: Path, tmp_path: Path) -> None:
    from vinci_olf.cut import cut_view, use_approved
    from vinci_olf.export import export

    _take(show, "e02/s03/sh014/v1", "video")  # its output asset/000... has no file in the show
    use_approved(load(show), "e02")
    # A wrong shape is an issue on the issues page, not a crash of the Cut screen.
    edit(show / SCENE, "    duration: 4s\n", "    duration: 4s\n    select: [a1]\n")
    assert cut_view(load(show), "e02")["clips"][0]["dialogue_take"] is None
    edit(show / SCENE, "    select: [a1]\n", "")
    # A lock.yaml URI that leaves the project must not become an export input.
    (tmp_path / "secret.mp4").write_bytes(b"not part of the show")
    zero = "0" * 64
    lock = show / "assets/lock.yaml"
    license_ = "{ owner: '@creator', terms: all-rights-reserved }"
    lock.write_text(
        lock.read_text()
        + f"asset/{zero}:\n  uri: ../secret.mp4\n  hash: sha256:{zero}\n  type: video/mp4\n"
        + f"  source: generated\n  license: {license_}\n",
        encoding="utf-8",
    )
    assert cut_view(load(show), "e02")["clips"][0]["file"] == "../secret.mp4"
    with pytest.raises(OlfError, match="outside the project folder"):
        export(load(show), "e02", aspects=("16:9",))


def _png(color: str, size: tuple[int, int] = (64, 32)) -> str:
    """A small PNG as base64, as the Studio uploads it."""
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_author_edits_change_only_their_lines(show: Path) -> None:
    import base64
    import difflib

    from vinci_olf.author import add_episode, add_form, add_scene, add_shot, replace_sheet, set_shot

    before = (show / SCENE).read_text(encoding="utf-8")
    shot = "e02/s03/sh014"
    set_shot(
        load(show), shot, description="Mira looks up: the door is open.", lens="35mm", move="static"
    )
    after = (show / SCENE).read_text(encoding="utf-8")
    changed = [
        line
        for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    assert changed == [
        "-    description: Mira looks up from the key toward the door.",
        "-    camera: { framing: close_up, angle: eye_level, lens: 50mm, move: push_in }",
        '+    description: "Mira looks up: the door is open."',
        "+    camera: { framing: close_up, angle: eye_level, lens: 35mm, move: static }",
    ]  # two lines; comments and the rest of the file stay as written
    assert resolve(load(show), shot)["camera"]["lens"] == "35mm"
    with pytest.raises(OlfError, match="camera.framing must be one of"):
        set_shot(load(show), shot, framing="huge")
    set_shot(load(show), "e02/s03/sh016", duration=3)  # a shot in its own file
    assert "duration: 3s\n" in (show / "episodes/e02/scenes/s03/sh016.yaml").read_text()
    new = add_shot(load(show), "e02/s03", "The door swings shut.", duration="2.5s", framing="wide")
    p = load(show)
    assert new == "e02/s03/sh020" and p.docs[new].data["camera"] == {"framing": "wide"}  # step 10
    episode = add_episode(load(show), "The Third Light", season="season/01")
    assert episode == "e03" and "episodes: [e02, e03]\n" in (show / "seasons/01.yaml").read_text()
    scene = add_scene(load(show), "e03", "EXT. CLIFF PATH - DUSK", location="loc/lighthouse")
    first = add_shot(load(show), scene, "Mira climbs the path.")
    p = load(show)
    assert (scene, first, p.docs["e03"].data["scenes"]) == ("e03/s01", "e03/s01/sh010", ["e03/s01"])
    assert [str(i) for i in validate(p) if i.level == "error"] == []
    # A new sheet keeps its file name, so the character file does not change. A form gets its
    # front view in forms/<name>/.
    before = (show / MIRA).read_text()
    assert replace_sheet(load(show), "char/mira", _png("red")) == "bible/characters/mira/sheet.png"
    assert (show / MIRA).read_text() == before
    add_form(
        load(show),
        "char/mira",
        "storm",
        "Grey hair, rain-dark tail.",
        palette=["#555566"],
        front=_png("blue"),
    )
    form = load(show).docs["char/mira"].data["forms"]["storm"]
    assert (
        form
        == {
            "description": "Grey hair, rain-dark tail.",
            "palette": ["#555566"],
            "views": {"front": "forms/storm/front.png"},
        }
        and (show / "bible/characters/mira/forms/storm/front.png").is_file()
    )
    with pytest.raises(OlfError, match="already has a form named"):
        add_form(load(show), "char/mira", "storm", "Again.")
    with pytest.raises(OlfError, match="not a PNG, JPEG or WebP"):
        replace_sheet(load(show), "char/mira", base64.b64encode(b"not an image").decode())


def test_sheets(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    from vinci_olf.author import add_sheet, replace_sheet
    from vinci_olf.render import render

    # More sheets: each a whole file listed in `sheets` (decision 2026-11-09: no crops).
    before = (show / MIRA).read_text()
    assert add_sheet(load(show), "char/mira", _png("orange", (400, 300))) == "sheet-2.png"
    assert add_sheet(load(show), "char/mira", _png("blue")) == "sheet-3.png"
    assert (show / MIRA).read_text() == before + "sheets: [sheet-2.png, sheet-3.png]\n"
    assert [str(i) for i in validate(load(show)) if i.level == "error"] == []
    # A form with no front view (winter, in sh014) sends every whole sheet.
    render(load(show), "e02/s03/sh014", kind="keyframe", engine=_demo_engine(tmp_path, monkeypatch))
    p = load(show)
    base = (show / MIRA).parent
    sheets = [p.asset_id(n, base) for n in ("sheet.png", "sheet-2.png", "sheet-3.png")]
    assert p.docs["e02/s03/sh014/kf1"].data["inputs"]["references"][:3] == sheets
    # Replace acts on the sheet it names, under that file name.
    out = replace_sheet(p, "char/mira", _png("red"), sheet="sheet-2.png")
    assert out == "bible/characters/mira/sheet-2.png" and stale(load(show), "e02/s03/sh014/kf1")
    with pytest.raises(OlfError, match="has no sheet 'sheet-9.png'"):
        replace_sheet(load(show), "char/mira", _png("red"), sheet="sheet-9.png")
    # A crop is not a reference, and `regions` is not a field.
    edit(show / MIRA, "eyes: details/eyes.png", "eyes: sheet.png#eyes")
    errors = [i.message for i in validate(load(show)) if i.level == "error"]
    crop = "sheet.png#eyes: point to a whole file (sheet.png or a separate image), not a crop"
    assert errors == [crop]
    edit(show / MIRA, "sheet: sheet.png ", "regions: { eyes: [0, 0, 9, 9] }\nsheet: sheet.png ")
    assert any("'regions' was unexpected" in i.message for i in validate(load(show)))


def test_stale_cause_and_keep(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    from vinci_olf.explain import explain, keep_take
    from vinci_olf.render import render

    shot, take = "e02/s03/sh014", "e02/s03/sh014/kf1"
    render(load(show), shot, kind="keyframe", engine=_demo_engine(tmp_path, monkeypatch))
    assert (show / "takes/e02/s03/sh014/kf1.inputs.json").is_file()  # the view it was rendered with
    assert explain(load(show), take) == {
        "take": take,
        "stale": False,
        "known": True,
        "changes": [],
        "summary": "",
    }
    edit(show / MIRA, "Wool sweater, no ribbons.", "Wool sweater, red scarf.")
    why = explain(load(show), take)
    assert (
        why["stale"] and why["summary"] == 'the outfit "night" of char/mira (description) changed'
    )
    assert why["changes"] == [
        {
            "field": "characters.char/mira.outfit.description",
            "label": 'the outfit "night" of char/mira (description)',
            "before": "Wool sweater, no ribbons.",
            "after": "Wool sweater, red scarf.",
        }
    ]
    kept = keep_take(load(show), take)
    p = load(show)
    assert kept["kept"] and p.docs[take].data["kept_from"] == kept["kept_from"]
    assert not stale(p, take) and explain(p, take)["changes"] == []  # fresh until the next change
    assert [str(i) for i in validate(p) if i.level == "error"] == []  # kept_from is in the schema
    # A take with no .inputs.json can be kept, but the engine cannot say what changed.
    (show / "takes/e02/s03/sh014/kf1.inputs.json").unlink()
    edit(show / MIRA, "red scarf.", "blue scarf.")
    assert explain(load(show), take)["known"] is False and keep_take(load(show), take)["kept"]


def test_palette_qa(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    from PIL import Image
    from vinci_olf.qa import palette_check, palettes

    colors = ["#eef6fb", "#7cc7e8", "#1f3a6b"]  # the winter form
    image = Image.new("RGB", (90, 30))
    for n, color in enumerate(colors):
        image.paste(color, (30 * n, 0, 30 * n + 30, 30))
    image.save(tmp_path / "match.png")
    Image.new("RGB", (90, 30), "#ff2a00").save(tmp_path / "miss.png")
    assert palette_check(tmp_path / "match.png", colors) == {
        "check": "palette",
        "score": 1.0,
        "pass": True,
    }
    miss = palette_check(tmp_path / "miss.png", colors)
    assert miss is not None and miss["score"] < 0.3 and miss["pass"] is False
    assert palette_check(tmp_path / "match.png", []) is None  # no palette: no check
    assert palettes(resolve(load(show), "e02/s03/sh014")) == colors
    if shutil.which("ffmpeg"):  # a render writes the check into the take
        from vinci_olf.render import render

        render(
            load(show), "e02/s03/sh014", kind="keyframe", engine=_demo_engine(tmp_path, monkeypatch)
        )
        qa = load(show).docs["e02/s03/sh014/kf1"].data["qa"]
        assert qa[0]["check"] == "palette" and 0 <= qa[0]["score"] <= 1


FOUNTAIN = """Title: Tidewatch

EXT. CLIFF PATH - DUSK

Mira climbs toward the lighthouse. She stops and looks back
at the village lights.

INT. LAMP ROOM - NIGHT

The brass lamp turns.

MIRA
(whisper)
You kept the key?

GUARD (O.S.)
Who's there?

CUT TO:
"""


def test_script_preview_without_ai() -> None:
    from vinci_olf.script import parse, preview, tagged

    # The design's example (screen 5): headings, action sentences, cues; title page and
    # transitions are skipped.
    scenes = parse(FOUNTAIN)
    assert [s["heading"] for s in scenes] == ["EXT. CLIFF PATH - DUSK", "INT. LAMP ROOM - NIGHT"]
    assert scenes[1]["beats"][1] == {
        "speaker": "MIRA",
        "line": "You kept the key?",
        "delivery": "whisper",
    }
    view = preview(
        FOUNTAIN,
        characters={"char/mira": "Mira Sol"},
        locations={"loc/lighthouse": "Lamp room"},
        variants={"loc/lighthouse": ["day", "night"]},
        lenses=["24mm", "35mm", "50mm"],
    )
    cliff, lamp = view["scenes"]
    assert (cliff["location"], cliff["variant"], cliff["characters"]) == (
        "loc/cliff-path",
        "dusk",
        ["char/mira"],  # named in the action, so her sheet is a reference
    )
    assert [s["camera"] for s in cliff["shots"]] == [
        {"framing": "wide", "lens": "24mm"},
        {"framing": "medium", "lens": "35mm"},
    ]
    assert (lamp["location"], lamp["variant"]) == ("loc/lighthouse", "night")
    # The line stays in dialogue: a quoted line in a description is drawn as a caption.
    assert lamp["shots"][1]["description"] == "Mira whispers."
    assert lamp["shots"][1]["dialogue"] == [
        {"speaker": "char/mira", "line": "You kept the key?", "delivery": "whisper"}
    ]
    assert lamp["shots"][2]["dialogue"] == [{"speaker": "char/guard", "line": "Who's there?"}]
    assert [c["id"] for c in view["characters"] if c["new"]] == ["char/guard"]
    assert view["shots"] == 5 and view["runtime"] == 12.5
    # A model's shot tags set framing, lens and length; the rules' own list round-trips.
    tags = preview("[ECU 85mm 1.5s] Her eyes open.", lenses=["85mm"])["scenes"][0]["shots"]
    assert tags == [
        {
            "description": "Her eyes open.",
            "duration": "1.5s",
            "camera": {"framing": "extreme_close_up", "lens": "85mm"},
        }
    ]
    shots = [scene["shots"] for scene in preview(FOUNTAIN)["scenes"]]
    assert [scene["shots"] for scene in preview(tagged(FOUNTAIN))["scenes"]] == shots
    assert "[WS" not in preview(tagged(FOUNTAIN))["scenes"][0]["script"]  # tags are not kept


def test_new_show_character_and_script(tmp_path: Path, monkeypatch: Any) -> None:
    from vinci_olf.author import add_character, add_episode, new_show
    from vinci_olf.batch import render_batch
    from vinci_olf.script import draft, import_script, split_with_model

    p = new_show(tmp_path / "show", "Tide Watch", aspect="9:16")
    assert '  aspect: "9:16"\n' in (p.root / "project.yaml").read_text()  # stays text in YAML 1.1
    assert add_character(p, "Mira Sol", "A fox spirit.", sheet=_png("teal")) == "char/mira"
    p = load(p.root)
    assert p.docs["char/mira"].data["sheet"] == "sheet.png"
    assert [e["uri"] for e in p.lock.values()] == ["bible/characters/mira/sheet.png"]
    episode = add_episode(p, "Episode 1")
    new = import_script(load(p.root), episode, FOUNTAIN)
    assert new == {
        "scenes": ["e01/s01", "e01/s02"],
        "locations": ["loc/cliff-path", "loc/lamp-room"],
        "characters": ["char/guard"],
    }
    p = load(p.root)
    scene = (p.root / "episodes/e01/scenes/s02.yaml").read_text()
    assert "  camera: {framing: wide, lens: 24mm}\n" in scene and "script: |\n" in scene
    # Keyframes first: each imported scene animates from the chosen keyframe (live test, 558).
    assert "control: {first_frame: keyframe}\n" in scene
    assert p.docs["e01"].data["scenes"] == ["e01/s01", "e01/s02"]
    # A speaker the bible did not know needs a sheet, as any character does.
    assert [i.message for i in validate(p) if i.level == "error"] == [
        "a character needs a sheet or another reference image"
    ]
    # A second script adds scenes after the first ones, with the places it now knows.
    again = import_script(load(p.root), episode, FOUNTAIN.replace("GUARD", "ROSA"))
    assert again == {"scenes": ["e01/s03", "e01/s04"], "locations": [], "characters": ["char/rosa"]}
    with pytest.raises(OlfError, match="no action or dialogue"):
        import_script(load(p.root), episode, "Title: Empty\n")
    with pytest.raises(OlfError, match="is not empty"):
        new_show(p.root, "Again")
    # The text steps run on the demo model at $0, through the runtime like a render.
    engine = _demo_engine(tmp_path, monkeypatch)
    plan = draft(
        "A fox spirit keeps the last light.", cast=["Mira Sol"], dry_run=True, engine=engine
    )
    assert plan["plan"][0]["model"] == "mock:llm:v1" and plan["text"] is None
    assert draft("A fox spirit keeps the last light.", engine=engine)["text"].startswith("EXT.")
    split = split_with_model(FOUNTAIN, engine=engine)
    assert split["text"].startswith("EXT. CLIFF PATH - DUSK\n\n[WS 24mm 2.5s] Mira climbs")
    # Create show and draw keyframes: two options for each shot without a keyframe.
    batch = render_batch(load(p.root), episode, mode="keyframes", dry_run=True, engine=engine)
    assert len(batch["jobs"]) == 10 and batch["jobs"][0]["count"] == 2 and batch["total"] == 0
    done = render_batch(load(p.root), episode, mode="keyframes", engine=engine)
    assert len(done["takes"]) == 20 and done["takes"][:2] == [
        "e01/s01/sh010/kf1",
        "e01/s01/sh010/kf2",
    ]
    assert (
        render_batch(load(p.root), episode, mode="keyframes", dry_run=True, engine=engine)["jobs"]
        == []
    )


def test_music_and_sfx_cues(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    from vinci_olf.cues import add_cue, place_cue, render_cue
    from vinci_olf.cut import cut_view

    episode = show / "episodes/e02/episode.yaml"
    engine = _demo_engine(tmp_path, monkeypatch)
    theme = add_cue(load(show), "e02", "music", "Slow piano, distant waves", 6)
    door = add_cue(load(show), "e02", "sfx", "Old door creaks open", 1.5)
    assert (theme, door) == ("e02/cue/slow-piano-distant", "e02/cue/old-door-creaks")
    cue = '{ kind: music, description: "Slow piano, distant waves", duration: 6s }'
    assert f"  slow-piano-distant: {cue}\n" in episode.read_text()
    with pytest.raises(OlfError, match="lasts 0.5 to 60 s"):  # the price covers one minute
        add_cue(load(show), "e02", "music", "Too long", 90)
    plan = render_cue(load(show), theme, dry_run=True, engine=engine)
    assert plan["plan"][0]["model"] == "mock:music:v1" and plan["takes"] == []
    take = render_cue(load(show), theme, engine=engine)["takes"][0]
    sfx = render_cue(load(show), door, engine=engine)["takes"][0]
    p = load(show)
    assert (take, sfx) == ("e02/cue/slow-piano-distant/a1", "e02/cue/old-door-creaks/a1")
    assert p.docs[take].data["provenance"]["model"] == "mock:music:v1"
    assert not stale(p, take) and [str(i) for i in validate(p) if i.level == "error"] == []
    place_cue(p, "e02", take, start=0, volume=0.5, duck=True)
    place_cue(load(show), "e02", sfx, start=1, volume=1, duck=False)
    row = "{ take: e02/cue/old-door-creaks/a1, start: 1s, volume: 1, duck_under_dialogue: false }"
    assert f"  - {row}\n" in episode.read_text()
    rows = cut_view(load(show), "e02")["audio"]
    assert [(r["kind"], r["start"], r["volume"], r["duck"], round(r["length"])) for r in rows] == [
        ("music", 0, 0.5, True, 6),
        ("sfx", 1, 1, False, 2),
    ]
    if shutil.which("ffmpeg"):  # export lays the cues over the (silent) stills of the cut
        from vinci_olf.cut import use_approved
        from vinci_olf.edit import set_take
        from vinci_olf.export import export
        from vinci_olf.render import render

        render(load(show), "e02/s03/sh014", kind="keyframe", engine=engine)
        set_take(load(show), "e02/s03/sh014/kf1", status="approved")
        use_approved(load(show), "e02")
        wide = show / export(load(show), "e02", aspects=("16:9",), subtitles=False)["files"][0]
        assert _loudness(wide, 0.2, 0.6) > -60  # the music is in the sound
    # The hash covers the cue's kind, description and length: an edit makes its take stale.
    edit(episode, "Slow piano, distant waves", "Slow cello, distant waves")
    assert stale(load(show), take) and not stale(load(show), sfx)
    # A scene or shot may name its cues; a name that is not a cue is an error.
    edit(
        show / SCENE,
        "mood: tense, quiet",
        "mood: tense, quiet\naudio: { sfx: e02/cue/old-door-creaks, music: e02/cue/nope }",
    )
    errors = [i.message for i in validate(load(show)) if i.level == "error"]
    assert errors == ["audio.music: e02/cue/nope is not in its episode's cues"]


def test_export_otio_stems_and_c2pa(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("export runs ffmpeg")
    import json

    from vinci_olf import provenance
    from vinci_olf.cues import add_cue, place_cue, render_cue
    from vinci_olf.cut import use_approved
    from vinci_olf.edit import set_clip, set_take
    from vinci_olf.export import export
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    for shot in ("e02/s03/sh014", "e02/s03/sh015"):  # two stills (4 s and 2.5 s) with a fade
        render(load(show), shot, kind="keyframe", engine=engine)
        set_take(load(show), f"{shot}/kf1", status="approved")
    use_approved(load(show), "e02")
    set_clip(load(show), "e02", 1, transition="fade")
    cue = add_cue(load(show), "e02", "music", "Slow piano", 3)
    take = render_cue(load(show), cue, engine=engine)
    place_cue(load(show), "e02", take["takes"][0], start=0.5, volume=0.6, duck=True)
    home, signed = tmp_path / "home", provenance.available()
    out = export(
        load(show), "e02", aspects=("16:9",), subtitles=False, otio=True, c2pa=signed, home=home
    )
    assert out["files"] == [
        "exports/e02/stems/e02-dialogue.wav",
        "exports/e02/stems/e02-music.wav",
        "exports/e02/e02-16x9.mp4",
        "exports/e02/e02.otio",
    ]
    # OTIO: a fade is a dissolve centered on the cut, so the clips still add up to the cut.
    video, dialogue, music = json.loads((show / "exports/e02/e02.otio").read_text())["tracks"][
        "children"
    ]
    kinds = [item["OTIO_SCHEMA"] for item in video["children"]]
    assert kinds == ["Clip.2", "Transition.1", "Clip.2"] and dialogue["children"] == []
    frames = sum(
        c["source_range"]["duration"]["value"]
        for c in video["children"]
        if "Clip" in c["OTIO_SCHEMA"]
    )
    assert frames / 24 == pytest.approx(out["duration"]) == 6.0
    first = video["children"][0]["media_references"]["DEFAULT_MEDIA"]["target_url"]
    assert first == "../../takes/e02/s03/sh014/kf1.png"  # relative to exports/e02/
    assert music["children"][0]["OTIO_SCHEMA"] == "Gap.1"
    assert music["children"][1]["metadata"]["olf"] == {"volume": 0.6, "duck_under_dialogue": True}
    if signed:  # the manifest names every take the file shows, signed by the local key
        import c2pa

        reader = c2pa.Reader(str(show / "exports/e02/e02-16x9.mp4"))
        assert reader.get_validation_state() == "Valid"
        labels = {a["label"]: a["data"] for a in reader.get_active_manifest()["assertions"]}
        ids = [t["id"] for t in labels["org.tryvinci.olf"]["takes"]]
        assert ids == ["e02/s03/sh014/kf1", "e02/s03/sh015/kf1", take["takes"][0]]
        assert (home / "c2pa/signer.key").stat().st_mode & 0o777 == 0o600


def test_voice_for_a_new_character_and_no_voice_stops_elevenlabs(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A speaker with no voice stops an ElevenLabs line at the plan (the live test of 2026-11-09:
    the plugin sent voice "default"); set_voice writes the entry and the dialogue then plans."""
    from vinci_olf.author import add_character, add_episode, new_show, set_voice
    from vinci_olf.render import render
    from vinci_olf.script import import_script

    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")  # in the catalog; dry runs only
    engine = _demo_engine(tmp_path, monkeypatch)
    p = new_show(tmp_path / "show", "Lamp Oil")
    cid = add_character(p, "Mira Sol", "A keeper.", sheet=_png("teal"))
    episode = add_episode(load(p.root), "Episode 1")
    scene = import_script(load(p.root), episode, "INT. LAMP ROOM - NIGHT\n\nMIRA\nYou kept it?\n")
    shot = f"{scene['scenes'][0]}/sh010"
    eleven = {"kind": "audio", "model": "elevenlabs:flash-v2.5:2026-08", "dry_run": True}
    with pytest.raises(OlfError, match="char/mira has no ElevenLabs voice: pick one"):
        render(load(p.root), shot, engine=engine, **eleven)
    assert render(load(p.root), shot, kind="audio", dry_run=True, engine=engine)["total"] == 0
    assert set_voice(load(p.root), cid, "EXAVITQu4vr4xnSDxMaL", "Sarah") == "voice/mira"
    voice = (p.root / "bible/voices/mira/mira.yaml").read_text()
    assert "elevenlabs: {voice_id: EXAVITQu4vr4xnSDxMaL}" in voice and "description: Sarah" in voice
    assert load(p.root).docs[cid].data["voice"] == "voice/mira"
    plan = render(load(p.root), shot, engine=engine, **eleven)
    assert plan["plan"][0]["model"] == "elevenlabs:flash-v2.5:2026-08"
    set_voice(load(p.root), cid, "other_voice")  # a new pick keeps the entry's description
    assert "description: Sarah" in (p.root / "bible/voices/mira/mira.yaml").read_text()
    assert [str(i) for i in validate(load(p.root))] == []
    with pytest.raises(OlfError, match="is not a voice ID"):
        set_voice(load(p.root), cid, "../evil")


def test_clone_voice_keeps_the_sample_and_gives_the_character_the_clone(tmp_path: Path) -> None:
    """COREPRODUC-559: Clone from sample. The clone comes first (a refused clone writes nothing);
    then the recording is the voice entry's sample with a lock entry, and a new clone replaces
    it (its old lock entry goes, so the show stays valid)."""
    import base64
    import hashlib

    from vinci_olf.author import add_character, clone_voice, new_show

    p = new_show(tmp_path / "show", "Lamp Oil")
    cid = add_character(p, "Mira Sol", "A keeper.", sheet=_png("teal"))
    asked: list[tuple[str, bytes, str]] = []

    def clone(name: str, data: bytes, file: str) -> str:
        asked.append((name, data, file))
        return f"clone_{len(asked)}"

    def refuse(name: str, data: bytes, file: str) -> str:
        raise OlfError("ElevenLabs refused the clone (HTTP 422): too short")

    mp3 = b"ID3\x04\x00" + b"\x00" * 64
    voice_file = p.root / "bible/voices/mira/mira.yaml"
    with pytest.raises(OlfError, match="too short"):
        clone_voice(load(p.root), cid, "", base64.b64encode(mp3).decode(), refuse)
    assert not (p.root / "bible/voices/mira").exists()  # nothing written
    with pytest.raises(OlfError, match="MP3, WAV, OGG or FLAC"):
        clone_voice(load(p.root), cid, "", base64.b64encode(b"not audio").decode(), clone)
    assert asked == []  # a wrong file is never sent
    entry = clone_voice(
        load(p.root), cid, "", "data:audio/mpeg;base64," + base64.b64encode(mp3).decode(), clone
    )
    assert entry == "voice/mira" and asked == [("Mira Sol's voice", mp3, "sample.mp3")]
    folder = p.root / "bible/voices/mira"
    first = f"sample-{hashlib.sha256(mp3).hexdigest()[:12]}.mp3"  # a file per recording
    text = voice_file.read_text()
    assert f"sample: {first}" in text and "voice_id: clone_1" in text
    assert (folder / first).read_bytes() == mp3
    assert f"bible/voices/mira/{first}" in [e["uri"] for e in load(p.root).lock.values()]
    # A replacement, on a project whose hashes were read first (a stale cache gave a wrong
    # lock entry; review of #528): the entry switches to the new file, and the old one goes.
    newer = mp3 + b"\x01"
    second = f"sample-{hashlib.sha256(newer).hexdigest()[:12]}.mp3"
    q = load(p.root)
    assert validate(q) == []
    clone_voice(q, cid, "Mira, older", base64.b64encode(newer).decode(), clone)
    text = voice_file.read_text()
    assert "voice_id: clone_2" in text and f"sample: {second}" in text
    assert not (folder / first).exists() and (folder / second).read_bytes() == newer
    assert [str(i) for i in validate(load(p.root))] == []  # the old sample's lock entry is gone
    # Made but not saved (a full disk): the error names the clone, so it is picked, not made
    # again; each clone holds a voice slot. The old sample, lock entry and voice entry stay
    # together (review of #528).
    from unittest import mock

    with mock.patch("vinci_olf.author.set_voice", side_effect=OSError("No space left")):
        with pytest.raises(OlfError, match=r'made the voice "Rae" \(clone_3\), but the show'):
            clone_voice(load(p.root), cid, "Rae", base64.b64encode(mp3).decode(), clone)
    text = voice_file.read_text()
    assert "voice_id: clone_2" in text and f"sample: {second}" in text
    assert (folder / second).read_bytes() == newer
    assert [str(i) for i in validate(load(p.root))] == []


def test_durations_in_seconds_and_in_frames(show: Path) -> None:
    from vinci_olf.author import add_shot, set_shot
    from vinci_olf.project import seconds

    forms = {"4s": 4, "2.5": 2.5, 4: 4, "3+12": 3.5, "0+18": 0.75, "3+00": 3, "3+6": 3.25}
    assert {k: seconds(k) for k in forms} == forms and seconds("0+10") == 10 / 24
    assert [seconds(x, -1.0) for x in ("3+24", "soon", None, True)] == [-1.0] * 4  # 24 carries
    shot = "e02/s03/sh014"
    edit(show / SCENE, "duration: 4s", "duration: 3+12")
    view = resolve(load(show), shot)
    assert view["duration"] == 3.5 and validate(load(show)) == []
    edit(show / SCENE, "duration: 3+12", "duration: 3.5s")  # one length, two spellings
    assert inputs_hash(resolve(load(show), shot), "video") == inputs_hash(view, "video")
    edit(show / SCENE, "duration: 3.5s", "duration: 3+24")
    assert ["duration" in str(i) for i in validate(load(show)) if i.level == "error"] == [True]
    edit(show / SCENE, "duration: 3+24", "duration: 4s")
    # A shot edit keeps seconds+frames as typed. Each other form becomes seconds.
    set_shot(load(show), shot, duration="2+06")
    assert "    duration: 2+06\n" in (show / SCENE).read_text(encoding="utf-8")
    set_shot(load(show), shot, duration="4")
    assert "    duration: 4s\n" in (show / SCENE).read_text(encoding="utf-8")
    new = add_shot(load(show), "e02/s03", "The lamp turns.", duration="0+18")
    assert load(show).docs[new].data["duration"] == "0+18"
    with pytest.raises(OlfError, match=r"duration must be seconds such as 4s or 3\+12"):
        set_shot(load(show), shot, duration="3+30")


def test_shot_edits_take_each_camera_field(show: Path) -> None:
    from vinci_olf.author import set_shot

    shot = "e02/s03/sh014"
    edit(show / SCENE, "move: push_in }", "move: push_in, center: [0.5, 0.42] }")  # by hand
    set_shot(load(show), shot, amount="0.35", ease="in_out", hold_end="0+12", render="engine")
    line = (
        "    camera: { framing: close_up, angle: eye_level, lens: 50mm, move: push_in, "
        "amount: 0.35, ease: in_out, hold_end: 0+12, center: [0.5, 0.42], render: engine }\n"
    )
    assert line in (show / SCENE).read_text(encoding="utf-8")  # the schema's order, plain values
    camera = resolve(load(show), shot)["camera"]
    assert (camera["amount"], camera["hold_end"], camera["center"]) == (0.35, 0.5, [0.5, 0.42])
    set_shot(load(show), shot, move="shake", ease=None)  # the fields it does not name stay
    kept = {k: v for k, v in camera.items() if k != "ease"} | {"move": "shake"}
    assert resolve(load(show), shot)["camera"] == kept
    for fields, message in (
        ({"amount": "much"}, "camera.amount must be a number, not 'much'"),
        ({"amount": 7}, "camera.amount: 7.0 is greater than the maximum of 5"),
        ({"ease": "slow"}, "camera.ease must be one of none, in, out, in_out, not 'slow'"),
        ({"hold_start": "0+30"}, "camera.hold_start: '0\\+30' is not valid"),
    ):
        with pytest.raises(OlfError, match=message):
            set_shot(load(show), shot, **fields)
    assert validate(load(show)) == []


def test_engine_move_makes_a_video_with_no_model(
    show: Path, tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("an engine move runs ffmpeg")
    from vinci_olf.__main__ import main
    from vinci_olf.api import shot_detail
    from vinci_olf.batch import jobs
    from vinci_olf.edit import set_select, set_take
    from vinci_olf.render import render
    from vinci_runtime.engine import Engine

    shot = "e02/s03/sh014"
    render(load(show), shot, kind="keyframe", engine=_demo_engine(tmp_path, monkeypatch))
    set_take(load(show), f"{shot}/kf1", status="approved")
    set_select(load(show), shot, keyframe="kf1")
    # A quick track up of 8 frames, then a hold: 0+18. No `control`: the engine move animates
    # the chosen keyframe by itself.
    edit(show / SCENE, "duration: 4s", "duration: 0+18")
    edit(
        show / SCENE,
        "move: push_in }",
        "move: push_in, amount: 0.3, ease: out, hold_end: 0+10, render: engine }",
    )
    edit(show / SCENE, "    control:\n      first_frame: keyframe      # animate", "    # animate")
    bare = Engine(tmp_path / "bare")  # no provider is connected, and an engine move needs none
    assert bare.routing_providers() == set() and validate(load(show)) == []
    plan = render(load(show), shot, engine=bare, dry_run=True)
    row = {"node": "video", "model": "local:ffmpeg:v1", "amount": 0.0, "capability": None}
    assert plan["plan"] == [row] and plan["total"] == 0 and plan["takes"] == []
    assert "enlarges it" in plan["notes"][0]  # the sample keyframe is small for a push
    assert jobs(load(show), "e02", "animate") == [
        {"shot": shot, "kind": "video", "why": "animate kf1"}
    ]
    assert render(load(show), shot, engine=bare)["takes"] == [f"{shot}/v1"]  # $0: no --yes
    p = load(show)
    take, proven = p.docs[f"{shot}/v1"].data, p.docs[f"{shot}/v1"].data["provenance"]
    assert take["inputs"] == {"first_frame": f"{shot}/kf1"} and take["duration"] == "0.750s"
    assert (proven["provider"], proven["model"], proven["cost"]["amount"]) == (
        "local",
        "local:ffmpeg:v1",
        0,
    )
    assert "prompt" not in proven and proven["parameters"] == {
        "move": "push_in",
        "amount": 0.3,
        "ease": "out",
        "hold_end": pytest.approx(10 / 24),
    }
    assert [str(i) for i in validate(p) if i.level == "error"] == []
    assert not stale(p, f"{shot}/kf1") and not stale(p, f"{shot}/v1")
    assert jobs(p, "e02", "animate") == []  # v1 is a fresh video from kf1
    edit(show / SCENE, "amount: 0.3", "amount: 0.2")  # a move edit: only the video is stale
    p = load(show)
    assert not stale(p, f"{shot}/kf1") and stale(p, f"{shot}/v1")
    edit(show / SCENE, "move: push_in, amount", "move: orbit, amount")
    with pytest.raises(OlfError, match="cannot make a orbit move from a held drawing"):
        render(load(show), shot, engine=bare, dry_run=True)
    edit(show / SCENE, "move: orbit, amount", "move: push_in, amount")
    # Render does not validate first: a wrong value or a huge frame stops with a plain reason.
    edit(show / SCENE, "amount: 0.2", "amount: far")
    with pytest.raises(OlfError, match="camera.amount: 'far' is not of type 'number'"):
        render(load(show), shot, engine=bare, dry_run=True)
    edit(show / SCENE, "amount: far", "amount: 0.2")
    edit(show / "project.yaml", "resolution: 1920x1080", "resolution: 99999x1080")
    with pytest.raises(OlfError, match="cannot use defaults 99999x1080 at 24 fps"):
        render(load(show), shot, engine=bare, dry_run=True)
    edit(show / "project.yaml", "resolution: 99999x1080", "resolution: 1920x1080")
    # A stated first frame that no image reader knows: the note is only advice, so the plan
    # still comes (CodeRabbit on #529: a WebP keyframe stopped the plan with a ValueError).
    (show / "bible/blank.png").write_text("not an image", encoding="utf-8")
    still = "    control: { first_frame: ../../../bible/blank.png }"
    edit(show / SCENE, "    # animate from the selected keyframe", still)
    assert "notes" not in render(load(show), shot, engine=bare, dry_run=True)
    edit(show / SCENE, still, "    # animate from the selected keyframe")
    set_select(load(show), shot, keyframe=None)  # no chosen keyframe: a model must draw one
    with pytest.raises(OlfError, match="no providers are connected"):
        render(load(show), shot, engine=bare, dry_run=True)
    # The video has no hash until a keyframe is chosen: the API and the CLI say the same.
    assert shot_detail(load(show), shot)["hashes"]["video"] is None
    capsys.readouterr()
    assert main(["resolve", shot, "-C", str(show)]) == 0
    assert "# inputs_hash (video): needs a selected keyframe" in capsys.readouterr().out


def test_cut_plays_a_video_for_the_length_of_its_shot(show: Path) -> None:
    from vinci_olf.cut import cut_view, use_approved
    from vinci_olf.edit import set_clip

    _take(show, "e02/s03/sh014/v1", "video")  # a 4 s shot on a model whose shortest clip is 5 s
    with (show / "takes/e02/s03/sh014/v1.yaml").open("a", encoding="utf-8") as file:
        file.write("duration: 5.0s\n")
    use_approved(load(show), "e02")

    def clip() -> tuple[float, float, float]:
        row = cut_view(load(show), "e02")["clips"][0]
        return row["in"], row["out"], row["length"]

    assert clip() == (0.0, 4.0, 4.0)  # the shot's length, not the take's
    set_clip(load(show), "e02", 0, **{"in": 0.5})
    assert clip() == (0.5, 4.5, 4.0)  # a later start keeps the shot's length
    set_clip(load(show), "e02", 0, **{"in": 2})
    assert clip() == (2.0, 5.0, 3.0)  # but no more than the take has
    set_clip(load(show), "e02", 0, **{"in": None}, out=5)
    assert clip() == (0.0, 5.0, 5.0)  # a person can still play the whole take
    edit(show / SCENE, "duration: 4s", "duration: 12s")
    set_clip(load(show), "e02", 0, out=None)
    assert clip() == (0.0, 5.0, 5.0)  # a take that is shorter than its shot plays whole


def test_camerawork_library_and_templates(show: Path) -> None:
    from vinci_olf.api import library, summary
    from vinci_olf.author import add_template, apply_template
    from vinci_olf.project import LIBRARY
    from vinci_olf.render import prompt
    from vinci_olf.resolve import origins
    from vinci_olf.validate import schema_errors

    # The library: each file is a valid template, named after its ID, with a version. CC0.
    assert len(library()) == 32 and len({row["id"] for row in library()}) == 32
    # A template declares each slot that its words name (`fix-hold` named {a} with no slots, #530).
    for row in library():
        named = set(re.findall(r"\{([abc])\}", f"{row.get('prompt')} {row.get('keyframe')}"))
        assert named <= set(row.get("slots") or []), row["id"]
    for path in sorted(LIBRARY.glob("*/*.yaml")):
        row = read(path)
        assert row["id"] == f"{path.parent.name}/{path.stem}" and row["version"] >= 1
        copy = {k: v for k, v in row.items() if k != "version"} | {"id": f"cam/{path.stem}"}
        assert schema_errors("camerawork", copy) == [], path.name
    assert (
        (LIBRARY / "LICENSE")
        .read_text(encoding="utf-8")
        .startswith("Creative Commons Legal Code\n\nCC0 1.0 Universal")
    )
    # A library template goes into the show's bible one time, and the shot points to it.
    shot = "e02/s03/sh014"
    camera = {"framing": "close_up", "angle": "eye_level", "lens": "50mm"}
    done = apply_template(load(show), shot, "anime/tu-to-eyes")
    assert done == {
        "template": "cam/tu-to-eyes",
        "duration": "3+00",  # the template's default length
        "camera": camera | {"template": "cam/tu-to-eyes"},  # the shot's own move is gone
    }
    entry = show / "bible/camerawork/tu-to-eyes/tu-to-eyes.yaml"
    assert "\nid: cam/tu-to-eyes\nsource: anime/tu-to-eyes@1\n" in entry.read_text("utf-8")
    assert add_template(load(show), "anime/tu-to-eyes") == "cam/tu-to-eyes"  # the same copy
    with pytest.raises(OlfError, match="the camerawork library has no template 'anime/../x'"):
        add_template(load(show), "anime/../x")
    p = load(show)
    view = resolve(p, shot)
    assert validate(p) == [] and view["duration"] == 3
    filled = {k: view["camera"][k] for k in ("move", "amount", "hold_start", "center", "render")}
    assert filled == {
        "move": "push_in",
        "amount": 0.35,
        "hold_start": 0.5,  # 0+12
        "center": [0.5, 0.42],
        "render": "engine",
    }
    words = "A slow, steady push toward {a}'s eyes. Only the eyes move.\n"
    assert view["camera"]["template"] == {"id": "cam/tu-to-eyes", "prompt": words}
    assert "A slow, steady push toward Mira Sol's eyes. Only" in prompt(view, "video")  # slot a
    assert "push toward" not in prompt(view, "keyframe")
    fields = origins(p, shot)["camera_fields"]
    assert (fields["framing"], fields["amount"]) == ("shot", "cam/tu-to-eyes")
    own, row = summary(p)["bible"]["camerawork"]  # the sample's own template, and the copy
    assert (own["id"], own["used_in"], own["data"].get("source")) == (
        "cam/key-insert",
        ["e02/s03/sh016"],
        None,
    )
    assert (row["id"], row["used_in"], row["data"]["source"]) == (
        "cam/tu-to-eyes",
        [shot],
        "anime/tu-to-eyes@1",
    )
    # A stated value wins over the template: at the shot, and at the scene for all its shots.
    edit(show / SCENE, "template: cam/tu-to-eyes }", "template: cam/tu-to-eyes, amount: 0.5 }")
    edit(show / SCENE, "mood: tense, quiet\n", "mood: tense, quiet\ncamera: { ease: none }\n")
    p = load(show)
    camera = resolve(p, shot)["camera"]
    assert (camera["amount"], camera["ease"], camera["hold_end"]) == (0.5, "none", 0.5)
    assert origins(p, shot)["camera_fields"]["ease"] == "scene" and validate(p) == []
    # The hash: a field that changes no render makes nothing stale. The camera and the motion
    # words make the video stale. The keyframe words make both stale.
    kinds = ("keyframe", "video")
    before = [inputs_hash(resolve(p, shot), kind) for kind in kinds]

    def changed() -> list[bool]:
        """For each kind, whether the shot's inputs hash is not the one from before."""
        view = resolve(load(show), shot)
        return [inputs_hash(view, kind) != old for kind, old in zip(kinds, before, strict=True)]

    edit(entry, "intent: Push from", "intent: Track up from")
    edit(entry, "timing: { default: 3+00", "timing: { default: 2+12")
    assert changed() == [False, False]
    edit(entry, "hold_end: 0+12", "hold_end: 1+00")
    assert changed() == [False, True]
    edit(entry, "Only the eyes move.", "Only the eyes move, a little.")
    assert changed() == [False, True]
    with entry.open("a", encoding="utf-8") as file:
        file.write("keyframe: The eyes of {a} catch the lamp light.\n")
    assert changed() == [True, True]
    assert "The eyes of Mira Sol catch the lamp light." in prompt(
        resolve(load(show), shot), "keyframe"
    )
    # Off again: the shot keeps its framing, and the template stays in the bible.
    assert apply_template(load(show), shot, None)["template"] is None
    assert "template" not in resolve(load(show), shot)["camera"] and entry.is_file()


def test_camerawork_warnings(show: Path) -> None:
    from vinci_olf.author import apply_template, set_shot
    from vinci_olf.render import prompt

    def warnings() -> list[str]:
        """The messages of validate, which must all be warnings."""
        issues = validate(load(show))
        assert all(i.level == "warning" for i in issues), [str(i) for i in issues]
        return [i.message for i in issues]

    first, second, insert = "e02/s03/sh014", "e02/s03/sh015", "e02/s03/sh016"
    apply_template(load(show), first, "anime/qtu-shock")  # 0+18 with a hold of 0+10: 8 frames
    assert warnings() == []
    set_shot(load(show), first, duration="1+12")  # a longer shot, the same hold: a slow move
    apply_template(load(show), second, "anime/qtu-shock")
    set_shot(load(show), second, framing="wide")
    assert warnings() == [
        "cam/qtu-shock is a quick move of 0+08 at most: this move takes 1+02 (make a hold longer)",
        "cam/qtu-shock suits the framings medium, medium_close, close_up, not wide",
        "cam/qtu-shock follows itself: e02/s03/sh014 uses it too",
    ]
    apply_template(load(show), first, "anime/reaction-cu")  # the shot has a line
    apply_template(load(show), second, "anime/kuchipaku-hold")  # the shot has no line
    assert warnings() == [
        "cam/reaction-cu is for a shot with no dialogue",
        "cam/kuchipaku-hold suits the framings medium, medium_close, close_up, not wide",
        "cam/kuchipaku-hold suits at least 1+00: the shot is 0+18",
        "cam/kuchipaku-hold is for a shot with a dialogue line",
    ]
    assert load(show).docs[second].data["duration"] == "0+18"  # no dialogue take: no new length
    apply_template(load(show), first, "anime/two-shot-axis")
    apply_template(load(show), second, "anime/tu-slow")
    set_shot(load(show), second, amount=0.5, duration="1+00", framing="medium")
    assert warnings() == [
        "cam/two-shot-axis suits the framings medium, wide, not close_up",
        "cam/two-shot-axis needs 2 characters in the shot: it has 1",
        "cam/tu-slow suits at least 2+00: the shot is 1+00",
        "cam/tu-slow is a small move: amount 0.5 is over 0.2",
    ]
    # A cast that the shot states stays through a BG-only template and a template with slots.
    # Before, the two picks gave the insert of the key the scene's cast, Mira (PR-Agent, #529).
    sh016 = show / "episodes/e02/scenes/s03/sh016.yaml"
    apply_template(load(show), insert, "anime/pillow-shot")
    apply_template(load(show), insert, "anime/tu-slow")
    assert "characters: { $remove: [char/mira] }" in sh016.read_text(encoding="utf-8")
    # A BG-only template clears a cast from the scene, and a template with slots gives it back.
    edit(sh016, "characters: { $remove: [char/mira] }\n", "")
    apply_template(load(show), insert, "cam/pillow-shot")
    text = sh016.read_text(encoding="utf-8")
    assert "characters: []\n" in text and resolve(load(show), insert)["characters"] == []
    assert "cam/pillow-shot suits the framings wide, extreme_wide, not insert" in warnings()
    assert "Background art only. No characters" in prompt(resolve(load(show), insert), "keyframe")
    apply_template(load(show), insert, "cam/tu-slow")
    assert [c["id"] for c in resolve(load(show), insert)["characters"]] == ["char/mira"]
    # A template that the bible does not have is an error, and so is a wrong kind of entry.
    edit(show / SCENE, "template: cam/two-shot-axis", "template: cam/nope")
    assert "unknown reference cam/nope" in [i.message for i in validate(load(show))]
    edit(show / SCENE, "template: cam/nope", "template: char/mira")
    assert any("char/mira" in i.message and i.level == "error" for i in validate(load(show)))


def test_camerawork_renders(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("the mock video model and an engine move run ffmpeg")
    from vinci_olf.api import summary
    from vinci_olf.author import apply_template
    from vinci_olf.edit import set_select
    from vinci_olf.explain import explain
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    # A model template: its motion words go in the prompt, its avoid words in the negative
    # prompt of the video (the keyframe keeps the style's words only).
    quiet = "e02/s03/sh015"
    apply_template(load(show), quiet, "anime/reaction-cu")
    assert render(load(show), quiet, engine=engine)["takes"] == [f"{quiet}/kf1", f"{quiet}/v1"]
    p = load(show)
    video, still = (p.docs[f"{quiet}/{name}"].data["provenance"] for name in ("v1", "kf1"))
    assert video["model"] == "mock:mp4:v1"
    # The edit impact of a template: its videos, and its keyframes too when it has keyframe words.
    quiet_entry = show / "bible/camerawork/reaction-cu/reaction-cu.yaml"

    def impact() -> int:
        """The number of takes that an edit of cam/reaction-cu makes stale."""
        rows = summary(load(show))["bible"]["camerawork"]
        return next(row["impact"] for row in rows if row["id"] == "cam/reaction-cu")

    assert impact() == 1
    with quiet_entry.open("a", encoding="utf-8") as file:
        file.write("keyframe: The eyes of {a} are wide.\n")
    assert impact() == 2
    assert "Mira Sol reacts with the eyes and the brows only" in video["prompt"]
    assert still["negative_prompt"] == "text, watermark, extra limbs" and video[
        "negative_prompt"
    ] == ("text, watermark, extra limbs, the mouth moves, speech, head turn, camera movement")
    # An engine template: a $0 take from the chosen keyframe. A new template on the shot does
    # not make its keyframe stale.
    shot, entry = "e02/s03/sh014", show / "bible/camerawork/tu-to-eyes/tu-to-eyes.yaml"
    render(load(show), shot, kind="keyframe", engine=engine)
    render(load(show), shot, kind="audio", engine=engine)  # a1: about 1.1 s of speech
    set_select(load(show), shot, keyframe="kf1", audio="a1")
    # A template whose length is the dialogue: the chosen dialogue take, up to a whole frame.
    assert apply_template(load(show), shot, "anime/kuchipaku-hold")["duration"] == "1+03"
    apply_template(load(show), shot, "anime/tu-to-eyes")
    assert not stale(load(show), f"{shot}/kf1")
    result = render(load(show), shot, engine=engine)
    assert result["takes"] == [f"{shot}/v1"] and result["plan"][-1]["model"] == "local:ffmpeg:v1"
    take = load(show).docs[f"{shot}/v1"].data
    assert take["duration"] == "3.000s"
    assert take["provenance"]["parameters"]["center"] == [0.5, 0.42]
    # An edit to the template makes the video stale, and the cause names the template.
    edit(entry, "amount: 0.35", "amount: 0.25")
    edit(entry, "Only the eyes move.", "Only the eyes move, a little.")
    p = load(show)
    assert stale(p, f"{shot}/v1") and not stale(p, f"{shot}/kf1")
    why = explain(p, f"{shot}/v1")
    assert [change["label"] for change in why["changes"]] == [
        "cam/tu-to-eyes (camera.amount)",
        "cam/tu-to-eyes (prompt)",
    ] and why["summary"] == "cam/tu-to-eyes (camera.amount) and 1 more changed"


def _two_characters(show: Path) -> None:
    """Give scene s03 of the sample a second character (Mira's sheet stands in for his)."""
    folder = show / "bible/characters/tomas"
    folder.mkdir(parents=True)
    shutil.copy(show / "bible/characters/mira/sheet.png", folder / "sheet.png")
    (folder / "tomas.yaml").write_text(
        "id: char/tomas\nname: Tomas Hale\ndescription: A retired keeper.\nsheet: sheet.png\n",
        encoding="utf-8",
    )
    edit(show / SCENE, "characters: [char/mira]", "characters: [char/mira, char/tomas]")


def test_pills_and_the_180_line(show: Path) -> None:
    """COREPRODUC-565: pills stand in for the cast, and a two-shot sets the 180° line."""
    from vinci_olf.api import summary
    from vinci_olf.author import apply_template, set_shot

    _two_characters(show)
    two, over, single = "e02/s03/sh014", "e02/s03/sh015", "e02/s03/sh016"
    apply_template(load(show), two, "anime/two-shot-axis")  # Mira at the left, Tomas at the right
    set_shot(load(show), two, framing="medium")
    apply_template(load(show), over, "anime/ots-b")  # over Tomas's shoulder, on Mira
    apply_template(load(show), single, None)
    set_shot(load(show), single, framing="close_up", angle="eye_level", lens="50mm")
    edit(show / "episodes/e02/scenes/s03/sh016.yaml", "{ $remove: [char/mira] }", "[char/mira]")

    def crossings() -> list[str]:
        return [i.message for i in validate(load(show)) if "180" in i.message]

    shots = summary(load(show))["shots"]
    assert [(x["name"], x["x"], x["facing"]) for x in shots[two]["pills"]["start"]] == [
        ("Mira Sol", 0.3, "right"),
        ("Tomas Hale", 0.7, "left"),
    ]
    assert [(x["slot"], x["facing"]) for x in shots[over]["pills"]["start"]] == [
        ("b", "away"),  # his shoulder, from behind
        ("a", "right"),  # Mira looks at him
    ]
    colors = {x["name"]: x["color"] for s in (two, over) for x in shots[s]["pills"]["start"]}
    assert colors == {"Mira Sol": "#1c9fb8", "Tomas Hale": "#e08a00"}
    # A single with no layout looks toward the other side of the line, with room for its gaze.
    # A character keeps its color in each shot: Tomas is the second pill in the two-shot and the
    # first (behind) in the over-the-shoulder shot, and amber in both.
    assert shots[single]["pills"] == {
        "start": [
            {"slot": "a", "id": "char/mira", "name": "Mira Sol"}
            | {"x": 0.4, "y": 0.42, "size": 0.75, "facing": "right", "color": "#1c9fb8"}
        ],
        "end": None,
        "aspect": "16:9",
        "stated": False,
        "crosses": None,
    }
    assert crossings() == []
    # A layout on the shot wins over the template's, and no take hashes it.
    before = inputs_hash(resolve(load(show), over), "keyframe")
    layout = "    layout: { start: [{ slot: a, x: 0.7 }, { slot: b, x: 0.3 }] }\n"
    edit(
        show / SCENE, "    forms: { char/mira: ember }", layout + "    forms: { char/mira: ember }"
    )
    assert inputs_hash(resolve(load(show), over), "keyframe") == before
    assert crossings() == [
        "Crosses the 180° line: e02/s03/sh014 has Mira Sol at the left of Tomas Hale"
    ]
    with (show / "episodes/e02/scenes/s03/sh016.yaml").open("a", encoding="utf-8") as file:
        file.write("layout: { start: [{ slot: a, facing: left }] }\n")
    assert crossings()[1:] == [
        "Crosses the 180° line: e02/s03/sh014 has Mira Sol on the left, so Mira Sol looks right"
    ]
    # Rules that look at the shot or at its scene: a prop, and one use a scene.
    edit(show / SCENE, layout, "")
    apply_template(load(show), over, "anime/insert-object")
    apply_template(load(show), two, "anime/harmony-freeze")
    apply_template(load(show), single, "anime/harmony-freeze")
    messages = [i.message for i in validate(load(show))]
    assert "cam/insert-object is for a shot of a prop: name it in the shot's props" in messages
    assert messages.count("cam/harmony-freeze suits 1 shot(s) of a scene at most") == 1
    # A layout off the schema: validate names it, the summary opens with no pills, and previs
    # says why. Before, both stopped with a ValueError: HTTP 500 (PR-Agent review of #530).
    from vinci_olf.previs import previs

    sh016 = show / "episodes/e02/scenes/s03/sh016.yaml"
    edit(
        sh016, "layout: { start: [{ slot: a, facing: left }] }", "layout: { start: [{ slot: d }] }"
    )
    assert any(i.level == "error" and "sh016" in i.where for i in validate(load(show)))
    assert not any("pills" in shot for shot in summary(load(show))["shots"].values())
    with pytest.raises(OlfError, match="previs of e02 stopped: fix the errors that validate"):
        previs(load(show), "e02", sheet=False, animatic=False)


def test_canvas_draws_a_wider_keyframe_for_a_pan(
    show: Path, tmp_path: Path, monkeypatch: Any
) -> None:
    """COREPRODUC-565: camera.canvas asks for a drawing of its shape, and the engine pans it."""
    if not shutil.which("ffmpeg"):
        pytest.skip("an engine move runs ffmpeg")
    from vinci_media.camera import drawing_size
    from vinci_olf.author import apply_template, set_shot
    from vinci_olf.edit import set_select
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    shot = "e02/s03/sh016"
    apply_template(load(show), shot, "anime/pan-establish")  # BG only, 21:9, an engine pan
    set_shot(load(show), shot, duration="0+12")  # short: the test draws few frames
    render(load(show), shot, kind="keyframe", engine=engine)
    p = load(show)
    still = p.docs[f"{shot}/kf1"].data
    assert still["provenance"]["parameters"]["aspect_ratio"] == "21:9"
    assert drawing_size(p.local_file(still["output"])) == (960, 412)  # the mock draws 21:9
    set_select(p, shot, keyframe="kf1")
    import vinci_media.camera as cam

    seen, real = [], cam.windows  # the canvas reaches the plan note and the runtime move
    monkeypatch.setattr(
        cam, "windows", lambda *a, **k: seen.append(k.get("canvas")) or real(*a, **k)
    )
    result = render(load(show), shot, engine=engine)
    assert len(seen) == 2 and set(seen) == {"21:9"}
    move = load(show).docs[f"{shot}/v1"].data["provenance"]
    assert move["model"] == "local:ffmpeg:v1" and move["parameters"]["move"] == "pan"
    assert move["parameters"]["canvas"] == "21:9"
    assert "enlarges it 2.6x" in result["notes"][0]  # 412 px high under a 1080 px frame
    # The keyframe hashes the canvas: another shape needs another drawing.
    set_shot(load(show), shot, canvas="2:1")
    assert stale(load(show), f"{shot}/kf1")
    # A model that cannot draw the shape stops at the plan, before any spend.
    set_shot(load(show), shot, canvas="4:3")
    with pytest.raises(OlfError, match="mock:png:v1 cannot draw a 4:3 keyframe"):
        render(load(show), shot, kind="keyframe", engine=engine, dry_run=True)


def test_previs_drawing_shape_is_bounded() -> None:
    """A canvas far from any frame shape draws no strip: `1:1000` asked for 2.7 GB (#530)."""
    from vinci_olf.previs import _drawing

    assert _drawing((1920, 1080), "21:9") == (2520, 1080)
    assert _drawing((1920, 1080), "1:1000") == (1920, 7680)
    assert _drawing((1920, 1080), "1000:1") == (4320, 1080)


def test_previs_sheet_and_animatic(show: Path, tmp_path: Path, monkeypatch: Any) -> None:
    """COREPRODUC-565: the e-conte sheet (5 cuts a page) and the animatic, at $0."""
    if not shutil.which("ffmpeg"):
        pytest.skip("the animatic runs ffmpeg")
    from PIL import Image
    from vinci_media import has_audio, probe
    from vinci_olf.__main__ import main
    from vinci_olf.author import add_shot
    from vinci_olf.edit import set_take
    from vinci_olf.previs import best_take, previs
    from vinci_olf.render import render

    engine = _demo_engine(tmp_path, monkeypatch)
    shot = "e02/s03/sh014"
    render(load(show), shot, kind="keyframe", count=2, engine=engine)
    p = load(show)
    assert best_take(p, shot, "keyframe") == p.local_file(p.docs[f"{shot}/kf2"].data["output"])
    set_take(p, f"{shot}/kf2", status="rejected")  # a rejected take is not the best picture
    p = load(show)
    assert best_take(p, shot, "keyframe") == p.local_file(p.docs[f"{shot}/kf1"].data["output"])
    assert best_take(p, "e02/s03/sh015", "keyframe") is None  # pills, then
    for n in range(3):  # 6 cuts: two pages of 5
        add_shot(load(show), "e02/s03", f"Wide shot {n}.", duration="0+12", framing="wide")
    result = previs(load(show), "e02")
    assert result["cuts"] == 6 and result["runtime"] == pytest.approx(10.0)
    assert result["files"] == [
        "previs/e02/e02-sheet.pdf",
        "previs/e02/e02-sheet-01.png",
        "previs/e02/e02-sheet-02.png",
        "previs/e02/e02-animatic.mp4",
    ]
    pdf = (show / result["files"][0]).read_bytes()
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") == 2
    with Image.open(show / result["files"][1]) as page:
        assert page.size == (1240, 1754)
    info = probe(show / result["files"][3])
    assert (info["width"], info["height"]) == (960, 540)
    assert float(info["duration"]) == pytest.approx(10.0, abs=0.1)
    # The mock render: one look for every cut (pills), the whole episode, no sound stream.
    mock = previs(load(show), "e02", sheet=False, animatic=False, mock=True)["files"]
    assert mock == ["previs/e02/e02-mock.mp4"]
    info = probe(show / mock[0])
    assert (info["width"], info["height"]) == (960, 540) and not has_audio(show / mock[0])
    assert float(info["duration"]) == pytest.approx(10.0, abs=0.05)
    # The CLI can make the sheet alone. Previs is derived output: the lock file does not list it.
    assert main(["previs", "e02", "--sheet", "-C", str(show)]) == 0
    assert "previs/" not in (show / "assets/lock.yaml").read_text(encoding="utf-8")


def test_import_gives_a_line_in_an_anime_show_kuchipaku(tmp_path: Path) -> None:
    """COREPRODUC-565: in a 2D anime show, the importer gives a line `kuchipaku-hold`."""
    from vinci_olf.author import add_episode, new_show
    from vinci_olf.script import import_script

    script = (
        "INT. LAMP ROOM - NIGHT\n\nMira lifts the key.\n\nMIRA\nYou kept it?\n\nTOMAS\nI did.\n"
    )
    for medium, template in (("2D anime", "cam/kuchipaku-hold"), ("3D CG", None)):
        p = new_show(tmp_path / medium.replace(" ", ""), "Show", medium=medium)
        episode = add_episode(load(p.root), "Pilot")
        scene = import_script(load(p.root), episode, script)["scenes"][0]
        shots = read(load(p.root).docs[scene].path)["shots"]
        assert [s["camera"].get("template") for s in shots] == [None, template, template]
        assert [s.get("characters") for s in shots][1:] == (
            [["char/mira"], ["char/tomas"]] if template else [None, None]
        )  # the speaker alone, so the template's {a} is the speaker
        source = load(p.root).docs.get("cam/kuchipaku-hold")
        assert (source.data["source"] if source else None) == (
            "anime/kuchipaku-hold@1" if template else None
        )
