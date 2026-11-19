"""The scene lab's 3D math (apps/studio/lib/scenelab.ts, COREPRODUC-721): easing, the lens, where
people stand and look over a shot, the camera's push and pull, background people, set pieces."""

from __future__ import annotations

from ts_module import run_ts

LIB = "apps/studio/lib/scenelab.ts"
NAMES = ["ease", "verticalFov", "yawFor", "placeAt", "cameraAt", "extrasOf", "pieceTransform"]
NAMES += ["HEIGHT", "staging", "tryChanges", "roomChanges", "aimAt"]
HEAD = r"""
const assert = (ok, what) => { if (!ok) throw new Error(what); };
const near = (a, b, what, tol = 1e-9) => assert(Math.abs(a - b) < tol, `${what}: ${a} != ${b}`);
"""


def test_ease_and_the_lens() -> None:
    body = HEAD + r"""
near(ease(0), 0, "start"); near(ease(1), 1, "end"); near(ease(0.5), 0.5, "half way");
assert(ease(0.25) < 0.25 && ease(0.75) > 0.75, "in-out starts and ends slow");
near(ease(0.3, "none"), 0.3, "none"); near(ease(-1), 0, "clamped"); near(ease(2), 1, "clamped");
// The shot's eases play as the engine plays them (vinci_media.camera.EASES).
near(ease(0.5, "in"), 0.25, "in"); near(ease(0.5, "out"), 0.75, "out"); near(ease(0.25), 0.15625, "in_out");
// 35mm on Super 35 (24.89 mm wide), a 16:9 frame: the same field the pill frame uses.
near(verticalFov("35mm", 16 / 9), 2 * Math.atan(24.89 / 2 / 35 / (16 / 9)) * 180 / Math.PI, "35mm");
near(verticalFov(undefined, 16 / 9), verticalFov(35, 16 / 9), "no lens: 35mm");
assert(verticalFov("85mm", 16 / 9) < verticalFov("24mm", 16 / 9), "a long lens sees less");
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr


def test_people_stand_look_and_walk() -> None:
    body = HEAD + r"""
const camera = [0, 1.5, 5];
const mira = { slot: "a", at: [0, 0, 0], faces: "camera", end: { at: [2, 0, 0], faces: 90 } };
const fox = { slot: "b", at: [-1, 0, 0] };
const cast = [mira, fox];
near(yawFor("camera", [0, 0, 0], cast, camera), 0, "toward the camera (+z)");
near(yawFor("away", [0, 0, 0], cast, camera), Math.PI, "away from it");
near(yawFor("b", [0, 0, 0], cast, camera), -Math.PI / 2, "toward the fox (-x)");
near(yawFor(90, [0, 0, 0], cast, camera), Math.PI / 2, "degrees: 90 turns +z toward +x");
near(yawFor(undefined, [0, 0, 0], cast, camera), 0, "no faces: toward the camera");
const start = placeAt(mira, cast, camera, 0), end = placeAt(mira, cast, camera, 1), half = placeAt(mira, cast, camera, 0.5);
assert(start.at[0] === 0 && end.at[0] === 2 && Math.abs(half.at[0] - 1) < 1e-9, "walks to the end place");
near(start.yaw, 0, "starts facing the camera"); near(end.yaw, Math.PI / 2, "ends facing 90 degrees");
near(half.yaw, Math.PI / 4, "turns the short way, eased");
const still = placeAt(fox, cast, camera, 0.7);
assert(still.at[0] === -1 && still.at[2] === 0, "a person with no end place stays");
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr


