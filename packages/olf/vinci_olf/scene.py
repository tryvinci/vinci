"""The scene lab's plans in 3D (COREPRODUC-714, -719): a scene's room and the tries of its shots.

A scene has one room: set pieces in basic shapes, with no colors or lights (the look comes from
the bible's references; the frame is for staging, motion and the camera only). A change to the
room is a new version, so frames made in an older version stay as they are until their shot moves.
Each shot is staged in a room version: the camera, the named people (start, and end when they
move), background groups and props for that shot only.

Files (SPEC.md, Scenes in 3D):

- ``scenes/<scene>/room/v<N>.json``: room versions, never changed after they are saved;
- ``scenes/<scene>/room/try-<N>.json``: room tries;
- ``scenes/<scene>/<shot>/try-<N>.json``: shot tries (``<shot>`` is the shot's last part);
- ``scenes/<scene>/<shot>/used.json``: the try the shot's keyframe layout came from.

They are plans, like pills: no take hashes them. Only the frame a shot uses as its keyframe
layout (``control.storyboard``) enters a hash, as before.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vinci_olf.layout import HEADS, slot_place
from vinci_olf.project import OlfError, Project
from vinci_olf.validate import Issue, schema_errors

log = logging.getLogger(__name__)

SENSOR_MM = 24.89  # Super 35 width: a lens gives the horizontal field of view on it
HEIGHT = 1.7  # a person's height when the try states none (metres)
RADIUS = 0.2  # a person's footprint on the floor (metres)
GAP = 0.05  # what counts as touching: a person on a piece, a piece on the floor
ROUND = ("cylinder", "cone", "sphere")
EYE = 0.93  # the eye line as a part of a person's height (a body 7 heads tall)
SAFE = 0.9  # the action-safe part of the frame (broadcast): heads and sides stay inside it
NEAR = 1.5  # metres: in a close framing, a lens nearer a face than this bends it (Ward 2018)
TURN = 30.0  # degrees: two shots in a row of one person turn this much, or the framing 2 steps
STEP = 0.6  # metres: one natural walking step
# A move shorter than this may not show in a video: Seedance 2.5 kept Lamp Oil sh010's Mira in
# place for 0.2 m (COREPRODUC-741) and showed about half of a 0.6 m step in 3 renders, while 2.9 m
# and 5.4 m walks came through whole (COREPRODUC-742, 2026-11-20).
SMALL_MOVE = 1.0
HALF_STEP = 0.4  # metres: a move under this is a half step in the prompt's words
WALK_SPEED = 0.4  # m/s: a walk slower than this plays in slow motion in the pin video (~1 m/s)
# The camera moves the pin video plays (``scene_lab._pushed``, the Studio's ``cameraPose``).
ANIMATED_MOVES = ("push_in", "pull_out", "dolly", "pan", "tilt", "truck", "crane", "orbit")
FRAMINGS = ("extreme_wide", "wide", "medium", "medium_close", "close_up", "extreme_close_up")
# The checks of a try's camera against the shot's words, after the measured pass of
# github.com/cbunseng/seedance-blockout-editor-private (Apache-2.0, docs/qa-engine-side.md):
# words that contradict the layout made results worse there (COREPRODUC-728).
ANGLES = {  # the camera's pitch in degrees (up is +) that each shot angle allows
    "eye_level": (-10.0, 10.0),
    "low": (3.0, 90.0),
    "high": (-90.0, -3.0),
    "overhead": (-90.0, -55.0),
}


@dataclass(frozen=True)
class Frame:
    """A try's camera at one moment: where it is, its axes, and its lens on Super 35."""

    at: list[float]
    forward: list[float]
    right: list[float]
    up: list[float]
    half_w: float
    half_h: float

    def screen(self, point: list[float]) -> tuple[float, float, float]:
        """A point's place in the frame: x and y (-1 to 1 at the edges, y up) and its depth
        (0 or less: behind the lens)."""
        d = [point[k] - self.at[k] for k in range(3)]
        depth = _dot(d, self.forward)
        near = max(depth, 1e-6)
        x, y = _dot(d, self.right) / near / self.half_w, _dot(d, self.up) / near / self.half_h
        return x, y, depth


