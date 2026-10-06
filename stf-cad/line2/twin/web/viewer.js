// DT-2 web viewer: the DT-1 GLB, moved by player.js from motion/timeline.json (the rules the gate proves).
// Serve stf-cad/line2 over HTTP (python3 -m http.server 8300) and open http://localhost:8300/twin/web/
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Timeline, offsetMatrix } from "./player.js";

const $ = (id) => document.getElementById(id);
const view = $("view");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
view.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
scene.background = new THREE.Color(dark ? 0x15191f : 0xe9ecef);
scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 2.2);
sun.position.set(-2, 4, 3);
scene.add(sun);
const camera = new THREE.PerspectiveCamera(40, innerWidth / innerHeight, 0.01, 50);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight);
});

const [gltf, tlJson] = await Promise.all([
  new GLTFLoader().loadAsync("../out/stf2.glb"),
  fetch("../../motion/timeline.json").then((r) => r.json()),
]);
const tl = new Timeline(tlJson);
const root = gltf.scene.getObjectByName("STF2");            // scales mm -> m, Z-up -> Y-up: we work in mm inside it
scene.add(gltf.scene);

const nodes = {}, modules = {};
root.traverse((o) => {
  if (o.userData && o.userData["stf:module"]) {             // a part node (extras -> userData)
    nodes[o.name] = o;
    (modules[o.userData["stf:module"]] ||= []).push(o);
  }
});
// part nodes are driven by matrix: M(t, q) * T(offset)
const offset = {};
for (const [n, o] of Object.entries(nodes)) {
  offset[n] = offsetMatrix([o.position.x, o.position.y, o.position.z]);
  if (o.userData["stf:moving"]) o.matrixAutoUpdate = false;
}
// drawn cylinders: reshaped tracks (band cookies, rods) and spawned cookies - a unit cylinder, base 0, axis +z
const unit = new THREE.CylinderGeometry(0.5, 0.5, 1, 96).rotateX(Math.PI / 2).translate(0, 0, 0.5);
const cyl = {};
const f0 = tl.frame(0);
for (const name of Object.keys(f0)) {
  if (!tl.reshaped.has(name) && !tl.spawn[name]) continue;
  const col = tl.spawn[name] ? tl.spawn[name].colour : (f0[name].col || "#c68f4c");
  const m = new THREE.Mesh(unit, new THREE.MeshStandardMaterial({ color: col, roughness: 0.7 }));
  m.matrixAutoUpdate = false;
  root.add(m);
  cyl[name] = m;
  if (nodes[name]) nodes[name].visible = false;              // its CAD mesh is replaced, as in the FreeCAD player
}
// oven elements glow with their SSR
const glow = {};
for (const n of Object.keys(tl.glow)) {
  const o = nodes[n];
  if (!o) continue;
  o.traverse((c) => { if (c.isMesh) { c.material = c.material.clone(); glow[n] = c.material; } });
}

function apply(k) {
  const f = tl.frame(k);
  for (const [name, m] of Object.entries(cyl)) {
    const cm = tl.cylinderOf(name, f);
    m.matrix.copy(cm);
    m.visible = f[name].vis;
    if (f[name].col) m.material.color.set(f[name].col);
  }
  for (const [name, o] of Object.entries(nodes)) {
    if (!o.userData["stf:moving"] || cyl[name]) continue;
    let mm = null, vis = true;
    if (f[name] && f[name].kind === "rigid") { mm = f[name].m; vis = f[name].vis; }
    else if (!f[name]) mm = tl.followerMatrix(name, f);
    if (!mm) continue;
    o.matrix.copy(mm).multiply(offset[name]);
    o.matrixWorldNeedsUpdate = true;
    o.visible = vis;
  }
  for (const [name, mat] of Object.entries(glow)) {
    const c = f[name].col;
    mat.color.set(c);
    mat.emissive = new THREE.Color(tl.glow[name].bits[k] === "1" ? c : "#000000");
    mat.emissiveIntensity = 0.6;
  }
  panel(k);
}

