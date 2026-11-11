/**
 * STF v2 — the tunnel-oven line, design preview.
 *
 * A fully self-contained scene (no shared app code): it visualizes the P1 blueprint
 * (STF-2 tunnel oven design) — HBW feed, feed pusher, 3-zone tunnel, flip chute,
 * sort line and empty-carrier buffer — as an animated loop. World coordinates are the
 * factory frame millimetres of packages/stf_layout/factory.layout.yaml so the preview can be
 * diffed against the future layout file.
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import "./v2.css";

// ---------------------------------------------------------------------------
// Blueprint constants (CALIBRATE items from the blueprint; sim seconds)
// ---------------------------------------------------------------------------
const PITCH_S = 5; // one carrier enters every 5 s
const SEG = { hbw: 4.0, pusher: 1.5, tunnel: 15.0, flip: 1.2, sort: 3.5, buffer: 2.0, gap: 1.0 };
const CYCLE_S =
  SEG.hbw + SEG.pusher + SEG.tunnel + SEG.flip + SEG.sort + SEG.buffer + SEG.gap;
const SEG_START = [0, SEG.hbw, SEG.hbw + SEG.pusher, SEG.hbw + SEG.pusher + SEG.tunnel,
  SEG.hbw + SEG.pusher + SEG.tunnel + SEG.flip,
  SEG.hbw + SEG.pusher + SEG.tunnel + SEG.flip + SEG.sort];
const POOL = Math.ceil(CYCLE_S / PITCH_S); // carriers in flight
const ZONES = [
  { name: "Z1 ramp", minX: 560, maxX: 660, temp: 180 },
  { name: "Z2 soak", minX: 660, maxX: 760, temp: 220 },
  { name: "Z3 finish", minX: 760, maxX: 860, temp: 200 },
];
const RAW = new THREE.Color("#e8dcc0"); // dough
const BAKED = new THREE.Color("#c98a3d"); // finished cookie

// factory frame (mm): x along the belts, z = factory -y (depth), y = up
const P = {
  hbwStart: new THREE.Vector3(400, 0, -110),
  hbwEnd: new THREE.Vector3(500, 0, -110),
  tunnelIn: new THREE.Vector3(545, 0, -215),
  tunnelOut: new THREE.Vector3(835, 0, -215),
  sortStart: new THREE.Vector3(845, 0, -265),
  sortEnd: new THREE.Vector3(895, 0, -265),
  buffer: new THREE.Vector3(640, 0, -290),
  gate: new THREE.Vector3(810, 0, -215), // back-pressure hold point before the exit
};

// ---------------------------------------------------------------------------
// Renderer / scene
// ---------------------------------------------------------------------------
const root = document.getElementById("v2-root")!;
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
root.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = null;

const center = new THREE.Vector3(630, 0, -205);
const camera = new THREE.PerspectiveCamera(42, 1, 1, 4000);
const CAM_HOME = new THREE.Vector3(330, 430, 330).add(center);
camera.position.copy(CAM_HOME);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.copy(center);
controls.maxPolarAngle = Math.PI * 0.49;
controls.enableDamping = true;

scene.add(new THREE.AmbientLight("#8fa3c0", 0.55));
const key = new THREE.DirectionalLight("#fff4e0", 2.2);
key.position.set(center.x - 300, 700, center.z - 200);
key.castShadow = true;
key.shadow.camera.left = -600;
key.shadow.camera.right = 600;
key.shadow.camera.top = 600;
key.shadow.camera.bottom = -600;
key.shadow.mapSize.set(2048, 2048);
scene.add(key);
const rim = new THREE.DirectionalLight("#4f7cff", 0.8);
rim.position.set(center.x + 400, 300, center.z + 400);
scene.add(rim);

const resize = () => {
  const w = root.clientWidth || window.innerWidth;
  const h = root.clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
};
window.addEventListener("resize", resize);

// ---------------------------------------------------------------------------
// World helpers
// ---------------------------------------------------------------------------
const mat = (color: string, opts: THREE.MeshStandardMaterialParameters = {}) =>
  new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0.15, ...opts });

function box(
  size: [number, number, number],
  pos: THREE.Vector3,
  material: THREE.Material,
  parent: THREE.Object3D = scene,
): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  m.position.copy(pos);
  m.castShadow = true;
  m.receiveShadow = true;
  parent.add(m);
  return m;
}

const floor = new THREE.Mesh(
  new THREE.BoxGeometry(760, 10, 460),
  mat("#141a24", { roughness: 0.95 }),
);
floor.position.set(620, -6, -190);
floor.receiveShadow = true;
scene.add(floor);

// HBW rack (3x3 bays; C-column = empty-carrier magazine) and its front belt
const rack = new THREE.Group();
scene.add(rack);
for (let i = 0; i < 9; i++) {
  const col = Math.floor(i / 3);
  const row = i % 3;
  const bay = box(
    [76, 10, 46],
    new THREE.Vector3(120 + col * 84, 40 + row * 54, 20),
    col === 2 ? mat("#2a3550") : mat("#233047"),
    rack,
  );
  bay.castShadow = false;
}
box([280, 8, 10], new THREE.Vector3(210, 12, -2), mat("#1b2436"), rack); // rack frame
box(
  [130, 5, 40],
  new THREE.Vector3((400 + 525) / 2, 2.5, -110),
  mat("#1f6f5f", { roughness: 0.6 }),
); // HBW belt
// carriers staged on the belt are the moving pool; the rack is scenery

// VGR tower — now the exception handler (idle sweep only)
const vgr = new THREE.Group();
vgr.position.set(600, 0, -110);
scene.add(vgr);
const baseCyl = new THREE.Mesh(new THREE.CylinderGeometry(26, 30, 10, 32), mat("#3a4a6b"));
baseCyl.position.y = 5;
baseCyl.castShadow = true;
vgr.add(baseCyl);
box([14, 150, 14], new THREE.Vector3(0, 80, 0), mat("#46587e"), vgr);
const arm = new THREE.Group();
arm.position.y = 150;
vgr.add(arm);
box([95, 10, 12], new THREE.Vector3(-47.5, 0, 0), mat("#5a70a0"), arm);
const cup = new THREE.Mesh(new THREE.CylinderGeometry(9, 9, 6, 20), mat("#7f95c4"));
cup.position.set(-95, -6, 0);
arm.add(cup);

// Feed pusher paddle (fixed axis)
const paddle = box([40, 6, 34], new THREE.Vector3(505, 3, -110), mat("#c46a2a"));
// tunnel: floor heaters (one emissive slab per zone) + transparent shell
const zoneMeshes: THREE.Mesh[] = [];
for (const z of ZONES) {
  const slab = box(
    [z.maxX - z.minX - 6, 4, 44],
    new THREE.Vector3((z.minX + z.maxX) / 2, 2, -215),
    mat("#20242c", { emissive: new THREE.Color("#ff5a1f"), emissiveIntensity: 0.12 }),
  );
  zoneMeshes.push(slab);
}
box(
  [310, 4, 50],
  new THREE.Vector3(710, 4, -215),
  mat("#2b3140", { roughness: 0.5 }),
); // tunnel belt
const shell = new THREE.Mesh(
  new THREE.BoxGeometry(310, 70, 64),
  new THREE.MeshStandardMaterial({
    color: "#9fb4d8",
    transparent: true,
    opacity: 0.08,
    roughness: 0.2,
    metalness: 0.4,
    depthWrite: false,
  }),
);
shell.position.set(710, 42, -215);
scene.add(shell);
box([310, 6, 64], new THREE.Vector3(710, 80, -215), mat("#39445c")); // tunnel roof
// exit gate light (back-pressure signal)
const gateLight = new THREE.Mesh(
  new THREE.SphereGeometry(6, 16, 12),
  mat("#233047", { emissive: new THREE.Color("#37e08b"), emissiveIntensity: 1.2 }),
);
gateLight.position.set(P.gate.x + 16, 18, -215);
scene.add(gateLight);
// flip chute ramp + sort belt + reject bin + buffer
const chute = box([46, 4, 60], new THREE.Vector3(842, 8, -240), mat("#3d4b66"));
chute.rotation.z = -0.35;
box(
  [130, 5, 40],
  new THREE.Vector3((800 + 930) / 2, 2.5, -265),
  mat("#1f6f5f", { roughness: 0.6 }),
); // sort belt
box([30, 26, 30], new THREE.Vector3(920, 13, -265), mat("#5c2f2f")); // reject bin
for (let i = 0; i < 3; i++) {
  box([90, 2, 14], new THREE.Vector3(640, 2 + i * 8, -290), mat("#2c3850"));
} // buffer rails

// ---------------------------------------------------------------------------
// Carriers (pool). Local clock `t` walks the segment list; the cookie separates
// at the flip and rides the sort line while the empty carrier takes a buffer slot.
// ---------------------------------------------------------------------------
interface Slot { carrier: Carrier | null }
const slots: Slot[] = [{ carrier: null }, { carrier: null }, { carrier: null }];
const slotPos = (i: number) =>
  new THREE.Vector3(P.buffer.x, 6 + i * 8, P.buffer.z);

let cookiesDone = 0;

class Carrier {
  group = new THREE.Group();
  tray: THREE.Mesh;
  cookie: THREE.Mesh;
  t: number; // local clock, seconds
  prevSeg = -1;
  holding = false;
  slot: Slot | null = null;

  constructor(stagger: number) {
    this.t = stagger;
    this.tray = new THREE.Mesh(new THREE.BoxGeometry(84, 6, 52), mat("#4c5f88"));
    this.tray.position.y = 3;
    this.tray.castShadow = true;
    this.cookie = new THREE.Mesh(
      new THREE.CylinderGeometry(16, 16, 5, 24),
      mat("#e8dcc0", { roughness: 0.7 }),
    );
    this.cookie.position.y = 9;
    this.cookie.castShadow = true;
    this.group.add(this.tray, this.cookie);
    scene.add(this.group);
  }

  reset() {
    this.t = 0;
    this.prevSeg = -1;
    this.holding = false;
    if (this.slot) {
      this.slot.carrier = null;
      this.slot = null;
    }
    this.cookie.visible = true;
    (this.cookie.material as THREE.MeshStandardMaterial).color.copy(RAW);
  }

  /** Segment index from the local clock; handles the back-pressure hold. */
  segAt(tt: number): number {
    let acc = 0;
    const order = [SEG.hbw, SEG.pusher, SEG.tunnel, SEG.flip, SEG.sort, SEG.buffer];
    for (let i = 0; i < order.length; i++) {
      if (tt < acc + order[i]) return i;
      acc += order[i];
    }
    return order.length; // gap / respawn
  }

  update(dt: number, time: number) {
    if (this.holding && slots.some((sl) => !sl.carrier)) this.holding = false; // slot freed
    if (!this.holding) this.t += dt;
    const s = this.segAt(this.t);
    const local = this.t - SEG_START[s];

    if (s === 0) {
      const k = local / SEG.hbw;
      this.group.position.lerpVectors(P.hbwStart, P.hbwEnd, k);
    } else if (s === 1) {
      const k = local / SEG.pusher;
      this.group.position.lerpVectors(P.hbwEnd, P.tunnelIn, k);
    } else if (s === 2) {
      const k = Math.min(local / SEG.tunnel, 1);
      const x = THREE.MathUtils.lerp(P.tunnelIn.x, P.tunnelOut.x, k);
      this.group.position.set(x, 6, P.tunnelIn.z);
      // bake: colour progresses through the tunnel; hold at the gate when the buffer is full
      if (x >= P.gate.x && !this.slot && slots.every((sl) => sl.carrier)) {
        this.holding = true;
        this.group.position.x = P.gate.x;
      }
      (this.cookie.material as THREE.MeshStandardMaterial).color.lerpColors(
        RAW,
        BAKED,
        k,
      );
    } else if (s === 3) {
      const k = local / SEG.flip;
      this.group.position.copy(P.tunnelOut); // carrier waits at the exit while the cookie tips over
      if (k >= 1 && !this.slot) {
        const free = slots.find((sl) => !sl.carrier) ?? null;
        if (free) {
          free.carrier = this;
          this.slot = free;
        }
      }
      // cookie tips onto the sort line during the flip
      this.cookie.position.lerpVectors(
        new THREE.Vector3(0, 9, 0),
        new THREE.Vector3(6, 9, -50),
        k,
      );
    } else if (s === 4) {
      const k = local / SEG.sort;
      this.group.position.set(P.tunnelOut.x, 6, P.tunnelIn.z); // parked at the exit
      this.cookie.position.lerpVectors(
        new THREE.Vector3(6, 9, -50),
        new THREE.Vector3(6 + (P.sortEnd.x - P.sortStart.x) * k, 9, -50),
        1,
      );
    } else if (s === 5) {
      const k = local / SEG.buffer;
      const i = slots.indexOf(this.slot ?? { carrier: null });
      this.group.position.lerpVectors(
        this.group.position,
        slotPos(Math.max(i, 0)),
        k,
      );
    } else {
      this.reset(); // gap: respawn on the HBW belt with fresh dough
      return;
    }

    if (s !== this.prevSeg) {
      if (s === 4) this.cookie.visible = true;
      if (this.prevSeg === 4 && s === 5) {
        this.cookie.visible = false;
        cookiesDone += 1;
      }
      this.prevSeg = s;
    }

    // pusher follows the carrier during its push
    if (s === 1) paddle.position.lerpVectors(
      new THREE.Vector3(505, 3, -110),
      new THREE.Vector3(540, 3, -205),
      local / SEG.pusher,
    );
    else paddle.position.set(505, 3, -110);

    // zone glow: a slab heats up while a carrier is inside its span
    for (let i = 0; i < ZONES.length; i++) {
      const z = ZONES[i];
      const inside =
        this.group.position.z === P.tunnelIn.z &&
        this.group.position.x > z.minX &&
        this.group.position.x < z.maxX;
      const target = inside ? 0.9 + 0.25 * Math.sin(time * 6) : 0.12;
      const m = zoneMeshes[i].material as THREE.MeshStandardMaterial;
      m.emissiveIntensity += (target - m.emissiveIntensity) * Math.min(dt * 8, 1);
    }
  }
}

const carriers = Array.from({ length: POOL }, (_, i) => new Carrier(i * PITCH_S));

// ---------------------------------------------------------------------------
// Overlay (DOM, updated per frame)
// ---------------------------------------------------------------------------
const el = (id: string) => document.getElementById(id)!;
const chips = ZONES.map((_, i) => el(`zone-${i}`));
let running = true;
let speed = Number((el("sel-speed") as HTMLSelectElement).value);
el("btn-play").addEventListener("click", () => {
  running = !running;
  el("btn-play").textContent = running ? "Pause" : "Play";
});
const resetCam = () => {
  camera.position.copy(CAM_HOME);
  controls.target.copy(center);
};
el("btn-cam").addEventListener("click", resetCam);
document.getElementById("v2-dock-cam")?.addEventListener("click", resetCam);

const themeBtn = document.getElementById("v2-theme-btn");
if (themeBtn) {
  themeBtn.addEventListener("click", () => {
    const isLight = document.documentElement.dataset.theme === "light";
    document.documentElement.dataset.theme = isLight ? "dark" : "light";
  });
}
el("sel-speed").addEventListener("change", (e) => {
  speed = Number((e.target as HTMLSelectElement).value);
});

let simTime = 0;
let last = performance.now();
let uiTick = 0;

function frame(now: number) {
  requestAnimationFrame(frame);
  const dt = Math.min((now - last) / 1000, 0.1) * speed;
  last = now;
  if (running) simTime += dt;

  // arm idles between its two exception stations (belt end and buffer)
  const sweep = (Math.sin(simTime * 0.35) * 0.5 + 0.5) * THREE.MathUtils.degToRad(105);
  arm.rotation.y = -sweep;

  for (const c of carriers) if (running) c.update(dt, simTime);

  const holding = carriers.some((c) => c.holding);
  const gm = gateLight.material as THREE.MeshStandardMaterial;
  gm.emissive.set(holding ? "#ff4040" : "#37e08b");

  if (++uiTick % 12 === 0) {
    ZONES.forEach((z, i) => {
      const drift = Math.sin(simTime * 0.8 + i * 2.1) * 2;
      chips[i].textContent = `${z.name} · ${(z.temp + drift).toFixed(0)} °C`;
    });
    el("wip").textContent = String(carriers.filter((c) => c.segAt(c.t) !== 6).length);
    el("done").textContent = String(cookiesDone);
    el("pitch").textContent = `${PITCH_S.toFixed(1)} s`;
    el("backpressure").textContent = holding ? "buffer full — holding at Z3 exit" : "line flowing";
  }

  controls.update();
  renderer.render(scene, camera);
}
resize();
requestAnimationFrame(frame);
