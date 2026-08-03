// The Vacuum Gripper Robot: a cylindrical R-P-P arm (not the three prismatic
// axes the old code assumed). It swivels about a base column, reaches out along
// the arm, and plunges a suction cup down. The docs (FACTORY_SPECS.md) record
// its third axis as "rotate clockwise/counterclockwise", which is why swivel is
// a rotation here.
//
//   base -> swivel (rotate about +Z/up) -> reach (+Y) -> plunge (+Z/up)

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";

export function Vgr({ scene }: { scene: SceneDescriptor }) {
  const swivel = useRef<THREE.Group>(null);
  const arm = useRef<THREE.Group>(null);
  const suction = useRef<THREE.Group>(null);

  const dev = scene.devices.vgr;
  const base = v3a(dev.base);
  const plungeMax = dev.joints.plunge.limits[1];

  useFrame(() => {
    const j = hot.joints;
    if (swivel.current) {
      // factory swivel is degrees about +Z (up) = three's Y axis
      swivel.current.rotation.y = -THREE.MathUtils.degToRad(j["vgr.swivel"] ?? 0);
    }
    if (arm.current) arm.current.position.z = (j["vgr.reach"] ?? 0) * VIEW;
    if (suction.current) suction.current.position.y = (j["vgr.plunge"] ?? 0) * VIEW;
  });

  const columnH = plungeMax * VIEW;

  return (
    <group position={base}>
      {/* base plate */}
      <mesh position={[0, 0.02, 0]}>
        <cylinderGeometry args={[0.12, 0.14, 0.04, 24]} />
        <meshStandardMaterial color="#3a4a5a" metalness={0.5} roughness={0.5} />
      </mesh>

      <group ref={swivel}>
        {/* column */}
        <mesh position={[0, columnH / 2, 0]}>
          <cylinderGeometry args={[0.04, 0.04, columnH, 20]} />
          <meshStandardMaterial color="#6a7a8a" metalness={0.5} roughness={0.5} />
        </mesh>

        {/* carriage that plunges up/down the column */}
        <group ref={suction}>
          {/* horizontal arm that reaches out */}
          <group ref={arm}>
            <mesh position={[0, 0, 0.09]}>
              <boxGeometry args={[0.05, 0.05, 0.18]} />
              <meshStandardMaterial color="#4aa3c8" metalness={0.3} roughness={0.6} />
            </mesh>
            {/* suction cup at the arm tip */}
            <mesh position={[0, -0.03, 0.18]}>
              <cylinderGeometry args={[0.03, 0.02, 0.03, 16]} />
              <meshStandardMaterial color="#222" roughness={0.9} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}
