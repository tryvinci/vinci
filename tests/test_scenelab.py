"""The scene lab's 3D math (apps/studio/lib/scenelab.ts, COREPRODUC-721): easing, the lens, where
people stand and look over a shot, the camera's push and pull, background people, set pieces."""

from __future__ import annotations

from ts_module import run_ts

LIB = "apps/studio/lib/scenelab.ts"
NAMES = ["ease", "verticalFov", "yawFor", "placeAt", "cameraAt", "extrasOf", "pieceTransform"]
NAMES += ["HEIGHT", "staging", "tryChanges", "roomChanges", "aimAt", "cameraPose", "ANIMATED_MOVES"]
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
near(cameraAt(cam, { move: "pan" }, 1)[2], 10, "a pan turns in place: the camera stays");
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


def test_a_walk_keeps_its_time_window() -> None:
    """`end.start_t` / `end.end_t` time a walk inside the shot: the person holds the start place
    before it, eases inside it and holds the end place after it; a hand edit reports them."""
    body = HEAD + r"""
const camera = [0, 1.5, 5];
const mira = { slot: "a", at: [0, 0, 0], faces: "camera", end: { at: [2, 0, 0], faces: 90, start_t: 0.2, end_t: 0.6 } };
const cast = [mira];
const before = placeAt(mira, cast, camera, 0.1), at = placeAt(mira, cast, camera, 0.2);
assert(before.at[0] === 0 && at.at[0] === 0, "holds the start place before the window");
near(before.yaw, 0, "still faces the camera");
near(placeAt(mira, cast, camera, 0.4).at[0], 1, "half way through the window, eased");
near(placeAt(mira, cast, camera, 0.3).at[0], 2 * ease(0.25), "eased inside the window");
const after = placeAt(mira, cast, camera, 0.8);
near(after.at[0], 2, "holds the end place after the window"); near(after.yaw, Math.PI / 2, "and the end facing");
const jump = { ...mira, end: { at: [2, 0, 0], start_t: 0.5, end_t: 0.5 } };
assert(placeAt(jump, cast, camera, 0.4).at[0] === 0 && placeAt(jump, cast, camera, 0.5).at[0] === 2, "no length: a jump at start_t");
const whole = { ...mira, end: { at: [2, 0, 0] } };
near(placeAt(whole, cast, camera, 0.5).at[0], 1, "no window: the whole shot, as before");
const shot = { shot: "s", room: 1, camera: { at: [0, 1.5, 5], looks_at: [0, 1, 0] }, cast: [whole] };
const said = tryChanges(shot, { ...shot, cast: [mira] }, { a: "Mira Sol" });
assert(said.includes("Mira Sol: walk starts none → 0.2"), said.join(" | "));
assert(said.includes("Mira Sol: walk ends none → 0.6"), said.join(" | "));
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr


def test_all_camera_moves_in_3d() -> None:
    """`cameraPose` plays every animated move in the camera's own axes, as
    `vinci_olf.scene_lab._pushed` does: the camera looks down -z, so its right is +x."""
    body = HEAD + r"""
