// One component in the viewer: its precise mesh, the sub-part that moves when it is operated
// (switch, valve, cylinder, motor, drag chain, spindle) and its dimension lines.

import { Html, Line, useGLTF } from "@react-three/drei";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";


import { Motion } from "./componentModel";
import { physical } from "./materials";



/** The chain's path: point (x, z) in mm and tangent angle about +Y, at arc length s, lift at u (0..1). */
function chainPose(m: Motion, s: number, u: number): [number, number, number] {
  const R = m.R!, L = m.length!, zF = m.zF!, zm = m.zM0! + m.travel! * u;
  const zc = (zF + zm + Math.PI * R - L) / 2, la = zF - zc;
  let x: number, z: number, tx: number, tz: number;
  if (s <= la) { x = 0; z = zF - s; tx = 0; tz = -1; }
  else if (s <= la + Math.PI * R) {
    const a = (s - la) / R;
    x = R - R * Math.cos(a); z = zc - R * Math.sin(a); tx = Math.sin(a); tz = -Math.cos(a);
  } else { x = 2 * R; z = zc + (s - la - Math.PI * R); tx = 0; tz = 1; }
  return [x, z, Math.atan2(-tz, tx)];
}

/** A part that can be operated in the viewer: which sub-part moves, and how far. */
export interface Actuator { part: string; travelMm: number }

