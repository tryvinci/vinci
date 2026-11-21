/**
 * The scene lab's 3D plans (COREPRODUC-714): a scene's room and a shot staged in it, as
 * `vinci_olf.scene` saves them (SPEC.md, Scenes in 3D). Pure math with no three.js import, so the
 * Studio tests can load it; `scenelab-gl.ts` draws it (COREPRODUC-721).
 *
 * Metres; y is up and the floor is y = 0. A yaw of 0 faces +z, and a positive yaw turns toward
 * +x, as three.js turns an object about y.
 */
import { SENSOR_MM } from "./pillframe";

export type V3 = [number, number, number];
/** A set piece: a basic shape; `at` is the centre of its bottom (y 0 stands on the floor). */
export type OlfPiece = {
  name?: string;
  shape: "box" | "cylinder" | "cone" | "sphere" | "plane" | "rock";
  size: V3;
  at: V3;
  turn?: number;
};
/** Where a person looks: degrees, `camera`, `away`, or another person's slot. */
export type OlfFaces = number | string;
/** `end`: where a person walks to; `start_t`/`end_t` (0..1 of the shot) time the walk, 0 to 1 when left out. */
export type OlfPerson = {
  slot: string;
  at: V3;
  faces?: OlfFaces;
  height?: number;
  end?: { at: V3; faces?: OlfFaces; start_t?: number; end_t?: number };
};
/** Background people: a count in an area of the floor (x0, z0, x1, z1); never named. */
export type OlfGroup = { name?: string; count: number; area: [number, number, number, number]; faces?: OlfFaces };
export type OlfRoom = { scene: string; version?: number; from?: string; set: OlfPiece[]; request?: string; model?: string };
export type OlfShotTry = {
  shot: string;
  room: number;
  /** `looks_at`: a point, or a person's slot (the camera follows their eyes: track subject). */
  camera: { at: V3; looks_at: V3 | string };
  cast: OlfPerson[];
  groups?: OlfGroup[];
  props?: OlfPiece[];
  request?: string;
  model?: string;
  try?: number;
  issues?: string[];
};
/** The shot's own camera words that the lab plays: its move, its way (`left`, `up`, `out`, ...)
 * and how far it goes. */
export type ShotMove = { move?: string; direction?: string; amount?: number; ease?: string };
/** The camera moves the lab plays in 3D (`cameraPose`); any other move stays put. */
export const ANIMATED_MOVES = ["push_in", "pull_out", "dolly", "pan", "tilt", "truck", "crane", "orbit"] as const;

export const HEIGHT = 1.7; // a person's height when the try states none
export const EYE = 0.93; // the eye line as a part of a person's height (vinci_olf.scene.EYE)
export const NEUTRAL = "#eef0f2"; // a background person's pin: white with dark stripes, no identity
const PUSH = 0.25; // a push or a pull with no amount

/** Eased time of a move, 0..1, by the shot's `ease` as the engine plays it
 * (`vinci_media.camera.EASES`: `none`, `in`, `out`; `in_out` unless the shot says another). */
export function ease(t: number, kind = "in_out"): number {
  const x = Math.min(Math.max(t, 0), 1);
  if (kind === "none") return x;
  if (kind === "in") return x * x;
  if (kind === "out") return 1 - (1 - x) ** 2;
  return x * x * (3 - 2 * x);
}

/** The vertical field of view in degrees of a lens (`35mm` or 35) on Super 35, for a frame shape. */
export function verticalFov(lens: string | number | undefined, aspect: number): number {
  const mm = parseFloat(String(lens ?? "")) || 35;
  return (2 * Math.atan(SENSOR_MM / 2 / mm / aspect) * 180) / Math.PI;
}

/** A person's yaw for `faces`: toward the camera, away from it, toward another person, or degrees.
 * No `faces`: toward the camera. */
