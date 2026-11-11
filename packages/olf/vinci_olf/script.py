"""Scripts to OLF scenes and shots (Claude Design screens 1 and 5; COREPRODUC-547, -548).

``parse`` reads Fountain or plain text without AI: a scene heading starts a scene, a character
cue starts a dialogue line, and each action sentence or dialogue line becomes one shot, numbered
in steps of 10 when written. A paragraph that starts with a shot tag, ``[WS 24mm 4s] The lamp
turns.``, is one shot with that framing, lens and length. A text model (``t2t``) writes tagged
scripts: "Shot list from script" asks it to split a script into shots, and "Draft from idea"
asks it for a script. A model's reply is parsed like any script, and each new file is checked
against the OLF schema before it is written.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from ruamel.yaml.scalarstring import LiteralScalarString

from vinci_olf.author import _list_value, add_template
from vinci_olf.edit import _save
from vinci_olf.project import OlfError, Project, write
from vinci_olf.render import run_one
from vinci_olf.validate import schema_errors

log = logging.getLogger(__name__)
TAGS = {
    "EWS": "extreme_wide",
    "WS": "wide",
    "MS": "medium",
    "MCU": "medium_close",
    "CU": "close_up",
    "ECU": "extreme_close_up",
    "INS": "insert",
}
ABBR = {framing: tag for tag, framing in TAGS.items()}
LENSES = {  # the lens a framing usually gets (design: WS 24mm, MS 35mm, CU 50mm, ECU 85mm)
    "extreme_wide": "24mm",
    "wide": "24mm",
    "medium": "35mm",
    "medium_close": "50mm",
    "close_up": "50mm",
    "extreme_close_up": "85mm",
    "insert": "85mm",
}
HEADING = re.compile(
    r"^(?:\.(?=\w)|(?P<io>INT\.?/EXT|EXT\.?/INT|I/E|INT|EXT|EST)[.\s])\s*(?P<rest>.+)$", re.I
)
CUE = re.compile(r"^(?:@(?P<forced>\S.*)|(?P<name>[A-Z][A-Z0-9 .'\-]*))(\s*\([A-Z.' ]+\))*\s*\^?$")
TAG = re.compile(
    r"^\[(?P<abbr>[A-Z]{2,3})(?:\s+(?P<lens>\d+mm))?(?:\s+(?P<sec>\d+(?:\.\d+)?)s)?\]\s*"
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
SKIP = re.compile(r"^(?:[A-Z0-9 .']+TO:|>.*<|={3,}|#.*)$")  # transitions, centered, breaks
TITLE_KEY = re.compile(
    r"^(?:title|credit|authors?|source|draft date|contact|notes|copyright):", re.I
)
MAX_SCRIPT = 200_000  # characters of one script
SPOKEN = "anime/kuchipaku-hold"  # the camerawork of a line in a 2D anime show
SHOTS_SYSTEM = (
    "You turn film scripts into shot lists. Reply with the script only, in Fountain. Keep every "
    "scene heading and every dialogue block (character cue, parenthetical, line) as written. "
    "Replace each action paragraph with one paragraph per shot, and start each shot paragraph "
    "with a tag [FRAMING LENS SECONDSs], for example [WS 24mm 4s]. FRAMING is one of "
    "EWS, WS, MS, MCU, CU, ECU, INS. Use only these lenses: {lenses}. Add no other text."
)
DRAFT_SYSTEM = (
    "You write short episode scripts in Fountain for an animated show. Reply with the script "
    "only: scene headings (INT. or EXT. PLACE - TIME), action paragraphs, and dialogue blocks "
    "with the character cue in capitals. Write 2 or 3 scenes and less than 300 words. Use these "
    "characters when they fit: {cast}."
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


def _heading(line: str) -> dict[str, Any] | None:
    """``INT. LAMP ROOM - NIGHT`` as heading, place, interior and time; None for other lines."""
    match = HEADING.match(line)
    if not match:
        return None
    rest = re.sub(r"\s*#[^#]*#$", "", match["rest"]).strip()  # a scene number: #12#
    place, _, time = rest.rpartition(" - ") if " - " in rest else (rest, "", "")
    inside = (match["io"] or "").upper().startswith(("INT", "I/E"))
    return {"heading": line.strip(), "place": place.strip(), "inside": inside, "time": time.strip()}


def parse(text: str) -> list[dict[str, Any]]:
    """Split a script into scenes of beats, without AI.

    Returns:
        ``[{"heading", "place", "inside", "time", "script", "beats"}]``. A beat is an action
        ``{"action", "tag"}`` or a line ``{"speaker", "line", "delivery"?}``; ``tag`` holds the
        shot tag's ``framing``, ``lens`` and ``seconds`` (empty without one). Text before the
        first heading, or a script without headings, is one scene with no heading.

    Raises:
        OlfError: The script is longer than 200,000 characters.
    """
    text = str(text or "")
    if len(text) > MAX_SCRIPT:
        raise OlfError(f"a script can have at most {MAX_SCRIPT:,} characters")
    body = re.sub(r"/\*.*?\*/|\[\[.*?\]\]", "", text.replace("\r\n", "\n"), flags=re.S)
    scenes: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", body):
        rows = [row.strip() for row in block.split("\n") if row.strip()]
        if not rows or (not scenes and TITLE_KEY.match(rows[0])):  # empty, or the title page
            continue
        if head := _heading(rows[0]):
            scenes.append(head | {"blocks": [], "beats": []})
            rows = rows[1:]
        elif not scenes:
            scenes.append(
                {
                    "heading": None,
                    "place": "",
                    "inside": False,
                    "time": "",
                    "blocks": [],
                    "beats": [],
                }
            )
        if not rows:
            continue
        scene = scenes[-1]
        scene["blocks"].append("\n".join(rows))
        cue = CUE.match(rows[0])
        if cue and len(rows) > 1 and (cue["forced"] or rows[0] == rows[0].upper()):
            said = [r for r in rows[1:] if not (r.startswith("(") and r.endswith(")"))]
            how = next(
                (r[1:-1].strip() for r in rows[1:] if r.startswith("(") and r.endswith(")")), ""
            )
            if said:
                speaker = (cue["forced"] or cue["name"]).strip()
                scene["beats"].append(
                    {"speaker": speaker, "line": " ".join(said)}
                    | ({"delivery": how} if how else {})
                )
            continue
        if SKIP.match(rows[0]):
            continue
        paragraph = " ".join(rows)
        if tag := TAG.match(paragraph):  # a model's shot: the whole paragraph is one shot
            framing = TAGS.get(tag["abbr"])
            scene["blocks"][-1] = paragraph[tag.end() :].strip()  # the scene's script has no tags
            scene["beats"].append(
                {
                    "action": paragraph[tag.end() :].strip(),
                    "tag": {
                        "framing": framing,
                        "lens": tag["lens"],
                        "seconds": float(tag["sec"]) if tag["sec"] else None,
                    },
                }
            )
            continue
        scene["beats"] += [
            {"action": s.strip(), "tag": {}} for s in SENTENCE.split(paragraph) if s.strip()
        ]
    for scene in scenes:
        scene["script"] = "\n\n".join(scene.pop("blocks"))
    return scenes


def _frame(beat: dict[str, Any], first: bool) -> tuple[str, float, str]:
    """Framing, seconds and lens of one beat: its tag, else a wide first shot, a medium action
    and a close-up line. A line lasts about 2.5 words a second; an action, 3 words plus 1 s."""
    tag = beat.get("tag") or {}
    words = len(str(beat.get("line") or beat.get("action") or "").split())
    if "line" in beat:
        framing, seconds = "close_up", min(max(words / 2.5 + 0.5, 1.5), 8.0)
    else:
        framing = tag.get("framing") or ("wide" if first else "medium")
        seconds = tag.get("seconds") or min(max(words / 3 + 1, 2.0), 6.0)
    return framing, round(seconds * 2) / 2, tag.get("lens") or LENSES[framing]


def tagged(text: str) -> str:
    """The script with each action paragraph replaced by tagged shots (the rules' shot list).

    The demo text model answers "Shot list from script" with this, so a $0 run takes the same
    path as a real model.
    """
    out: list[str] = []
    for scene in parse(text):
        out += [scene["heading"]] if scene["heading"] else []
        for i, beat in enumerate(scene["beats"]):
            if "line" in beat:
                how = f"\n({beat['delivery']})" if beat.get("delivery") else ""
                out.append(f"{beat['speaker'].upper()}{how}\n{beat['line']}")
            else:
                framing, seconds, lens = _frame(beat, i == 0)
                out.append(f"[{ABBR[framing]} {lens} {seconds:g}s] {beat['action']}")
    return "\n\n".join(out) + "\n"


def bible_names(p: Project) -> dict[str, Any]:
    """What ``preview`` needs from a show: characters and locations (ID -> name), the
    variants of each location, and the style lenses."""
    rows = {kind: p.of_kind(kind) for kind in ("character", "location")}
    style = p.docs.get("style")
    return {
        "characters": {k: str(d.data.get("name") or k) for k, d in rows["character"].items()},
        "locations": {k: str(d.data.get("name") or k) for k, d in rows["location"].items()},
        "variants": {k: list(d.data.get("variants") or []) for k, d in rows["location"].items()},
        "lenses": [str(x) for x in ((style.data.get("lenses") if style else None) or [])],
    }


def _match(name: str, known: dict[str, str]) -> str | None:
    """A known ID whose name, first name or slug is ``name`` (case does not matter)."""
    want = name.strip().lower()
    for key, full in known.items():
        if want in {full.lower(), full.split()[0].lower() if full else "", key.split("/")[-1]}:
            return key
    return None


def preview(
    text: str,
    *,
    characters: dict[str, str] | None = None,
    locations: dict[str, str] | None = None,
    variants: dict[str, list[str]] | None = None,
    lenses: list[str] | None = None,
) -> dict[str, Any]:
    """Turn a script into the scenes and shots that ``import_script`` writes, without writing.

    Args:
        text: Fountain or plain text.
        characters: Known characters, ID -> name. A cue matches a name, a first name or a slug.
        locations: Known locations, ID -> name. A heading's place matches a name or a slug.
        variants: The variants of known locations. A scene gets its time as the variant when
            the location lists it (or lists none); a new location lists the times it is used at.
        lenses: The style lenses. A shot gets the usual lens of its framing only when listed.

    Returns:
        ``{"scenes": [{"heading", "location", "variant", "characters", "script", "shots"}],
        "characters": [{"name", "id", "new"}], "locations": [{"name", "id", "new", ...}],
        "shots": count, "runtime": seconds}``. New entries get IDs from their names.
    """
    characters, locations, lenses = characters or {}, locations or {}, lenses or []
    variants = variants or {}
    cast: dict[str, dict[str, Any]] = {}
    places: dict[str, dict[str, Any]] = {}
    scenes = []
    for scene in parse(text):
        speakers = [b["speaker"] for b in scene["beats"] if "speaker" in b]
        for name in speakers:
            if name.lower() not in cast:
                known = _match(name, characters)
                cast[name.lower()] = {
                    "name": characters[known] if known else name.title(),
                    "id": known or f"char/{_slug(name)}",
                    "new": known is None,
                }
        loc, variant = None, None
        if scene["place"]:
            key = scene["place"].lower()
            if key not in places:
                known = _match(scene["place"], locations)
                places[key] = {
                    "name": locations[known] if known else scene["place"].capitalize(),
                    "id": known or f"loc/{_slug(scene['place'])}",
                    "new": known is None,
                    "inside": scene["inside"],
                    "variants": [],
                }
            loc = places[key]
            variant = _slug(scene["time"]) if scene["time"] else None
            if variant and loc["new"] and variant not in loc["variants"]:
                loc["variants"].append(variant)
            elif (
                variant and not loc["new"] and variant not in (variants.get(loc["id"]) or [variant])
            ):
                variant = None  # the validator allows only a variant the location lists
        # Known characters named in the action are in the scene too, so their sheets are used.
        action = " ".join(b.get("action", "") for b in scene["beats"]).lower()
        named = [
            k
            for k, v in characters.items()
            if v.strip() and re.search(rf"\b{re.escape(v.split()[0].lower())}\b", action)
        ]
        in_scene = list(dict.fromkeys([cast[n.lower()]["id"] for n in speakers] + named))
        shots = []
        for i, beat in enumerate(scene["beats"]):
            framing, seconds, lens = _frame(beat, i == 0)
            camera = {"framing": framing} | ({"lens": lens} if lens in lenses else {})
            if "line" in beat:
                who = cast[beat["speaker"].lower()]
                verb = (
                    f"{beat['delivery']}s"
                    if re.fullmatch(r"[a-z]+", beat.get("delivery", ""))
                    else "speaks"
                )
                line = {"speaker": who["id"], "line": beat["line"]}
                line |= {"delivery": beat["delivery"]} if beat.get("delivery") else {}
                # The line stays in `dialogue`: an image model draws a quoted line as a caption.
                shot = {
                    "description": f"{who['name'].split()[0]} {verb}.",
                    "duration": f"{seconds:g}s",
                    "camera": camera,
                    "dialogue": [line],
                }
            else:
                shot = {
                    "description": beat["action"],
                    "duration": f"{seconds:g}s",
                    "camera": camera,
                }
            shots.append(shot)
        scenes.append(
            {
                "heading": scene["heading"] or "Scene",
                "location": loc["id"] if loc else None,
                "variant": variant,
                "characters": in_scene,
                "script": scene["script"],
                "shots": shots,
            }
        )
    runtime = sum(float(s["duration"][:-1]) for scene in scenes for s in scene["shots"])
    count = sum(len(scene["shots"]) for scene in scenes)
    return {
        "scenes": scenes,
        "characters": list(cast.values()),
        "locations": list(places.values()),
        "shots": count,
        "runtime": runtime,
    }


def import_script(p: Project, episode_id: str, text: str) -> dict[str, Any]:
    """Add a script to an episode: its scenes and shots, and new locations and characters.

    A new location gets a text description; a new character gets a description and needs a
    sheet before it is valid (the issues page says so). Every file is checked against the OLF
    schema first, so nothing is written when one would be wrong.

    In a show whose ``style.look.medium`` is 2D anime, a shot of a line gets the camerawork
    template ``kuchipaku-hold`` (a held pose; only the mouth moves) and only its speaker in
    ``characters``, so the template's ``{a}`` is the speaker.

    Returns:
        ``{"scenes": [new scene IDs], "locations": [new IDs], "characters": [new IDs]}``.

    Raises:
        OlfError: The episode is missing, the script has no shots, or a file would be invalid.
    """
    episode = p.docs.get(episode_id)
    if episode is None or p.kind(episode_id) != "episode":
        raise OlfError(f"{episode_id}: no such episode")
    view = preview(text, **bible_names(p))
    if not view["shots"]:
        raise OlfError("the script has no action or dialogue to make shots from")
    style = p.docs.get("style")
    look = (style.data.get("look") if style else None) or {}
    anime = "anime" in str(look.get("medium") if isinstance(look, dict) else "").lower()
    spoken = f"cam/{SPOKEN.split('/')[1]}"
    files: list[tuple[Any, str, dict[str, Any]]] = []  # (path, OLF kind, data)
    for loc in (x for x in view["locations"] if x["new"]):
        side = "interior" if loc["inside"] else "exterior"
        data = {
            "id": loc["id"],
            "name": loc["name"],
            "description": f"{loc['name']} ({side}), from the episode script.",
        }
        data |= {"variants": loc["variants"]} if loc["variants"] else {}
        slug = loc["id"].split("/", 1)[1]
        files.append((p.root / "bible" / "locations" / slug / f"{slug}.yaml", "location", data))
    for char in (x for x in view["characters"] if x["new"]):
        data = {
            "id": char["id"],
            "name": char["name"],
            "description": f"{char['name']}, from the episode script.",
        }
        slug = char["id"].split("/", 1)[1]
        files.append((p.root / "bible" / "characters" / slug / f"{slug}.yaml", "character", data))
    numbers = [
        int(s.rsplit("/s", 1)[1]) for s in p.of_kind("scene") if s.startswith(f"{episode_id}/")
    ]
    scene_ids = []
    for n, scene in enumerate(view["scenes"], max(numbers, default=0) + 1):
        scene_id = f"{episode_id}/s{n:02d}"
        data = {"id": scene_id, "heading": scene["heading"]}
        data |= {k: scene[k] for k in ("location", "variant", "characters") if scene[k]}
        data |= {"script": LiteralScalarString(scene["script"] + "\n")} if scene["script"] else {}
        data["control"] = {"first_frame": "keyframe"}  # keyframes first: video animates the pick
        data["shots"] = [
            {"id": f"{scene_id}/sh{10 * i:03d}", **s} for i, s in enumerate(scene["shots"], 1)
        ]
        for shot in data["shots"] if anime else []:
            if shot.get("dialogue"):
                shot["characters"] = [shot["dialogue"][0]["speaker"]]
                shot["camera"] = shot["camera"] | {"template": spoken}
        files.append((episode.path.parent / "scenes" / f"s{n:02d}.yaml", "scene", data))
        scene_ids.append(scene_id)
    for path, kind, data in files:  # check every file before writing any (548: validate first)
        if problems := schema_errors(kind, data):
            raise OlfError(f"{data['id']} would not be valid OLF: {problems[0]}")
        if p.inside(path).exists():
            raise OlfError(f"{p.rel(path)} already exists; nothing was written")
    uses = any(
        "template" in s["camera"] for _, kind, d in files if kind == "scene" for s in d["shots"]
    )
    if uses and spoken not in p.docs:  # a show's own template of that name stays as it is
        add_template(p, SPOKEN)
    for path, _, data in files:
        write(data, p.inside(path), compact=True)
    listed = [s for s in episode.data.get("scenes") or [] if isinstance(s, str)]
    lines = episode.path.read_text(encoding="utf-8").splitlines(keepends=True)
    _list_value(lines, "scenes", [*listed, *scene_ids])  # one flow line: scenes: [e01/s01, ...]
    _save(episode.path, lines, lambda d: d.get("scenes") == [*listed, *scene_ids])
    new = {
        "scenes": scene_ids,
        "locations": [x["id"] for x in view["locations"] if x["new"]],
        "characters": [x["id"] for x in view["characters"] if x["new"]],
    }
    log.info("episode %s: imported a script: %s (%d shots)", episode_id, new, view["shots"])
    return new


def ask(prompt: str, system: str, *, mock_reply: str, **run: Any) -> dict[str, Any]:
    """Run one text step (``t2t``) with the price first, as a render does (``render.run_one``).

    ``mock_reply`` is what the demo text model answers, so demo mode runs the same path at $0.

    Returns:
        ``{"plan", "total", "unpriced", "text"}``; ``text`` is None for a dry run.

    Raises:
        OlfError: No text model is connected, the price stops the step, or the run fails.
    """
    # olf_request is Vinci-only (providers send prompt and system): each ask is a new reply.
    params = {"prompt": prompt, "system": system, "mock_reply": mock_reply}
    result = run_one("t2t", params | {"olf_request": uuid.uuid4().hex}, **run)
    output = result.pop("output")
    result.pop("provenance")
    result["text"] = output.decode("utf-8", "replace") if output is not None else None
    log.info("text step: %s characters back", len(result["text"] or ""))
    return result


def split_with_model(text: str, *, lenses: list[str] | None = None, **run: Any) -> dict[str, Any]:
    """Ask a text model to split a script into tagged shots ("Shot list from script").

    Returns ``ask``'s result; parse ``text`` with ``preview``.
    """
    if not parse(text):
        raise OlfError("write or paste a script first")
    system = SHOTS_SYSTEM.format(lenses=", ".join(lenses or []) or "24mm, 35mm, 50mm, 85mm")
    return ask(str(text), system, mock_reply=tagged(text), **run)


def draft(idea: str, *, cast: list[str] | None = None, **run: Any) -> dict[str, Any]:
    """Ask a text model for a first episode script from an idea ("Draft from idea").

    Returns ``ask``'s result; ``text`` is a Fountain script.
    """
    idea = " ".join(str(idea or "").split())
    if not idea or len(idea) > 2000:
        raise OlfError("write the idea in one or two sentences (at most 2,000 characters)")
    who = (cast[0].split()[0] if cast else "Hero").upper()
    demo = f"EXT. OPENING - DAY\n\n{idea}\n\n{who}\nThis is where it starts.\n"
    return ask(
        idea,
        DRAFT_SYSTEM.format(cast=", ".join(cast or []) or "invent one or two"),
        mock_reply=demo,
        **run,
    )