def aim(data: dict[str, Any], moment: str = "start") -> list[float]:
    """Where a try's camera looks at the start or the end: its ``looks_at`` point, or the eyes of
    the person whose slot it names (the camera follows them as they move: track subject).

    Raises:
        OlfError: ``looks_at`` names a slot that is not staged.
    """
    target = data["camera"]["looks_at"]
    if not isinstance(target, str):
        return [float(v) for v in target]
    person = next((x for x in data["cast"] if x["slot"] == target), None)
    if person is None:
        raise OlfError(f"the camera follows slot {target}, who is not staged")
    place = person["end"] if moment == "end" and person.get("end") else person
    height = float(person.get("height") or HEIGHT)
    return [place["at"][0], place["at"][1] + EYE * height, place["at"][2]]


def _camera_axes(forward: list[float]) -> tuple[list[float], list[float]]:
    """Orthonormal right and up axes for a unit forward vector, with a fallback for vertical
    cameras so overhead shots keep valid pan/tilt/truck axes (CodeRabbit on #741)."""
    ref = [0.0, 0.0, -1.0] if abs(forward[1]) > 0.999 else [0.0, 1.0, 0.0]
    right = _unit(_cross(forward, ref))
    return right, _cross(right, forward)


def frame_of(data: dict[str, Any], moment: str, lens: float, aspect: float) -> Frame:
    """A try's camera at the start or the end, as a ``Frame``."""
    at = [float(v) for v in data["camera"]["at"]]
    forward = _unit([b - a for a, b in zip(at, aim(data, moment), strict=True)])
    right, up = _camera_axes(forward)
    half_w = SENSOR_MM / 2 / lens
    return Frame(at, forward, right, up, half_w, half_w / aspect)


def end_pose(
    staged: dict[str, Any], camera: dict[str, Any], lens: float = 35.0, aspect: float = 16 / 9
) -> dict[str, Any]:
    """The try with its camera where the shot's move ends, as the pin video moves it (the lab's
    ``cameraPose`` at t = 1, in the camera's own axes). Any non-animated move returns ``staged``."""
    move, way, amount = camera.get("move"), camera.get("direction"), camera.get("amount")
    if move not in ANIMATED_MOVES:
        return staged
    at, to = [float(v) for v in staged["camera"]["at"]], aim(staged, "end")
    if move == "dolly":
        move = "pull_out" if way in ("out", "back") else "push_in"
    if move in ("push_in", "pull_out"):
        push = min(max(0.25 if amount is None else float(amount), 0.0), 0.9)
        k = push if move == "push_in" else 1 - 1 / (1 - push)
        moved_at = [a + (b - a) * k for a, b in zip(at, to, strict=True)]
        return staged | {"camera": staged["camera"] | {"at": moved_at}}
    d = [b - a for a, b in zip(at, to, strict=True)]
    dist = math.sqrt(_dot(d, d)) or 1.0
    fwd = _unit(d)
    right, up = _camera_axes(fwd)
    hfov = 2 * math.atan(SENSOR_MM / 2 / lens)
    vfov = 2 * math.atan(SENSOR_MM / 2 / lens / aspect)
    size = 0.3 if amount is None else float(amount)
    sign = -1 if way == ("down" if move in ("tilt", "crane") else "left") else 1
    if move in ("pan", "tilt"):
        axis, angle = (right, sign * size * hfov) if move == "pan" else (up, sign * size * vfov)
        look = [
            at[k] + dist * (fwd[k] * math.cos(angle) + axis[k] * math.sin(angle)) for k in range(3)
        ]
    elif move == "truck":
        shift = sign * size * 2 * dist * math.tan(hfov / 2)
        at, look = (
            [a + r * shift for a, r in zip(at, right, strict=True)],
            [b + r * shift for b, r in zip(to, right, strict=True)],
        )
    elif move == "crane":
        dy = sign * size * 2 * dist * math.tan(vfov / 2)
        at, look = [at[0], max(0.1, at[1] + dy), at[2]], [to[0], to[1] + dy * 0.5, to[2]]
    else:  # orbit: rotate horizontally around world Y so near-vertical orbits stay circular
        angle = sign * size * (math.pi / 2)
        rx, rz = at[0] - to[0], at[2] - to[2]
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        at, look = [to[0] + rx * cos_a + rz * sin_a, at[1], to[2] - rx * sin_a + rz * cos_a], to
    return staged | {"camera": staged["camera"] | {"at": at, "looks_at": look}}


