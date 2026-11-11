"""Pills: the 2D staging plan of a shot (SPEC.md, Layout).

A pill is a flat stand-in for one character: where it stands in the frame, how large it is and
where it looks. A shot states its pills in ``layout``, else its camerawork template does, else
each character gets one pill from the framing. Pills are a plan, so no take hashes them. This
module only calculates (``vinci_olf.previs`` draws), so the validator can use it.
"""

from __future__ import annotations

from typing import Any

from vinci_olf.project import Project

# Head height as a part of the frame height, and the eye line from the frame top, by framing.
HEADS = {
    "extreme_wide": (0.04, 0.45),
    "wide": (0.11, 0.2),
    "medium": (0.28, 0.3),
    "medium_close": (0.42, 0.36),
    "close_up": (0.75, 0.42),
    "extreme_close_up": (1.6, 0.5),
}
SLOTS = "abc"  # a layout names its pills by cast slot: the shot's first, second, third character
OFF = 0.35  # how far outside the frame a pill is before it enters or after it leaves
# One color per character for the whole show (by the order of the bible), so a character keeps
# its color in each cut, whatever its slot there. A pill with no character is grey.
COLORS = ("#1c9fb8", "#e08a00", "#c2255c", "#2f9e44", "#7048e8", "#e8590c")
NO_ONE = "#868e96"
ROOM = (
    0.1  # look room: a single that looks off screen sits this far from the centre, behind its gaze
)


