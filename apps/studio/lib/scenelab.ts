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
export type OlfPerson = { slot: string; at: V3; faces?: OlfFaces; height?: number; end?: { at: V3; faces?: OlfFaces } };
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
/** The shot's own camera words that the lab plays: its move and how far it goes. */
export type ShotMove = { move?: string; amount?: number; ease?: string };

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
 * place walks there over the shot; one with none stays. */
export function placeAt(person: OlfPerson, cast: OlfPerson[], camera: V3, t: number): { at: V3; yaw: number } {
  const start = yawFor(person.faces, person.at, cast, camera);
  if (!person.end || t <= 0) return { at: person.at, yaw: start };
  const e = ease(t);
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

/** The camera's place at time `t`: a push moves it toward what it looks at by `amount` of the
 * distance (the end frame is 1 - amount of the start frame, SPEC.md `camera.amount`), a pull
 * moves it away by the same rule backwards; any other move stays put in the lab for now. */
export function cameraAt(camera: { at: V3; looks_at: V3 }, move: ShotMove, t: number): V3 {
  const amount = Math.min(Math.max(move.amount ?? PUSH, 0), 0.9);
  const e = ease(t, move.ease);
  const from = camera.at, to = camera.looks_at;
  let k = 0;
  if (move.move === "push_in") k = amount * e;
  else if (move.move === "pull_out") k = (1 - 1 / (1 - amount)) * e; // negative: backwards
  return from.map((v, i) => v + (to[i] - v) * k) as V3;
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