def used(p: Project, shot: str) -> dict[str, Any] | None:
    """The try a shot's keyframe layout came from (``scene_lab.use`` writes ``used.json``):
    ``try``, ``room``, ``storyboard`` and the try as saved (``staged``). None when the shot's
    frame is another one now (a redraw), or the try is gone."""
    scene, name = shot.rsplit("/", 1)
    folder = _scene_dir(p, scene) / name
    if not (folder / "used.json").is_file():
        return None
    found = _read(folder / "used.json")
    doc = p.docs.get(shot)
    board = ((doc.data if doc is not None else None) or {}).get("control") or {}
    path = folder / f"try-{found.get('try')}.json"
    if found.get("storyboard") != board.get("storyboard") or not path.is_file():
        return None
    return found | {"staged": _read(path)}


def _scene_dir(p: Project, scene: str) -> Path:
    return p.inside(p.root / "scenes" / scene)


def _numbers(folder: Path, prefix: str) -> list[int]:
    """The numbers of ``<prefix><N>.json`` files in a folder, in order."""
    found = (re.fullmatch(rf"{prefix}(\d+)\.json", f.name) for f in folder.glob("*.json"))
    return sorted(int(m.group(1)) for m in found if m)


def _write_new(folder: Path, prefix: str, data: dict[str, Any]) -> tuple[int, Path]:
    """Write ``data`` as the next ``<prefix><N>.json``; an existing file is never overwritten."""
    folder.mkdir(parents=True, exist_ok=True)
    n = (_numbers(folder, prefix) or [0])[-1] + 1
    path = folder / f"{prefix}{n}.json"
    with path.open("x", encoding="utf-8") as file:  # "x": two saves never share a number
        json.dump(data, file, indent=2)
        file.write("\n")
    return n, path


