/**
 * Draw the scene lab's room and a staged shot with three.js (COREPRODUC-721): the set in grey
 * clay under today's standard light, each named person as a pin in their character's stripes
 * (or a clay figure, to check the blocking), background people as neutral pins, and the shot's
 * camera with its move. The frame a keyframe model gets has no lab overlays: those (the walk
 * path, the faded start pin, a group's area, the shot camera) show only in the lab.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { PinShape } from "./pillframe";
import { clayWorld, figure, fitPin, shoot } from "./pillframe-gl";
import {
  HEIGHT,
  NEUTRAL,
  type OlfPiece,
  type OlfRoom,
  type OlfShotTry,
  type ShotMove,
  type V3,
  aimAt,
  cameraPose,
  cameraUp,
  extrasOf,
  pieceTransform,
  placeAt,
  verticalFov,
} from "./scenelab";

const SET = "#bdbab3"; // set pieces: a clay a little lighter than the floor
const LAB = "#21dad2"; // lab overlays only (never in a frame)

export type SceneOptions = {
  /** Each named person's pin stripes, by slot (the shot's pills say them: `pills.start[].stripe`). */
  stripes: Record<string, string>;
  standin?: "pin" | "figure";
  /** Time in the shot, 0 (the start) to 1 (the end). */
  t?: number;
  /** Draw the lab overlays (never for a frame). */
  lab?: boolean;
  /** The pin shape (the comparison, COREPRODUC-718); today's pin when left out. */
  pin?: PinShape;
};

/** A unit shape for a piece; `pieceTransform` scales and places it. */
function shape(piece: OlfPiece): THREE.BufferGeometry {
  switch (piece.shape) {
    case "box":
      return new THREE.BoxGeometry(1, 1, 1);
    case "cylinder":
      return new THREE.CylinderGeometry(0.5, 0.5, 1, 40);
    case "cone":
      return new THREE.ConeGeometry(0.5, 1, 40);
    case "sphere":
      return new THREE.SphereGeometry(0.5, 32, 20);
    case "rock":
      return new THREE.DodecahedronGeometry(0.5);
    case "plane":
      return new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
  }
}

function piece(one: OlfPiece): THREE.Mesh {
  const mesh = new THREE.Mesh(shape(one), new THREE.MeshStandardMaterial({ color: SET, roughness: 0.95 }));
  const { position, scale, yaw } = pieceTransform(one);
  mesh.position.set(...position);
  mesh.scale.set(...scale);
  mesh.rotation.y = yaw;
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

/** A person: a pin fitted to a clay figure (or the figure), scaled to their height. */
function person(stripe: string, standin: "pin" | "figure", height: number, opacity = 1, shape?: PinShape): THREE.Group {
  const body = figure();
  const one = standin === "figure" ? body : fitPin(body, stripe, shape);
  one.scale.setScalar(height / HEIGHT);
  if (opacity < 1)
    one.traverse((o) => {
      if (o instanceof THREE.Mesh) Object.assign(o.material as THREE.Material, { transparent: true, opacity });
    });
  return one;
}

/** A built scene, and `update(t)`, which moves the people (and the shot camera) to time `t`. */
export type Built = { scene: THREE.Scene; update: (t: number, camera?: THREE.Camera) => void };

/** Build the scene of a room and a staged shot once; `update` plays the move without building
 * anything again (the lab plays a shot at the screen's frame rate).
 *
 * @param move The shot's camera words: move, direction, amount, ease and lens (`cameraPose`).
 * @param aspect The frame shape as width over height (a pan or a tilt turns by the lens's field).
 */
export function buildScene(room: OlfRoom, staged: OlfShotTry, move: ShotMove & { lens?: string }, opts: SceneOptions, aspect = 16 / 9): Built {
  const scene = clayWorld();
  const standin = opts.standin ?? "pin";
  const start = cameraPose({ at: staged.camera.at, looks_at: aimAt(staged, 0) }, move, 0, aspect).at;
  for (const one of [...room.set, ...(staged.props ?? [])]) scene.add(piece(one));
  const people = staged.cast.map((one) => {
    const height = one.height ?? HEIGHT;
    const stripe = opts.stripes[one.slot] || "#00c8d7";
    const pin = person(stripe, standin, height, 1, opts.pin);
    scene.add(pin);
    if (opts.lab && one.end) {
      const ghost = person(stripe, standin, height, 0.3, opts.pin); // where they start
      const first = placeAt(one, staged.cast, start, 0);
      ghost.position.set(...first.at);
      ghost.rotation.y = first.yaw;
      scene.add(ghost, path(one.at, one.end.at));
    }
    return { one, pin };
  });
  for (const group of staged.groups ?? []) {
    for (const place of extrasOf(group, start)) {
      const pin = person(NEUTRAL, standin, HEIGHT, 1, opts.pin);
      pin.position.set(...place.at);
      pin.rotation.y = place.yaw;
      scene.add(pin);
    }
    if (opts.lab) scene.add(area(group.area));
  }
  const update = (t: number, camera?: THREE.Camera) => {
    const target = aimAt(staged, t); // a camera that follows someone turns with them
    const pose = cameraPose({ at: staged.camera.at, looks_at: target }, move, t, aspect); // a pan turns the aim too
    for (const { one, pin } of people) {
      const place = placeAt(one, staged.cast, pose.at, t);
      pin.position.set(...place.at);
      pin.rotation.y = place.yaw;
    }
    if (camera) {
      camera.up.set(...cameraUp(pose.at, pose.looks_at));
      camera.position.set(...pose.at);
      camera.lookAt(...pose.looks_at);
    }
  };
  update(opts.t ?? 0);
  return { scene, update };
}

/** Free a scene's meshes, materials and textures (the lab shows many tries). */
function free(scene: THREE.Scene): void {
  scene.traverse((o) => {
    if (o instanceof THREE.Mesh || o instanceof THREE.LineLoop) {
      o.geometry.dispose();
      const mat = o.material as THREE.MeshStandardMaterial;
      mat.map?.dispose();
      mat.dispose();
    }
  });
}

/** The walk as a flat strip on the floor (lab only). */
function path(from: V3, to: V3): THREE.Mesh {
  const [dx, dz] = [to[0] - from[0], to[2] - from[2]];
  const strip = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.01, Math.hypot(dx, dz)), new THREE.MeshBasicMaterial({ color: LAB }));
  strip.position.set((from[0] + to[0]) / 2, 0.012, (from[2] + to[2]) / 2);
  strip.rotation.y = Math.atan2(dx, dz);
  return strip;
}

/** A background group's area as an outline on the floor (lab only). */
function area([x0, z0, x1, z1]: [number, number, number, number]): THREE.LineLoop {
  const corners = [
    [x0, z0],
    [x1, z0],
    [x1, z1],
    [x0, z1],
  ].map(([x, z]) => new THREE.Vector3(x, 0.02, z));
  return new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(corners), new THREE.LineBasicMaterial({ color: LAB }));
}

/** The shot's camera at time `t`: the try's place and aim, the shot's lens and shape, its move. */
export function shotCamera(staged: OlfShotTry, move: ShotMove, lens: string | undefined, aspect: number, t = 0): THREE.PerspectiveCamera {
  const camera = new THREE.PerspectiveCamera(verticalFov(lens, aspect), aspect, 0.05, 300);
  const pose = cameraPose({ at: staged.camera.at, looks_at: aimAt(staged, t) }, { ...move, lens }, t, aspect);
  camera.up.set(...cameraUp(pose.at, pose.looks_at));
  camera.position.set(...pose.at);
  camera.lookAt(...pose.looks_at);
  return camera;
}

/** Render the frame a keyframe model gets (no lab overlays), at the start unless `opts.t` says.
 *
 * @param room The room version the try stands in.
 * @param staged The shot try.
 * @param camera The shot's camera words: lens, move, amount, ease.
 * @param aspect The frame shape as width over height.
 * @param opts The pin stripes by slot; pins or figures; the time.
 * @param height The frame height in pixels.
 * @returns A PNG `data:` URL (`POST /olf/scene/use` saves it as the shot's keyframe layout).
 */
export function renderSceneFrame(
  room: OlfRoom,
  staged: OlfShotTry,
  camera: ShotMove & { lens?: string },
  aspect: number,
  opts: SceneOptions,
  height = 1080,
): string {
  const t = opts.t ?? 0;
  const { scene } = buildScene(room, staged, camera, { ...opts, lab: false }, aspect);
  const lens = shotCamera(staged, camera, camera.lens, aspect, t);
  console.info("[shows] scene frame", { shot: staged.shot, room: staged.room, t, people: staged.cast.length, pieces: room.set.length });
  return shoot(scene, lens, Math.round(height * aspect), height);
}