// ----------------------------------------------------------------- UI
const zonesEl = $("zones");
const zoneT = (tlJson.zones || []).map((z) => z.T);
function panel(k) {
  $("time").textContent = `t = ${(k * tl.dt).toFixed(1)} s`;
  $("t").value = k;
  const p = tlJson.power?.[k];
  if (p) {
    const on = Object.values(tl.glow).filter((g) => g.bits[k] === "1").length;
    $("power").textContent = `${(p[0] / 1000).toFixed(2)} kW · ${on}/${Object.keys(tl.glow).length} elements on · ` +
      `L1 ${p[1].toFixed(1)} A  L2 ${p[2].toFixed(1)} A  L3 ${p[3].toFixed(1)} A`;
  }
  const y = tlJson.temps?.[k] || [];
  zonesEl.innerHTML = Object.entries(tlJson.duty || {}).sort().map(([z, d], i) =>
    `<div class="zone"><b>${z}</b><span class="duty"><i style="width:${(d * 100).toFixed(0)}%"></i></span>` +
    `<span>${(d * 100).toFixed(0)} %</span><span>${y[i] !== undefined ? y[i].toFixed(1) : "–"} °C</span></div>`).join("") +
    (zoneT.length ? `<div class="muted">duty · TC reading · set points ${zoneT.join(" / ")} °C</div>` : "");
  const ex = (tlJson.phases?.exchange || []).find(([, t0, d]) => k * tl.dt >= t0 && k * tl.dt < t0 + d);
  $("phase").textContent = ex ? `airlock: ${ex[0]}` : "";
}

let k = 0, t = 0, playing = true, last = performance.now();
$("play").onclick = () => { playing = !playing; $("play").textContent = playing ? "Pause" : "Play"; };
$("t").max = tl.n - 1;
$("t").oninput = (e) => { k = +e.target.value; t = k * tl.dt; apply(k); };
const guardNodes = modules["M10_safety"] || [];
$("guards").onchange = (e) => guardNodes.forEach((o) => { o.visible = e.target.checked; });
guardNodes.forEach((o) => { o.visible = false; });           // start with the enclosure off: the process is inside
$("mods").innerHTML = Object.keys(modules).filter((m) => m !== "M10_safety")
  .sort((a, b) => parseInt(a.slice(1)) - parseInt(b.slice(1)))
  .map((m) => `<label><input type="checkbox" data-m="${m}" checked> ${m} <span class="muted">(${modules[m].length})</span></label>`).join("");
$("mods").onchange = (e) => modules[e.target.dataset.m].forEach((o) => { o.visible = e.target.checked; });

const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
renderer.domElement.addEventListener("click", (e) => {
  ptr.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ptr, camera);
  const hit = ray.intersectObjects(scene.children, true).find((h) => h.object.visible);
  if (!hit) return;
  let o = hit.object;
  while (o && !(o.userData && o.userData["stf:module"])) o = o.parent;
  const name = o ? o.name : Object.keys(cyl).find((n) => cyl[n] === hit.object);
  const u = o ? o.userData : {};
  $("pick").innerHTML = name ? `<b>${name}</b><br>${u["stf:module"] || "cylinder drawn by the player"}` +
    `${u["stf:group"] ? " · " + u["stf:group"] : ""}${u["stf:tag"] ? "<br>tag <b>" + u["stf:tag"] + "</b>" : ""}` +
    `${u["stf:hw"] ? "<br>" + u["stf:hw"] : ""}${u["stf:moving"] ? "<br>moving" : ""}` : "";
});

// frame the line
const bb = new THREE.Box3().setFromObject(gltf.scene);
const c = bb.getCenter(new THREE.Vector3()), size = bb.getSize(new THREE.Vector3()).length();
camera.position.copy(c).add(new THREE.Vector3(-0.55, 0.55, 0.75).multiplyScalar(size));
controls.target.copy(c);
controls.update();

$("load").remove();
["side", "oven", "bar"].forEach((id) => { $(id).hidden = false; });
apply(0);
renderer.setAnimationLoop((now) => {
  const dtw = Math.min((now - last) / 1000, 0.1);
  last = now;
  if (playing) {
    t = (t + dtw * +$("speed").value) % (tl.n * tl.dt);
    const nk = Math.floor(t / tl.dt);
    if (nk !== k) { k = nk; apply(k); }
  }
  controls.update();
  renderer.render(scene, camera);
});
