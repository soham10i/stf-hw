// The CAD primitives of the 3D twin: a part from the export drawn with its material, and the
// parts that move - spindles, rollers, belt strips, the cookie and the mould.

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { VIEW } from "../coords";
import { ThreadedRod } from "./ThreadedRod";

import { PcbBoard, PreciseComp, ProfileBox } from "./FactoryDetail";

import { Suspense } from "react";


import { MM_TO_SCENE, PreciseMesh, usePrecise } from "./Precise";

import { type CadPart, type CadDoc, boxSize, cylSpec } from "../shared/model";
import { Drive, vgrHot } from "./hot";







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

function Mat({ part }: { part: CadPart }) {
  const metal = part.c === "#d6d9da" || part.c === "#aeb4b8";
  return (
    <meshStandardMaterial
      color={part.c}
      roughness={part.g === "workpiece" ? 0.45 : metal ? 0.3 : 0.62}
      metalness={metal ? 0.7 : 0.1}
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
      <meshStandardMaterial map={map} color="#c8ccd2" roughness={0.85} />
    </mesh>
  );
}

const BAND_MM = 10; // one texture band per 10 mm of belt

export function Solid({ part, drive, pitch, tex, drumD }: {
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
  if (/pcb/i.test(part.n) && part.k === "box")
    return <PcbBoard p={part.p} s={boxSize(part)} />;
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

/** The cookie: one 20 mm puck. z = its underside. Its colour can follow a hot
    object, so the same mesh shows raw dough and then the baked flavour. */

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
        <i style={{ background: col }} />{baked.length ? `${baked.length} baked · ${baked.join(" ")}` : "rack: raw dough only"}
      </span>
    </Html>
  );
}

/** A cookie. Raw dough is pale and matt; a BAKED one has its flavour colour with
    a faint glow, so it still reads deep in a mould. */
export function Cookie({
  x, y, z, colour = DOUGH, dynamic = false, hot,
}: {
  x: number; y: number; z: number; colour?: string; dynamic?: boolean;
  hot?: { colour: string };
}) {
  const r = 22.5 * MM;
  const mat = useRef<THREE.MeshStandardMaterial>(null);
  const paint = (c: string) => {
    if (!mat.current) return;
    const baked = c.toLowerCase() !== DOUGH.toLowerCase();
    mat.current.color.set(c);
    mat.current.emissive.set(baked ? c : "#000000");
    mat.current.emissiveIntensity = baked ? 0.18 : 0;
  };
  useFrame(() => {
    if (hot) paint(hot.colour);
    else if (dynamic) paint(vgrHot.cupColour);
  });
  useEffect(() => { if (!hot && !dynamic) paint(colour); });
  return (
    <group position={v(x, y, z)}>
      <mesh position={[0, 10 * MM, 0]} castShadow>
        <cylinderGeometry args={[r, r, 20 * MM, 32]} />
        <meshStandardMaterial ref={mat} color={colour} roughness={0.5} />
      </mesh>
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

/** The ridged belt texture, shared by every belt. */
export function useBeltTexture() {
  return useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 8;
    c.height = 16;
    const g = c.getContext("2d")!;
    g.fillStyle = "#4a4f57";
    g.fillRect(0, 0, 8, 16);
    g.fillStyle = "#23272c";
    g.fillRect(0, 0, 8, 5);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
  }, []);
}
