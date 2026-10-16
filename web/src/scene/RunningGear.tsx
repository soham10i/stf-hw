// The running gear between the moving carriages and what they ride on, found from the parts
// themselves: wherever a guide (a rod, a lead screw or an aluminium profile) passes through a
// part on ANOTHER moving frame, that part rides on it, and a real machine has hardware there -
// a linear ball bearing with wiper seals on a plain rod, a flanged bronze nut on a lead screw,
// low-friction UHMW-PE guide shoes on a profile - and a film of grease along every rod and screw
// something runs on (profiles with polymer shoes run dry).
//
// Drawn, not exported: the proofs check the carriage envelopes, and every piece here is sized
// to stay inside the carriage it belongs to along the guide.
import { useMemo } from "react";
import * as THREE from "three";
import { type CadPart, boxSize, cylSpec } from "../shared/model";
import { AIM, MM, v } from "./parts";

type Axis = 0 | 1 | 2;
type Kind = "rod" | "screw" | "profile";
type Guide = { part: CadPart; axis: Axis; lo: number; hi: number; c: [number, number]; half: [number, number]; kind: Kind };
type Ride = { g: Guide; lo: number; hi: number };

const AX: Axis[] = [0, 1, 2];
const NAME = ["x", "y", "z"] as const;
const others = (a: Axis) => AX.filter((i) => i !== a) as [Axis, Axis];

/** A part that something can run along: long, straight and round, or a long profile. */
function guideOf(p: CadPart): Guide | null {
  if (p.k === "cyl") {
    const [ax, len, dia] = cylSpec(p);
    if (len < 150) return null;                                   // piston rods, shafts, pins
    const axis = (NAME as readonly string[]).indexOf(ax) as Axis, [i, j] = others(axis);
    return { part: p, axis, lo: p.p[axis], hi: p.p[axis] + len, c: [p.p[i], p.p[j]], half: [dia / 2, dia / 2],
      kind: p.mech.startsWith("thread:") ? "screw" : "rod" };
  }
  if (p.k === "box" && p.mech.startsWith("profile")) {
    const s = boxSize(p);
    const axis = AX.reduce((a, b) => (s[b] > s[a] ? b : a), 0 as Axis), [i, j] = others(axis);
    if (s[axis] < 150 || s[axis] < 6 * Math.max(s[i], s[j])) return null;
    return { part: p, axis, lo: p.p[axis], hi: p.p[axis] + s[axis],
      c: [p.p[i] + s[i] / 2, p.p[j] + s[j] / 2], half: [s[i] / 2, s[j] / 2], kind: "profile" };
  }
  return null;
}

/** The direction each moving frame slides in ("x" | "y" | "z"); rotating frames are left out. */
export type FrameAxes = Record<string, "x" | "y" | "z">;

/** Where each carriage of `frame` rides on a guide of another frame: one interval per guide.
    A carriage rides a guide when the guide's centre line runs through it and the two frames
    move relative to each other ALONG the guide. When the carriage's own frame is the one that
    slides, its authored position along the axis is only the joint's zero, so the guide's extent
    there is not compared; when the guide slides through it, the overlap is. */
function ridesOf(all: CadPart[], frame: string, axes: FrameAxes): Ride[] {
  const guides = all.map(guideOf).filter((g): g is Guide => !!g && g.part.f !== frame
    && (axes[frame] === NAME[g.axis] || axes[g.part.f] === NAME[g.axis]));
  const boxes = all.filter((p) => p.f === frame && p.k === "box" && p.g !== "frame" && p.mech !== "pneumatic" && !guideOf(p));
  const out: Ride[] = [];
  for (const g of guides) {
    const [i, j] = others(g.axis), spans: [number, number][] = [];
    const own = axes[frame] === NAME[g.axis];
    for (const b of boxes) {
      const s = boxSize(b);
      if (g.c[0] <= b.p[i] || g.c[0] >= b.p[i] + s[i] || g.c[1] <= b.p[j] || g.c[1] >= b.p[j] + s[j]) continue;
      const lo = own ? b.p[g.axis] : Math.max(g.lo, b.p[g.axis]), hi = own ? b.p[g.axis] + s[g.axis] : Math.min(g.hi, b.p[g.axis] + s[g.axis]);
      if (hi - lo > 2) spans.push([lo, hi]);
    }
    spans.sort((a, b) => a[0] - b[0]);
    const merged: [number, number][] = [];
    for (const s of spans) {
      const m = merged[merged.length - 1];
      if (m && s[0] <= m[1]) m[1] = Math.max(m[1], s[1]); else merged.push([...s]);
    }
    for (const [lo, hi] of merged) out.push({ g, lo, hi });
  }
  return out;
}

/** factory point on a guide's centre line at axial position `t` */
function onLine(g: Guide, t: number) {
  const q = [0, 0, 0];
  const [i, j] = others(g.axis);
  q[g.axis] = t; q[i] = g.c[0]; q[j] = g.c[1];
  return v(q[0], q[1], q[2]);
}

const STEEL = { color: "#c9ced4", metalness: 1, roughness: 0.22 };
const BRONZE = { color: "#b58a4c", metalness: 0.85, roughness: 0.35 };
const RUBBER = { color: "#141414", roughness: 0.9 };

// The carriage is drawn as a solid block, so what shows of the hardware inside it is what a
// real carriage shows at its two faces. Each piece is built in the aimed frame (local +Y = the
// guide axis, pointing out of the face `s`) and stands at most 4.5 mm proud of the face.
const Disc = ({ r, t, y, m, seg = 32 }: { r: number; t: number; y: number; m: object; seg?: number }) => (
  <mesh position={[0, (y + t / 2) * MM, 0]} castShadow><cylinderGeometry args={[r * MM, r * MM, t * MM, seg]} /><meshStandardMaterial {...m} /></mesh>
);

/** Linear ball bearing: its steel flange on the face, a rubber wiper seal outside it. */
function BearingFace({ R }: { R: number }) {
  return <><Disc r={R + 5.5} t={3} y={0} m={STEEL} /><Disc r={R + 2.6} t={1.5} y={3} m={RUBBER} /></>;
}
/** Lead-screw nut: the bronze flange bolted to the face, a wiper on the far side. */
function NutFace({ R, flange }: { R: number; flange: boolean }) {
  return flange
    ? <><Disc r={R + 8} t={3} y={0} m={BRONZE} /><Disc r={R + 4.5} t={1.5} y={3} m={BRONZE} seg={6} /></>
    : <Disc r={R + 2.6} t={1.5} y={0} m={RUBBER} />;
}
/** UHMW-PE guide shoe: an end plate hugging the profile, 2.5 mm clearance-free on each side. */
function ShoeFace({ g }: { g: Guide }) {
  const [hi, hj] = g.half;
  //   x-guide: local X/Z = factory z / y,  y-guide: factory x / z,  z-guide: factory x / y
  const w = [0, 0, 0], [i, j] = others(g.axis); w[i] = (hi + 2.5) * 2; w[j] = (hj + 2.5) * 2;
  const [a, b] = g.axis === 0 ? [w[2], w[1]] : g.axis === 1 ? [w[0], w[2]] : [w[0], w[1]];
  return <mesh position={[0, 2 * MM, 0]} castShadow><boxGeometry args={[a * MM, 4 * MM, b * MM]} /><meshStandardMaterial color="#efeee8" roughness={0.55} /></mesh>;
}

/** The bearings, nuts and shoes on the carriages of `frame`, and the grease on the rods and
    screws of `frame` that carriages of other frames ride on. Put one in every frame group. */
export function RunningGear({ all, frame, axes }: { all: CadPart[]; frame: string; axes: FrameAxes }) {
  const rides = useMemo(() => ridesOf(all, frame, axes), [all, frame, axes]);
  const greased = useMemo(() => {
    const ridden = new Set(Array.from(new Set(all.map((p) => p.f))).filter((f) => f !== frame)
      .flatMap((f) => ridesOf(all, f, axes)).map((r) => r.g.part.n));
    return all.map(guideOf).filter((g): g is Guide => !!g && g.part.f === frame && g.kind !== "profile" && ridden.has(g.part.n));
  }, [all, frame, axes]);
  return (
    <group>
      {rides.flatMap((r, k) => ([[r.hi, 1], [r.lo, -1]] as const).map(([at, s]) => {
        const R = Math.max(...r.g.half);
        return (
          <group key={`${k}${s}`} position={onLine(r.g, at)} rotation={AIM[NAME[r.g.axis]]}>
            <group scale={[1, s, 1]}>
              {r.g.kind === "rod" ? <BearingFace R={R} /> : r.g.kind === "screw" ? <NutFace R={R} flange={s < 0} /> : <ShoeFace g={r.g} />}
            </group>
          </group>
        );
      }))}
      {greased.map((g) => {
        const R = Math.max(...g.half) + (g.kind === "screw" ? 0.45 : 0.3);
        return (
          <mesh key={g.part.n} position={onLine(g, (g.lo + g.hi) / 2)} rotation={AIM[NAME[g.axis]]} renderOrder={1}>
            <cylinderGeometry args={[R * MM, R * MM, (g.hi - g.lo) * 0.97 * MM, 28, 1, true]} />
            <meshPhysicalMaterial color="#c9a14a" transparent opacity={0.2} roughness={0.06} metalness={0}
              clearcoat={1} clearcoatRoughness={0.04} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
        );
      })}
    </group>
  );
}

/** How each module's frames slide (the joints in hbw_model / vgr_model / oven_model). */
export const HBW: FrameAxes = { travel: "x", lift: "z", fork: "y" };
export const VGR: FrameAxes = { plunge: "z", reach: "y" };
export const OVEN: FrameAxes = { slider: "x", door: "z", sauger: "y", lower: "z", push: "y" };

/** For tests: which guides carry what. */
export const _ridesOf = ridesOf;