def _stamp(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "made_at": data.get("made_at") or datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OlfError(f"{path.name}: not a JSON file ({exc})") from exc
    if not isinstance(data, dict):
        raise OlfError(f"{path.name}: not a JSON object")
    return data


def _refuse(where: str, issues: list[Issue]) -> None:
    """Stop a save that has errors; warnings are saved with the plan and shown in the lab."""
    errors = [i.message for i in issues if i.level == "error"]
    if errors:
        raise OlfError(f"{where}: " + "; ".join(errors))


def room_versions(p: Project, scene: str) -> list[int]:
    """The room versions of a scene, oldest first (empty: the scene has no room yet)."""
    return _numbers(_scene_dir(p, scene) / "room", "v")


def read_room(p: Project, scene: str, version: int | None = None) -> dict[str, Any]:
    """A room version of a scene; the newest when ``version`` is None.

    Raises:
        OlfError: The scene has no room, or not that version.
    """
    versions = room_versions(p, scene)
    if not versions or (version is not None and version not in versions):
        raise OlfError(
            f"{scene}: no room version {version}" if version else f"{scene}: no room yet"
        )
    return _read(_scene_dir(p, scene) / "room" / f"v{version or versions[-1]}.json")


def save_room_try(p: Project, scene: str, data: dict[str, Any]) -> int:
    """Save a room try (from a model, a pasted answer or a hand edit) and return its number.

    Raises:
        OlfError: The room has errors (``check_room``).
    """
    room = _stamp({**data, "scene": scene})
    room.pop("version", None)
    _refuse(f"{scene} room try", check_room(room))
    n, path = _write_new(_scene_dir(p, scene) / "room", "try-", room)
    log.info("scene lab: %s room try %d (%d pieces) -> %s", scene, n, len(room["set"]), p.rel(path))
    return n


def save_room(p: Project, scene: str, data: dict[str, Any], *, source: str | None = None) -> int:
    """Save a new room version of a scene and return its number. Versions never change: a
    change to the room is a new version, and each shot moves to it when its person says so.

    Args:
        p: The loaded project.
        scene: The scene ID (``e01/s01``).
        data: The room (``set`` and its words).
        source: What it was made from (``try-2``, ``v2``), kept in ``from``.

    Raises:
        OlfError: The scene is missing, or the room has errors.
    """
    if p.kind(scene) != "scene" or scene not in p.docs:
        raise OlfError(f"{scene}: no such scene")
    room = _stamp({k: v for k, v in data.items() if k != "version"} | {"scene": scene})
    if source:
        room["from"] = source
    _refuse(f"{scene} room", check_room(room))
    folder = _scene_dir(p, scene) / "room"
    n = (room_versions(p, scene) or [0])[-1] + 1
    _, path = _write_new(folder, "v", room | {"version": n})
    log.info(
        "scene lab: %s room v%d (%d pieces, from %s) -> %s",
        scene,
        n,
        len(room["set"]),
        source,
        p.rel(path),
    )
    return n


def save_try(p: Project, shot: str, data: dict[str, Any]) -> int:
    """Save a shot try in its scene's room and return its number.

    Raises:
        OlfError: The shot is missing, or the try has errors (``check_try``).
    """
    if p.kind(shot) != "shot" or shot not in p.docs:
        raise OlfError(f"{shot}: no such shot")
    staged = _stamp({**data, "shot": shot})
    _refuse(f"{shot} try", check_try(p, shot, staged))
    scene, name = shot.rsplit("/", 1)
    n, path = _write_new(_scene_dir(p, scene) / name, "try-", staged)
    log.info("scene lab: %s try %d in room v%s -> %s", shot, n, staged["room"], p.rel(path))
    return n


def tries(p: Project, shot: str) -> list[dict[str, Any]]:
    """A shot's tries, oldest first, each with its ``try`` number and its check ``issues``."""
    scene, name = shot.rsplit("/", 1)
    folder = _scene_dir(p, scene) / name
    out = []
    for n in _numbers(folder, "try-"):
        data = _read(folder / f"try-{n}.json")
        out.append(data | {"try": n, "issues": [i.message for i in check_try(p, shot, data)]})
    return out


def room_tries(p: Project, scene: str) -> list[dict[str, Any]]:
    """A scene's room tries, oldest first, each with its ``try`` number."""
    folder = _scene_dir(p, scene) / "room"
    return [_read(folder / f"try-{n}.json") | {"try": n} for n in _numbers(folder, "try-")]


def check_room(data: Any) -> list[Issue]:
    """Check a room: the schema, and no piece below the floor."""
    where = f"{data.get('scene', 'room')} room" if isinstance(data, dict) else "room"
    errors = schema_errors("room", data)
    if errors:
        return [Issue("error", where, m) for m in errors]
    return [
        Issue("error", where, f"{_label(piece)} is below the floor (y {piece['at'][1]:g})")
        for piece in data["set"]
        if piece["at"][1] < -GAP
    ]


def check_try(p: Project, shot: str, data: Any) -> list[Issue]:
    """Check a shot try against its shot and its room.

    Errors: the schema, a room version that does not exist, a slot that names no one of the
    shot, a slot twice, a prop below the floor. Warnings: a person outside the frame at the start
    or the end, a person inside a set piece, a person who floats.
    """
    from vinci_olf.resolve import resolve

    where = f"{shot} try"
    if isinstance(data, dict):  # the shot is the one asked about, whatever the data says
        data = {**data, "shot": shot}
    errors = schema_errors("shotTry", data)
    if errors:
        return [Issue("error", where, m) for m in errors]
    issues: list[Issue] = []
    scene = shot.rsplit("/", 1)[0]
    try:
        room = read_room(p, scene, data["room"])
    except OlfError as exc:
        return [Issue("error", where, str(exc))]
    view = resolve(p, shot)
    names = [
        str(c.get("name") or c.get("id"))
        for c in view.get("characters") or []
        if isinstance(c, dict)
    ]
    slots = [person["slot"] for person in data["cast"]]
    for slot in sorted({s for s in slots if slots.count(s) > 1}):
        issues.append(Issue("error", where, f"slot {slot} is staged twice"))
    for person in data["cast"]:  # a walk window ends after it starts (0 to 1 when left out)
        end = person.get("end") or {}
        s, e = float(end.get("start_t", 0.0)), float(end.get("end_t", 1.0))
        if ("start_t" in end or "end_t" in end) and e <= s:
            issues.append(
                Issue(
                    "error",
                    where,
                    f"slot {person['slot']}: end_t ({e:g}) must be after start_t ({s:g})",
                )
            )
    pieces = room["set"] + (data.get("props") or [])
    issues += [
        Issue("error", where, f"{_label(piece)} is below the floor (y {piece['at'][1]:g})")
        for piece in data.get("props") or []
        if piece["at"][1] < -GAP
    ]
    camera = view.get("camera") or {}
    lens = _lens(camera.get("lens"))
    aspect = _aspect(camera.get("canvas") or (view.get("defaults") or {}).get("aspect"))
    # Reference renders play the pin video, so check cast against the moved end camera pose too
    # (CodeRabbit on #741); non-reference shots only use the start keyframe layout.
    animated = camera.get("render") == "reference" and camera.get("move") in ANIMATED_MOVES
    try:
        frames = {
            "start": frame_of(data, "start", lens, aspect),
            "end": frame_of(
                end_pose(data, camera, lens, aspect) if animated else data, "end", lens, aspect
            ),
        }
    except OlfError as exc:
        return [*issues, Issue("error", where, str(exc))]
    heads: list[float] = []  # the head size of each person in the frame at the start
    for person in data["cast"]:
        place = slot_place(person["slot"])
        if place >= len(names):
            issues.append(
                Issue(
                    "error",
                    where,
                    f"slot {person['slot']} names no one: {shot} has {len(names)} character"
                    + ("" if len(names) == 1 else "s"),
                )
            )
            continue
        who, height = names[place], float(person.get("height") or HEIGHT)
        # Check unchanged cast at the end too when the camera moves (CodeRabbit on #741).
        moments = [("start", person["at"])] + (
            [("end", person["end"]["at"])]
            if person.get("end")
            else ([("end", person["at"])] if animated else [])
        )
        for moment, at in moments:
            frame = frames[moment]
            reach = _reach(frame, at, height)
            if reach is None or reach > 1:
                issues.append(
                    Issue(
                        "warning", where, f"{who} is outside the {lens:g}mm frame at the {moment}"
                    )
                )
            else:
                issues += _seen(frame, who, moment, at, height, pieces, reach, camera, where)
                if moment == "start":
                    heads.append(_head(frame, at, height))
            if moment == "start" or person.get("end"):
                for piece in pieces:
                    if _inside(piece, at, height):
                        issues.append(
                            Issue(
                                "warning",
                                where,
                                f"{who} stands inside the {_label(piece)} at the {moment}",
                            )
                        )
                if at[1] > GAP and not any(_holds(piece, at) for piece in pieces):
                    issues.append(
                        Issue(
                            "warning",
                            where,
                            f"{who} floats {at[1]:g} m above the floor at the {moment}",
                        )
                    )
    issues += _words(camera, frames["start"], heads, where)
    issues += _jump(p, shot, data, camera, names, where)
    issues += _stiff(data, camera, names, where, float(view.get("duration") or 0))
    return issues


def moved(person: dict[str, Any]) -> float:
    """How far a person moves on the floor during the shot, in metres (0 with no ``end``)."""
    if not person.get("end"):
        return 0.0
    a, b = person["at"], person["end"]["at"]
    return math.dist((a[0], a[2]), (b[0], b[2]))


def _stiff(
    data: dict[str, Any],
    camera: dict[str, Any],
    names: list[str],
    where: str,
    duration: float = 0.0,
) -> list[Issue]:
    """Warnings for motion a video model may not show (COREPRODUC-741), after the rules of
    github.com/sirioberati/ai-filmmaking-camera-control-seedance-2-5 (MIT; docs/why/
    why-no-static-shots.md).

    Args:
        data: The shot try.
        camera: The shot's resolved camera words.
        names: The shot's character names, by slot.
        where: The issue's place.
        duration: The shot's length in seconds (0: unknown, no speed check).

    Returns:
        Warnings: a move shorter than ``SMALL_MOVE`` (1 m); and for a reference render, a walk
        slower than ``WALK_SPEED`` over its ``start_t``..``end_t`` window (it plays in slow
        motion in the pin video), a camera move the pin video does not play, and a pin video
        that hardly moves (a static camera and no one moving a full step): it comes
        back stiff.
    """
    out: list[Issue] = []
    reference = camera.get("render") == "reference"  # only a reference render plays the pins
    for person in data["cast"]:
        far, k = moved(person), slot_place(person["slot"])
        if reference and far >= SMALL_MOVE and duration > 0 and k < len(names):
            end = person["end"]
            window = max(float(end.get("end_t", 1.0)) - float(end.get("start_t", 0.0)), 1e-6)
            walk_s = duration * window
            if far / walk_s < WALK_SPEED:
                out.append(
                    Issue(
                        "warning",
                        where,
                        f"{names[k]}'s move takes {walk_s:.1f} s ({far / walk_s:.2f} m/s), which "
                        "plays in slow motion in the pin video; tighten start_t/end_t for a "
                        "natural walking pace (~1 m/s)",
                    )
                )
        if 0 < far < SMALL_MOVE and k < len(names):
            out.append(
                Issue(
                    "warning",
                    where,
                    f"{names[k]} moves only {far:.1f} m: a video model may show a move this small "
                    "at about half its size, or not at all. Stage two steps (1.2 m) or more for a "
                    "move the audience must see, or no move",
                )
            )
    move = camera.get("move")
    if reference and move and move not in ("static", *ANIMATED_MOVES):
        out.append(
            Issue(
                "warning",
                where,
                f"the pin video does not animate {move}: the camera stays static in @Video1",
            )
        )
    still = move in (None, "", "static") and not isinstance(data["camera"]["looks_at"], str)
    if reference and still:
        if all(moved(x) < STEP for x in data["cast"]):  # "no one moves a full step"
            out.append(
                Issue(
                    "warning",
                    where,
                    "the shot hardly moves: the camera is static and no one moves a full step. "
                    "A reference render of a still shot often comes back stiff",
                )
            )
    return out


def _reach(frame: Frame, at: list[float], height: float) -> float | None:
    """How far out in the frame a person reaches: the largest of their sides' x and their head
    top's y (1 is the frame edge; feet may leave the bottom: a medium shot cuts the legs). None
    when they are behind the lens."""
    out = 0.0
    for dx, dy in ((-RADIUS, height), (RADIUS, height), (-RADIUS, 0.0), (RADIUS, 0.0)):
        x, y, depth = frame.screen([at[0] + dx, at[1] + dy, at[2]])
        if depth <= 0:
            return None
        out = max(out, abs(x), y if dy else 0.0)
    return out


def _head(frame: Frame, at: list[float], height: float) -> float:
    """A person's head height as a part of the frame height (as ``layout.HEADS`` counts it)."""
    eye, head = at[1] + EYE * height, 0.135 * height
    top = frame.screen([at[0], eye + head / 2, at[2]])[1]
    low = frame.screen([at[0], eye - head / 2, at[2]])[1]
    return (top - low) / 2


def _seen(
    frame: Frame,
    who: str,
    moment: str,
    at: list[float],
    height: float,
    pieces: list[dict[str, Any]],
    reach: float,
    camera: dict[str, Any],
    where: str,
) -> list[Issue]:
    """Checks of a person in the frame: the safe area, a piece that hides their eyes, a lens too
    near a face in a close framing."""
    out: list[Issue] = []
    if reach > SAFE:
        out.append(Issue("warning", where, f"{who} is at the frame edge at the {moment}"))
    eyes = [at[0], at[1] + EYE * height, at[2]]
    for piece in pieces:
        if not _inside(piece, at, height) and _hides(piece, frame.at, eyes):
            out.append(Issue("warning", where, f"the {_label(piece)} hides {who} at the {moment}"))
            break
    near = math.dist(frame.at, eyes)
    if camera.get("framing") in ("medium_close", "close_up", "extreme_close_up") and near < NEAR:
        out.append(
            Issue(
                "warning",
                where,
                f"the camera is {near:.1f} m from {who}'s face at the {moment}: nearer than "
                f"{NEAR:g} m a lens bends a face; step back with a longer lens",
            )
        )
    return out


def _hides(piece: dict[str, Any], start: list[float], end: list[float]) -> bool:
    """Whether a piece stands between the lens and a person's eyes (up to 0.3 m before them).
    A plane never hides anyone; a round piece counts as its box."""
    if piece["shape"] == "plane":
        return False
    hw, hd, turn = _span(piece)
    h = piece["size"][1] / 2
    centre = [piece["at"][0], piece["at"][1] + h, piece["at"][2]]

    def local(point: list[float]) -> list[float]:  # into the piece's own axes, as _distance
        dx, dy, dz = (point[k] - centre[k] for k in range(3))
        cos, sin = math.cos(turn), math.sin(turn)
        return [dx * cos - dz * sin, dy, dx * sin + dz * cos]

    a, b = local(start), local(end)
    length = math.dist(a, b)
    if length <= 0.3:
        return False
    low, high = 0.0, 1.0 - 0.3 / length
    for k, half in enumerate((hw, h, hd)):  # the slabs of the box, one axis at a time
        step = b[k] - a[k]
        if abs(step) < 1e-9:
            if abs(a[k]) > half:
                return False
            continue
        t0, t1 = sorted(((-half - a[k]) / step, (half - a[k]) / step))
        low, high = max(low, t0), min(high, t1)
        if low > high:
            return False
    return True


def words_of(frame: Frame, heads: list[float]) -> dict[str, str]:
    """The framing and angle a try's camera shows at the start: the framing whose head size is
    nearest the nearest person's (``layout.HEADS``), and the angle of the camera's pitch
    (``ANGLES``). No framing when no one is in the frame."""
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, frame.forward[1]))))
    angle = "eye_level"
    if abs(pitch) > 10:
        angle = "low" if pitch > 0 else "overhead" if pitch <= -55 else "high"
    if not heads:
        return {"angle": angle}
    size = max(max(heads), 1e-3)
    return {
        "framing": min(FRAMINGS, key=lambda f: abs(math.log(size / HEADS[f][0]))),
        "angle": angle,
    }


