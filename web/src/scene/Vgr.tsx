// The Vacuum Gripper Robot - a cylindrical-coordinate arm, per the manual: its
// work envelope is a "hollow cylinder" formed by a Drehkranz (rotary turntable)
// plus two translational axes and a downward suction effector.
//
//   base + Drehkranz (swivel, rotate about +up)
//     -> column
//        -> carriage (plunge, up/down the column)
//           -> arm head (reach, extends horizontally) -> suction cup (points down)
//
// The turntable rotates the whole column+arm assembly - that is what sweeps the
// hollow-cylinder envelope. Joints are read imperatively from the hot store.

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";

export function Vgr({ scene }: { scene: SceneDescriptor }) {
  const swivel = useRef<THREE.Group>(null);
  const carriage = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);

  const dev = scene.devices.vgr;
  const base = v3a(dev.base);
  const columnH = (dev.joints.plunge.limits[1] + 20) * VIEW;
  const reachMax = dev.joints.reach.limits[1] * VIEW;

  useFrame(() => {
    const j = hot.joints;
    if (swivel.current) {
      swivel.current.rotation.y = -THREE.MathUtils.degToRad(j["vgr.swivel"] ?? 0);
    }
    if (carriage.current) carriage.current.position.y = (j["vgr.plunge"] ?? 0) * VIEW;
    if (head.current) head.current.position.z = (j["vgr.reach"] ?? 0) * VIEW;
  });

  return (
    <group position={base}>
      {/* fixed base plate */}
      <mesh position={[0, 0.02, 0]} receiveShadow>
        <cylinderGeometry args={[0.16, 0.18, 0.04, 28]} />
        <meshStandardMaterial color="#2f3e4e" metalness={0.5} roughness={0.5} />
      </mesh>

      {/* everything above rotates on the Drehkranz */}
      <group ref={swivel} position={[0, 0.04, 0]}>
        {/* Drehkranz (rotary turntable ring) */}
        <mesh position={[0, 0.02, 0]}>
          <cylinderGeometry args={[0.13, 0.13, 0.035, 28]} />
          <meshStandardMaterial color="#46586b" metalness={0.6} roughness={0.4} />
        </mesh>

        {/* vertical column */}
        <mesh position={[0, columnH / 2, 0]} castShadow>
          <boxGeometry args={[0.08, columnH, 0.08]} />
          <meshStandardMaterial color="#6a7a8a" metalness={0.5} roughness={0.5} />
        </mesh>

        {/* carriage that plunges up/down the column */}
        <group ref={carriage}>
          <mesh castShadow>
            <boxGeometry args={[0.11, 0.08, 0.11]} />
            <meshStandardMaterial color="#4aa3c8" metalness={0.3} roughness={0.6} />
          </mesh>

          {/* fixed horizontal guide the arm reaches along (+depth) */}
          <mesh position={[0, 0, reachMax / 2]}>
            <boxGeometry args={[0.04, 0.04, reachMax]} />
            <meshStandardMaterial color="#3a5568" metalness={0.4} roughness={0.6} />
          </mesh>

          {/* reaching head + downward suction cup */}
          <group ref={head}>
            <mesh castShadow>
              <boxGeometry args={[0.07, 0.06, 0.09]} />
              <meshStandardMaterial color="#4aa3c8" metalness={0.3} roughness={0.6} />
            </mesh>
            {/* suction stem + cup, pointing down */}
            <mesh position={[0, -0.05, 0]}>
              <cylinderGeometry args={[0.012, 0.012, 0.06, 12]} />
              <meshStandardMaterial color="#222831" roughness={0.9} />
            </mesh>
            <mesh position={[0, -0.09, 0]}>
              <cylinderGeometry args={[0.035, 0.02, 0.03, 16]} />
              <meshStandardMaterial color="#1a1f26" roughness={0.9} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}
