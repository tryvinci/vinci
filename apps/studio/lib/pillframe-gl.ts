/**
 * Render a shot's 3D pill frame with three.js (COREPRODUC-673): a grey clay set under the shot's
 * camera, and a striped pin in place of each figure of `stage()`. The pin is the previs "pin" of
 * github.com/sirioberati/ai-filmmaking-camera-control-seedance-2-5 (MIT, standins.ts): a head on a
 * slim body, in a loud color with near-black diagonal stripes, with a white dot on the head at eye
 * height on the side the person faces. No names and no grid: a model copies text and lines.
 */
import * as THREE from "three";
import { BODY, type PinShape, stage } from "./pillframe";
import type { OlfCamera, OlfPills } from "./shows";

const NEAR_BLACK = "#141414";
export const CLAY = { floor: "#a3a39e", sky: "#d4d4cf", dot: "#f4f4f2" };
const HEAD = { w: 0.2, h: 0.27, d: 0.23 }; // a real head, so a close shot shows a head on shoulders

/** Diagonal stripes of a color and near-black (hazard tape), as a small repeating texture. */
function stripes(hex: string): THREE.DataTexture {
  const [c, d, n] = [new THREE.Color(hex), new THREE.Color(NEAR_BLACK), 64];
  const px = new Uint8Array(n * n * 4);
  for (let y = 0; y < n; y++)
    for (let x = 0; x < n; x++) {
      const k = (x + y) % 32 < 16 ? c : d;
      px.set([k.r * 255, k.g * 255, k.b * 255, 255], (y * n + x) * 4);
    }
  const tex = new THREE.DataTexture(px, n, n);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.magFilter = THREE.LinearFilter; // smooth stripe edges: a DataTexture defaults to nearest
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.generateMipmaps = true;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}

/** A clay human figure (head, neck, torso, arms, legs) of `BODY`, standing at the origin and
 * facing +z. The previs places people first and fits a pin to each one (`fitPin`); the figure is
 * drawn only for a check (`standin: "figure"`), never sent to a model: a body gets copied. */
export function figure(): THREE.Group {
  const clay = new THREE.MeshStandardMaterial({ color: "#c9c6bf", roughness: 0.9 });
  const group = new THREE.Group();
  const part = (geo: THREE.BufferGeometry, [x, y, z]: number[], [sx, sy, sz] = [1, 1, 1]) => {
    const mesh = new THREE.Mesh(geo, clay);
    mesh.position.set(x, y, z);
    mesh.scale.set(sx, sy, sz);
    mesh.castShadow = mesh.receiveShadow = true;
    group.add(mesh);
  };
  const limb = (r: number, length: number) => new THREE.CapsuleGeometry(r, length, 4, 12);
  part(new THREE.SphereGeometry(0.5, 24, 16), [0, BODY.eye + 0.02, 0], [HEAD.w, HEAD.h, HEAD.d]);
  part(limb(0.06, 0.06), [0, 1.45, 0]); // neck
  part(limb(0.17, 0.3), [0, 1.18, 0], [1.25, 1, 0.75]); // chest to hips
  for (const side of [-1, 1]) {
    part(limb(0.065, 0.72), [side * 0.1, 0.43, 0]); // a leg, sole to hip
    part(limb(0.045, 0.52), [side * 0.25, 1.1, 0]); // an arm, shoulder to wrist
  }
  return group;
}

/** A pin fitted to a figure: as tall as it is, at the real shoulder width (slim: the arms are left
 * out, or a close shot reads as a giant dome), a head where its head is, and a white dot on the
 * head at eye height. Stripes keep one size (about 0.2 m): the capsule's own UVs follow its
 * segments, so they are set from real metres (the previs `uvMetres`). */
export function fitPin(person: THREE.Object3D, hex: string, shape: PinShape = "pin"): THREE.Group {
  if (shape !== "pin") return onePiece(person, hex, shape);
  const box = new THREE.Box3().setFromObject(person);
  const [sole, width] = [box.min.y, Math.min(box.max.x - box.min.x, BODY.shoulders)];
  const group = new THREE.Group();
  const headY = BODY.eye + 0.02;
  const headTex = stripes(hex);
  headTex.repeat.set(Math.round((Math.PI * (HEAD.w + HEAD.d)) / 2 / 0.2), Math.max(1, Math.round((Math.PI * HEAD.h) / 2 / 0.2)));
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.5, 28, 20), new THREE.MeshStandardMaterial({ map: headTex, roughness: 0.75 }));
  head.scale.set(HEAD.w, HEAD.h, HEAD.d);
  head.position.y = headY;
  // A flattened dome for shoulders that slope, from the soles to just under the chin.
  const [r, depth] = [width / 2, BODY.depth];
  const sy = r * 0.5;
  const top = headY - HEAD.h / 2 + 0.09;
  const geo = new THREE.CapsuleGeometry(1, Math.max(0.01, (top - sole) / sy - 2), 6, 20);
  const [pos, uv] = [geo.getAttribute("position"), geo.getAttribute("uv")];
  const around = Math.round((Math.PI * (width + depth)) / 2 / 0.2);
  for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * around, (pos.getY(i) * sy) / 0.2);
  uv.needsUpdate = true;
  const body = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: stripes(hex), roughness: 0.75 }));
  body.scale.set(r, sy, depth / 2);
  body.position.y = (top + sole) / 2;
  const dot = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 1, 32), new THREE.MeshStandardMaterial({ color: CLAY.dot, roughness: 0.6 }));
  dot.rotation.x = Math.PI / 2;
  dot.scale.set(0.11, 0.02, 0.11);
  dot.position.set(0, headY, HEAD.d / 2 + 0.004);
  for (const mesh of [head, body]) mesh.castShadow = mesh.receiveShadow = true;
  group.add(head, body, dot);
  return group;
}

/** A one-piece pin fitted to a figure (`one-piece` or `capsule`): as tall as it is, at the real
 * shoulder width and depth, with the same stripes in metres and the white dot at eye height. */
function onePiece(person: THREE.Object3D, hex: string, shape: PinShape): THREE.Group {
  const box = new THREE.Box3().setFromObject(person);
  const [sole, tall] = [box.min.y, box.max.y - box.min.y];
  const around = (w: number, d: number) => Math.round((Math.PI * (w + d)) / 2 / 0.2);
  const metres = (geo: THREE.BufferGeometry, n: number) => {
    const [pos, uv] = [geo.getAttribute("position"), geo.getAttribute("uv")];
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * n, pos.getY(i) / 0.2);
    uv.needsUpdate = true;
  };
  const eye = BODY.eye - sole;
  let geo: THREE.BufferGeometry;
  let dot: [number, number]; // the dot's depth out from the axis, and its tilt
  if (shape === "one-piece") {
    // A profile (radius, height) of a 1.7 m person, turned about the axis: shoulders slope into a
    // neck and a head, all one surface. The body keeps its real depth; the head stays round.
    const rows = [[0.001, 0], [0.17, 0.03], [0.22, 0.2], [0.23, 0.7], [0.225, 1.2], [0.2, 1.33], [0.12, 1.41], [0.075, 1.46], [0.1, 1.51], [0.11, 1.58], [0.095, 1.66], [0.045, 1.695], [0.001, 1.7]];
    const k = tall / 1.7;
    geo = new THREE.LatheGeometry(new THREE.SplineCurve(rows.map(([r, y]) => new THREE.Vector2(r, y * k))).getPoints(120), 48);
    const body = BODY.depth / BODY.shoulders, pos = geo.getAttribute("position");
    for (let i = 0; i < pos.count; i++) {
      const head = Math.min(Math.max((pos.getY(i) / k - 1.33) / 0.13, 0), 1);
      pos.setZ(i, pos.getZ(i) * (body + (1 - body) * head));
    }
    geo.computeVertexNormals();
    metres(geo, around(BODY.shoulders, BODY.depth));
    dot = [0.11, 0];
  } else {
    const r = 0.21; // a plain capsule, as wide as a slim pin's body, flattened to the real depth
    geo = new THREE.CapsuleGeometry(r, Math.max(0.01, tall - 2 * r), 12, 48).translate(0, tall / 2, 0);
    geo.scale(1, 1, BODY.depth / 2 / r);
    metres(geo, around(2 * r, BODY.depth));
    const rise = Math.max(0, eye - (tall - r)); // the eye line is on the top dome
    dot = [Math.sqrt(r * r - rise * rise) * (BODY.depth / 2 / r), Math.asin(rise / r) * 0.6];
  }
  const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: stripes(hex), roughness: 0.75 }));
  mesh.position.y = sole;
  mesh.castShadow = mesh.receiveShadow = true;
  const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 1, 32), new THREE.MeshStandardMaterial({ color: CLAY.dot, roughness: 0.6 }));
  disc.rotation.x = Math.PI / 2 - dot[1];
  disc.scale.set(0.11, 0.02, 0.11);
  disc.position.set(0, BODY.eye, dot[0] + 0.004);
  const group = new THREE.Group();
  group.add(mesh, disc);
  return group;
}