def staging(p: Project, views: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the pills of each shot, with the 180° line of its scene applied.

    In a scene, a shot whose template has ``rules.sets_axis`` fixes the line: which side each
    of its characters is on. A later shot of the scene that states a layout with two of them
    in the other order, or with one of them alone and looking away from the others, crosses
    the line. A new ``sets_axis`` shot sets the line again. A shot that states no layout
    keeps each character on its side.

    Args:
        p: The loaded project (for the templates).
        views: Resolved shots by ID (``vinci_olf.resolve.resolve``).

    Returns:
        Shot ID -> ``{"start": [pill], "end": [pill] or None, "aspect": the shape of the
        drawing ("16:9"), "stated": a layout is written down, "crosses": the reason or None}``.
        A pill is ``{"slot", "id", "name", "x", "y", "size", "facing", "color"}``: the centre
        and the eye line from the top left (0 to 1), the head height as a part of the frame
        height, and the character's color (the same in each shot of the show).
    """
    out: dict[str, dict[str, Any]] = {}
    colors = {cid: COLORS[n % len(COLORS)] for n, cid in enumerate(sorted(p.of_kind("character")))}
    scene, axis, setter = "", dict[str, float](), ""  # axis: character -> x where the line was set
    for shot_id in sorted(views):
        view = views[shot_id]
        if shot_id.rsplit("/", 1)[0] != scene:  # the line belongs to one scene
            scene, axis, setter = shot_id.rsplit("/", 1)[0], {}, ""
        camera = view.get("camera") or {}
        found = camera.get("template")
        template: dict[str, Any] = found if isinstance(found, dict) else {}
        entry = p.docs[template["id"]].data if template.get("id") in p.docs else {}
        stated = view.get("layout") or entry.get("layout") or {}
        cast = [c for c in view.get("characters") or [] if isinstance(c, dict)]
        rows = stated.get("start") if stated else None  # `start: []`: nobody is in frame yet
        if rows is None:
            rows = [{"slot": slot} for slot, _ in zip(SLOTS, cast, strict=False)]
        start = _pills(rows, cast, camera.get("framing"), colors)
        sets = bool((entry.get("rules") or {}).get("sets_axis")) and len(start) > 1
        crosses = None if sets or not stated else _crosses(start, axis, setter)
        if not stated and len(start) > 1 and all(pill["id"] in axis for pill in start):
            xs = sorted(pill["x"] for pill in start)  # no plan: each one stays on its side
            for pill, x in zip(sorted(start, key=lambda pill: axis[pill["id"]]), xs, strict=True):
                pill["x"] = x
        if sets:
            axis, setter = {pill["id"]: pill["x"] for pill in start if pill["id"]}, shot_id
        end = (
            _pills(stated["end"], cast, camera.get("framing"), colors)
            if stated.get("end")
            else None
        )
        for pills in filter(None, (start, end)):
            _face(pills, axis)
        if end is not None:  # a pill at one end only: it enters or leaves on the side it faces
            slots = ({pill["slot"] for pill in start}, {pill["slot"] for pill in end})
            end += [_outside(pill, leaves=True) for pill in start if pill["slot"] not in slots[1]]
            start += [_outside(pill, leaves=False) for pill in end if pill["slot"] not in slots[0]]
        aspect = camera.get("canvas") or (view.get("defaults") or {}).get("aspect") or "16:9"
        out[shot_id] = {
            "start": [_public(pill) for pill in start],
            "end": [_public(pill) for pill in end] if end is not None else None,
            "aspect": aspect,
            "stated": bool(stated),
            "crosses": crosses,
        }
    return out


def _pills(
    rows: list[dict[str, Any]], cast: list[dict[str, Any]], framing: Any, colors: dict[str, str]
) -> list[Any]:
    """The pills of a layout row list, each with its character, its color and the defaults of
    the framing. ``placed`` records whether the layout states ``x`` (look room moves only the
    others)."""
    size, y = HEADS.get(str(framing), HEADS["medium"])
    out = []
    for n, row in enumerate(rows):
        place = SLOTS.index(row["slot"])
        char = cast[place] if place < len(cast) else {}
        default = {"x": (n + 1) / (len(rows) + 1), "y": y, "size": size, "facing": None}
        who = {"id": char.get("id"), "name": char.get("name") or char.get("id")}
        color = {"color": colors.get(str(char.get("id")), NO_ONE), "placed": "x" in row}
        out.append(default | row | who | color)
    return out


def _face(pills: list[Any], axis: dict[str, float]) -> None:
    """Fill where each pill looks: at its ``look_at`` pill, else as it is stated, else at the
    other pills of the frame, else (alone) at the other characters of the line, else at the
    camera."""
    for pill in pills:
        target = next((q["x"] for q in pills if q["slot"] == pill.get("look_at")), None)
        if target is None and pill["facing"]:
            continue
        here, single = pill["x"], False
        if target is None:
            others = [q["x"] for q in pills if q is not pill]
            if not others and pill["id"] in axis:  # a single: the others are off screen
                others = [x for cid, x in axis.items() if cid != pill["id"]]
                here, single = axis[pill["id"]], bool(others)
            target = sum(others) / len(others) if others else here
        pill["facing"] = "right" if target > here else "left" if target < here else "camera"
        if single and not pill["placed"] and pill["facing"] != "camera":  # room for the gaze
            pill["x"] = 0.5 + (ROOM if pill["facing"] == "left" else -ROOM)


def _crosses(pills: list[Any], axis: dict[str, float], setter: str) -> str | None:
    """Say why a stated layout crosses the line that ``setter`` set, or None."""
    known = [pill for pill in pills if pill["id"] in axis]
    names = {pill["id"]: pill["name"] for pill in known}
    for one in known:
        for two in known:
            if (one["x"] - two["x"]) * (axis[one["id"]] - axis[two["id"]]) < 0:
                left, right = sorted((one, two), key=lambda pill: axis[pill["id"]])
                return f"{setter} has {left['name']} at the left of {right['name']}"
    if len(known) == 1 and len(axis) > 1 and known[0]["facing"] in ("left", "right"):
        cid = known[0]["id"]  # a single: it must look at the side where the others are
        others = [x for other, x in axis.items() if other != cid]
        want = "right" if sum(others) / len(others) > axis[cid] else "left"
        if known[0]["facing"] != want:
            side = "left" if want == "right" else "right"
            return f"{setter} has {names[cid]} on the {side}, so {names[cid]} looks {want}"
    return None


def _outside(pill: dict[str, Any], *, leaves: bool) -> dict[str, Any]:
    """The pill outside the frame: it leaves on the side it faces, and it enters from the other
    side. A pill that faces the camera (or away) uses the nearer side."""
    right = pill["facing"] == "right" if pill["facing"] in ("left", "right") else pill["x"] > 0.5
    if not leaves and pill["facing"] in ("left", "right"):
        right = not right
    return pill | {"x": 1 + OFF if right else -OFF}


def _public(pill: dict[str, Any]) -> dict[str, Any]:
    """A pill as the API sends it: only its public fields."""
    return {k: pill[k] for k in ("slot", "id", "name", "x", "y", "size", "facing", "color")}