export function yawFor(faces: OlfFaces | undefined, at: V3, cast: OlfPerson[], camera: V3): number {
  const toward = (p: V3) => Math.atan2(p[0] - at[0], p[2] - at[2]);
  if (typeof faces === "number") return (faces * Math.PI) / 180;
  if (faces === "away") return toward(camera) + Math.PI;
  const other = cast.find((person) => person.slot === faces);
  return other ? toward(other.at) : toward(camera);
}

/** Where a person stands and looks at time `t` (0: the start, 1: the end). A person with an end
 * place walks there between `end.start_t` and `end.end_t` (the whole shot when left out): they
 * hold the start place before it and the end place after it. One with no end place stays.
 *
 * @param person The person, with an optional end place and walk window.
 * @param cast The shot's cast (a person may face another).
 * @param camera The camera's place (a person may face it).
 * @param t Time in the shot, 0..1.
 * @returns Their place and yaw at `t`.
 */
export function placeAt(person: OlfPerson, cast: OlfPerson[], camera: V3, t: number): { at: V3; yaw: number } {
  const start = yawFor(person.faces, person.at, cast, camera);
  if (!person.end) return { at: person.at, yaw: start };
  const [s, eT] = [person.end.start_t ?? 0, person.end.end_t ?? 1];
  // Progress inside the walk window; a window of no length jumps at `start_t`.
  const u = eT > s ? Math.min(Math.max((t - s) / (eT - s), 0), 1) : t >= s ? 1 : 0;
  if (u <= 0) return { at: person.at, yaw: start };
  const e = ease(u);
  const at = person.at.map((v, k) => v + (person.end!.at[k] - v) * e) as V3;
  const end = yawFor(person.end.faces ?? person.faces, person.end.at, cast, camera);
  const turn = Math.atan2(Math.sin(end - start), Math.cos(end - start)); // the short way round
  return { at, yaw: start + turn * e };
}

/** Where the camera looks at time `t`: its `looks_at` point, or the eyes of the person whose
 * slot it names, who may walk (track subject, COREPRODUC-728; `vinci_olf.scene.aim`). */
export function aimAt(staged: OlfShotTry, t: number): V3 {
  const target = staged.camera.looks_at;
  if (typeof target !== "string") return target;
  const person = staged.cast.find((one) => one.slot === target);
  if (!person) return [0, 1, 0]; // the check says the slot is not staged
  const { at } = placeAt(person, staged.cast, staged.camera.at, t);
  return [at[0], at[1] + EYE * (person.height ?? HEIGHT), at[2]];
}

const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a: V3, k: number): V3 => [a[0] * k, a[1] * k, a[2] * k];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a: V3): V3 => scale(a, 1 / (Math.hypot(...a) || 1));

/** The camera's place and aim at time `t` for the shot's move, as `vinci_olf.scene_lab._pushed`
 * plays it (in the camera's own axes, so it works from any place):
 * - `push_in` / `pull_out` (and `dolly` in or `out`/`back`): move along the aim by `amount` of the
 *   distance (a push's end frame is 1 - amount of the start frame, SPEC.md `camera.amount`; a pull
 *   is the same rule backwards). Default amount 0.25, at most 0.9.
 * - `pan` / `tilt`: turn the aim in place by `amount` of the lens's horizontal / vertical field.
 * - `truck` / `crane`: slide sideways / up by `amount` of the view's width / height at the aim
 *   (a crane tilts half as far and never goes under 0.1 m).
 * - `orbit`: circle the aim on the floor plane by `amount` of a quarter turn.
 * `direction` `left` or `down` turns the move the other way (default 0.3 for these). Any other
 * move (`static`, `handheld`, `shake`, none) stays put.
 *
 * @param camera The try's camera place and the point it aims at.
 * @param move The shot's camera words and lens.
 * @param t Time in the shot, 0..1 (eased by `move.ease`).
 * @param aspect The frame shape as width over height.
 * @returns The camera's place and aim at `t`.
 */
/** Reference up axis for a camera pose: world up unless aiming vertically, shared by 3D rendering
 * and pill projection (CodeRabbit on #741). */