/** Render a shot's first frame as a 3D pill frame.
 *
 * @param pills The shot's staging plan; each pill's `stripe` is its pin's color.
 * @param camera The shot's camera (lens, angle).
 * @param height The frame height in pixels; the width follows the shot's shape.
 * @param standin `pin` (what a model gets) or `figure` (the clay people the pins are fitted to).
 * @returns The frame as a PNG `data:` URL (`POST /olf/storyboard` stores it).
 */
export function renderPillFrame(
  pills: OlfPills,
  camera: OlfCamera | undefined,
  height = 1080,
  standin: "pin" | "figure" = "pin",
): string {
  const plan = stage(pills, camera);
  const [w, h] = [Math.round(height * plan.aspect), height];
  const scene = clayWorld();
  for (const place of plan.figures) {
    // People first, then a pin fitted to each person in their place (the previs order).
    const person = figure();
    const one = standin === "figure" ? person : fitPin(person, place.pill.stripe || "#00c8d7");
    one.position.set(place.eye[0], place.eye[1] - BODY.eye, place.eye[2]);
    one.rotation.y = place.yaw;
    scene.add(one);
  }
  const lens = new THREE.PerspectiveCamera(plan.fov, plan.aspect, 0.05, 300);
  lens.position.set(0, plan.y, 0);
  lens.rotation.x = plan.pitch;
  console.info("[shows] pill frame", { standin, w, h, fov: plan.fov.toFixed(1), y: plan.y.toFixed(2), figures: plan.figures.length });
  return shoot(scene, lens, w, h);
}

/** The grey clay world of a frame: the sky, a floor that fades into the horizon, and the
 * standard light with its shadows (the same for every frame a keyframe model gets). */
export function clayWorld(): THREE.Scene {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(CLAY.sky);
  scene.fog = new THREE.Fog(CLAY.sky, 30, 120); // the floor fades into the horizon
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshStandardMaterial({ color: CLAY.floor, roughness: 1 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor, new THREE.HemisphereLight("#ffffff", "#8a8a85", 1.2));
  const sun = new THREE.DirectionalLight("#ffffff", 1.6);
  sun.position.set(4, 9, 4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, far: 40 });
  scene.add(sun);
  return scene;
}

/** Render a scene once to a PNG `data:` URL, then free the renderer and the scene's meshes. */
export function shoot(scene: THREE.Scene, lens: THREE.Camera, w: number, h: number): string {
  const canvas = document.createElement("canvas");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  try {
    renderer.setSize(w, h, false);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.render(scene, lens);
    return canvas.toDataURL("image/png");
  } finally {
    renderer.dispose();
    renderer.forceContextLoss();
    scene.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        const mat = o.material as THREE.MeshStandardMaterial;
        mat.map?.dispose();
        mat.dispose();
      }
    });
  }
}
