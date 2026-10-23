// One material per look: meshes whose materials are identical share one.
//
// The factory is built part by part, and each part makes its own material: about 2,000 materials
// for some 140 different looks. three.js pays per material on every draw (program checks, uniform
// uploads), so the frame was CPU-bound at ~70 ms. Sharing them brings the frame under 20 ms.
//
// The pool works on the scene as it is, so nothing that builds a part has to change:
//   - every so often it scans the scene and, for each mesh, swaps a poolable material for the
//     shared one with the same look (all of its settings, colours and textures equal);
//   - every frame it watches the materials it took off: one that changes (a tint, an LED, a
//     heater's glow, a texture's needsUpdate) goes straight back on its mesh, for good - so code
//     that animates its own material keeps working, one frame late at most.
// A material is never pooled with clipping planes (joints.ts trims), a canvas texture (displays),
// a custom shader, or userData.noPool. Shared materials carry userData.shared, so code that wants
// to change a mesh's material clones it first (joints.ts, Precise.tsx already do).
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";

const POOLABLE = new Set(["MeshStandardMaterial", "MeshPhysicalMaterial", "MeshBasicMaterial", "MeshLambertMaterial", "MeshPhongMaterial"]);
const SKIP = new Set(["uuid", "id", "name", "version", "userData", "type"]);
const SCAN_EVERY = 45; // frames
const BASE_COMPILE = THREE.Material.prototype.onBeforeCompile;

/** The look of a material: every setting that changes how it draws; null when it must stay its own. */
export function lookOf(m: THREE.Material): string | null {
  if (!POOLABLE.has(m.type) || m.userData.noPool || m.onBeforeCompile !== BASE_COMPILE) return null;
  if (m.clippingPlanes?.length) return null;
  const parts: (string | number | boolean)[] = [m.type];
  const rec = m as unknown as Record<string, unknown>;
  for (const k of Object.keys(rec).sort()) {
    if (SKIP.has(k)) continue;
    const v = rec[k];
    if (v === null || v === undefined) continue;
    if (typeof v === "number" || typeof v === "boolean" || typeof v === "string") parts.push(k, v);
    else if ((v as THREE.Color).isColor) parts.push(k, (v as THREE.Color).getHexString());
    else if ((v as THREE.Vector2).isVector2) parts.push(k, (v as THREE.Vector2).x, (v as THREE.Vector2).y);
    else if ((v as THREE.Texture).isTexture) {
      const data = (v as THREE.Texture).source?.data;
      if ((v as THREE.CanvasTexture).isCanvasTexture || (typeof HTMLCanvasElement !== "undefined" && data instanceof HTMLCanvasElement)) return null;
      parts.push(k, (v as THREE.Texture).uuid);
    } else if ((v as THREE.Euler).isEuler) parts.push(k, (v as THREE.Euler).x, (v as THREE.Euler).y, (v as THREE.Euler).z);
    else if (Array.isArray(v)) {
      if (v.every((x) => typeof x === "number")) parts.push(k, v.join(","));
      else if (v.length) return null;       // clipping planes and the like
    } else if (typeof v === "function" || k.startsWith("_listeners")) continue;
    else if (Object.getPrototypeOf(v) === Object.prototype) parts.push(k, JSON.stringify(v)); // defines
    else return null; // something we do not know how to compare: keep it its own
  }
  return parts.join("|");
}

// what the watch compares each frame: what animation code changes
const WATCH = 12;
function snap(m: THREE.Material, out: Float64Array, o: number) {
  const s = m as THREE.MeshStandardMaterial;
  out[o] = s.color ? s.color.r : 0; out[o + 1] = s.color ? s.color.g : 0; out[o + 2] = s.color ? s.color.b : 0;
  out[o + 3] = s.emissive ? s.emissive.r : 0; out[o + 4] = s.emissive ? s.emissive.g : 0; out[o + 5] = s.emissive ? s.emissive.b : 0;
  out[o + 6] = s.emissiveIntensity ?? 0; out[o + 7] = m.opacity; out[o + 8] = m.version;
  out[o + 9] = m.visible ? 1 : 0; out[o + 10] = s.roughness ?? 0; out[o + 11] = (s.metalness ?? 0) + (s.map ? s.map.version * 1e-3 + 7 : 0);
}

