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
const v3 = (x: number, y: number, z: number) => new THREE.Vector3(x * MM, z * MM, y * MM);

/** The chain's centreline (factory mm, in its fixed frame) and its width axis. */
function centreline(c: ChainSpec, m: number, zBase: number): { pts: THREE.Vector3[]; width: THREE.Vector3 } {
  const { R, length: L } = c;
  const P: [number, number, number][] = [];
  const arc = (cx: number, cz: number, a0: number, a1: number, plane: "xz" | "yz", fixed: number) => {
    for (let k = 1; k <= 18; k++) {
      const a = a0 + ((a1 - a0) * k) / 18;
      const u = cx + R * Math.cos(a), w = cz + R * Math.sin(a);
      P.push(plane === "xz" ? [u, fixed, w] : [fixed, u, w]);
    }
  };
  if (c.axis === "x") {
    // lower strand from the fixed end to the loop, the bend, upper strand back to the moving end
    const [fx, fy, fz] = c.F;
    const xL = (L - Math.PI * R + fx + m) / 2;
    P.push([fx, fy, fz], [xL, fy, fz]);
    arc(xL, fz + R, -Math.PI / 2, Math.PI / 2, "xz", fy);
    P.push([m, fy, fz + 2 * R]);
    return { pts: P.map((p) => v3(...p)), width: new THREE.Vector3(0, 0, 1) };
  }
  if (c.axis === "-y") {
    // upper strand from the fixed end over the arm to the loop, the bend, lower strand back to the moving end
    const [fx, fy, fz0] = c.F;
    const fz = fz0 + zBase;
    const yL = (L - Math.PI * R + fy + m) / 2;
    P.push([fx, fy, fz], [fx, yL, fz]);
    arc(yL, fz - R, Math.PI / 2, -Math.PI / 2, "yz", fx);
    P.push([fx, m, fz - 2 * R]);
    return { pts: P.map((p) => v3(...p)), width: new THREE.Vector3(1, 0, 0) };
  }
  // vertical U hanging from both attach points
  const alongX = Math.abs(c.F[0] - c.M[0]) > Math.abs(c.F[1] - c.M[1]);
  const af = alongX ? c.F[0] : c.F[1], am = alongX ? c.M[0] : c.M[1];
  const other = alongX ? c.F[1] : c.F[0];
  const fz = c.F[2], zm = m;
  const zc = (fz + zm + Math.PI * R - L) / 2;
  const mid = (af + am) / 2;
  const plane = alongX ? "xz" : "yz";
  const pt = (a: number, z: number): [number, number, number] => (alongX ? [a, other, z] : [other, a, z]);
  P.push(pt(af, fz), pt(af, zc));
  const s = Math.sign(am - af) || 1;
  arc(mid, zc, s > 0 ? Math.PI : 0, s > 0 ? 2 * Math.PI : -Math.PI, plane, other);
  P.push(pt(am, zm));
  return { pts: P.map((p) => v3(...p)), width: alongX ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1, 0, 0) };
}

export function DragChain({ spec, joint, zBase = 0 }: {
  spec: ChainSpec; joint: () => number; zBase?: number;
}) {
  const links = useRef<THREE.InstancedMesh>(null);
  const pins = useRef<THREE.InstancedMesh>(null);
  const n = Math.ceil(spec.length / PITCH) + 2;
  const tmp = useMemo(() => ({
    m: new THREE.Matrix4(), q: new THREE.Quaternion(), s: new THREE.Vector3(1, 1, 1),
    e1: new THREE.Vector3(), e2: new THREE.Vector3(), e3: new THREE.Vector3(),
  }), []);
  useFrame(() => {
    const L = links.current, Pn = pins.current;
    if (!L || !Pn) return;
    const { pts, width } = centreline(spec, joint(), zBase);
    const seg: { a: THREE.Vector3; d: THREE.Vector3; len: number; s0: number }[] = [];
    let tot = 0;
    for (let i = 0; i + 1 < pts.length; i++) {
      const d = pts[i + 1].clone().sub(pts[i]);
      const len = d.length();
      if (len < 1e-9) continue;
      seg.push({ a: pts[i], d: d.normalize(), len, s0: tot });
      tot += len;
    }
    let k = 0;
    for (let i = 0; i < n; i++) {
      const s = (i + 0.5) * PITCH * MM;
      if (s > tot) {
        tmp.m.makeScale(0, 0, 0);
        L.setMatrixAt(i, tmp.m); Pn.setMatrixAt(i, tmp.m);
        continue;
      }
      while (k + 1 < seg.length && seg[k].s0 + seg[k].len < s) k++;
      const g = seg[k];
      const p = g.a.clone().addScaledVector(g.d, s - g.s0);
      tmp.e1.copy(g.d);
      tmp.e3.copy(width);
      tmp.e2.crossVectors(tmp.e3, tmp.e1).normalize();
      tmp.m.makeBasis(tmp.e1, tmp.e2, tmp.e3).setPosition(p);
      L.setMatrixAt(i, tmp.m);
      Pn.setMatrixAt(i, tmp.m);
    }
    L.instanceMatrix.needsUpdate = true;
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
