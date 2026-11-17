/**
 * The stage of a shot's 3D pill frame (COREPRODUC-673): the camera, and a human figure where each
 * character stands. `pillframe-gl.ts` renders it with three.js, a striped pin in place of each
 * figure, and the frame goes to the keyframe model as its layout (`control.storyboard`).
 *
 * This is the previs method of github.com/sirioberati/ai-filmmaking-camera-control-seedance-2-5
 * (MIT): build the shot in 3D first, with real people at real places under a real lens, then
 * swap each person for a pin that has their place, size and facing and no body to copy.
 *
 * The figures come from the shot's 2D pills (vinci_olf.layout): each figure stands at the depth
 * where a real head is as large as its pill's head, and where its eyes land on its pill's eyes.
 * Pure math with no three.js import, so the Studio tests can load it.
 */
import type { OlfCamera, OlfPill, OlfPills } from "./shows";

/** Super 35 width in mm: a shot's lens gives the field of view on it. */
export const SENSOR_MM = 24.89;
/** A 1.7 m adult (metres): the eye line, the head height, the shoulders and the depth. */
export const BODY = { eye: 1.58, head: 0.23, shoulders: 0.46, depth: 0.28 };
/** The camera's pitch by shot angle, in degrees (up is positive). */
const PITCH: Record<string, number> = { eye_level: 0, low: 14, high: -14, overhead: -70, dutch: 0 };
const LENS = 35; // a shot with no lens
const TURN = (75 * Math.PI) / 180; // a figure that looks off screen turns this far from the lens

/** One figure: its pill, its eyes in world metres, and its yaw (0 faces +z, toward the lens). */
export type Figure = { pill: OlfPill; eye: [number, number, number]; yaw: number };
/** The camera at (0, y, 0) looking down -z, pitched; and the figures in front of it. */
export type Stage = { fov: number; aspect: number; pitch: number; y: number; figures: Figure[] };

/** The shape of a frame (`16:9`) as width over height. */
export function aspectOf(text: string | undefined): number {
  const [w, h] = String(text || "16:9").split(":").map(Number);
  return w > 0 && h > 0 ? w / h : 16 / 9;
}

/** Place the camera and the figures of a shot's first frame.
 *
 * @param pills The shot's staging plan (`GET /olf/project`: shots[id].pills).
 * @param camera The shot's camera (lens in mm, angle).
 * @returns The vertical field of view in degrees, the pitch in radians, the camera height, and
 *   one figure for each pill inside the frame (a pill that enters later is not drawn).
 */
export function stage(pills: OlfPills, camera: OlfCamera | undefined): Stage {
  const aspect = aspectOf(pills.aspect);
  const lens = parseFloat(String(camera?.lens || "")) || LENS;
  const tanH = SENSOR_MM / 2 / lens;
  const tanV = tanH / aspect;
  const pitch = ((PITCH[String(camera?.angle || "eye_level")] ?? 0) * Math.PI) / 180;
  const inFrame = pills.start.filter((pill) => pill.x >= 0 && pill.x <= 1);
  // Camera space -> world: a rotation about x by the pitch, then the camera height.
  const placed = inFrame.map((pill) => {
    const depth = BODY.head / (Math.max(pill.size, 0.01) * 2 * tanV);
    const [cx, cy, cz] = [(2 * pill.x - 1) * depth * tanH, (1 - 2 * pill.y) * depth * tanV, -depth];
    const up = cy * Math.cos(pitch) - cz * Math.sin(pitch);
    const z = cy * Math.sin(pitch) + cz * Math.cos(pitch);
    return { pill, x: cx, up, z };
  });
  // The camera height puts the nearest figure's feet on the floor (y = 0).
  const near = [...placed].sort((a, b) => b.pill.size - a.pill.size)[0];
  const y = Math.max(0.2, BODY.eye - (near?.up ?? 0));
  const figures = placed.map((one) => {
    const eye: [number, number, number] = [one.x, y + one.up, one.z];
    return { pill: one.pill, eye, yaw: yawOf(one, placed, eye) };
  });
  return { fov: (2 * Math.atan(tanV) * 180) / Math.PI, aspect, pitch, y, figures };
}

/** Where a figure looks: at the lens, away from it, or toward the side its pill faces. A figure
 * that faces a side looks at the nearest other figure on that side (a real eye line), else turns
 * `TURN` from the lens toward that side. */
function yawOf(
  one: { pill: OlfPill; x: number; z: number },
  all: { pill: OlfPill; x: number; z: number }[],
  eye: [number, number, number],
): number {
  const toLens = Math.atan2(-eye[0], -eye[2]); // the lens is at x = 0, z = 0
  const facing = one.pill.facing;
  if (facing === "away") return toLens + Math.PI;
  if (facing !== "left" && facing !== "right") return toLens;
  const sign = facing === "left" ? -1 : 1; // screen left is -x
  const others = all.filter((o) => o !== one && Math.sign(o.x - one.x) === sign);
  const target = others.sort((a, b) => Math.hypot(a.x - one.x, a.z - one.z) - Math.hypot(b.x - one.x, b.z - one.z))[0];
  if (target) return Math.atan2(target.x - one.x, target.z - one.z);
  return toLens + sign * TURN; // a yaw step down turns the face toward screen left (-x)
}