interface Entry { mesh: THREE.Mesh; slot: number; orig: THREE.Material; shared: THREE.Material }

export interface PoolStats { pooled: number; looks: number; restored: number }

export class MaterialPoolCore {
  readonly looks = new Map<string, THREE.Material>();
  private entries: Entry[] = [];
  private snaps = new Float64Array(0);
  private cur = new Float64Array(WATCH);
  restored = 0;

  /** Swap every poolable material in `root` for its look's shared one. */
  scan(root: THREE.Object3D) {
    // forget meshes that left the scene
    this.entries = this.entries.filter((e) => this.attached(e.mesh, root));
    const taken = new Set(this.entries.map((e) => e.orig));
    root.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      list.forEach((m, slot) => {
        if (!m || m.userData.pooled || taken.has(m)) return;
        const look = lookOf(m);
        if (!look) return;
        let shared = this.looks.get(look);
        if (!shared) {
          shared = m.clone();
          shared.userData = { ...shared.userData, pooled: true, shared: true };
          this.looks.set(look, shared);
        }
        if (Array.isArray(mesh.material)) mesh.material[slot] = shared; else mesh.material = shared;
        this.entries.push({ mesh, slot, orig: m, shared });
        taken.add(m);
      });
    });
    this.snaps = new Float64Array(this.entries.length * WATCH);
    this.entries.forEach((e, i) => snap(e.orig, this.snaps, i * WATCH));
  }

  /** Put back every original that changed since it was pooled; it stays its own from then on. */
  watch() {
    const S = this.snaps, C = this.cur;
    let gone = false;
    for (let i = 0; i < this.entries.length; i++) {
      const e = this.entries[i];
      snap(e.orig, C, 0);
      const o = i * WATCH;
      let same = true;
      for (let k = 0; k < WATCH; k++) if (C[k] !== S[o + k]) { same = false; break; }
      if (same) continue;
      e.orig.userData.noPool = true;
      const now = Array.isArray(e.mesh.material) ? e.mesh.material[e.slot] : e.mesh.material;
      if (now === e.shared) {
        if (Array.isArray(e.mesh.material)) e.mesh.material[e.slot] = e.orig; else e.mesh.material = e.orig;
      }
      this.restored++;
      this.entries[i] = null as unknown as Entry;
      gone = true;
    }
    if (gone) {
      const keep: Entry[] = [], snaps: number[] = [];
      this.entries.forEach((e, i) => { if (e) { keep.push(e); for (let k = 0; k < WATCH; k++) snaps.push(S[i * WATCH + k]); } });
      this.entries = keep;
      this.snaps = Float64Array.from(snaps);
    }
  }

  stats(): PoolStats { return { pooled: this.entries.length, looks: this.looks.size, restored: this.restored }; }

  dispose() { for (const m of this.looks.values()) m.dispose(); this.looks.clear(); this.entries = []; }

  private attached(o: THREE.Object3D, root: THREE.Object3D) {
    for (let p: THREE.Object3D | null = o; p; p = p.parent) if (p === root) return true;
    return false;
  }
}

export const poolStats: { current: PoolStats | null } = { current: null };

/** Mount once inside the Canvas. `?pool=0` turns it off (to compare). */
export function MaterialPool() {
  const scene = useThree((s) => s.scene);
  const core = useRef<MaterialPoolCore | null>(null);
  const frame = useRef(0);
  const off = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("pool") === "0";
  useEffect(() => {
    if (off) return;
    const c = new MaterialPoolCore();
    core.current = c;
    return () => { c.dispose(); core.current = null; poolStats.current = null; };
  }, [off]);
  useFrame(() => {
    const c = core.current;
    if (!c) return;
    c.watch();
    if (frame.current++ % SCAN_EVERY === 0) { c.scan(scene); poolStats.current = c.stats(); }
  });
  return null;
}