/** A try's move as a reference video for a video model (COREPRODUC-732): the frame of
 * `renderSceneFrame` played from the start to the end of the shot at 24 fps, with no lab
 * overlays and no sound. The pin video of github.com/cbunseng/seedance-blockout-editor-private
 * (Apache-2.0): a model follows its camera path and timing; a body in it would be copied, a pin
 * gives nothing to copy. The daemon or host makes the MP4 (`author.add_reference_video`).
 *
 * With WebCodecs (a secure page in Chrome, Edge, Safari) each frame is encoded at its exact
 * time, as fast as the machine draws: a raw H.264 stream (`raw`). Else MediaRecorder records it
 * in real time, each frame at the moment it is drawn (fewer frames on a slow machine, never a
 * slower move). Bug fixed before release (a first test in software WebGL): poses by frame
 * number in real time stretched a 3 s move over 13 s of frames.
 *
 * @param seconds The shot's length, and the clip's (2 s at least: a video model wants it).
 * @param height The clip's height in pixels (720 is inside every provider's limits).
 * @returns The clip, and whether it is a raw H.264 stream.
 */
export async function recordMove(
  room: OlfRoom,
  staged: OlfShotTry,
  camera: ShotMove & { lens?: string },
  aspect: number,
  opts: SceneOptions,
  seconds: number,
  height = 720,
): Promise<{ blob: Blob; raw: boolean }> {
  const [w, h] = [Math.round((height * aspect) / 2) * 2, height]; // even sides for H.264
  const canvas = Object.assign(document.createElement("canvas"), { width: w, height: h });
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(w, h, false);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const built = buildScene(room, staged, camera, { ...opts, lab: false }, aspect);
  const lens = shotCamera(staged, camera, camera.lens, aspect, 0);
  const draw = (t: number) => {
    built.update(t, lens);
    renderer.render(built.scene, lens);
  };
  const frames = Math.max(48, Math.round(seconds * 24)); // 2 s at least
  const config = { codec: "avc1.42001f", width: w, height: h, bitrate: 6_000_000, framerate: 24, avc: { format: "annexb" as const } };
  const exact = typeof VideoEncoder !== "undefined" && (await VideoEncoder.isConfigSupported(config)).supported;
  console.info("[shows] reference video", { shot: staged.shot, try: staged.try, seconds: frames / 24, size: `${w}x${h}`, exact });
  try {
    return exact ? { blob: await encodeFrames(canvas, draw, frames, config), raw: true } : { blob: await recordFrames(canvas, draw, frames), raw: false };
  } finally {
    renderer.dispose();
    renderer.forceContextLoss();
    free(built.scene);
  }
}

/** Encode `frames` frames, each drawn at its time in the shot, as a raw H.264 stream at 24 fps. */
async function encodeFrames(canvas: HTMLCanvasElement, draw: (t: number) => void, frames: number, config: VideoEncoderConfig): Promise<Blob> {
  const parts: Uint8Array[] = [];
  let failed: unknown = null;
  const encoder = new VideoEncoder({
    output: (chunk) => {
      const bytes = new Uint8Array(chunk.byteLength);
      chunk.copyTo(bytes);
      parts.push(bytes);
    },
    error: (err) => (failed = err),
  });
  encoder.configure(config);
  for (let i = 0; i < frames && !failed; i++) {
    draw(i / (frames - 1));
    const frame = new VideoFrame(canvas, { timestamp: Math.round((i * 1e6) / 24), duration: Math.round(1e6 / 24) });
    encoder.encode(frame, { keyFrame: i % 48 === 0 });
    frame.close();
    if (encoder.encodeQueueSize > 4) await new Promise((resolve) => setTimeout(resolve, 0)); // let it drain
  }
  await encoder.flush();
  encoder.close();
  if (failed) throw failed;
  return new Blob(parts as BlobPart[], { type: "video/h264" });
}