def test_camera_moves_extras_and_pieces() -> None:
    body = HEAD + r"""
const cam = { at: [0, 1.5, 10], looks_at: [0, 1.5, 0] };
near(cameraAt(cam, { move: "push_in", amount: 0.35 }, 1)[2], 6.5, "push: 35% of the distance");
near(cameraAt(cam, { move: "push_in", amount: 0.35 }, 0)[2], 10, "push: the start is the try's place");
near(cameraAt(cam, { move: "pull_out", amount: 0.5 }, 1)[2], 20, "pull: the end frame is twice as wide");
near(cameraAt(cam, { move: "pan" }, 1)[2], 10, "other moves stay put in the lab for now");
near(cameraAt(cam, { move: "push_in" }, 1)[2], 7.5, "a push with no amount goes a quarter");
const group = { name: "villagers", count: 12, area: [-4, -6, 3, -3], faces: "camera" };
const places = extrasOf(group, [0, 1.5, 5]);
assert(places.length === 12, "one place per person");
assert(places.every((p) => p.at[0] >= -4 && p.at[0] <= 3 && p.at[2] >= -6 && p.at[2] <= -3 && p.at[1] === 0), "inside the area, on the floor");
assert(JSON.stringify(extrasOf(group, [0, 1.5, 5])) === JSON.stringify(places), "the same places each time");
assert(new Set(places.map((p) => p.at.join())).size === 12, "no two in one place");
const box = pieceTransform({ shape: "box", size: [2, 1, 0.5], at: [1, 0.5, -2], turn: 90 });
assert(box.position.join() === "1,1,-2", "a box's centre is half its height over its bottom");
near(box.yaw, Math.PI / 2, "turn in degrees");
const floor = pieceTransform({ shape: "plane", size: [10, 0, 10], at: [0, 0, 0] });
assert(floor.position[1] > 0 && floor.position[1] < 0.01 && floor.scale[1] === 1, "a plane lies just over the floor");
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr


def test_hand_edit_and_room_changes() -> None:
    """COREPRODUC-723: a hand edit starts from the try's staging and lists what it changed; a
    room version lists its pieces added, removed and moved."""
    body = HEAD + r"""
const before = { shot: "e01/s01/sh020", room: 1, try: 2, issues: ["x"], made_at: "t", request: "r",
  camera: { at: [0, 1.5, 5], looks_at: [0, 1, 0] }, cast: [{ slot: "a", at: [0, 0, 0] }] };
const start = staging(before);
assert(!("try" in start) && !("issues" in start) && !("made_at" in start) && start.room === 1, "staging only");
near(tryChanges(start, start).length, 0, "no change");
const after = { ...start, cast: [{ slot: "a", at: [0.5, 0, 0], end: { at: [1, 0, 0] } }],
  groups: [{ name: "villagers", count: 8, area: [-2, -3, 2, -2] }] };
const said = tryChanges(start, after, { a: "Mira Sol" });
assert(said.includes("Mira Sol: place 0, 0, 0 → 0.5, 0, 0"), said.join(" | "));
assert(said.includes("Mira Sol: end place none → 1, 0, 0"), said.join(" | "));
assert(said.includes("villagers (group 1): people none → 8"), said.join(" | "));
const desk = { name: "desk", shape: "box", size: [1, 1, 1], at: [0, 0, 0] };
const lamp = { name: "lamp", shape: "cylinder", size: [1, 1, 1], at: [1, 0, 0] };
const room = roomChanges([desk, lamp], [{ ...desk, at: [2, 0, 0] }, { shape: "rock", size: [1, 1, 1], at: [0, 0, 0] }]);
assert(JSON.stringify(room) === JSON.stringify(["rock 2: added", "lamp: removed", "desk: moved or resized"]), room.join(" | "));
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr


def test_the_camera_follows_a_person() -> None:
    """COREPRODUC-728: `looks_at` as a slot aims at that person's eyes as they walk (track
    subject), as `vinci_olf.scene.aim` does; a point stays a point."""
    body = HEAD + r"""
const walk = { slot: "a", at: [-1, 0, 0], end: { at: [1, 0, 0] } };
const staged = { shot: "s", room: 1, camera: { at: [0, 1.5, 3], looks_at: "a" }, cast: [walk] };
const eye = 0.93 * 1.7;
assert(JSON.stringify(aimAt(staged, 0)) === JSON.stringify([-1, eye, 0]), "the start: her eyes");
near(aimAt(staged, 1)[0], 1, "the end: her end place"); near(aimAt(staged, 0.5)[0], 0, "half way");
const tall = { ...staged, cast: [{ ...walk, height: 0.45 }] };
near(aimAt(tall, 0)[1], 0.93 * 0.45, "a fox's eyes are low");
const point = { ...staged, camera: { at: [0, 1.5, 3], looks_at: [0, 1, 0] } };
assert(aimAt(point, 0.7).join() === "0,1,0", "a point stays a point");
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr
