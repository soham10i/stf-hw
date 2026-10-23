// The CAD primitives of the 3D twin: a part from the export drawn with its material, and the
// parts that move - spindles, rollers, belt strips, the cookie and the mould.

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { createContext, useContext, useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { VIEW } from "../coords";
import { ThreadedRod } from "./ThreadedRod";

import { DeviceModel, PcbBoard, PreciseComp, ProfileBox } from "./FactoryDetail";

import { Suspense } from "react";


import { MM_TO_SCENE, PreciseMesh, depthBias, useModuleName, usePrecise } from "./Precise";
import { Pickable } from "./electricPick";

import { type CadPart, type CadDoc, boxSize, cylSpec } from "../shared/model";
import { Trimmed, type Trim } from "./joints";
import type { Drive, Tint } from "./store/useCellStore";







export const MM = VIEW;
/** factory (x,y,z) mm -> three (x, z, y) scene units */
export const v = (x: number, y: number, z: number) =>
  new THREE.Vector3(x * MM, z * MM, y * MM);

/** rotation that aims a locally-+Y part along a factory axis */
export const AIM: Record<string, [number, number, number]> = {
  z: [0, 0, 0],            // factory +Z -> three +Y
  x: [0, 0, -Math.PI / 2], // factory +X -> three +X
  y: [Math.PI / 2, 0, 0],  // factory +Y -> three +Z
};

export function centreOf(part: CadPart) {
  const [px, py, pz] = part.p;
  if (part.k === "box") {
    const [dx, dy, dz] = boxSize(part);
    return v(px + dx / 2, py + dy / 2, pz + dz / 2);
  }
  const [axis, len] = cylSpec(part);
  const h = len / 2;
  return axis === "x" ? v(px + h, py, pz) : axis === "y" ? v(px, py + h, pz) : v(px, py, pz + h);
}

/** A part's volume in mm^3, for its depth bias (see depthBias in Precise.tsx). */
function volumeOf(part: CadPart) {
  if (part.k === "box") { const [dx, dy, dz] = boxSize(part); return dx * dy * dz; }
  const [, len, dia] = cylSpec(part);
  return Math.PI * (dia / 2) ** 2 * len;
}

function Mat({ part }: { part: CadPart }) {
  const metal = part.c === "#d6d9da" || part.c === "#aeb4b8";
  // guide rods, piston rods and shafts are ground, hardened steel: polished, fully metallic
  const ground = metal && part.k === "cyl" && /rod|shaft|spindle/.test(part.n);
  return (
    <meshStandardMaterial
      color={ground ? "#d3d8de" : part.c}
      roughness={part.g === "workpiece" ? 0.45 : ground ? 0.12 : metal ? 0.3 : 0.62}
      metalness={ground ? 1 : metal ? 0.7 : 0.1}
      {...depthBias(volumeOf(part))}
    />
  );
}

/** A spindle: real 4 mm lead, turning at exactly translation / pitch. */
function Spindle({ part, drive, pitch }: { part: CadPart; drive: React.MutableRefObject<Drive>; pitch: number }) {
  const spin = useRef<THREE.Group>(null);
  const [axis, len, dia] = cylSpec(part);
  const joint = part.mech.split(":")[1] as keyof Drive;
  useFrame(() => {
    // `?? 0`: a spindle whose joint the drive does not carry used to get NaN,
    // and three.js silently stops drawing an object with a NaN transform - which
    // is how the VGR's plunge spindle and spring stem went invisible.
    if (spin.current) spin.current.rotation.y = ((drive.current[joint] ?? 0) / pitch) * Math.PI * 2;
  });
  return (
    <group position={centreOf(part)} rotation={AIM[axis]}>
      <group ref={spin}>
        <ThreadedRod length={len * MM} radius={(dia / 2) * MM} color={part.c} />
      </group>
    </group>
  );
}

/** A drum or gear driven by the belt: one turn per pi*D of belt travel. */
function Roller({ part, drive, drumD, precise }: {
  part: CadPart; drive: React.MutableRefObject<Drive>; drumD?: number; precise?: THREE.Mesh[];
}) {
  const spin = useRef<THREE.Group>(null);
  // a precise mesh is in module mm: undo the roller's own placement so it
  // spins about the part's axis and sits exactly on its box
  const inner = useMemo(() => {
    if (!precise) return null;
    const [ax] = cylSpec(part);
    const R = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(...AIM[ax]));
    const c = centreOf(part);
    return R.invert().multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z)).multiply(MM_TO_SCENE);
  }, [precise, part]);
  const [axis, len, dia] = cylSpec(part);
  // The drive pulleys sit on the drum's axle, so they turn at the DRUM's rate,
  // not at the rate their own diameter would give.
  const d0 = part.mech === "spin:belt_x" && drumD ? drumD : dia;
  useFrame(() => {
    if (spin.current) spin.current.rotation.y = (drive.current.belt / (Math.PI * d0)) * Math.PI * 2;
  });
  const r = (dia / 2) * MM;
  if (precise && inner)
    return (
      <group position={centreOf(part)} rotation={AIM[axis]}>
        <group ref={spin}><PreciseMesh meshes={precise} matrix={inner} /></group>
      </group>
    );
  return (
    <group position={centreOf(part)} rotation={AIM[axis]}>
      <group ref={spin}>
        <mesh castShadow>
          <cylinderGeometry args={[r, r, len * MM, 20]} />
          <Mat part={part} />
        </mesh>
        {/* A key on each END face, so the drum's rotation is readable without
            putting a bump on the running surface the workpiece rides. */}
        {[-1, 1].map((sgn) => (
          <mesh key={sgn} position={[0, (sgn * len * MM) / 2, r * 0.52]}>
            <boxGeometry args={[r * 0.3, 0.004, r * 0.86]} />
            <meshStandardMaterial color="#9aa2ab" metalness={0.4} roughness={0.5} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

/** A belt strip whose surface scrolls with the belt. */
function BeltStrip({
  part, drive, tex,
}: { part: CadPart; drive: React.MutableRefObject<Drive>; tex: THREE.Texture }) {
  const [dx, dy, dz] = boxSize(part);
  // "belt" runs along Y, "belt:z" is the vertical drive belt from the motor up
  // to the drum - same texture, different long axis.
  // a belt runs along its LONG horizontal side: the sorting line's runs along X
  const alongX = part.mech !== "belt:z" && dx > dy;
  const runLen = part.mech === "belt:z" ? dz : alongX ? dx : dy;
  const map = useMemo(() => {
    const t = tex.clone();
    // One band per BAND_MM of belt, so the ridges are at a fixed real spacing
    // whatever the length. Without this the whole strip is one band and the
    // belt reads as static.
    if (alongX) {
      t.rotation = Math.PI / 2;
      t.repeat.set(1, runLen / BAND_MM);
    } else t.repeat.set(1, runLen / BAND_MM);
    t.needsUpdate = true;
    return t;
  }, [tex, runLen, alongX]);
  // Offset moves the sample point, so it runs OPPOSITE the surface: negate it
  // and the ridges travel with the workpiece.
  useFrame(() => {
    map.offset.y = (alongX ? 1 : -1) * drive.current.belt / BAND_MM;
  });
  return (
    <mesh position={centreOf(part)} castShadow receiveShadow>
      <boxGeometry args={[dx * MM, dz * MM, dy * MM]} />
      <meshStandardMaterial map={map} roughness={0.85} />
    </mesh>
  );
}

const BAND_MM = 10; // one texture band per 10 mm of belt

/** The trims of the parts drawn below (scene/joints.ts), by part name; each module provides its own. */
export const TrimsCtx = createContext<Map<string, Trim[]> | null>(null);

/** One exported part, drawn trimmed where it is slotted into another (scene/joints.ts). */
export function Solid(props: {
  part: CadPart; drive: React.MutableRefObject<Drive>; pitch: number; tex: THREE.Texture;
  drumD?: number;
}) {
  const trims = useContext(TrimsCtx)?.get(props.part.n);
  const module = useModuleName();
  // an electrical part opens its sheet when clicked (electricPick.tsx)
  return (
    <Pickable cad={`${module}/${props.part.n}`}>
      {trims ? <Trimmed trims={trims}><SolidBody {...props} /></Trimmed> : <SolidBody {...props} />}
    </Pickable>
  );
}

function SolidBody({ part, drive, pitch, tex, drumD }: {
  part: CadPart; drive: React.MutableRefObject<Drive>; pitch: number; tex: THREE.Texture;
  drumD?: number;
}) {
  const precise = usePrecise(part.n);
  // module plates are replaced by the one continuous base (FactoryTable)
  if (part.g === "frame") return null;
  // the drive belt's box is its envelope for the checker; BeltLoop draws the loop
  if (part.mech === "belt:loop") return null;
  // a drag chain's envelope box is for the proofs; DragChain draws the chain
  if (part.mech.startsWith("chain:")) return null;
  // I/O parts are drawn as the precise FreeCAD component they are
  if (part.fit) return <Suspense fallback={null}><PreciseComp fit={part.fit} /></Suspense>;
  // the adapter PCB's own renderer (headers, relays, terminals) is richer than its CAD block
  // the adapter PCB: its precise model (devices.py), on its standoffs in the box the CAD reserves
  if (/pcb/i.test(part.n) && part.k === "box")
    return <DeviceModel comp="adaptor_pcb" p={part.p} s={boxSize(part)} lift={5} fallback={<PcbBoard p={part.p} s={boxSize(part)} />} />;
  // Upgrade 1: the exact CAD shape (web_precise.py), where one was exported
  if (precise) {
    if (part.mech === "pulley" || part.mech.startsWith("spin:"))
      return <Roller part={part} drive={drive} drumD={drumD} precise={precise} />;
    return <PreciseMesh meshes={precise} />;
  }
  if (/pcb/i.test(part.n) && part.k === "box")
    return <PcbBoard p={part.p} s={boxSize(part)} />;
  if (part.mech.startsWith("thread:")) return <Spindle part={part} drive={drive} pitch={pitch} />;
  if (part.mech === "pulley" || part.mech.startsWith("spin:")) return <Roller part={part} drive={drive} drumD={drumD} />;
  if (part.mech.startsWith("belt")) return <BeltStrip part={part} drive={drive} tex={tex} />;
  if (part.k === "box" && /^profile(:20)?$/.test(part.mech))
    return <ProfileBox p={part.p as [number, number, number]} s={boxSize(part)} />;

  if (part.k === "box") {
    const [dx, dy, dz] = boxSize(part);
    return (
      <mesh position={centreOf(part)} castShadow receiveShadow>
        <boxGeometry args={[dx * MM, dz * MM, dy * MM]} />
        <Mat part={part} />
      </mesh>
    );
  }
  const [axis, len, dia] = cylSpec(part);
  return (
    <mesh position={centreOf(part)} rotation={AIM[axis]} castShadow receiveShadow>
      <cylinderGeometry args={[(dia / 2) * MM, (dia / 2) * MM, len * MM, 24]} />
      <Mat part={part} />
    </mesh>
  );
}

/** The cookie: 45 mm across, 20 mm high, its top a dome - the "shallow dome" the vision models
    were trained on (stf-cad/hbw/vision/render.py shades the cookie 1 - k d^2 from its centre).
    Under the hood's even ring light a surface's brightness is the cosine of its slope, so the
    dome is the profile whose cosine is that shading, k = 0.3 (the least the trained models read
    as a whole, good cookie: a flat top they call chipped): 16.6 mm of dome on a 3.4 mm wall.
    z = its underside. */
const COOKIE_R = 22.5, COOKIE_H = 20, DOME_K = 0.3;
const DOME_GEO = (() => {
  const n = 24, prof: THREE.Vector2[] = [];
  // the dome's height below its crown at d = r / R, from its slope: tan = sqrt(1 - c^2) / c
  const slope = (d: number) => { const c = (1 - DOME_K * d * d) ** 2.2; return Math.sqrt(1 - c * c) / c; };
  const drop = [0];
  for (let i = 1; i <= n; i++) {
    const a = (i - 1) / n, b = i / n;
    drop.push(drop[i - 1] + ((slope(a) + slope(b)) / 2) * (b - a) * COOKIE_R);
  }
  for (let i = 0; i <= n; i++) prof.push(new THREE.Vector2((i / n) * COOKIE_R * MM, (COOKIE_H - drop[i]) * MM));
  // from the rim up to the crown, so the faces look outward; the wall is a mesh of its own, so
  // the rim's normals are the dome's, not averaged with the wall's (that drew a dark ring)
  return new THREE.LatheGeometry(prof.reverse(), 48);
})();
const WALL_H = 20 - (() => {
  let d = 0;
  const slope = (x: number) => { const c = (1 - DOME_K * x * x) ** 2.2; return Math.sqrt(1 - c * c) / c; };
  for (let i = 1; i <= 24; i++) d += ((slope((i - 1) / 24) + slope(i / 24)) / 2) * (COOKIE_R / 24);
  return d;
})();
const WALL_GEO = new THREE.CylinderGeometry(COOKIE_R * MM, COOKIE_R * MM, WALL_H * MM, 48).translate(0, (WALL_H / 2) * MM, 0);

const DOUGH = "#D8B98C";

/** A constant-size badge over the rack: which slots hold a baked cookie. The
    cookies themselves are a few pixels wide from across the table. */
export function RackBadge({ doc, rack, raw }: { doc: CadDoc; rack: Record<string, string | null>; raw: string }) {
  const baked = Object.entries(rack).filter(([, c]) => c && c.toLowerCase() !== raw.toLowerCase()).map(([q]) => q).sort();
  const pos = useMemo(() => {
    const ps = Object.values(doc.slots);
    const cx = ps.reduce((a, p) => a + p[0], 0) / ps.length, cy = ps.reduce((a, p) => a + p[1], 0) / ps.length;
    const top = Math.max(...ps.map((p) => p[2]));
    return [cx * MM, (top + 150) * MM, cy * MM] as [number, number, number];
  }, [doc]);
  const col = baked.length ? rack[baked[0]]! : raw;
  return (
    <Html position={pos} center zIndexRange={[5, 0]}>
      <span className="zone-tag rack-badge" style={{ borderColor: col }}>
        <i style={{ background: col }} />{baked.length ? `${baked.length} baked · ${baked.join(" ")}` : "Rack: raw dough only"}
      </span>
    </Html>
  );
}

/** A cookie. Raw dough is pale and matt; a BAKED one has its flavour colour with
    a faint glow, so it still reads deep in a mould. A fixed `colour`, or a `tint`
    the coordinator rewrites in place every frame (copied, never parsed). */
/** A fault drawn on a cookie's dome (`fault` is read every frame: the travelling cookie's). */
export type Fault = { defect: string | null; seed: number };

/** The dome's texture for a fault, as the vision models were trained to see it (render.py):
    burnt - the rim darkened from 60-75 % of the radius out; cracked - a wavy dark line across the
    top, 1-2 px wide in the camera's 64 px image and 60-95 % of the radius long. The dome's UVs
    are polar: u goes round the axis, v from the rim (0) to the crown (1). Cached per fault. */
const FAULT_MAPS = new Map<string, THREE.Texture>();
function faultMap(defect: string, seed: number): THREE.Texture | null {
  if (defect !== "burnt" && defect !== "cracked") return null;
  const key = `${defect}:${seed}`;
  const hit = FAULT_MAPS.get(key);
  if (hit) return hit;
  let st = (seed * 2654435761) >>> 0;
  const rnd = () => { st = (st + 0x6d2b79f5) >>> 0; let t = Math.imul(st ^ (st >>> 15), st | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const u = (a: number, b: number) => a + (b - a) * rnd();
  const W = 512, H = 128, RPX = 18; // the cookie's radius in the camera's 64 px image
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const g = c.getContext("2d")!;
  const img = g.createImageData(W, H);
  const rimAt = u(0.6, 0.75);
  const rot = u(0, 2 * Math.PI), ax = Math.cos(rot), ay = Math.sin(rot);
  const f = u(0.4, 0.8), ph = u(0, 6), w = u(0.8, 1.6), len = RPX * u(0.6, 0.95), k = u(0.25, 0.45);
  for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) {
    // the texture is flipped onto the mesh: canvas row 0 lands on v = 1, the crown - so the radius
    // d (0 at the crown, 1 at the rim) grows with the row
    const d = (j + 0.5) / H, th = ((i + 0.5) / W) * 2 * Math.PI;
    let m = 1;
    if (defect === "burnt") m = 1 - 0.7 * Math.min(1, Math.max(0, (d - rimAt) / 0.3));
    else {
      const x = d * RPX * Math.cos(th), y = d * RPX * Math.sin(th);
      const along = x * ax + y * ay, across = -x * ay + y * ax;
      if (Math.abs(across - 1.6 * Math.sin(along * f + ph)) < w && Math.abs(along) < len) m = k;
    }
    const o = (j * W + i) * 4;
    img.data[o] = img.data[o + 1] = img.data[o + 2] = Math.round(255 * m); img.data[o + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  FAULT_MAPS.set(key, t);
  return t;
}

export function Cookie({
  x, y, z, colour = DOUGH, tint, fault,
}: {
  x: number; y: number; z: number; colour?: string; tint?: Tint; fault?: Fault;
}) {
  // baked dough is matte: no glare back into the inspection camera's lens
  const material = useMemo(() => new THREE.MeshPhysicalMaterial({ roughness: 0.9, specularIntensity: 0 }), []);
  // the wall keeps its colour without the dome's fault texture
  const wall = useMemo(() => new THREE.MeshPhysicalMaterial({ roughness: 0.9, specularIntensity: 0 }), []);
  useEffect(() => () => { material.dispose(); wall.dispose(); }, [material, wall]);
  const mat = useRef(material);
  const shown = useRef("");
  useFrame(() => {
    if (!tint || !mat.current) return;
    mat.current.color.copy(tint.color);
    if (tint.baked) mat.current.emissive.copy(tint.color);
    else mat.current.emissive.setRGB(0, 0, 0);
    mat.current.emissiveIntensity = tint.baked ? 0.18 : 0;
    wall.color.copy(mat.current.color); wall.emissive.copy(mat.current.emissive); wall.emissiveIntensity = mat.current.emissiveIntensity;
    // a fault shows once the cookie is baked
    const want = fault?.defect && tint.baked ? `${fault.defect}:${fault.seed}` : "";
    if (want !== shown.current) {
      shown.current = want;
      mat.current.map = want ? faultMap(fault!.defect!, fault!.seed) : null;
      mat.current.needsUpdate = true;
    }
  });
  useEffect(() => {
    if (tint || !mat.current) return;
    const baked = colour.toLowerCase() !== DOUGH.toLowerCase();
    mat.current.color.set(colour);
    mat.current.emissive.set(baked ? colour : "#000000");
    mat.current.emissiveIntensity = baked ? 0.18 : 0;
  });
  return (
    <group position={v(x, y, z)}>
      <mesh geometry={DOME_GEO} material={material} castShadow />
      <mesh geometry={WALL_GEO} material={tint ? wall : material} castShadow />
    </group>
  );
}
/** The mould (Werkstuecktraeger): base + four rim bars, matching the model.
    x,y = its centre; z = its underside (the face the fork lifts). */
export function Mould({ x, y, z, doc }: { x: number; y: number; z: number; doc: CadDoc }) {
  const [mw, md, mb] = doc.moulds.size;
  const rt = 5, rh = doc.moulds.rim_h;
  const bar = (w: number, d: number, ox: number, oy: number) => (
    <mesh position={v(ox, oy, z + mb + rh / 2)} castShadow receiveShadow>
      <boxGeometry args={[w * MM, rh * MM, d * MM]} />
      <meshStandardMaterial color="#9aa3ac" metalness={0.5} roughness={0.42} />
    </mesh>
  );
  return (
    <group>
      <mesh position={v(x, y, z + mb / 2)} castShadow receiveShadow>
        <boxGeometry args={[mw * MM, mb * MM, md * MM]} />
        <meshStandardMaterial color="#9aa3ac" metalness={0.5} roughness={0.42} />
      </mesh>
      {bar(rt, md, x - mw / 2 + rt / 2, y)}
      {bar(rt, md, x + mw / 2 - rt / 2, y)}
      {bar(mw - 2 * rt, rt, x, y - md / 2 + rt / 2)}
      {bar(mw - 2 * rt, rt, x, y + md / 2 - rt / 2)}
    </group>
  );
}

/** The ridged belt texture, shared by every belt: the CAD's black rubber (detail_rich.RUBBER,
    #1f2023 - also the belt the vision models were trained on, render.py BELT) with its lateral
    ribs a shade lighter, so a running belt is seen to move. */
export function useBeltTexture() {
  return useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 8;
    c.height = 16;
    const g = c.getContext("2d")!;
    g.fillStyle = "#1f2023";
    g.fillRect(0, 0, 8, 16);
    g.fillStyle = "#33353a";
    g.fillRect(0, 0, 8, 5);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
  }, []);
}
