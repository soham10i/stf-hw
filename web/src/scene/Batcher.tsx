// Draw-call batching: meshes that look alike (colour aside) are drawn by one BatchedMesh.
//
// After the transmission fix the factory still made ~1,900 draw calls a frame, one per mesh, and
// three.js spends ~20 us of CPU on each. A BatchedMesh draws many geometries in one call (WebGL
// multi-draw), each instance with its own matrix and colour.
//
// Nothing that builds the scene changes: the meshes stay where they are - their components still
// move them, toggle them and click them - and the batcher follows them:
//   - scan (every SCAN_EVERY frames, once the scene has settled): meshes whose material the pool
//     has shared (MaterialPool: so its original is watched, and an animated one is never batched)
//     are grouped by look-without-colour, geometry layout and shadow flags; each group of
//     MIN_GROUP or more becomes one BatchedMesh, rebuilt when its members change;
//   - every render (scene.onBeforeRender: after three.js has updated the world matrices, so the
//     batch is never a frame behind the parts it draws): each instance takes its mesh's world
//     matrix and visibility; a mesh whose material was swapped (the pool put an animated original
//     back) or that left the scene leaves the batch at once;
//   - the meshes themselves move to BATCHED_LAYER, which the camera does not draw and the
//     raycaster does test, so they are drawn once - by the batch - and still picked.
// The inspection camera renders only its own layer, which photo.ts enables on what it sees, so
// photos keep using the meshes themselves.
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { lookOf } from "./MaterialPool";

export const BATCHED_LAYER = 30;
const SCAN_EVERY = 90;   // frames
const MIN_GROUP = 4;     // fewer meshes than this are not worth a batch

interface Member { mesh: THREE.Mesh; id: number; mat: THREE.Material; layers: number; color: THREE.Color }
interface Group { key: string; batch: THREE.BatchedMesh; members: Member[]; mirrored: boolean }

// the stage is drawn inside a mirror (Stage.tsx: scale z -1); a batch of mirrored parts carries
// the mirror itself, so its instances keep a positive determinant and three.js flips the winding
// once, for the batch, as it does for each mirrored mesh
const MIRROR = new THREE.Matrix4().makeScale(1, 1, -1);
const tmp = new THREE.Matrix4();

/** What a mesh is batched by: its material's look without the colour (the batch carries colour
    per instance), its geometry's attribute layout, and its shadow flags; null: not batchable. */
export function batchKey(mesh: THREE.Mesh): string | null {
  if (Array.isArray(mesh.material) || (mesh as unknown as THREE.InstancedMesh).isInstancedMesh ||
      (mesh as unknown as THREE.SkinnedMesh).isSkinnedMesh || (mesh as unknown as THREE.BatchedMesh).isBatchedMesh) return null;
  const m = mesh.material as THREE.MeshStandardMaterial;
  if (!m.userData.pooled || m.transparent || !m.visible) return null;
  if (m.emissive && (m.emissiveIntensity > 0 && (m.emissive.r || m.emissive.g || m.emissive.b))) return null;
  if (mesh.layers.mask !== 1 || mesh.morphTargetInfluences || mesh.renderOrder !== 0) return null;
  const g = mesh.geometry;
  if (!g.attributes.position || g.morphAttributes.position) return null;
  const white = m.clone() as THREE.MeshStandardMaterial;
  white.color?.set(1, 1, 1);
  const look = lookOf(white);
  white.dispose();
  if (!look) return null;
  const attrs = Object.keys(g.attributes).sort().map((k) => `${k}${g.attributes[k].itemSize}${g.attributes[k].normalized ? "n" : ""}`).join(",");
  const mirrored = mesh.matrixWorld.determinant() < 0;
  return `${look}#${attrs}#${g.index ? "i" : "n"}#${mesh.castShadow ? 1 : 0}${mesh.receiveShadow ? 1 : 0}#${mirrored ? "m" : "p"}`;
}

function shown(o: THREE.Object3D, root: THREE.Object3D): boolean {
  for (let p: THREE.Object3D | null = o; p; p = p.parent) {
    if (!p.visible) return false;
    if (p === root) return true;
  }
  return false; // left the scene
}

export interface BatchStats { batches: number; batched: number }

export class BatcherCore {
  private groups = new Map<string, Group>();
  private byMesh = new Map<THREE.Mesh, Group>();
  private lastCount = -1;
  private settled = 0;
  private readonly tmpColor = new THREE.Color();

  constructor(private readonly root: THREE.Object3D) {}