export function Part({
  url, picked, onPick, wire, actuator, pressed = false, onToggle, motion, running = false, xray = false,
}: {
  url: string; picked: string | null; onPick: (n: string | null) => void; wire: boolean;
  actuator?: Actuator | null; pressed?: boolean; onToggle?: () => void;
  motion?: Motion[]; running?: boolean; xray?: boolean;
}) {
  const { scene } = useGLTF(url);
  const model = useMemo(() => scene.clone(true), [scene]);
  // sub-parts driven by the component's motion table
  const driven = useMemo(() => {
    const out: { m: Motion; o: THREE.Object3D }[] = [];
    for (const m of motion ?? []) {
      if (m.type === "chain" || m.type === "screw") {
        const names = m.type === "chain" ? null : new Set([m.part, ...(m.turns ?? [])]);
        const seen = new Set<string>();                  // a part is a node, or a mesh when it has one primitive
        model.traverse((o) => {
          const p = (o.userData as { part?: string }).part;
          if (!p || seen.has(p)) return;
          if (m.type === "chain" ? p.startsWith(`${m.part}_`) || p === m.moving : names!.has(p)) { seen.add(p); out.push({ m, o }); }
        });
        continue;
      }
      model.traverse((o) => {
        if ((o.userData as { part?: string }).part === m.part && !(o as THREE.Mesh).isMesh) out.push({ m, o });
      });
      if (!out.some((d) => d.m === m)) {
        model.traverse((o) => {
          if ((o.userData as { part?: string }).part === m.part && !out.some((d) => d.m === m)) out.push({ m, o });
        });
      }
    }
    return out;
  }, [model, motion]);
  const clock = useRef({ theta: 0, u: 0 });
  useFrame((_, dt) => {
    if (!driven.length) return;
    const k = clock.current;
    if (running) k.theta += dt;
    k.u += ((running ? 1 : 0) - k.u) * Math.min(1, dt * 10);
    for (const { m, o } of driven) {
      const ax = new THREE.Vector3(...m.axis).normalize();
      const part = (o.userData as { part?: string }).part ?? "";
      if (m.type === "chain") {
        // every link is meshed at its pose for u0; move it from there to its pose now
        const u0 = m.u0 ?? 0.5;
        const u = Math.min(1, Math.max(0, u0 + 0.5 * Math.sin(THREE.MathUtils.degToRad((m.dps ?? 30) * k.theta))));
        if (part === m.moving) {
          o.position.set(0, 0, m.travel! * (u - u0) * 0.001);
          continue;
        }
        const s = (Number(part.split("_").pop()) + 0.5) * m.pitch!;
        const [x0, z0, a0] = chainPose(m, s, u0), [x1, z1, a1] = chainPose(m, s, u);
        const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), a1 - a0);
        o.quaternion.copy(q);
        o.position.copy(new THREE.Vector3(x1, 0, z1).sub(new THREE.Vector3(x0, 0, z0).applyQuaternion(q)).multiplyScalar(0.001));
        continue;
      }
      if (m.type === "screw") {
        // the nut goes up and down; one turn of the spindle per pitch of travel
        const z = (m.travel ?? 0) * (0.5 - 0.5 * Math.cos(THREE.MathUtils.degToRad((m.dps ?? 45) * k.theta)));
        if (part === m.part) o.position.copy(ax.multiplyScalar(z * 0.001));
        else o.quaternion.setFromAxisAngle(ax, (z / (m.pitch ?? 1)) * 2 * Math.PI);
        continue;
      }
      if (m.type === "spin" || m.type === "orbit") {
        const piv = new THREE.Vector3(...(m.pivot ?? [0, 0, 0])).multiplyScalar(0.001);
        const q = new THREE.Quaternion().setFromAxisAngle(ax, THREE.MathUtils.degToRad((m.dps ?? 360) * k.theta));
        o.quaternion.copy(q);
        o.position.copy(piv.clone().sub(piv.clone().applyQuaternion(q)));
      } else if (m.type === "reciprocate") {
        const th = THREE.MathUtils.degToRad((m.dps ?? 360) * k.theta);
        o.position.copy(ax.multiplyScalar(((m.amp ?? 0) / 2) * (1 - Math.cos(th)) * 0.001));
      } else if (m.type === "slide") {
        o.position.copy(ax.multiplyScalar((m.travel ?? 0) * k.u * 0.001));
      } else if (m.type === "squash") {
        const len = m.length ?? 1;
        const sc = (len - (m.travel ?? 0) * k.u) / len;
        const i = Math.abs(m.axis[0]) > 0.5 ? 0 : Math.abs(m.axis[1]) > 0.5 ? 1 : 2;
        const anc = (m.anchor ?? [0, 0, 0])[i] * 0.001;
        o.scale.setComponent(i, sc);
        o.position.setComponent(i, anc * (1 - sc));
      }
    }
  });
  const moving = useRef<THREE.Object3D | null>(null);
  useEffect(() => {
    moving.current = null;
    if (!actuator) return;
    model.traverse((o) => {
      if ((o.userData as { part?: string }).part === actuator.part) moving.current = o;
    });
  }, [model, actuator]);
  // Ease the actuator to its target: pressed = pushed down by its travel. The
  // node sits under the glb root, whose frame is the part's own Z-up, in metres.
  useFrame((_, dt) => {
    const m = moving.current;
    if (!m || !actuator) return;
    const target = pressed ? -actuator.travelMm * 0.001 : 0;
    m.position.z += (target - m.position.z) * Math.min(1, dt * 18);
  });
  useEffect(() => {
    model.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const u = m.userData as { material?: string; colour?: string; part?: string };
      const mat = physical(u.material ?? "abs", u.colour ?? "#888") as THREE.MeshPhysicalMaterial;
      // X-ray: the enclosures go glassy so the mechanism inside can be watched
      if (xray && ["housing", "u_gearbox", "coil"].includes(u.part ?? "")) {
        mat.transparent = true;
        mat.opacity = 0.16;
        mat.depthWrite = false;
      }
      if (u.part === picked) {
        mat.emissive = new THREE.Color("#4aa3c8");
        mat.emissiveIntensity = 0.55;
      }
      mat.wireframe = wire;
      m.material = mat;
      m.castShadow = m.receiveShadow = true;
    });
  }, [model, picked, wire, xray]);
  return (
    <primitive
      object={model}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation();
        const part = (e.object.userData as { part?: string }).part ?? null;
        // the actuator OPERATES the switch; selecting it too would tint it pink
        if (actuator && part === actuator.part) onToggle?.();
        else onPick(part);
      }}
    />
  );
}

/** A dimension line with extension ticks, drawn in the part's own mm frame. */
export function DimLine({ a, b, label, off }: { a: number[]; b: number[]; label: string; off: number[] }) {
  const A = new THREE.Vector3(...(a as [number, number, number])).add(new THREE.Vector3(...(off as [number, number, number])));
  const B = new THREE.Vector3(...(b as [number, number, number])).add(new THREE.Vector3(...(off as [number, number, number])));
  const mid = A.clone().add(B).multiplyScalar(0.5);
  return (
    <group>
      <Line points={[A, B]} color="#4aa3c8" lineWidth={1.5} />
      <Line points={[new THREE.Vector3(...(a as [number, number, number])), A]} color="#4aa3c8" lineWidth={0.8} dashed dashSize={0.6} gapSize={0.4} />
      <Line points={[new THREE.Vector3(...(b as [number, number, number])), B]} color="#4aa3c8" lineWidth={0.8} dashed dashSize={0.6} gapSize={0.4} />
      <Html position={mid} center className="dim-label">{label}</Html>
    </group>
  );
}
