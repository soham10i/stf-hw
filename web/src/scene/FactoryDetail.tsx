// Real-world detail for the complete setup, all driven by hbw_parts.json:
//
//  PreciseComp  - an I/O part drawn as the PRECISE FreeCAD component it is
//                 (components/<id>.glb, 0.01 mm tessellation), at real size,
//                 laid into the model part's envelope by the axis permutation
//                 stf-cad/hbw/wiring.py computed. Never stretched.
//  PcbBoard     - the 24 V adapter PCB of each module: ST1/ST2 to the model,
//                 ST3 34-pin to the PLC, terminals 1-30, relays R1-R8, V1-V4.
//  PlcCabinet   - PSU + RevPi Core + 3x DIO + AIO on a DIN rail, feed terminals.
//  Wiring       - one cable per I/O part to its PCB, and a 34-way ribbon from
//                 each PCB to the PLC, routed as wiring.py planned.
//
// Coordinates: parts are in their module frame, everything else in the factory
// frame, both in the stage's "factory-as-three" space v(x,y,z) = (x, z, y).

import { Html, useGLTF } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";
import { useContext } from "react";
import { MM_TO_SCENE, PreciseLibCtx, PreciseMesh } from "./Precise";
import { VIEW } from "../coords";
import { physical } from "../views/ComponentView";

const MM = VIEW;
const BASE = `${import.meta.env.BASE_URL}components/`;
const v = (x: number, y: number, z: number) => new THREE.Vector3(x * MM, z * MM, y * MM);

export interface Fit {
  comp: string; perm: [number, number, number]; sign: [number, number, number];
  centre: [number, number, number]; origin: [number, number, number];
}

/** Stage-space matrix for a component: component (Z-up metres, as in the glb
    under its root's -90 deg X turn) -> module mm -> stage. */
function fitMatrix(f: Fit) {
  const R = new THREE.Matrix4();
  const cols = [0, 1, 2].map((i) => {
    const e = new THREE.Vector3();
    e.setComponent(f.perm[i], f.sign[i]);
    return e;
  });
  R.makeBasis(cols[0], cols[1], cols[2]);
  // module mm -> stage (swap y/z, scale)
  const S = new THREE.Matrix4().set(MM, 0, 0, 0, 0, 0, MM, 0, 0, MM, 0, 0, 0, 0, 0, 1);
  const T = new THREE.Matrix4().makeTranslation(f.centre[0], f.centre[1], f.centre[2]);
  const To = new THREE.Matrix4().makeTranslation(-f.origin[0], -f.origin[1], -f.origin[2]);
  const K = new THREE.Matrix4().makeScale(1000, 1000, 1000);
  const unroot = new THREE.Matrix4().makeRotationX(Math.PI / 2);
  return S.multiply(T).multiply(R).multiply(To).multiply(K).multiply(unroot);
}

export function PreciseComp({ fit }: { fit: Fit }) {
  const { scene } = useGLTF(`${BASE}${fit.comp}.glb`);
  const obj = useMemo(() => {
    const o = scene.clone(true);
    o.traverse((c) => {
      const m = c as THREE.Mesh;
      if (!m.isMesh) return;
      const u = m.userData as { material?: string; colour?: string };
      m.material = physical(u.material ?? "abs", u.colour ?? "#888");
      m.castShadow = true;
      m.receiveShadow = true;
    });
    return o;
  }, [scene]);
  const mat = useMemo(() => fitMatrix(fit), [fit]);
  return (
    <group matrix={mat} matrixAutoUpdate={false}>
      <primitive object={obj} />
    </group>
  );
}

// ------------------------------------------------------------------- PCB

function B({ at, size, colour, metal = false }: {
  at: [number, number, number]; size: [number, number, number]; colour: string; metal?: boolean;
}) {
  return (
    <mesh position={v(at[0] + size[0] / 2, at[1] + size[1] / 2, at[2] + size[2] / 2)} castShadow receiveShadow>
      <boxGeometry args={[size[0] * MM, size[2] * MM, size[1] * MM]} />
      <meshStandardMaterial color={colour} roughness={metal ? 0.3 : 0.6} metalness={metal ? 0.8 : 0.05} />
    </mesh>
  );
}

/** An aluminium slot profile inside a part's box: the bar, a T-slot on each
    of its four long faces, black end caps. Drawn in the part's own frame. */
export function ProfileBox({ p, s }: { p: [number, number, number]; s: [number, number, number] }) {
  const L = s.indexOf(Math.max(...s));                 // the long axis
  const edge = Math.min(...s);
  const slot = edge >= 18 ? 6 : 5, dep = 0.6;
  const els: JSX.Element[] = [<B key="bar" at={p} size={s} colour="#cfd3d6" metal />];
  const others = [0, 1, 2].filter((i) => i !== L);
  let k = 0;
  for (const i of others) {
    const j = others.find((q) => q !== i)!;
    for (const side of [0, 1]) {
      const at = [...p] as [number, number, number], sz = [...s] as [number, number, number];
      sz[i] = dep; at[i] = side ? p[i] + s[i] - dep + 0.2 : p[i] - 0.2;
      sz[j] = slot; at[j] = p[j] + s[j] / 2 - slot / 2;
      els.push(<B key={`s${k++}`} at={at} size={sz} colour="#2e3236" />);
    }
  }
  for (const end of [0, 1]) {
    const at = [...p] as [number, number, number], sz = [...s] as [number, number, number];
    sz[L] = 1; at[L] = end ? p[L] + s[L] - 0.6 : p[L] - 0.4;
    els.push(<B key={`c${end}`} at={at} size={sz} colour="#16181a" />);
  }
  return <group>{els}</group>;
}

type UpPart = { n: string; g: string; k: string; p: [number, number, number]; s: unknown[]; c: string; mech: string };

/** Upgrade 1's own parts (central air station, cookie buffer), factory frame. */
export function UpgradeParts({ parts, module = "upgrade" }: { parts: UpPart[]; module?: string }) {
  const lib = useContext(PreciseLibCtx);
  return (
    <group>
      {parts.filter((q) => q.g !== "frame").map((q) => {
        // polycarbonate guard panels: clear, so the machine stays visible
        if (q.mech === "panel") {
          const s = q.s as [number, number, number];
          return (
            <mesh key={q.n} position={v(q.p[0] + s[0] / 2, q.p[1] + s[1] / 2, q.p[2] + s[2] / 2)} renderOrder={2}>
              <boxGeometry args={[s[0] * MM, s[2] * MM, s[1] * MM]} />
              <meshPhysicalMaterial color="#d6ecff" transparent opacity={q.n === "guard_roof" ? 0.06 : 0.14}
                roughness={0.08} metalness={0} depthWrite={false} />
            </mesh>
          );
        }
        const pm = lib?.get(`${module}:${q.n}`);
        if (pm) return <PreciseMesh key={q.n} meshes={pm} />;
        if (q.k === "box") {
          const s = q.s as [number, number, number];
          return /^profile(:\d+)?$/.test(q.mech)
            ? <ProfileBox key={q.n} p={q.p} s={s} />
            : <B key={q.n} at={q.p} size={s} colour={q.c} metal={q.c === "#d6d9da" || q.c === "#aeb4b8"} />;
        }
        const [ax, len, dia] = q.s as [string, number, number];
        const c = ax === "z" ? v(q.p[0], q.p[1], q.p[2] + len / 2)
          : ax === "x" ? v(q.p[0] + len / 2, q.p[1], q.p[2]) : v(q.p[0], q.p[1] + len / 2, q.p[2]);
        const rot: [number, number, number] = ax === "z" ? [0, 0, 0] : ax === "x" ? [0, 0, -Math.PI / 2] : [Math.PI / 2, 0, 0];
        const metal = q.c === "#aeb4b8" || q.c === "#d6d9da";
        return (
          <mesh key={q.n} position={c} rotation={rot} castShadow receiveShadow>
            <cylinderGeometry args={[(dia / 2) * MM, (dia / 2) * MM, len * MM, 32]} />
            <meshStandardMaterial color={q.c} roughness={metal ? 0.35 : 0.55} metalness={metal ? 0.45 : 0.05} />
          </mesh>
        );
      })}
    </group>
  );
}

/** Upgrade 2: every hazard zone (the swept envelope of a mechanism over its
    full joint range), translucent red, with its PLr. */
export function HazardZones({ hazards }: { hazards: { id: string; zone: number[] | null; PLr: string;
  cyl?: { centre: [number, number]; r: number; z: [number, number]; poly?: number[][] } }[] }) {
  const col: Record<string, string> = { a: "#fde68a", b: "#fbbf24", c: "#f97316", d: "#ef4444", e: "#b91c1c" };
  return (
    <group>
      {hazards.filter((h) => h.zone).map((h) => {
        const z = h.zone!;
        if (h.cyl?.poly) return <SweptPrism key={h.id} poly={h.cyl.poly} z={h.cyl.z} colour={col[h.PLr]} />;
        return (
          <mesh key={h.id} position={v((z[0] + z[3]) / 2, (z[1] + z[4]) / 2, (z[2] + z[5]) / 2)} renderOrder={3}>
            <boxGeometry args={[(z[3] - z[0]) * MM, (z[5] - z[2]) * MM, (z[4] - z[1]) * MM]} />
            <meshBasicMaterial color={col[h.PLr]} transparent opacity={0.2} depthWrite={false} />
          </mesh>
        );
      })}
    </group>
  );
}

/** A swept outline (factory mm polygon) extruded over z0..z1. */
function SweptPrism({ poly, z, colour }: { poly: number[][]; z: [number, number]; colour: string }) {
  const geo = useMemo(() => {
    const sh = new THREE.Shape(poly.map(([x, y]) => new THREE.Vector2(x, y)));
    const g = new THREE.ExtrudeGeometry(sh, { depth: z[1] - z[0], bevelEnabled: false, curveSegments: 1 });
    g.translate(0, 0, z[0]);
    return g;
  }, [poly, z]);
  return (
    <group matrix={MM_TO_SCENE} matrixAutoUpdate={false}>
      <mesh geometry={geo} renderOrder={3}>
        <meshBasicMaterial color={colour} transparent opacity={0.13} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

/** The adapter PCB, drawn inside the model part's envelope (its box). */
export function PcbBoard({ p, s }: { p: [number, number, number]; s: [number, number, number] }) {
  const alongX = s[0] >= s[1];
  const U = alongX ? s[0] : s[1], Wd = alongX ? s[1] : s[0];
  // local (u along the long side, w across, z up) -> module
  const at = (u: number, w: number, z: number): [number, number, number] =>
    alongX ? [p[0] + u, p[1] + w, p[2] + z] : [p[0] + w, p[1] + u, p[2] + z];
  const sz = (du: number, dw: number, dz: number): [number, number, number] => (alongX ? [du, dw, dz] : [dw, du, dz]);
  const bz = 5; // standoffs
  const els: JSX.Element[] = [];
  let k = 0;
  const add = (u: number, w: number, z: number, du: number, dw: number, dz: number, c: string, metal = false) =>
    els.push(<B key={k++} at={at(u, w, z)} size={sz(du, dw, dz)} colour={c} metal={metal} />);
  for (const [u, w] of [[4, 4], [U - 8, 4], [4, Wd - 8], [U - 8, Wd - 8]]) add(u, w, 0, 4, 4, bz, "#c9ced3", true);
  add(0, 0, bz, U, Wd, 1.6, "#1d6b3a");                               // FR4
  const top = bz + 1.6;
  add(8, Wd - 18, top, 44, 9, 9, "#17181b");                          // ST3: 17x2 to the PLC
  add(60, Wd - 18, top, 27, 9, 9, "#17181b");                         // ST1 to the model
  add(92, Wd - 18, top, 21, 9, 9, "#17181b");                         // ST2 to the model
  for (let i = 0; i < 30 && 4 + i * 5 < U - 4; i++) add(4 + i * 5, 4, top, 4.6, 12, 11, i % 2 ? "#9aa1a8" : "#b8bec4"); // terminals 1-30
  for (let i = 0; i < 8; i++) add(10 + i * 18, 26, top, 15, 10, 12, "#101113");                   // R1-R8
  for (let i = 0; i < 4; i++) add(U - 42 + i * 9, Wd - 34, top, 8, 8, 10, "#2d8a4e");            // V1-V4
  add(U / 2 - 10, 44, top, 20, 12, 3, "#1a1a1a");                     // driver ICs
  add(U / 2 + 16, 44, top, 14, 10, 3, "#1a1a1a");
  for (let i = 0; i < 4; i++) add(20 + i * 12, 46, top, 6, 6, 9, "#2a4a8c");                     // electrolytics
  return <group>{els}</group>;
}

// ------------------------------------------------------------------- PLC
export function PlcCabinet({ parts, at }: {
  parts: { n: string; p: [number, number, number]; s: [number, number, number]; c: string; g: string }[];
  at: [number, number];
}) {
  return (
    <group position={v(at[0], at[1], 0)}>
      {parts.filter((q) => q.g !== "frame").map((q) => (
        <group key={q.n}>
          <B at={q.p} size={q.s} colour={q.c} metal={q.n === "din_rail"} />
          {q.n.startsWith("revpi") && (() => {
            // front face is UP: two 14-pole spring plugs, the status LEDs
            const [x, y, z] = q.p, [dx, dy, dz] = q.s, t = z + dz;
            return (
              <>
                <B at={[x + 6, y + 3, t]} size={[36, dy - 6, 9]} colour="#2f8a4f" />
                <B at={[x + dx - 42, y + 3, t]} size={[36, dy - 6, 9]} colour="#2f8a4f" />
                {[0, 1, 2].map((i) => (
                  <B key={i} at={[x + dx / 2 - 6 + i * 5, y + dy / 2 - 1.5, t]} size={[3, 3, 1]}
                     colour={i === 0 ? "#39d353" : i === 1 ? "#f0b429" : "#39d353"} />
                ))}
              </>
            );
          })()}
          {q.n === "psu_wdr120" && (() => {
            const [x, y, z] = q.p, [dx, dy, dz] = q.s, t = z + dz;
            return <B at={[x + 8, y + 4, t]} size={[dx - 16, dy - 8, 6]} colour="#6b7178" />;
          })()}
        </group>
      ))}
    </group>
  );
}

// ---------------------------------------------------------------- wiring
function rounded(pts: THREE.Vector3[], r = 10) {
  // replace each corner with two points r mm either side: straight runs stay
  // straight and the wire bends round a radius, as a real one does
  const out: THREE.Vector3[] = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i].clone().sub(pts[i - 1]), b = pts[i + 1].clone().sub(pts[i]);
    const ra = Math.min(r, a.length() / 2), rb = Math.min(r, b.length() / 2);
    out.push(pts[i].clone().sub(a.normalize().multiplyScalar(ra)));
    out.push(pts[i].clone().add(b.normalize().multiplyScalar(rb)));
  }
  out.push(pts[pts.length - 1]);
  return out.filter((q, i) => i === 0 || q.distanceTo(out[i - 1]) > 0.01);
}

/** Shift a factory-mm polyline sideways by d (in plan), so the conductors of
    one cable lie side by side instead of on top of each other. */
function offsetPath(pts: number[][], d: number) {
  const P = pts.map((q) => new THREE.Vector3(q[0], q[1], q[2]));
  const n = P.map((_, i) => {
    // plan normal of the nearest horizontal segment
    for (const j of [i, i - 1, i + 1, i - 2, i + 2]) {
      const a = P[j], b = P[j + 1];
      if (!a || !b) continue;
      const h = new THREE.Vector2(b.x - a.x, b.y - a.y);
      if (h.length() > 0.5) return h.normalize();
    }
    return new THREE.Vector2(1, 0);
  });
  return P.map((p, i) => new THREE.Vector3(p.x - n[i].y * d, p.y + n[i].x * d, p.z));
}

const peTexture = (() => {
  let t: THREE.Texture | null = null;
  return () => {
    if (t) return t;
    const c = document.createElement("canvas");
    c.width = 8; c.height = 32;
    const g = c.getContext("2d")!;
    g.fillStyle = "#1f9d3a"; g.fillRect(0, 0, 8, 32);
    g.fillStyle = "#f2d02b"; g.fillRect(0, 0, 8, 12);
    t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
  };
})();

function Conductor({ pts, colour, radius, translucent = false }: {
  pts: THREE.Vector3[]; colour: string; radius: number; translucent?: boolean;
}) {
  const geo = useMemo(() => {
    const p = rounded(pts).map((q) => v(q.x, q.y, q.z));
    const curve = new THREE.CatmullRomCurve3(p, false, "centripetal", 0.2);
    return new THREE.TubeGeometry(curve, Math.max(24, p.length * 12), radius * MM, 8, false);
  }, [pts, radius]);
  const len = useMemo(() => pts.reduce((a, q, i) => (i ? a + q.distanceTo(pts[i - 1]) : 0), 0), [pts]);
  const map = useMemo(() => {
    if (colour !== "PE") return null;
    const t = peTexture().clone();
    t.repeat.set(len / 12, 1);   // one yellow band per 12 mm, like PE insulation
    t.needsUpdate = true;
    return t;
  }, [colour, len]);
  return (
    <mesh geometry={geo} castShadow>
      {map ? (
        <meshStandardMaterial map={map} roughness={0.5} />
      ) : (
        <meshPhysicalMaterial color={colour} roughness={translucent ? 0.15 : 0.45} clearcoat={0.4}
          transparent={translucent} opacity={translucent ? 0.7 : 1} />
      )}
    </mesh>
  );
}

/** A cable: its conductors laid side by side along one route. */
function Run({ points, conductors, roles, radius = 0.75, pitch = 1.8 }: {
  points: number[][]; conductors: string[]; roles: Record<string, { colour: string }>;
  radius?: number; pitch?: number;
}) {
  const paths = useMemo(
    () => conductors.map((_, i) => offsetPath(points, (i - (conductors.length - 1) / 2) * pitch)),
    [points, conductors, pitch],
  );
  return (
    <group>
      {paths.map((p, i) => <Conductor key={i} pts={p} colour={roles[conductors[i]]?.colour ?? "#999"} radius={radius} />)}
    </group>
  );
}

export interface WiringDoc {
  roles: Record<string, { colour: string; label: string }>;
  cables: { module: string; part: string; tag: string; conductors: string[]; points: number[][] }[];
  hoses: { module: string; from: string; to: string; points: number[][]; main?: boolean }[];
  bundles: { module: string; conductors: string[]; points: number[][] }[];
  power: { name: string; conductors: string[]; points: number[][] }[];
}

export function Wiring({ w }: { w: WiringDoc }) {
  const hoses = useMemo(() => w.hoses.map((h) => ({
    main: !!h.main, pts: h.points.map((q) => new THREE.Vector3(q[0], q[1], q[2])),
  })), [w]);
  return (
    <group>
      {w.cables.map((c) => <Run key={c.module + c.part} points={c.points} conductors={c.conductors} roles={w.roles} />)}
      {w.bundles.map((b) => <Run key={b.module} points={b.points} conductors={b.conductors} roles={w.roles} radius={0.8} pitch={1.9} />)}
      {w.power.map((p) => <Run key={p.name} points={p.points} conductors={p.conductors} roles={w.roles} radius={1.1} pitch={2.6} />)}
      {hoses.map((h, i) => <Conductor key={i} pts={h.pts} colour={w.roles.AIR.colour} radius={h.main ? 3 : 2} translucent />)}
    </group>
  );
}


