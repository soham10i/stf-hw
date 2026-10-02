// A threaded spindle (Leitspindel): a smooth core with a helical ridge wrapped
// around it, so the rod reads as the screw that converts the motor's rotation
// into the axis' straight-line motion. All axes of the real machine are
// spindle-driven (4 mm pitch per the layout drive data), so every linear axis
// draws one of these along its travel direction.
//
// Built along local +Y, centred at the origin - rotate the parent group to
// aim it. All dimensions are scene units (mm * VIEW); pitch defaults to the
// real 4 mm spindle pitch so the thread count stays honest.

import { useMemo } from "react";
import * as THREE from "three";
import { VIEW } from "../coords";

export function ThreadedRod({
  length,
  radius,
  pitch = 4 * VIEW,
  color = "#9aa6b4",
}: {
  length: number; // scene units, along local Y
  radius: number; // scene units, outer thread radius
  pitch?: number; // scene units per turn
  color?: string;
}) {
  const thread = useMemo(() => {
    const turns = Math.max(2, Math.round(length / pitch));
    const steps = turns * 14;
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const a = t * turns * Math.PI * 2;
      pts.push(
        new THREE.Vector3(Math.cos(a) * radius, (t - 0.5) * length, Math.sin(a) * radius)
      );
    }
    const curve = new THREE.CatmullRomCurve3(pts);
    return new THREE.TubeGeometry(curve, steps, radius * 0.32, 6, false);
  }, [length, radius, pitch]);

  return (
    <group>
      <mesh>
        <cylinderGeometry args={[radius * 0.72, radius * 0.72, length, 10]} />
        <meshStandardMaterial color={color} metalness={0.85} roughness={0.3} />
      </mesh>
      <mesh geometry={thread}>
        <meshStandardMaterial color={color} metalness={0.9} roughness={0.25} />
      </mesh>
    </group>
  );
}
