import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { lookOf, MaterialPoolCore } from "./MaterialPool";

const box = new THREE.BoxGeometry();
const mesh = (m: THREE.Material) => new THREE.Mesh(box, m);

describe("the material pool", () => {
  it("gives identical materials one look, and different ones different looks", () => {
    const a = new THREE.MeshPhysicalMaterial({ color: "#c33", roughness: 0.5 });
    const b = new THREE.MeshPhysicalMaterial({ color: "#c33", roughness: 0.5 });
    const c = new THREE.MeshPhysicalMaterial({ color: "#c33", roughness: 0.6 });
    const d = new THREE.MeshStandardMaterial({ color: "#c33", roughness: 0.5 });
    expect(lookOf(a)).not.toBeNull();
    expect(lookOf(a)).toBe(lookOf(b));
    expect(lookOf(a)).not.toBe(lookOf(c));
    expect(lookOf(a)).not.toBe(lookOf(d));
  });

  it("never pools clipped, custom-shader or opted-out materials", () => {
    const clipped = new THREE.MeshStandardMaterial(); clipped.clippingPlanes = [new THREE.Plane()];
    const custom = new THREE.MeshStandardMaterial(); custom.onBeforeCompile = () => {};
    const own = new THREE.MeshStandardMaterial(); own.userData.noPool = true;
    expect([clipped, custom, own, new THREE.ShaderMaterial()].map(lookOf)).toEqual([null, null, null, null]);
  });

  it("shares one material among a hundred identical parts", () => {
    const scene = new THREE.Scene();
    for (let i = 0; i < 100; i++) scene.add(mesh(new THREE.MeshStandardMaterial({ color: i % 2 ? "#fff" : "#000" })));
    const pool = new MaterialPoolCore();
    pool.scan(scene);
    expect(new Set(scene.children.map((m) => (m as THREE.Mesh).material)).size).toBe(2);
    expect(pool.stats()).toMatchObject({ pooled: 100, looks: 2 });
  });

  it("a material that animates goes back on its own mesh, and is never pooled again", () => {
    const scene = new THREE.Scene();
    const led = new THREE.MeshStandardMaterial({ color: "#222" });
    const twin = new THREE.MeshStandardMaterial({ color: "#222" });
    const m1 = mesh(led), m2 = mesh(twin);
    scene.add(m1, m2);
    const pool = new MaterialPoolCore();
    pool.scan(scene);
    expect(m1.material).toBe(m2.material);
    led.emissive.set("#0f0"); led.emissiveIntensity = 1;   // the LED lights
    pool.watch();
    expect(m1.material).toBe(led);
    expect(m2.material).not.toBe(led);
    pool.scan(scene);
    expect(m1.material).toBe(led);
    expect(pool.stats().restored).toBe(1);
  });

  it("forgets meshes that left the scene", () => {
    const scene = new THREE.Scene();
    const m = mesh(new THREE.MeshStandardMaterial());
    scene.add(m);
    const pool = new MaterialPoolCore();
    pool.scan(scene);
    scene.remove(m);
    pool.scan(scene);
    expect(pool.stats().pooled).toBe(0);
  });
});