export function cameraUp(at: V3, looks_at: V3): V3 {
  const fwd = unit([looks_at[0] - at[0], looks_at[1] - at[1], looks_at[2] - at[2]]);
  return Math.abs(fwd[1]) > 0.999 ? [0, 0, -1] : [0, 1, 0];
}

export function cameraPose(camera: { at: V3; looks_at: V3 }, move: ShotMove & { lens?: string }, t: number, aspect = 16 / 9): { at: V3; looks_at: V3 } {
  const e = ease(t, move.ease);
  const { at, looks_at: to } = camera;
  const d: V3 = [to[0] - at[0], to[1] - at[1], to[2] - at[2]];
  const dist = Math.hypot(...d) || 1;
  const fwd = unit(d);
  const right = unit(cross(fwd, cameraUp(at, to))), up = cross(right, fwd);
  const mm = parseFloat(String(move.lens ?? "")) || 35;
  const hfov = 2 * Math.atan(SENSOR_MM / 2 / mm), vfov = 2 * Math.atan(SENSOR_MM / 2 / mm / aspect);
  const push = Math.min(Math.max(move.amount ?? PUSH, 0), 0.9);
  const amount = move.amount ?? 0.3; // pan, tilt, truck, crane, orbit
  const side = move.direction === "left" ? -1 : 1, rise = move.direction === "down" ? -1 : 1; // the other way
  const along = (k: number) => ({ at: add(at, scale(d, k)), looks_at: to });
  const turn = (axis: V3, angle: number) => ({ at, looks_at: add(at, scale(add(scale(fwd, Math.cos(angle)), scale(axis, Math.sin(angle))), dist)) });
  const back = move.move === "pull_out" || (move.move === "dolly" && (move.direction === "out" || move.direction === "back"));
  switch (move.move) {
    case "push_in":
    case "pull_out":
    case "dolly":
      return along(back ? (1 - 1 / (1 - push)) * e : push * e); // a pull's k is negative: backwards
    case "pan":
      return turn(right, side * amount * hfov * e);
    case "tilt":
      return turn(up, rise * amount * vfov * e);
    case "truck": {
      const shift = scale(right, side * amount * 2 * dist * Math.tan(hfov / 2) * e);
      return { at: add(at, shift), looks_at: add(to, shift) };
    }
    case "crane": {
      const dy = rise * amount * 2 * dist * Math.tan(vfov / 2) * e;
      return { at: [at[0], Math.max(0.1, at[1] + dy), at[2]], looks_at: [to[0], to[1] + dy * 0.5, to[2]] };
    }
    case "orbit": {
      const angle = side * amount * (Math.PI / 2) * e;
      const [rx, rz] = [at[0] - to[0], at[2] - to[2]];
      const [cos, sin] = [Math.cos(angle), Math.sin(angle)];
      return { at: [to[0] + rx * cos + rz * sin, at[1], to[2] - rx * sin + rz * cos], looks_at: to };
    }
    default:
      return { at, looks_at: to };
  }
}

/** The camera's place at time `t` (`cameraPose` without the aim; kept for older callers). */
export function cameraAt(camera: { at: V3; looks_at: V3 }, move: ShotMove & { lens?: string }, t: number, aspect = 16 / 9): V3 {
  return cameraPose(camera, move, t, aspect).at;
}

/** The places of a background group: `count` people spread inside its area, the same each time
 * for the same group (a seeded random), each looking where the group faces. */
export function extrasOf(group: OlfGroup, camera: V3): { at: V3; yaw: number }[] {
  // A positive seed (an area left of or behind the origin gave a negative one: people outside it).
  let seed = (Math.abs(7 + group.count * 31 + Math.round(group.area.reduce((a, b) => a + b * 97, 0))) % 2147483646) + 1;
  const random = () => {
    seed = (seed * 16807) % 2147483647;
    return (seed - 1) / 2147483646;
  };
  const [x0, z0, x1, z1] = group.area;
  return Array.from({ length: group.count }, () => {
    const at: V3 = [x0 + random() * (x1 - x0), 0, z0 + random() * (z1 - z0)];
    const yaw = group.faces === undefined || group.faces === "any" ? (random() - 0.5) * 2 * Math.PI : yawFor(group.faces, at, [], camera);
    return { at, yaw };
  });
}

