"""The scene lab's build step (COREPRODUC-714, -720): ask a text model for a room or a staged
shot, read its answer, and use a try as a shot's keyframe layout.

A request goes to a scene (``e02/s03``: build its room) or to a shot (``e02/s03/sh014``: stage
it in the scene's room; a scene with no room yet gets the room and the shot in one answer).
The model answers with a scene description in JSON (``vinci_olf.scene``); it never writes
code. The same prompt runs on any text model, or is copied for the person's own agent, and a
pasted answer is read the same way.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from vinci_olf.layout import COLORS, HEADS, STRIPES, _shot_colors, slot_name, slot_place
from vinci_olf.project import OlfError, Project
from vinci_olf.scene import (
    EYE,
    HEIGHT,
    NEAR,
    SENSOR_MM,
    Frame,
    _aspect,
    _dot,
    _label,
    _lens,
    _scene_dir,
    _unit,
    check_try,
    frame_of,
    read_room,
    room_tries,
    room_versions,
    save_room,
    save_room_try,
    save_try,
    tries,
    used,
)

log = logging.getLogger(__name__)
STAGING = ("camera", "cast", "groups", "props")  # what a shot try holds beside its room

PIECE = (
    '{ "name": "desk", "shape": "box|cylinder|cone|sphere|plane|rock", '
    '"size": [width, height, depth], "at": [x, y, z], "turn": degrees }'
)
RULES = (
    "Metres; y is up and the floor is y = 0. A piece's `at` is the centre of its bottom, so "
    "`y` 0 stands on the floor and a lamp on a 0.5 m base has `y` 0.5. Use only basic shapes; "
    "give each piece a short `name`. No colors, no lights, no materials: the look comes from "
    "the show's references. Answer with one JSON object and nothing else."
)
ROOM_SYSTEM = (
    "You build the 3D set of one scene of an animated show, as a list of set pieces. "
    f'Answer as {{ "set": [{PIECE}] }}. A wall is a thin box; a floor or ground is a plane. '
    "Keep the set coarse: the walls and ground, and only the pieces the action uses or that "
    "stand in a person's way. No trees, plants, rocks, lamps, benches or decoration nobody uses: "
    "a model copies small shapes it sees (a cone comes back as a cone pine), so the words of "
    "the show carry the detail. " + RULES
)
SHOT_SYSTEM = (
    "You stage one shot of an animated show in 3D: where the camera is and where each named "
    'person stands. Answer as { "camera": { "at": [x, y, z], "looks_at": [x, y, z] | "a" }, '
    '"cast": [{ "slot": "a", "at": [x, y, z], "faces": "camera" | "away" | degrees | "b", '
    '"end": { "at": [x, y, z], "faces": ... } }], '
    '"groups": [{ "name": "villagers", "count": 8, "area": [x0, z0, x1, z1], "faces": "camera" }], '
    f'"props": [{PIECE}] }}. A person\'s `at` is where the feet are; `end` only when they '
    "move during the shot. `looks_at` as a slot makes the camera follow that person's eyes. "
    "Keep every named person inside the camera's frame at the start and "
    "the end. `groups` are background people, never named. `props` are pieces for this shot "
    "only. " + RULES
)
BOTH = 'The scene has no set yet: add "set": [' + PIECE + "] to the same object, built first. "


def prompt_for(
    p: Project, target: str, request: str, room: int | None = None, base: int | None = None
) -> tuple[str, str]:
    """The system text and the prompt of a scene lab request.

    Args:
        p: The loaded project.
        target: A scene (build its room) or a shot (stage it).
        request: What the person asks for.
        room: The room version to stage the shot in; the newest when None.
        base: A try of the shot to start from (the compare screen's "change for a new try").

    Raises:
        OlfError: The scene or the shot is missing, or the request is empty.
    """
    request = " ".join(str(request or "").split())
    if not request or len(request) > 2000:
        raise OlfError("describe the scene in one or a few sentences (at most 2,000 characters)")
    kind = p.kind(target)
    if kind == "scene" and target in p.docs:
        return ROOM_SYSTEM, _scene_words(p, target) + f"\n\nThe person wants:\n{request}"
    if kind != "shot" or target not in p.docs:
        raise OlfError(f"{target}: no such scene or shot")
    scene = target.rsplit("/", 1)[0]
    has_room = bool(room_versions(p, scene))
    words = [_scene_words(p, scene), _shot_words(p, target)]
    if has_room:
        found = read_room(p, scene, room)
        words.append(
            f"The room (version {found['version']}), set pieces:\n" + json.dumps(found["set"])
        )
    if base:
        start = {k: v for k, v in _try_of(p, target, base).items() if k in STAGING}
        words.append(
            "Start from this staging; change only what the person asks for:\n" + json.dumps(start)
        )
    words.append(f"The person wants:\n{request}")
    return SHOT_SYSTEM + ("" if has_room else " " + BOTH), "\n\n".join(words)


def build(
    p: Project,
    target: str,
    request: str,
    *,
    room: int | None = None,
    base: int | None = None,
    **run: Any,
) -> dict[str, Any]:
    """Ask a text model (or copy the prompt) for a room or a staged shot, price first.

    ``run`` is ``script.ask``'s: ``model``, ``yes``, ``max_total``, ``dry_run``, ``engine`` and
    ``copy``. Demo mode answers with a simple room or staging, so a $0 run takes the same path.

    Returns:
        ``script.ask``'s answer; when a model answered, also what ``save_answer`` saved.
    """
    from vinci_olf.script import ask

    system, prompt = prompt_for(p, target, request, room, base)
    out = ask(prompt, system, mock_reply=json.dumps(_demo(p, target)), **run)
    if out.get("text") is None:  # a copied prompt, or a dry run for the price
        return out
    model = str(((out.get("plan") or [{}])[0] or {}).get("model") or "")
    return out | save_answer(p, target, out["text"], request=request, model=model, room=room)


def save_answer(
    p: Project,
    target: str,
    text: str,
    *,
    request: str = "",
    model: str = "",
    room: int | None = None,
) -> dict[str, Any]:
    """Read a model's or a pasted answer and save it: a room try for a scene; a shot try for a
    shot (and the scene's first room version, when the scene had none).

    Raises:
        OlfError: The answer is not JSON, or what it describes has errors.
    """
    data = parse(text)
    words = {k: v for k, v in (("request", request), ("model", model)) if v}
    if p.kind(target) == "scene":
        n = save_room_try(p, target, {"set": data.get("set")} | words)
        return {"room_try": n}
    scene, name = target.rsplit("/", 1)
    out: dict[str, Any] = {}
    if not room_versions(p, scene):  # the first shot of a scene builds its room too
        room = out["room"] = save_room(p, scene, {"set": data.get("set")} | words, source=name)
    staged: dict[str, Any] = {k: data[k] for k in STAGING if k in data}
    staged["room"] = room or room_versions(p, scene)[-1]
    out["try"] = save_try(p, target, staged | words)
    return out


def keep_room(
    p: Project,
    scene: str,
    *,
    room_try: int | None = None,
    pieces: list[dict[str, Any]] | None = None,
    source: str | None = None,
) -> int:
    """Save a new room version: a room try kept as it is, or hand-edited ``pieces``.

    Raises:
        OlfError: The room try is missing, or the room has errors.
    """
    if room_try is None:
        return save_room(p, scene, {"set": pieces or []}, source=source)
    path = p.inside(p.root / "scenes" / scene / "room" / f"try-{room_try}.json")
    if not path.is_file():
        raise OlfError(f"{scene}: no room try {room_try}")
    return save_room(
        p, scene, json.loads(path.read_text(encoding="utf-8")), source=f"try-{room_try}"
    )


def parse(text: str) -> dict[str, Any]:
    """The JSON object of an answer: a fenced block, or the outermost braces.

    Raises:
        OlfError: No JSON object, with the line and the reason.
    """
    fenced = re.search(r"```(?:json)?\s*(.*?)```", str(text or ""), re.S)
    body = fenced.group(1) if fenced else str(text or "")
    if not fenced and "{" in body and "}" in body[body.index("{") :]:  # else: not JSON, below
        body = body[body.index("{") : body.rindex("}") + 1]
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise OlfError(f"the answer is not JSON: line {exc.lineno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise OlfError("the answer is not one JSON object")
    return data


def overview(p: Project, target: str) -> dict[str, Any]:
    """What the lab shows for a scene or a shot: the room versions, the newest room, and the
    shot's tries with their check issues and the room versions they stand in (``rooms``, by
    version: a try keeps its room when the scene gets a new one)."""
    scene = target if p.kind(target) == "scene" else target.rsplit("/", 1)[0]
    versions = room_versions(p, scene)
    out: dict[str, Any] = {"scene": scene, "versions": versions}
    out["room"] = read_room(p, scene) if versions else None
    if p.kind(target) == "shot":
        out["tries"] = tries(p, target)
        used = {t["room"] for t in out["tries"]} & set(versions)
        out["rooms"] = {str(v): read_room(p, scene, v) for v in sorted(used)}
        return out
    # The scene room screen: every version, the room tries, and the room each shot stands in.
    out["rooms"] = {str(v): read_room(p, scene, v) for v in versions}
    out["room_tries"] = room_tries(p, scene)
    out["shots"] = {}
    for shot in sorted(s for s in p.of_kind("shot") if s.startswith(scene + "/")):
        found = tries(p, shot)
        last = found[-1] if found else {}
        out["shots"][shot] = {"tries": len(found), "try": last.get("try"), "room": last.get("room")}
    return out


def check(p: Project, shot: str, data: dict[str, Any]) -> list[dict[str, str]]:
    """Check an unsaved try (a hand edit) as saving would: errors and warnings, nothing saved."""
    return [{"level": i.level, "message": i.message} for i in check_try(p, shot, data)]


def _try_of(p: Project, shot: str, n: int) -> dict[str, Any]:
    """Try ``n`` of a shot as saved (without its number and check issues).

    Raises:
        OlfError: The shot has no try ``n``.
    """
    found = next((t for t in tries(p, shot) if t["try"] == n), None)
    if found is None:
        raise OlfError(f"{shot}: no try {n}")
    return {k: v for k, v in found.items() if k not in ("try", "issues")}


def use(
    p: Project,
    shot: str,
    n: int,
    frame: str,
    pin: str = "pin",
    video: str | None = None,
    raw: bool = False,
) -> dict[str, Any]:
    """Use a shot try as the shot's keyframe layout: save its start frame (rendered by the
    Studio) as ``control.storyboard``, and its places as the shot's pills.

    Args:
        p: The loaded project.
        shot: The shot.
        n: The try number.
        frame: The start frame as base64 PNG, the clay set with pins.
        pin: The pin shape in the frame (``render.PINS``; the comparison, COREPRODUC-718).
        video: The try's pin video (base64), for a ``render: reference`` video
            (``author.add_reference_video``; ``raw``: a raw H.264 stream). COREPRODUC-732.

    Raises:
        OlfError: The try is missing or has errors.
    """
    from vinci_olf.author import add_reference_video, add_storyboard, set_layout
    from vinci_olf.render import PINS

    if pin not in PINS:
        raise OlfError(f"no such pin shape: {pin} (one of {', '.join(PINS)})")
    staged = _try_of(p, shot, n)
    if errors := [i.message for i in check_try(p, shot, staged) if i.level == "error"]:
        raise OlfError(f"{shot} try {n}: " + "; ".join(errors))
    layout = pills_of(p, shot, staged)
    notes = {"olf-scene-room": str(staged["room"]), "olf-scene-try": str(n)}
    asset = add_storyboard(p, shot, frame, notes)
    clip = add_reference_video(p, shot, video, raw=raw) if video else None
    set_layout(p, shot, layout)
    # Which try the frame came from: the keyframe prompt names its grey shapes (`layout_words`).
    scene, name = shot.rsplit("/", 1)
    mark = {"try": n, "room": staged["room"], "storyboard": asset, "pin": pin}
    mark |= {"reference_video": clip} if clip else {}
    (_scene_dir(p, scene) / name / "used.json").write_text(json.dumps(mark), encoding="utf-8")
    log.info("scene lab: %s uses try %d (room v%s): %s", shot, n, staged["room"], asset)
    out = {"storyboard": asset, "layout": layout, "room": staged["room"], "try": n}
    return out | ({"reference_video": clip} if clip else {})


def pills_of(p: Project, shot: str, staged: dict[str, Any]) -> dict[str, Any]:
    """The 2D pills of a try: each person's place in the frame (the centre, the eye line, the
    head height) and facing, at the start and, when someone moves, at the end."""
    from vinci_olf.resolve import resolve

    view = resolve(p, shot)
    camera = view.get("camera") or {}
    lens = _lens(camera.get("lens"))
    aspect = _aspect(camera.get("canvas") or (view.get("defaults") or {}).get("aspect"))
    # A camera that follows someone looks elsewhere at the end (`scene.aim`).
    frames = {end: frame_of(staged, "end" if end else "start", lens, aspect) for end in (0, 1)}
    places = {person["slot"]: person for person in staged["cast"]}

    def facing(frame: Frame, at: list[float], faces: Any) -> str | None:
        if faces is None:
            return None
        if faces in ("camera", "away"):
            return str(faces)
        if isinstance(faces, str):  # another person's slot: look at where they stand
            other = places.get(faces)
            if other is None:
                return None
            way = [other["at"][0] - at[0], 0.0, other["at"][2] - at[2]]
        else:  # degrees about the up axis; 0 faces +z
            way = [math.sin(math.radians(faces)), 0.0, math.cos(math.radians(faces))]
        toward = -_dot(_unit(way), frame.forward)
        if abs(toward) > 0.7:
            return "camera" if toward > 0 else "away"
        return "right" if _dot(way, frame.right) > 0 else "left"

    def pill(person: dict[str, Any], end: bool) -> dict[str, Any]:
        place = person["end"] if end else person
        at, height = place["at"], float(person.get("height") or HEIGHT)
        eye, head = at[1] + EYE * height, 0.135 * height  # a body 7 heads tall, eyes near the top
        frame = frames[int(end)]
        x, y, _ = frame.screen([at[0], eye, at[2]])
        top = frame.screen([at[0], eye + head / 2, at[2]])[1]
        low = frame.screen([at[0], eye - head / 2, at[2]])[1]
        row: dict[str, Any] = {
            "slot": person["slot"],
            "x": round(min(max((x + 1) / 2, 0.0), 1.0), 3),
            "y": round(min(max((1 - y) / 2, 0.0), 1.0), 3),
            "size": round(min(max((top - low) / 2, 0.03), 2.0), 3),
        }
        faces = place.get("faces", person.get("faces")) if end else person.get("faces")
        if way := facing(frame, at, faces):
            row["facing"] = way
        return row

    layout: dict[str, Any] = {"start": [pill(person, False) for person in staged["cast"]]}
    if any(person.get("end") for person in staged["cast"]):
        layout["end"] = [pill(person, bool(person.get("end"))) for person in staged["cast"]]
    return layout


def layout_words(p: Project, shot: str) -> dict[str, str]:
    """The keyframe prompt's words for a frame that came from a scene lab try (``used.json``):
    what each grey shape in the frame stands for, and the camera in numbers. Empty for a plain
    pill frame, so its keyframes keep their hash.

    After github.com/cbunseng/seedance-blockout-editor-private (Apache-2.0,
    docs/why/why-the-set-stays-coarse.md): a model copies the shapes it sees (cone pines, ball
    trees) unless each one is named as its real object and none may stay (COREPRODUC-728).
    """
    from vinci_olf.resolve import resolve

    found = used(p, shot)
    if found is None:
        return {}
    staged = found["staged"]
    out: dict[str, str] = {"pin": str(found.get("pin") or "pin")}
    view = resolve(p, shot)
    camera = view.get("camera") or {}
    lens = _lens(camera.get("lens"))
    aspect = _aspect(camera.get("canvas") or (view.get("defaults") or {}).get("aspect"))
    frame = frame_of(staged, "start", lens, aspect)
    room = read_room(p, shot.rsplit("/", 1)[0], staged["room"])
    shapes = []
    for piece in room["set"] + (staged.get("props") or []):
        if place := _where(frame, piece):
            shapes.append(f"the {_label(piece)} ({SHAPE_WORDS[piece['shape']]}, {place})")
    cast = [c for c in view.get("characters") or [] if isinstance(c, dict)]
    if shapes:
        out["shapes"] = (
            "The grey shapes stand for real things of the same size in the same place: "
            + "; ".join(shapes)
            + ". Build each one as its real object: no cone, ball, plain box or untextured "
            "surface stays in the picture"
        )
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, frame.forward[1]))))
    looks = "level" if abs(pitch) < 2 else f"{'up' if pitch > 0 else 'down'} {abs(pitch):.0f}°"
    words = [f"The camera is {frame.at[1]:.1f} m above the floor and looks {looks}"]
    for person in staged["cast"]:  # each named person in front of the lens
        k = slot_place(person["slot"])
        if k < len(cast) and frame.screen(person["at"])[2] > 0:
            height = float(person.get("height") or HEIGHT)
            eyes = [person["at"][0], person["at"][1] + EYE * height, person["at"][2]]
            name = cast[k].get("name") or cast[k].get("id")
            words.append(f"{math.dist(frame.at, eyes):.1f} m from {name}")
    out["camera"] = ", ".join(words)
    return out


SHAPE_WORDS = {
    "box": "a box",
    "cylinder": "a cylinder",
    "cone": "a cone",
    "sphere": "a ball",
    "plane": "a flat shape on the floor",
    "rock": "a rough block",
}


def _where(frame: Frame, piece: dict[str, Any]) -> str | None:
    """Where a piece shows in the frame (left, middle, right; at the top or the bottom), or None
    when its outline misses the frame. The outline is the box of its corners in front of the
    lens, so a wall that fills the frame (every corner outside it) still counts."""
    w, h, d = piece["size"]
    turn = math.radians(piece.get("turn") or 0)
    seen = []
    for dx in (-w / 2, w / 2):
        for dz in (-d / 2, d / 2):
            for dy in (0.0, h):
                x = piece["at"][0] + dx * math.cos(turn) + dz * math.sin(turn)
                z = piece["at"][2] - dx * math.sin(turn) + dz * math.cos(turn)
                sx, sy, depth = frame.screen([x, piece["at"][1] + dy, z])
                if depth > 0:
                    seen.append((sx, sy))
    if not seen:
        return None
    left, right = min(x for x, _ in seen), max(x for x, _ in seen)
    low, top = min(y for _, y in seen), max(y for _, y in seen)
    if left > 1 or right < -1 or low > 1 or top < -1:
        return None
    x = (max(left, -1) + min(right, 1)) / 2  # the middle of the part in the frame
    y = (max(low, -1) + min(top, 1)) / 2
    side = "on the left" if x < -0.33 else "on the right" if x > 0.33 else "in the middle"
    return side + (" at the top" if y > 0.5 else " at the bottom" if y < -0.5 else "")


def _scene_words(p: Project, scene: str) -> str:
    data = p.docs[scene].data
    words = [f"Scene {scene}: {data.get('heading') or ''}".strip()]
    location = p.docs.get(str(data.get("location") or ""))
    if location is not None:
        place = location.data
        variant = f" ({data['variant']})" if data.get("variant") else ""
        about = place.get("description") or ""
        words.append(f"Place: {place.get('name') or location}{variant}. {about}".strip())
    if data.get("script"):
        words.append("Script:\n" + str(data["script"]).strip())
    return "\n".join(words)


def _shot_words(p: Project, shot: str) -> str:
    from vinci_olf.resolve import resolve

    view = resolve(p, shot)
    camera = view.get("camera") or {}
    lens = _lens(camera.get("lens"))
    across = math.degrees(2 * math.atan(SENSOR_MM / 2 / lens))
    shape = camera.get("canvas") or (view.get("defaults") or {}).get("aspect") or "16:9"
    framing = ", ".join(f"{k} {camera[k]}" for k in ("framing", "angle", "move") if camera.get(k))
    cast = [c for c in view.get("characters") or [] if isinstance(c, dict)]
    show = {cid: COLORS[n % len(COLORS)] for n, cid in enumerate(sorted(p.of_kind("character")))}
    colors = _shot_colors(cast, show)  # the same stripes as the frame (layout.staging)
    lines = [
        f"Shot {shot}: {view.get('description') or ''}".strip(),
        f"Camera: {framing}; a {lens:g}mm lens on Super 35 ({across:.0f}° across), frame {shape}.",
        "Named people (each is drawn as a striped pin; give each a place):",
    ]
    for n, char in enumerate(cast):
        stripe = STRIPES.get(colors.get(str(char.get("id")), ""), ("", "grey"))[1]
        about = str(char.get("description") or "").split(".")[0]
        who = char.get("name") or char.get("id")
        lines.append(f"  {slot_name(n)} = {who} ({stripe} pin). {about}".rstrip())
    if not cast:
        lines.append("  (none: an empty shot; leave cast empty)")
    return "\n".join(lines)


def _demo(p: Project, target: str) -> dict[str, Any]:
    """The demo text model's answer: a floor and a table, the cast in a row facing the camera,
    and a camera that keeps the shot's words: as far as its framing needs on its lens (a close
    framing no nearer than ``scene.NEAR``), as high as its angle says."""
    room = [
        {"name": "floor", "shape": "plane", "size": [10, 0, 10], "at": [0, 0, 0]},
        {"name": "table", "shape": "box", "size": [1.2, 0.75, 0.7], "at": [0, 0, -1.8]},
    ]
    if p.kind(target) == "scene":
        return {"set": room}
    from vinci_olf.resolve import resolve

    view = resolve(p, target)
    count = len([c for c in view.get("characters") or [] if isinstance(c, dict)])
    cast = [
        {
            "slot": slot_name(n),
            "at": [round((n - (count - 1) / 2) * 0.8, 2), 0, 0],
            "faces": "camera",
        }
        for n in range(count)
    ]
    camera = view.get("camera") or {}
    lens = _lens(camera.get("lens"))
    aspect = _aspect(camera.get("canvas") or (view.get("defaults") or {}).get("aspect"))
    head = HEADS.get(str(camera.get("framing")), HEADS["medium"])[0]
    depth = 0.135 * HEIGHT / (head * 2 * SENSOR_MM / 2 / lens / aspect)
    if camera.get("framing") in ("medium_close", "close_up", "extreme_close_up"):
        depth = max(depth, NEAR + 0.1)
    eye = round(EYE * HEIGHT, 2)
    at = {
        "low": [0, max(0.2, eye - 0.35 * depth), depth],
        "high": [0, eye + 0.35 * depth, depth],
        "overhead": [0, eye + depth, 0.4 * depth],
    }.get(str(camera.get("angle")), [0, eye, depth])
    aim = {"at": [round(v, 2) for v in at], "looks_at": [0, eye, 0]}
    out: dict[str, Any] = {"camera": aim, "cast": cast}
    if not room_versions(p, target.rsplit("/", 1)[0]):
        out["set"] = room
    return out
