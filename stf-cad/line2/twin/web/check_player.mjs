// DT-2 gate helper (P2): player.js applied to the GLB under Node - what the browser would draw, as boxes (mm).
// node web/check_player.mjs 0,10,20,...  ->  JSON {frame: {part: [xmin, ymin, zmin, xmax, ymax, zmax, visible, kind, colour]}}
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Matrix4, Vector3 } from "three";
import { Timeline, offsetMatrix } from "./player.js";

const here = dirname(fileURLToPath(import.meta.url));
const raw = readFileSync(join(here, "..", "out", "stf2.glb"));
const jl = raw.readUInt32LE(12);
const g = JSON.parse(raw.subarray(20, 20 + jl).toString());
const bin = raw.subarray(20 + jl + 8);
const tl = new Timeline(JSON.parse(readFileSync(join(here, "..", "..", "motion", "timeline.json"))));

const cache = new Map();
function positions(meshIndex) {                 // the mesh's POSITION accessor, straight from the binary chunk
  if (!cache.has(meshIndex)) {
    const a = g.accessors[g.meshes[meshIndex].primitives[0].attributes.POSITION];
    const v = g.bufferViews[a.bufferView];
    const f = new Float32Array(bin.buffer, bin.byteOffset + v.byteOffset + (a.byteOffset || 0), a.count * 3);
    cache.set(meshIndex, Float32Array.from(f));
  }
  return cache.get(meshIndex);
}
const unitCyl = [];                              // the browser's cylinder: a 96-gon, base at 0, height 1, diameter 1
for (let i = 0; i < 96; i++) {
  const a = (2 * Math.PI * i) / 96;
  unitCyl.push(0.5 * Math.cos(a), 0.5 * Math.sin(a), 0, 0.5 * Math.cos(a), 0.5 * Math.sin(a), 1);
}
const p = new Vector3();
function box(m, pts) {
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < pts.length; i += 3) {
    p.set(pts[i], pts[i + 1], pts[i + 2]).applyMatrix4(m);
    for (let j = 0; j < 3; j++) { const c = p.getComponent(j); if (c < lo[j]) lo[j] = c; if (c > hi[j]) hi[j] = c; }
  }
  return [...lo, ...hi];
}
const parts = g.nodes.filter((n) => n.mesh !== undefined);
const out = {};
for (const k of process.argv[2].split(",").map(Number)) {
  const f = tl.frame(k);
  const rows = {};
  for (const name of Object.keys(f)) {           // every drawn cylinder (reshaped tracks, spawned cookies)
    const cm = tl.cylinderOf(name, f);
    if (cm) rows[name] = [...box(cm, unitCyl), f[name].vis ? 1 : 0, "cyl",
                           (f[name].col || (tl.spawn[name] && tl.spawn[name].colour) || "").toLowerCase()];
  }
  for (const n of parts) {
    if (rows[n.name]) continue;                   // its CAD mesh is hidden: the cylinder is what is drawn
    let m = null, vis = true;
    if (f[n.name] && f[n.name].kind === "rigid") { m = f[n.name].m; vis = f[n.name].vis; }
    else if (!f[n.name] && n.extras["stf:moving"]) m = tl.followerMatrix(n.name, f);
    if (!m) continue;
    rows[n.name] = [...box(m.clone().multiply(offsetMatrix(n.translation)), positions(n.mesh)), vis ? 1 : 0, "mesh",
                    (f[n.name] && f[n.name].col || "").toLowerCase()];
  }
  out[k] = rows;
}
process.stdout.write(JSON.stringify(out));
