// Upgrade 3: a drag chain (cable carrier) drawn link by link along its real
// path, recomputed every frame from the live joint value. The geometry is the
// same as stf-cad/hbw/chains.py: a U with two straight strands and a bend of
// radius R whose position follows from the chain's fixed length - so the loop
// travels at half the speed of the moving end, as a real one does.

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { VIEW as MM } from "../coords";

export interface ChainSpec {
  axis: "x" | "z" | "-y";
  R: number; h: number; w: number; length: number;
  F: [number, number, number]; M: [number, number, number];
}

const PITCH = 12;           // link pitch, mm (assumed)
const CAP = 24;               // centreline points: 2 straights + an 18-step bend + the end

/** The chain's centreline (factory mm, in its fixed frame -> three) and its width axis, written
    into buffers made once: the drag chain is recomputed every frame and must not allocate. */
type Line = { pts: THREE.Vector3[]; n: number; width: THREE.Vector3 };
const newLine = (): Line => ({ pts: Array.from({ length: CAP }, () => new THREE.Vector3()), n: 0, width: new THREE.Vector3() });
const put = (o: Line, x: number, y: number, z: number) => { o.pts[o.n++].set(x * MM, z * MM, y * MM); };
/** an 18-step arc of radius R about (cu, cw) in the plane "xz" (fixed y) or "yz" (fixed x) */
function arcInto(o: Line, R: number, cu: number, cw: number, a0: number, a1: number, xz: boolean, fixed: number) {
  for (let k = 1; k <= 18; k++) {
    const a = a0 + ((a1 - a0) * k) / 18;
    const u = cu + R * Math.cos(a), w = cw + R * Math.sin(a);
    if (xz) put(o, u, fixed, w); else put(o, fixed, u, w);
  }
}

function centrelineInto(c: ChainSpec, m: number, zBase: number, o: Line): Line {
  const { R, length: L } = c;
  o.n = 0;
  if (c.axis === "x") {
    // lower strand from the fixed end to the loop, the bend, upper strand back to the moving end
    const [fx, fy, fz] = c.F;
    const xL = (L - Math.PI * R + fx + m) / 2;
    put(o, fx, fy, fz); put(o, xL, fy, fz);
    arcInto(o, R, xL, fz + R, -Math.PI / 2, Math.PI / 2, true, fy);
    put(o, m, fy, fz + 2 * R);
    o.width.set(0, 0, 1);
    return o;
  }
  if (c.axis === "-y") {
    // upper strand from the fixed end over the arm to the loop, the bend, lower strand back to the moving end
    const [fx, fy, fz0] = c.F;
    const fz = fz0 + zBase;
    const yL = (L - Math.PI * R + fy + m) / 2;
    put(o, fx, fy, fz); put(o, fx, yL, fz);
    arcInto(o, R, yL, fz - R, Math.PI / 2, -Math.PI / 2, false, fx);
    put(o, fx, m, fz - 2 * R);
    o.width.set(1, 0, 0);
    return o;
  }
  // vertical U hanging from both attach points
  const alongX = Math.abs(c.F[0] - c.M[0]) > Math.abs(c.F[1] - c.M[1]);
  const af = alongX ? c.F[0] : c.F[1], am = alongX ? c.M[0] : c.M[1];
  const other = alongX ? c.F[1] : c.F[0];
  const fz = c.F[2], zm = m;
  const zc = (fz + zm + Math.PI * R - L) / 2;
  const mid = (af + am) / 2;
  if (alongX) { put(o, af, other, fz); put(o, af, other, zc); } else { put(o, other, af, fz); put(o, other, af, zc); }
  const sg = Math.sign(am - af) || 1;
  arcInto(o, R, mid, zc, sg > 0 ? Math.PI : 0, sg > 0 ? 2 * Math.PI : -Math.PI, alongX, other);
  if (alongX) put(o, am, other, zm); else put(o, other, am, zm);
  if (alongX) o.width.set(0, 0, 1); else o.width.set(1, 0, 0);
  return o;
}

export function DragChain({ spec, joint, zBase = 0 }: {
  spec: ChainSpec; joint: () => number; zBase?: number;
}) {
  const links = useRef<THREE.InstancedMesh>(null);
  const pins = useRef<THREE.InstancedMesh>(null);
  const n = Math.ceil(spec.length / PITCH) + 2;
  const tmp = useMemo(() => ({
    m: new THREE.Matrix4(), p: new THREE.Vector3(),
    e1: new THREE.Vector3(), e2: new THREE.Vector3(), e3: new THREE.Vector3(),
    line: newLine(),
    // the centreline's segments: start point index, unit direction, length, distance at start
    segA: new Int32Array(CAP), segD: Array.from({ length: CAP }, () => new THREE.Vector3()),
    segL: new Float64Array(CAP), segS: new Float64Array(CAP),
  }), []);
  useFrame(() => {
    const Lm = links.current, Pn = pins.current;
    if (!Lm || !Pn) return;
    const { pts, n: np, width } = centrelineInto(spec, joint(), zBase, tmp.line);
    let ns = 0, tot = 0;
    for (let i = 0; i + 1 < np; i++) {
      const d = tmp.segD[ns].subVectors(pts[i + 1], pts[i]);
      const len = d.length();
      if (len < 1e-9) continue;
      d.multiplyScalar(1 / len);
      tmp.segA[ns] = i; tmp.segL[ns] = len; tmp.segS[ns] = tot;
      ns++;
      tot += len;
    }
    let k = 0;
    for (let i = 0; i < n; i++) {
      const s = (i + 0.5) * PITCH * MM;
      if (s > tot || ns === 0) {
        tmp.m.makeScale(0, 0, 0);
        Lm.setMatrixAt(i, tmp.m); Pn.setMatrixAt(i, tmp.m);
        continue;
      }
      while (k + 1 < ns && tmp.segS[k] + tmp.segL[k] < s) k++;
      const dir = tmp.segD[k];
      tmp.p.copy(pts[tmp.segA[k]]).addScaledVector(dir, s - tmp.segS[k]);
      tmp.e1.copy(dir);
      tmp.e3.copy(width);
      tmp.e2.crossVectors(tmp.e3, tmp.e1).normalize();
      tmp.m.makeBasis(tmp.e1, tmp.e2, tmp.e3).setPosition(tmp.p);
      Lm.setMatrixAt(i, tmp.m);
      Pn.setMatrixAt(i, tmp.m);
    }
    Lm.instanceMatrix.needsUpdate = true;
    Pn.instanceMatrix.needsUpdate = true;
  });
  return (
    <group>
      <instancedMesh ref={links} args={[undefined, undefined, n]} castShadow>
        <boxGeometry args={[PITCH * 0.92 * MM, spec.h * MM, spec.w * MM]} />
        <meshStandardMaterial color="#26282c" roughness={0.7} />
      </instancedMesh>
      {/* the link pins on both side plates: what makes it read as a chain */}
      <instancedMesh ref={pins} args={[undefined, undefined, n]}>
        <boxGeometry args={[PITCH * 0.25 * MM, spec.h * 0.4 * MM, (spec.w + 1.2) * MM]} />
        <meshStandardMaterial color="#8a9098" metalness={0.6} roughness={0.4} />
      </instancedMesh>
    </group>
  );
}