def measured(p: Project, shot: str, data: dict[str, Any]) -> dict[str, str]:
    """``words_of`` a shot try: the framing and angle its camera shows (COREPRODUC-739). The shot
    takes them when the try is used, so its words and its layout agree."""
    from vinci_olf.resolve import resolve

    view = resolve(p, shot)
    camera = view.get("camera") or {}
    aspect = _aspect(camera.get("canvas") or (view.get("defaults") or {}).get("aspect"))
    frame = frame_of(data, "start", _lens(camera.get("lens")), aspect)
    heads = []
    for person in data.get("cast") or []:
        height = float(person.get("height") or HEIGHT)
        reach = _reach(frame, person["at"], height)
        if reach is not None and reach <= 1:
            heads.append(_head(frame, person["at"], height))
    return words_of(frame, heads)


def _words(camera: dict[str, Any], frame: Frame, heads: list[float], where: str) -> list[Issue]:
    """The shot's framing and angle words against the try: the nearest person's head size and
    the camera's pitch at the start."""
    out: list[Issue] = []
    framing, angle = camera.get("framing"), camera.get("angle")
    if framing in FRAMINGS and heads:
        size = max(heads)
        read = words_of(frame, heads)["framing"]
        if abs(FRAMINGS.index(read) - FRAMINGS.index(framing)) >= 2:
            out.append(
                Issue(
                    "warning",
                    where,
                    f"the shot says {_say(framing)}, but the nearest person reads as "
                    f"{_say(read)} (a head {size:.2f} of the frame height)",
                )
            )
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, frame.forward[1]))))
    low, high = ANGLES.get(str(angle), (-90.0, 90.0))
    if not low <= pitch <= high:
        way = "level" if abs(pitch) < 1 else f"{'up' if pitch > 0 else 'down'} {abs(pitch):.0f}°"
        said = f"the shot says {_say(angle)} angle, but the camera looks {way}"
        out.append(Issue("warning", where, said))
    return out


