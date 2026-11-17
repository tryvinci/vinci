/**
 * Render a shot's 3D pill frame with three.js (COREPRODUC-673): a grey clay set under the shot's
 * camera, and a striped pin in place of each figure of `stage()`. The pin is the previs "pin" of
 * github.com/sirioberati/ai-filmmaking-camera-control-seedance-2-5 (MIT, standins.ts): a head on a
 * slim body, in a loud color with near-black diagonal stripes, with a white dot on the head at eye
 * height on the side the person faces. No names and no grid: a model copies text and lines.
 */
import * as THREE from "three";
import { BODY, stage } from "./pillframe";
import type { OlfCamera, OlfPills } from "./shows";

const NEAR_BLACK = "#141414";
const CLAY = { floor: "#a3a39e", sky: "#d4d4cf", dot: "#f4f4f2" };
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
function figure(): THREE.Group {
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
function fitPin(person: THREE.Object3D, hex: string): THREE.Group {
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
  const canvas = document.createElement("canvas");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  try {
    renderer.setSize(w, h, false);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.render(scene, lens);
    console.info("[shows] pill frame", { standin, w, h, fov: plan.fov.toFixed(1), y: plan.y.toFixed(2), figures: plan.figures.length });
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