const cam = { at: [0, 1.5, 10], looks_at: [0, 1.5, 0] };
const half = 24.89 / 2 / 35; // tan of half the 35mm horizontal field on Super 35
const [hfov, vfov] = [2 * Math.atan(half), 2 * Math.atan(half / (16 / 9))];
const pose = (move) => cameraPose(cam, move, 1);
const same = (a, b, what) => a.forEach((v, i) => near(v, b[i], `${what} [${i}]`));
assert(ANIMATED_MOVES.length === 8 && ANIMATED_MOVES.includes("orbit"), "eight moves");
same(pose({ move: "push_in", amount: 0.35 }).at, [0, 1.5, 6.5], "push in");
same(pose({ move: "pull_out", amount: 0.5 }).at, [0, 1.5, 20], "pull out");
same(pose({ move: "dolly" }).at, [0, 1.5, 7.5], "dolly: in by default");
same(pose({ move: "dolly", direction: "out" }).at, [0, 1.5, 10 + 10 / 3], "dolly out: a pull");
same(pose({ move: "dolly", direction: "back" }).looks_at, cam.looks_at, "a dolly keeps its aim");
const a = 0.3 * hfov;
same(pose({ move: "pan" }).at, cam.at, "a pan stays in place");
same(pose({ move: "pan", direction: "right" }).looks_at, [10 * Math.sin(a), 1.5, 10 - 10 * Math.cos(a)], "pan right turns +x");
same(pose({ move: "pan", direction: "left" }).looks_at, [-10 * Math.sin(a), 1.5, 10 - 10 * Math.cos(a)], "pan left turns -x");
const b = 0.3 * vfov;
same(pose({ move: "tilt", direction: "up" }).looks_at, [0, 1.5 + 10 * Math.sin(b), 10 - 10 * Math.cos(b)], "tilt up");
same(pose({ move: "tilt", direction: "down" }).looks_at, [0, 1.5 - 10 * Math.sin(b), 10 - 10 * Math.cos(b)], "tilt down");
same(pose({ move: "tilt", direction: "up" }).at, cam.at, "a tilt stays in place");
const shift = 0.3 * 2 * 10 * half;
const right = pose({ move: "truck", direction: "right" }), left = pose({ move: "truck", direction: "left" });
same(right.at, [shift, 1.5, 10], "truck right"); same(right.looks_at, [shift, 1.5, 0], "the aim slides with it");
same(left.at, [-shift, 1.5, 10], "truck left");
const dy = 0.3 * 2 * 10 * (half / (16 / 9));
same(pose({ move: "crane", direction: "up" }).at, [0, 1.5 + dy, 10], "crane up");
same(pose({ move: "crane", direction: "up" }).looks_at, [0, 1.5 + dy / 2, 0], "the aim rises half as far");
same(pose({ move: "crane", direction: "down", amount: 1 }).at, [0, 0.1, 10], "never under the floor");
const o = 0.3 * Math.PI / 2;
same(pose({ move: "orbit", direction: "right" }).at, [10 * Math.sin(o), 1.5, 10 * Math.cos(o)], "orbit right");
same(pose({ move: "orbit", direction: "left" }).at, [-10 * Math.sin(o), 1.5, 10 * Math.cos(o)], "orbit left");
same(pose({ move: "orbit" }).looks_at, cam.looks_at, "an orbit keeps its aim");
for (const move of ["static", "handheld", "shake", undefined]) {
  const still = pose({ move });
  same(still.at, cam.at, `${move} stays`); same(still.looks_at, cam.looks_at, `${move} keeps its aim`);
}
same(cameraPose(cam, { move: "truck" }, 0).at, cam.at, "the start is the try's place");
near(cameraPose(cam, { move: "pan", lens: "85mm" }, 1).looks_at[0], 10 * Math.sin(0.3 * 2 * Math.atan(24.89 / 2 / 85)), "a long lens pans less");
near(cameraAt(cam, { move: "truck" }, 1)[0], shift, "cameraAt is cameraPose's place");
// Overhead camera (vertical forward): fallback axis keeps pan, tilt, and truck active (CodeRabbit on #741).
const over = { at: [0, 10, 0], looks_at: [0, 0, 0] };
assert(cameraPose(over, { move: "pan", direction: "right" }, 1).looks_at[0] > 0.5, "overhead pan right moves +x");
assert(cameraPose(over, { move: "tilt", direction: "up" }, 1).looks_at[2] < -0.5, "overhead tilt up moves -z");
assert(cameraPose(over, { move: "truck", direction: "right" }, 1).at[0] > 0.5, "overhead truck right moves +x");
// Oblique near-vertical orbit stays circular around world Y (CodeRabbit on #741).
const oblique = { at: [0.2, 10, 0.2], looks_at: [0, 0, 0] };
const orb = cameraPose(oblique, { move: "orbit", amount: 0.5 }, 1).at;
near(Math.hypot(orb[0], orb[2]), Math.hypot(0.2, 0.2), "oblique orbit keeps its radius");
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr
