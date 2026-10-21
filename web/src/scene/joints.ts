// Joints drawn as joints. The export models a part slotted into another as overlapping solids -
// a rack's shelf support 5 mm into its post's groove, a guard post's ends inside the frame rails,
// a belt drum's axle in its side rails. Drawn as they are, the hidden end of the inserted part
// shares the host's faces, and the two fight for each pixel (z-fighting), with the inserted
// part's bevelled end showing through the host. So each inserted part is drawn trimmed at the
// face it enters by - a clipping plane per joint; the CAD keeps its overlap, and the proofs
// that read it are untouched.
//
// Found from the parts' envelopes: a static part A enters a larger static part B through one
// face when, along one axis, A starts (or ends) inside B and leaves it on the other side, and
// across that axis A lies within B. A part passing right through (a rod through a wall) is left
// as it is: one plane cannot trim its middle.

import { useFrame } from "@react-three/fiber";
import { useRef, type ReactNode } from "react";
import { createElement } from "react";
import * as THREE from "three";
import { VIEW as MM } from "../coords";

type Part = { n: string; k: string; p: number[]; s: (number | string)[]; f?: string; g?: string; mech?: string };
/** keep the side of `at` (mm, the part's own module frame) along `axis` that `keep` names */
export type Trim = { axis: 0 | 1 | 2; at: number; keep: 1 | -1 };

const EPS = 0.01;

function envelope(p: Part): number[] | null {
  const [x, y, z] = p.p;
  if (p.k === "box") {
    const [sx, sy, sz] = p.s as number[];
    return [x, y, z, x + sx, y + sy, z + sz];
  }
  if (p.k !== "cyl") return null;
  const [ax, L, d] = p.s as [string, number, number];
  const r = d / 2;
  return ax === "x" ? [x, y - r, z - r, x + L, y + r, z + r]
    : ax === "y" ? [x - r, y, z - r, x + r, y + L, z + r] : [x - r, y - r, z, x + r, y + r, z + L];
}

/** a part that is drawn solid and does not move: a host can hide what enters it */
const staticPart = (p: Part) => (p.f ?? "world") === "world";
const solidHost = (p: Part) => staticPart(p) && p.g !== "frame" && p.mech !== "panel" && !(p.mech ?? "").startsWith("belt") && !(p.mech ?? "").startsWith("chain:");

/** Each static part's trims, by name. */
export function jointTrims(parts: Part[]): Map<string, Trim[]> {
  const E = parts.filter(staticPart).map((p) => ({ p, e: envelope(p) })).filter((q): q is { p: Part; e: number[] } => !!q.e);
  const vol = (e: number[]) => (e[3] - e[0]) * (e[4] - e[1]) * (e[5] - e[2]);
  const out = new Map<string, Trim[]>();
  for (const { p: a, e: A } of E) {
    for (const { p: b, e: B } of E) {
      if (a === b || !solidHost(b) || vol(A) > vol(B)) continue;
      if ([0, 1, 2].some((j) => Math.min(A[j + 3], B[j + 3]) - Math.max(A[j], B[j]) <= EPS)) continue;
      for (const ax of [0, 1, 2] as const) {
        const across = [0, 1, 2].filter((j) => j !== ax);
        if (!across.every((j) => A[j] >= B[j] - EPS && A[j + 3] <= B[j + 3] + EPS)) continue;
        const startsIn = A[ax] >= B[ax] - EPS && A[ax] < B[ax + 3] - EPS && A[ax + 3] > B[ax + 3] + EPS;
        const endsIn = A[ax + 3] <= B[ax + 3] + EPS && A[ax + 3] > B[ax] + EPS && A[ax] < B[ax] - EPS;
        if (!startsIn && !endsIn) continue;
        const t: Trim = startsIn ? { axis: ax, at: B[ax + 3], keep: 1 } : { axis: ax, at: B[ax], keep: -1 };
        out.set(a.n, [...(out.get(a.n) ?? []), t]);
        break;
      }
    }
  }
  return out;
}

/** The trims of a module's parts, computed once per parts list. */
// the module frame's axes in three's: v(x, y, z) = (x, z, y)
const AXIS = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 1, 0)];

/** Its children drawn with the trims applied: the planes are placed in the world once (the part
    and its module do not move), and every mesh below gets them - including meshes that arrive
    later, as the precise ones do. */
export function Trimmed({ trims, children }: { trims?: Trim[]; children: ReactNode }) {
  const g = useRef<THREE.Group>(null);
  const planes = useRef<THREE.Plane[] | null>(null);
  useFrame(() => {
    const grp = g.current;
    if (!grp || !trims?.length) return;
    if (!planes.current) {
      grp.updateWorldMatrix(true, false);
      planes.current = trims.map((t) =>
        new THREE.Plane(AXIS[t.axis].clone().multiplyScalar(t.keep), -t.keep * t.at * MM).applyMatrix4(grp.matrixWorld));
    }
    grp.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh || m.userData.trimmed) return;
      m.userData.trimmed = true;
      // a material shared with other meshes (the precise library's) is cloned; a part's own is
      // trimmed in place, so whatever animates it (a heater's glow) keeps its hold on it
      const mats = Array.isArray(m.material) ? m.material : [m.material];
      const clipped = mats.map((x) => {
        const c = x.userData.shared ? x.clone() : x;
        c.userData = { ...c.userData, shared: false };
        c.clippingPlanes = planes.current;
        c.clipShadows = true;
        c.needsUpdate = true;
        return c;
      });
      m.material = Array.isArray(m.material) ? clipped : clipped[0];
    });
  });
  return trims?.length ? createElement("group", { ref: g }, children) : createElement("group", null, children);
}