  /** Group the batchable meshes; build or rebuild a batch whose members changed. Waits until the
      number of meshes has held for two scans (loading is over) before the first build. */
  scan() {
    const found = new Map<string, THREE.Mesh[]>();
    let meshes = 0;
    this.root.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh || (mesh as unknown as THREE.BatchedMesh).isBatchedMesh) return;
      meshes++;
      const own = this.byMesh.get(mesh);
      // a member keeps its group while its material is the one it was batched with
      if (own) {
        const m = own.members.find((x) => x.mesh === mesh)!;
        if (mesh.material === m.mat) { (found.get(own.key) ?? found.set(own.key, []).get(own.key)!).push(mesh); return; }
      }
      if (!shown(mesh, this.root)) return;   // hidden parts join once they are shown
      const k = batchKey(mesh);
      if (k) (found.get(k) ?? found.set(k, []).get(k)!).push(mesh);
    });
    this.settled = meshes === this.lastCount ? this.settled + 1 : 0;
    this.lastCount = meshes;
    if (this.settled < 2 && !this.groups.size) return;
    for (const [key, list] of found) {
      const g = this.groups.get(key);
      const same = g && g.members.length === list.length && g.members.every((m, i) => m.mesh === list[i]);
      if (same) continue;
      if (g) this.drop(g);
      if (list.length >= MIN_GROUP) this.build(key, list);
    }
    for (const g of [...this.groups.values()]) if (!found.has(g.key)) this.drop(g);
  }

  private build(key: string, list: THREE.Mesh[]) {
    const geos = new Map<THREE.BufferGeometry, number>();
    let verts = 0, index = 0;
    for (const m of list) {
      if (geos.has(m.geometry)) continue;
      geos.set(m.geometry, -1);
      verts += m.geometry.attributes.position.count;
      index += m.geometry.index ? m.geometry.index.count : 0;
    }
    const mat = (list[0].material as THREE.Material).clone() as THREE.MeshStandardMaterial;
    mat.color?.set(1, 1, 1);
    mat.userData = { batch: true };
    const batch = new THREE.BatchedMesh(list.length, verts, index, mat);
    batch.castShadow = list[0].castShadow;
    batch.receiveShadow = list[0].receiveShadow;
    batch.sortObjects = false;
    batch.name = "batch";
    batch.raycast = () => {};   // the meshes themselves are picked
    const mirrored = key.endsWith("#m");
    batch.matrixAutoUpdate = false;
    if (mirrored) batch.matrix.copy(MIRROR);
    for (const [geo] of geos) geos.set(geo, batch.addGeometry(geo));
    const group: Group = { key, batch, members: [], mirrored };
    for (const mesh of list) {
      const id = batch.addInstance(geos.get(mesh.geometry)!);
      const color = ((mesh.material as THREE.MeshStandardMaterial).color ?? new THREE.Color(1, 1, 1)).clone();
      batch.setColorAt(id, color);
      batch.setMatrixAt(id, mirrored ? tmp.multiplyMatrices(MIRROR, mesh.matrixWorld) : mesh.matrixWorld);
      group.members.push({ mesh, id, mat: mesh.material as THREE.Material, layers: mesh.layers.mask, color });
      mesh.layers.set(BATCHED_LAYER);
      this.byMesh.set(mesh, group);
    }
    this.root.add(batch);
    batch.updateMatrixWorld(true);
    this.groups.set(key, group);
  }

  private drop(g: Group) {
    for (const m of g.members) this.release(m);
    g.batch.removeFromParent();
    g.batch.dispose();
    (g.batch.material as THREE.Material).dispose();
    this.groups.delete(g.key);
  }

  private release(m: Member) {
    if (m.mesh.layers.mask === 1 << BATCHED_LAYER || m.mesh.layers.isEnabled(BATCHED_LAYER)) {
      m.mesh.layers.mask = m.layers | (m.mesh.layers.mask & ~(1 << BATCHED_LAYER));
    }
    this.byMesh.delete(m.mesh);
  }

  /** Every render, after the world matrices: each instance follows its mesh. */
  sync() {
    for (const g of this.groups.values()) {
      const b = g.batch;
      let lost = false;
      for (const m of g.members) {
        if (m.id < 0) continue;
        const mesh = m.mesh;
        if (mesh.material !== m.mat) { this.release(m); b.setVisibleAt(m.id, false); m.id = -1; lost = true; continue; }
        const vis = shown(mesh, this.root);
        b.setVisibleAt(m.id, vis);
        if (!vis) continue;
        b.setMatrixAt(m.id, g.mirrored ? tmp.multiplyMatrices(MIRROR, mesh.matrixWorld) : mesh.matrixWorld);
        const c = (mesh.material as THREE.MeshStandardMaterial).color;
        if (c && !c.equals(m.color)) { m.color.copy(c); b.setColorAt(m.id, this.tmpColor.copy(c)); }
      }
      if (lost) g.members = g.members.filter((m) => m.id >= 0);
    }
  }

  stats(): BatchStats {
    let batched = 0;
    for (const g of this.groups.values()) batched += g.members.length;
    return { batches: this.groups.size, batched };
  }

  dispose() { for (const g of [...this.groups.values()]) this.drop(g); }
}

export const batchStats: { current: BatchStats | null } = { current: null };

/** Mount once inside the Canvas, after MaterialPool. `?batch=0` turns it off (to compare). */
export function Batcher() {
  const scene = useThree((s) => s.scene);
  const raycaster = useThree((s) => s.raycaster);
  const core = useRef<BatcherCore | null>(null);
  const frame = useRef(0);
  const off = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("batch") === "0";
  useEffect(() => {
    if (off) return;
    const c = new BatcherCore(scene);
    core.current = c;
    raycaster.layers.enable(BATCHED_LAYER);
    const prev = scene.onBeforeRender;
    scene.onBeforeRender = function (...a) { c.sync(); prev.apply(this, a); };
    return () => {
      scene.onBeforeRender = prev;
      c.dispose();
      core.current = null;
      batchStats.current = null;
    };
  }, [off, scene, raycaster]);
  useFrame(() => {
    const c = core.current;
    if (!c || frame.current++ % SCAN_EVERY !== 0) return;
    c.scan();
    batchStats.current = c.stats();
  });
  return null;
}