/** Record the move in real time with MediaRecorder (MP4 where the browser makes it, else WebM). */
async function recordFrames(canvas: HTMLCanvasElement, draw: (t: number) => void, frames: number): Promise<Blob> {
  const mime = ["video/mp4;codecs=avc1", "video/webm;codecs=vp9", "video/webm"].find((type) => MediaRecorder.isTypeSupported(type));
  if (!mime) throw new Error("this browser cannot record a video");
  const stream = canvas.captureStream(0); // a frame only when we ask: one per drawn step
  const track = stream.getVideoTracks()[0] as CanvasCaptureMediaStreamTrack;
  const recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 6_000_000 });
  const parts: Blob[] = [];
  recorder.ondataavailable = (event) => event.data.size && parts.push(event.data);
  const stopped = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
  draw(0); // a warm-up frame: the first draw compiles the shaders
  recorder.start();
  const [begin, total] = [performance.now(), (frames / 24) * 1000];
  try {
    for (let t = 0; ; ) {
      draw(t);
      track.requestFrame();
      await new Promise((resolve) => setTimeout(resolve, 1000 / 24)); // yield: the capture runs
      if (t >= 1) break; // the end pose was drawn and held one frame, so it is in the clip
      t = Math.min((performance.now() - begin) / total, 1);
    }
  } finally {
    recorder.stop();
    await stopped;
    stream.getTracks().forEach((one) => one.stop());
  }
  return new Blob(parts, { type: mime.split(";")[0] });
}

/** The lab's live view of a try: the shot camera, or a free view to walk around the room, and
 * the move played over the shot's length. */
export class SceneViewer {
  private readonly renderer: THREE.WebGLRenderer;
  private built: Built | null = null;
  private shot: THREE.PerspectiveCamera | null = null;
  private free: THREE.PerspectiveCamera | null = null;
  private controls: OrbitControls | null = null;
  private args: [OlfRoom, OlfShotTry, ShotMove & { lens?: string }, number, SceneOptions] | null = null;
  private frame = 0;

  constructor(private readonly canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.shadowMap.enabled = true;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
  }

  /** Show a try (with the lab overlays) at time `opts.t`. */
  show(room: OlfRoom, staged: OlfShotTry, camera: ShotMove & { lens?: string }, aspect: number, opts: SceneOptions): void {
    if (this.built) free(this.built.scene);
    this.args = [room, staged, camera, aspect, opts];
    this.built = buildScene(room, staged, camera, { ...opts, lab: true }, aspect);
    this.shot = shotCamera(staged, camera, camera.lens, aspect, opts.t ?? 0);
    if (this.free && staged.shot) this.built.scene.add(new THREE.CameraHelper(this.shot)); // a room alone has no shot camera
    console.info("[shows] scene lab view", { shot: staged.shot, try: staged.try, room: staged.room, free: !!this.free });
    this.draw();
  }

  /** Move to time `t` in the shot (0..1): only the people and the camera move. */
  at(t: number): void {
    if (!this.built || !this.shot) return;
    this.built.update(t, this.shot);
    this.draw();
  }

  /** Play the move over `seconds`, calling `tick` with the time; returns a stop function. */
  play(seconds: number, tick?: (t: number) => void): () => void {
    const begin = performance.now();
    const step = () => {
      const t = Math.min((performance.now() - begin) / 1000 / Math.max(seconds, 0.1), 1);
      this.at(t);
      tick?.(t);
      if (t < 1) this.frame = requestAnimationFrame(step);
    };
    cancelAnimationFrame(this.frame);
    this.frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(this.frame);
  }

  /** Switch between the shot camera and a free view with orbit controls. */
  freeView(on: boolean): void {
    this.controls?.dispose();
    this.controls = null;
    this.free = null;
    if (on && this.shot) {
      this.free = new THREE.PerspectiveCamera(40, this.shot.aspect, 0.05, 300);
      this.free.position.set(7.5, 7, 9);
      this.controls = new OrbitControls(this.free, this.canvas);
      this.controls.target.set(0, 0.8, -0.5);
      this.controls.addEventListener("change", () => this.draw());
      this.controls.update();
    }
    if (this.args) this.show(...this.args);
  }

  private draw(): void {
    const camera = this.free ?? this.shot;
    if (!camera || !this.built) return;
    const { clientWidth: w, clientHeight: h } = this.canvas;
    this.renderer.setSize(w, h, false);
    this.renderer.render(this.built.scene, camera);
  }

  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.controls?.dispose();
    if (this.built) free(this.built.scene);
    this.renderer.dispose();
  }
}