def _jump(
    p: Project,
    shot: str,
    data: dict[str, Any],
    camera: dict[str, Any],
    names: list[str],
    where: str,
) -> list[Issue]:
    """A jump cut from the shot before (the 30° rule): the same person, the camera turned less
    than 30° around them, and the framing changed less than two steps."""
    from vinci_olf.resolve import resolve

    scene = shot.rsplit("/", 1)[0]
    order = sorted(s for s in p.of_kind("shot") if s.rsplit("/", 1)[0] == scene)
    before = order[order.index(shot) - 1] if shot in order and order.index(shot) else None
    found = used(p, before) if before else None
    if before is None or found is None:
        return []
    other = resolve(p, before)
    steps = 2  # a framing that is not on the ladder never counts as a jump
    if camera.get("framing") in FRAMINGS and (other.get("camera") or {}).get("framing") in FRAMINGS:
        steps = abs(FRAMINGS.index(camera["framing"]) - FRAMINGS.index(other["camera"]["framing"]))
    them = [str(c.get("name") or c.get("id")) for c in other.get("characters") or []]
    places = {
        them[slot_place(x["slot"])]: x["at"]
        for x in found["staged"].get("cast") or []
        if slot_place(x["slot"]) < len(them)
    }
    out: list[Issue] = []
    for person in data["cast"]:
        who = names[slot_place(person["slot"])] if slot_place(person["slot"]) < len(names) else ""
        if who not in places or steps >= 2:
            continue
        turn = abs(
            _azimuth(data["camera"]["at"], person["at"])
            - _azimuth(found["staged"]["camera"]["at"], places[who])
        )
        turn = min(turn, 360 - turn)
        if turn < TURN:
            out.append(
                Issue(
                    "warning",
                    where,
                    f"a jump cut from {before.rsplit('/', 1)[1]}: the camera turns {turn:.0f}° "
                    f"around {who}; turn {TURN:g}° or more, or change the framing two steps",
                )
            )
    return out


