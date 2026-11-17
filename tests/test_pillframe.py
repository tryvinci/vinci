"""The stage of a 3D pill frame (apps/studio/lib/pillframe.ts, COREPRODUC-673): the figures
stand where their pills say, under the shot's camera, and look where their pills look."""

from __future__ import annotations

from ts_module import run_ts

LIB = "apps/studio/lib/pillframe.ts"
NAMES = ["stage", "aspectOf", "BODY", "SENSOR_MM"]


def test_figures_project_back_onto_their_pills() -> None:
    """An over-the-shoulder pair (ots-b): Mira faces Tomas, Tomas is a near back. Each figure's
    eyes, seen through the shot's lens and pitch, land on its pill, at its pill's head size."""
    body = r"""
const assert = (ok, what) => { if (!ok) throw new Error(what); };
const near = (a, b, what) => assert(Math.abs(a - b) < 1e-6, `${what}: ${a} != ${b}`);
const pills = { aspect: "16:9", stated: false, crosses: null, end: null, start: [
  { slot: "a", id: "char/mira", name: "Mira", x: 0.34, y: 0.33, size: 0.42, facing: "right" },
  { slot: "b", id: "char/tomas", name: "Tomas", x: 0.82, y: 0.35, size: 0.6, facing: "away" },
  { slot: "c", id: "char/kid", name: "Kid", x: 1.35, y: 0.3, size: 0.4, facing: "left" },
] };
for (const angle of ["eye_level", "low", "high"]) {
  const s = stage(pills, { framing: "medium_close", lens: "50mm", angle });
  assert(s.figures.length === 2, "a pill outside the frame (it enters later) is not drawn");
  const tanV = SENSOR_MM / 2 / 50 / s.aspect, tanH = SENSOR_MM / 2 / 50;
  for (const f of s.figures) {
    // world -> camera: undo the height, then the pitch (a rotation about x)
    const [x, up, z] = [f.eye[0], f.eye[1] - s.y, f.eye[2]];
    const cy = up * Math.cos(-s.pitch) - z * Math.sin(-s.pitch);
    const cz = up * Math.sin(-s.pitch) + z * Math.cos(-s.pitch);
    const depth = -cz;
    near((x / depth / tanH + 1) / 2, f.pill.x, `${angle} ${f.pill.name} x`);
    near((1 - cy / depth / tanV) / 2, f.pill.y, `${angle} ${f.pill.name} eye line`);
    near(BODY.head / (2 * tanV * depth), f.pill.size, `${angle} ${f.pill.name} head size`);
  }
  // The nearest figure (the largest head) stands on the floor.
  const tomas = s.figures.find((f) => f.pill.name === "Tomas");
  near(tomas.eye[1] - BODY.eye, 0, `${angle} Tomas on the floor`);
}
const s = stage(pills, { lens: "50mm" });
const [mira, tomas] = s.figures;
const facing = (f) => [Math.sin(f.yaw), Math.cos(f.yaw)];
const toward = (f, g) => { const [dx, dz] = [g.eye[0] - f.eye[0], g.eye[2] - f.eye[2]]; const n = Math.hypot(dx, dz); return [dx / n, dz / n]; };
const [fm, tm] = [facing(mira), toward(mira, tomas)];
near(fm[0], tm[0], "Mira looks at Tomas (x)"); near(fm[1], tm[1], "Mira looks at Tomas (z)");
const [ft, lens] = [facing(tomas), toward(tomas, { eye: [0, 0, 0] })];
near(ft[0], -lens[0], "Tomas turns his back to the lens (x)"); near(ft[1], -lens[1], "Tomas turns his back (z)");
// Alone and facing left, a figure turns toward screen left (-x) from the lens.
const one = stage({ ...pills, start: [{ ...pills.start[0], x: 0.6, facing: "left" }] }, { lens: "35mm" });
assert(Math.sin(one.figures[0].yaw) < 0, "a single facing left turns toward -x");
near(aspectOf("21:9"), 21 / 9, "a pan canvas shape"); near(aspectOf("nope"), 16 / 9, "the default shape");
"""
    result = run_ts(LIB, NAMES, body)
    assert result.returncode == 0, result.stderr or result.stdout