// ------------------------------------------------------------------ U11
type Box6 = [number, number, number, number, number, number];
const ZC = { Z0: "#ef4444", Z1: "#3b82f6" };

/** Upgrade 11: the IEC 62443 zones drawn on the machine - a box per remote
 *  I/O node and the PLC cabinet (Z1, cell control), and the hardwired safety
 *  devices (Z0), which have no network interface. Factory frame, mm. */
export function SecurityOverlay({ io, plc, safety, ips }: {
  io: { n: string; p: [number, number, number]; s: unknown[] }[];
  plc: { at: [number, number]; parts: { n: string; p: [number, number, number]; s: [number, number, number] }[] };
  safety: { n: string; p: [number, number, number]; s: unknown[] }[];
  ips: Record<string, string>;
}) {
  const bound = (ps: { p: [number, number, number]; s: unknown[] }[], pad: number): Box6 => {
    const b: Box6 = [1e9, 1e9, 1e9, -1e9, -1e9, -1e9];
    for (const q of ps) {
      const s = q.s as number[];
      if (typeof s[0] !== "number") continue;
      for (let i = 0; i < 3; i++) { b[i] = Math.min(b[i], q.p[i]); b[i + 3] = Math.max(b[i + 3], q.p[i] + s[i]); }
    }
    return [b[0] - pad, b[1] - pad, Math.max(0, b[2] - pad), b[3] + pad, b[4] + pad, b[5] + pad];
  };
  const boxes: { key: string; b: Box6; col: string; label: string }[] = [];
  for (const m of ["hbw", "vgr", "oven", "sorting"]) {
    const ps = io.filter((q) => q.n.startsWith(`io_${m}_`));
    if (ps.length) boxes.push({ key: m, b: bound(ps, 14), col: ZC.Z1, label: `${m} node · ${ips[m] ?? ""}` });
  }
  const [ax, ay] = plc.at;
  const cab = bound(plc.parts.map((q) => ({ ...q, p: [q.p[0] + ax, q.p[1] + ay, Math.max(0, q.p[2])] as [number, number, number] })), 10);
  boxes.push({ key: "plc", b: cab, col: ZC.Z1, label: "PLC · 192.168.10.10" });
  for (const d of ["ES1", "ES2", "ES3", "S3"]) {
    const ps = safety.filter((q) => q.n.startsWith(`${d}_`));
    if (ps.length) boxes.push({ key: d, b: bound(ps, 10), col: ZC.Z0, label: d === "S3" ? "reset · hardwired" : `${d} · hardwired` });
  }
  return (
    <group>
      {boxes.map(({ key, b, col, label }) => {
        const size: [number, number, number] = [(b[3] - b[0]) * MM, (b[5] - b[2]) * MM, (b[4] - b[1]) * MM];
        const c = v((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, (b[2] + b[5]) / 2);
        return (
          <group key={key} position={c}>
            <mesh renderOrder={3}>
              <boxGeometry args={size} />
              <meshBasicMaterial color={col} transparent opacity={0.28} depthWrite={false} />
            </mesh>
            <lineSegments renderOrder={4}>
              <edgesGeometry args={[new THREE.BoxGeometry(...size)]} />
              <lineBasicMaterial color={col} />
            </lineSegments>
            <Html position={[0, size[1] / 2 + 0.12, 0]} center distanceFactor={16} zIndexRange={[4, 0]}>
              <span className="zone-tag" style={{ borderColor: col }}><i style={{ background: col }} />{label}</span>
            </Html>
          </group>
        );
      })}
    </group>
  );
}
