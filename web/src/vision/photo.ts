// The inspection camera in the colour hood: the live view and the photograph of each cookie.
//
// It images the way the vision models were trained (stf-cad/hbw/vision/render.py): a top view
// of an 80 mm field (camera.json fov_mm) on the belt, the cookie seen at its true size whatever
// its height - a telecentric view, rendered orthographically - and lit only by the hood's ring
// light. So it sees only what is in the hood (the INSPECT layer: the belt, its rails, the cookie
// and the ring light), not the room's light or the rest of the machine. mount.py's 80.8° lens
// frames 80 mm at the belt only: the cookie's top, 20 mm nearer, would fill its frame, and a
// model trained on 45 mm cookies in an 80 mm field rejects every one of them (measured: all 14
// stored twin photos "chipped", the autoencoder at 25x its threshold).
//
// Two uses, one renderer:
//   - the LIVE FEED: a frame every FEED_MS while a dashboard watches (Vision QC); streamed to it
//     over a BroadcastChannel and never stored;
//   - the PHOTO: one exposure as each cookie crosses the lens's axis; kept in the tab's gallery,
//     sent to the dashboard for inspection and stored by the API (POST /vision/captures,
//     services/api/captures.py) as the dataset for the vision models.
// Rendered off screen, into a render target of its own, so the visitor's view is not disturbed.

import * as THREE from "three";
import { HAS_API } from "../shared/mode";
import { VISION_CHANNEL } from "./channel";

export const PHOTO_PX = 256;
/** the three.js layer the inspection camera sees */
export const INSPECT_LAYER = 5;
/** the live feed's frame interval (about 8 frames a second) */
export const FEED_MS = 125;

/** What the inspection camera sees: the belt and its rails under the lens and the grey target
    (the hood), and the cookie on its way along the line (the subject), register themselves. */
export const inspected = new Set<THREE.Object3D>();
export const subjects = new Set<THREE.Object3D>();

let target: THREE.WebGLRenderTarget | null = null;
const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.0005, 2);
cam.layers.set(INSPECT_LAYER);
let buf: Uint8Array | null = null;
let canvas: HTMLCanvasElement | null = null;

/** One exposure: the field (`fieldM` square, world units) around `at` on the belt, seen from
    `eye` with `up` as the image's top; drawn into a canvas (top row first). `empty`: the hood
    without its subject - the reference image of the empty station an inspection compares a
    photo with (the same instant, so the belt's ribs are where they are in the photo). */
export function expose(gl: THREE.WebGLRenderer, scene: THREE.Scene, eye: THREE.Vector3, at: THREE.Vector3,
  up: THREE.Vector3, fieldM: number, empty = false): HTMLCanvasElement | null {
  const px = PHOTO_PX;
  target ??= new THREE.WebGLRenderTarget(px, px, { colorSpace: THREE.SRGBColorSpace, samples: 4 });
  buf ??= new Uint8Array(px * px * 4);
  const h = fieldM / 2;
  cam.left = -h; cam.right = h; cam.top = h; cam.bottom = -h;
  cam.near = 0.0005; cam.far = eye.distanceTo(at) + 0.5;
  cam.position.copy(eye);
  cam.up.copy(up);
  cam.lookAt(at);
  cam.updateProjectionMatrix();
  cam.updateMatrixWorld();
  // the hood is closed: no studio environment, only the ring light (on the inspection layer);
  // and the glow the twin gives a baked cookie, so it reads deep in a mould, is the twin's, not
  // the cookie's: the camera does not see it
  const env = scene.environment, bg = scene.background;
  scene.environment = null; scene.background = null;
  const glow: [THREE.MeshStandardMaterial, number][] = [];
  const shown = [...subjects].filter((o) => o.visible);
  if (empty) shown.forEach((o) => { o.visible = false; });
  for (const o of [...inspected, ...subjects]) o.traverse((m) => {
    m.layers.enable(INSPECT_LAYER);
    const mat = (m as THREE.Mesh).material as THREE.MeshStandardMaterial | undefined;
    if (mat && "emissiveIntensity" in mat && mat.emissiveIntensity) { glow.push([mat, mat.emissiveIntensity]); mat.emissiveIntensity = 0; }
  });
  const prev = gl.getRenderTarget(), clear = gl.getClearColor(new THREE.Color()), alpha = gl.getClearAlpha();
  gl.setRenderTarget(target);
  gl.setClearColor(0x000000, 1);
  gl.clear();
  gl.render(scene, cam);
  gl.readRenderTargetPixels(target, 0, 0, px, px, buf);
  gl.setRenderTarget(prev);
  gl.setClearColor(clear, alpha);
  scene.environment = env; scene.background = bg;
  for (const [mat, k] of glow) mat.emissiveIntensity = k;
  if (empty) shown.forEach((o) => { o.visible = true; });
  canvas ??= document.createElement("canvas");
  canvas.width = canvas.height = px;
  const g = canvas.getContext("2d");
  if (!g) return null;
  const img = g.createImageData(px, px);
  // WebGL rows run bottom-up
  for (let y = 0; y < px; y++) img.data.set(buf.subarray((px - 1 - y) * px * 4, (px - y) * px * 4), y * px * 4);
  g.putImageData(img, 0, 0);
  return canvas;
}

export const jpeg = (c: HTMLCanvasElement, q = 0.9) => new Promise<Blob | null>((ok) => c.toBlob((b) => ok(b), "image/jpeg", q));

/** The photos taken in this tab, newest first. */
export const photos = {
  list: [] as { n: number; flavour: string; url: string; stored: "yes" | "no" | "off" }[],
  listeners: new Set<() => void>(),
};

let channel: BroadcastChannel | null = null;
/** The channel to the dashboard, or null where there is none. */
export function visionChannel() {
  try { channel ??= new BroadcastChannel(VISION_CHANNEL); } catch { /* no BroadcastChannel */ }
  return channel;
}

/** Keep the photo: in the tab's gallery, at the dashboard's inspection (Vision QC, with the empty
    hood's reference image) and, with the API, in the server's photo store. The only camera
    images that are kept. */
export async function keep(blob: Blob, empty: Blob | null, flavour: string, n: number, truth = "ok") {
  const entry = { n, flavour, url: URL.createObjectURL(blob), stored: "off" as "yes" | "no" | "off" };
  photos.list.unshift(entry);
  for (const old of photos.list.splice(24)) URL.revokeObjectURL(old.url);
  photos.listeners.forEach((f) => f());
  visionChannel()?.postMessage({ type: "photo", n, flavour, truth, jpeg: blob, empty, t: Date.now() });
  if (!HAS_API) return;
  try {
    const q = new URLSearchParams({ flavour, n: String(n), source: "twin" });
    const r = await fetch(`/vision/captures?${q}`, { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob });
    entry.stored = r.ok ? "yes" : "no";
  } catch {
    entry.stored = "no";
  }
  photos.listeners.forEach((f) => f());
}
