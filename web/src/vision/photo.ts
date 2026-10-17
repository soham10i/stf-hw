// The inspection camera's photograph: the 3D scene rendered from the camera in the colour hood
// (vision/camera.json - its pose and lens from vision/mount.py), looking straight down at the
// belt, at the moment a baked cookie is under the lens. Sent to the API's photo store
// (POST /vision/captures, services/api/captures.py) as a dataset for the vision models.
//
// Rendered off screen, into a render target of its own, so the view the visitor looks at is
// not disturbed; the ring light's flash (a point light at the lens) lights the inside of the hood.

import * as THREE from "three";
import { HAS_API } from "../shared/mode";

export const PHOTO_PX = 256;

let target: THREE.WebGLRenderTarget | null = null;
const cam = new THREE.PerspectiveCamera(80, 1, 0.004, 2);
let buf: Uint8Array | null = null;

/** Render the scene from `eye` looking at `at` (world, metres) with a `fovDeg` lens; a JPEG. */
export function photograph(gl: THREE.WebGLRenderer, scene: THREE.Scene, eye: THREE.Vector3, at: THREE.Vector3,
  fovDeg: number, up: THREE.Vector3): Promise<Blob | null> {
  const px = PHOTO_PX;
  target ??= new THREE.WebGLRenderTarget(px, px, { colorSpace: THREE.SRGBColorSpace, samples: 4 });
  buf ??= new Uint8Array(px * px * 4);
  cam.fov = fovDeg;
  cam.position.copy(eye);
  cam.up.copy(up);
  cam.lookAt(at);
  cam.updateProjectionMatrix();
  cam.updateMatrixWorld();
  const prev = gl.getRenderTarget();
  gl.setRenderTarget(target);
  gl.clear();
  gl.render(scene, cam);
  gl.readRenderTargetPixels(target, 0, 0, px, px, buf);
  gl.setRenderTarget(prev);
  // WebGL rows run bottom-up
  const c = document.createElement("canvas");
  c.width = c.height = px;
  const g = c.getContext("2d");
  if (!g) return Promise.resolve(null);
  const img = g.createImageData(px, px);
  for (let y = 0; y < px; y++) img.data.set(buf.subarray((px - 1 - y) * px * 4, (px - y) * px * 4), y * px * 4);
  g.putImageData(img, 0, 0);
  return new Promise((ok) => c.toBlob((b) => ok(b), "image/jpeg", 0.9));
}

/** The photos taken in this tab, newest first (the Vision panel shows them). */
export const photos = {
  list: [] as { n: number; flavour: string; url: string; stored: "yes" | "no" | "off" }[],
  listeners: new Set<() => void>(),
};

/** Keep the photo in the tab's gallery and, with the API, in the server's photo store. */
export async function keep(blob: Blob, flavour: string, n: number) {
  const entry = { n, flavour, url: URL.createObjectURL(blob), stored: "off" as "yes" | "no" | "off" };
  photos.list.unshift(entry);
  for (const old of photos.list.splice(24)) URL.revokeObjectURL(old.url);
  photos.listeners.forEach((f) => f());
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