def _azimuth(camera: list[float], at: list[float]) -> float:
    """Where a camera stands around a person, in degrees on the floor."""
    return math.degrees(math.atan2(camera[0] - at[0], camera[2] - at[2])) % 360


def _say(word: Any) -> str:
    """A framing or angle word for people: ``close_up`` -> ``a close up``."""
    text = str(word or "").replace("_", " ")
    return ("an " if text[:1] in "aeiou" else "a ") + text if text else "no"


def scene_issues(p: Project) -> list[Issue]:
    """Check every plan under ``scenes/`` (``validate`` calls it). A file that does not read is
    an error; a broken plan never stops the show from opening."""
    issues: list[Issue] = []
    top = p.root / "scenes"
    for path in sorted(top.rglob("*.json")) if top.is_dir() else []:
        rel = p.rel(path)
        try:
            data = _read(path)
        except OlfError as exc:
            issues.append(Issue("error", rel, str(exc)))
            continue
        parts = path.relative_to(top).parts
        if parts[-1] == "used.json":  # which try a frame came from: it reads, nothing to check
            continue
        if parts[-2] == "room":
            found = check_room(data)
        else:
            shot = "/".join(parts[:-1])
            if p.kind(shot) != "shot" or shot not in p.docs:
                issues.append(
                    Issue("warning", rel, f"{shot}: no such shot (a plan left from a deleted shot)")
                )
                continue
            found = check_try(p, shot, data)
        issues += [Issue(i.level, rel, i.message) for i in found]
    return issues


