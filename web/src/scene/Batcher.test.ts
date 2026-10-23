import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { MaterialPoolCore } from "./MaterialPool";
import { BATCHED_LAYER, BatcherCore, batchKey } from "./Batcher";

const box = new THREE.BoxGeometry(1, 1, 1);
const cyl = new THREE.CylinderGeometry(1, 1, 2);

function factory(n: number) {
  const scene = new THREE.Scene();
  const mirror = new THREE.Group(); mirror.scale.set(1, 1, -1); scene.add(mirror);
  const parts: THREE.Mesh[] = [];
  for (let i = 0; i < n; i++) {
    const m = new THREE.Mesh(i % 2 ? box : cyl, new THREE.MeshStandardMaterial({ color: i % 3 ? "#c33" : "#3c3", roughness: 0.5 }));
    m.position.set(i, 0, i);
    m.castShadow = true;
    mirror.add(m);
    parts.push(m);
  }
  const pool = new MaterialPoolCore(), batcher = new BatcherCore(scene);
  const frame = () => { pool.watch(); pool.scan(scene); scene.updateMatrixWorld(); batcher.scan(); batcher.sync(); };
  return { scene, mirror, parts, pool, batcher, frame };
}

describe("draw-call batching", () => {
  it("draws parts that differ only in colour and shape with one batch, once loading has settled", () => {
    const f = factory(12);
    f.frame(); f.frame();
    expect(f.batcher.stats().batches).toBe(0);         // still settling
    f.frame();
    expect(f.batcher.stats()).toEqual({ batches: 1, batched: 12 });
    expect(f.parts.every((p) => p.layers.mask === 1 << BATCHED_LAYER)).toBe(true);
  });

  it("each instance follows its part: matrix (through the mirror), colour and visibility", () => {
    const f = factory(8);
    f.frame(); f.frame(); f.frame();
    const batch = f.scene.children.find((o) => (o as THREE.BatchedMesh).isBatchedMesh) as THREE.BatchedMesh;
    expect(batch.matrixWorld.determinant()).toBeLessThan(0);       // the batch carries the mirror
    f.parts[3].position.set(5, 6, 7);
    f.scene.updateMatrixWorld();
    f.batcher.sync();
    const inst = new THREE.Matrix4();
    batch.getMatrixAt(3, inst);
    const world = new THREE.Matrix4().multiplyMatrices(batch.matrixWorld, inst);
    world.elements.forEach((x, i) => expect(x).toBeCloseTo(f.parts[3].matrixWorld.elements[i], 9));
    expect(inst.determinant()).toBeGreaterThan(0);
    (f.parts[3].material as THREE.MeshStandardMaterial).color.set("#00f");
    f.parts[3].visible = false;
    f.batcher.sync();
    expect(batch.getVisibleAt(3)).toBe(false);
    f.parts[3].visible = true;
    f.batcher.sync();
    const got = new THREE.Color();
    batch.getColorAt(3, got);
    expect(got.getHexString()).toBe("0000ff");
  });

  it("an animated part leaves the batch and is drawn as itself again", () => {
    const f = factory(8);
    f.frame(); f.frame(); f.frame();
    const own = (f.pool as unknown as { entries: { mesh: THREE.Mesh; orig: THREE.MeshStandardMaterial }[] }).entries.find((e) => e.mesh === f.parts[2])!.orig;
    own.emissive.set("#ff0000"); own.emissiveIntensity = 1;        // e.g. an LED turns on
    f.pool.watch();                                                // the pool puts its own back
    f.batcher.sync();
    expect(f.parts[2].material).toBe(own);
    expect(f.parts[2].layers.mask).toBe(1);                        // drawn by the camera again
    expect(batchKey(f.parts[2])).toBeNull();
  });

  it("removing parts rebuilds the batch without them; disposing gives every part back", () => {
    const f = factory(8);
    f.frame(); f.frame(); f.frame();
    f.mirror.remove(f.parts[0]);
    f.frame();
    expect(f.batcher.stats().batched).toBe(7);
    f.batcher.dispose();
    expect(f.parts.slice(1).every((p) => p.layers.mask === 1)).toBe(true);
    expect(f.scene.children.some((o) => (o as THREE.BatchedMesh).isBatchedMesh)).toBe(false);
  });
});