/** How to place a piece's unit shape: its centre (the bottom is `at`), its scale and its turn. */
export function pieceTransform(piece: OlfPiece): { position: V3; scale: V3; yaw: number } {
  const [w, h, d] = piece.size;
  const flat = piece.shape === "plane";
  return {
    position: [piece.at[0], piece.at[1] + (flat ? 0.002 : h / 2), piece.at[2]],
    scale: [Math.max(w, 0.001), flat ? 1 : Math.max(h, 0.001), Math.max(d, 0.001)],
    yaw: ((piece.turn ?? 0) * Math.PI) / 180,
  };
}

/** A try as the scene description holds it (no number, checks, words or date): what a hand
 * edit starts from, and what `POST /olf/scene/check` and `/paste` take. */
export function staging(staged: OlfShotTry): OlfShotTry {
  const { shot, room, camera, cast, groups, props } = staged;
  return { shot, room, camera, cast, ...(groups ? { groups } : {}), ...(props ? { props } : {}) };
}

const said = (v: unknown): string =>
  v === undefined || v === null ? "none" : Array.isArray(v) ? v.map((n) => (typeof n === "number" ? +n.toFixed(2) : n)).join(", ") : String(v);

/** What a hand edit changed, one line each (`Mira Sol: place 0.2, 0, -0.5 → 0.5, 0, -0.5`).
 *
 * @param names Each slot's character name.
 */
export function tryChanges(before: OlfShotTry, after: OlfShotTry, names: Record<string, string> = {}): string[] {
  const rows = (t: OlfShotTry) => {
    const aim = t.camera.looks_at; // a slot: the person the camera follows
    const out: Record<string, unknown> = { "Camera place": t.camera.at, "Camera aims at": typeof aim === "string" ? names[aim] || `Slot ${aim}` : aim };
    for (const p of t.cast) {
      const who = names[p.slot] || `Slot ${p.slot}`;
      Object.assign(out, { [`${who}: place`]: p.at, [`${who}: faces`]: p.faces, [`${who}: height`]: p.height });
      Object.assign(out, { [`${who}: end place`]: p.end?.at, [`${who}: end faces`]: p.end?.faces });
      Object.assign(out, { [`${who}: walk starts`]: p.end?.start_t, [`${who}: walk ends`]: p.end?.end_t });
    }
    (t.groups || []).forEach((g, i) => {
      const who = `${g.name || "Background"} (group ${i + 1})`;
      Object.assign(out, { [`${who}: people`]: g.count, [`${who}: area`]: g.area, [`${who}: faces`]: g.faces });
    });
    (t.props || []).forEach((p, i) => (out[`Prop ${p.name || i + 1}`] = `${p.shape} ${p.size.join(" × ")} m at ${said(p.at)}, turn ${p.turn ?? 0}°`));
    return out;
  };
  const [a, b] = [rows(before), rows(after)];
  return [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
    .map((k) => `${k} ${said(a[k])} → ${said(b[k])}`);
}

/** What a room version changed from the one before, by piece name: added, removed, changed. */
export function roomChanges(before: OlfPiece[], after: OlfPiece[]): string[] {
  const index = (set: OlfPiece[]) => new Map(set.map((p, i) => [p.name || `${p.shape} ${i + 1}`, JSON.stringify([p.shape, p.size, p.at, p.turn ?? 0])]));
  const [a, b] = [index(before), index(after)];
  return [
    ...[...b.keys()].filter((k) => !a.has(k)).map((k) => `${k}: added`),
    ...[...a.keys()].filter((k) => !b.has(k)).map((k) => `${k}: removed`),
    ...[...b.keys()].filter((k) => a.has(k) && a.get(k) !== b.get(k)).map((k) => `${k}: moved or resized`),
  ];
}