def _label(piece: dict[str, Any]) -> str:
    return str(piece.get("name") or piece["shape"])


def _lens(text: Any) -> float:
    """``35mm`` -> 35.0; a shot with no lens is a 35mm shot (as the 3D pill frame draws it)."""
    match = re.match(r"\s*(\d+(?:\.\d+)?)", str(text or ""))
    return float(match.group(1)) if match else 35.0


def _aspect(text: Any) -> float:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*", str(text or ""))
    return float(match.group(1)) / float(match.group(2)) if match else 16 / 9


def _span(piece: dict[str, Any]) -> tuple[float, float, float]:
    """A piece's half width and half depth on the floor (a round one: its radius twice), and
    its turn in radians."""
    w, _, d = piece["size"]
    if piece["shape"] in ROUND:
        r = max(w, d) / 2
        return r, r, 0.0
    return w / 2, d / 2, math.radians(piece.get("turn") or 0)


def _distance(piece: dict[str, Any], at: list[float]) -> float:
    """How far a point of the floor is from a piece's footprint (0 when inside it)."""
    hw, hd, turn = _span(piece)
    dx, dz = at[0] - piece["at"][0], at[2] - piece["at"][2]
    if piece["shape"] in ROUND:
        return max(0.0, math.hypot(dx, dz) - hw)
    lx = dx * math.cos(turn) - dz * math.sin(turn)  # into the piece's own axes
    lz = dx * math.sin(turn) + dz * math.cos(turn)
    return math.hypot(max(abs(lx) - hw, 0.0), max(abs(lz) - hd, 0.0))


def _inside(piece: dict[str, Any], at: list[float], height: float) -> bool:
    """Whether a person stands inside a piece: their footprint meets it, and the piece is
    between their feet and their head (a plane, the floor, never counts)."""
    bottom, top = piece["at"][1], piece["at"][1] + piece["size"][1]
    if piece["shape"] == "plane" or top <= at[1] + GAP or bottom >= at[1] + height - GAP:
        return False
    return _distance(piece, at) < RADIUS


def _holds(piece: dict[str, Any], at: list[float]) -> bool:
    """Whether a person at ``at`` stands on top of a piece."""
    top = piece["at"][1] + piece["size"][1]
    return abs(top - at[1]) <= GAP and _distance(piece, at) <= 0


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a: list[float], b: list[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(_dot(v, v)) or 1.0
    return [x / n for x in v]
