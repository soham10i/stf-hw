// The Vacuum Gripper Robot (Vakuum-Sauggreifer), built to match the labelled
// photo in the manual (p18): (1) Drehkranz - a rotary turntable at the base,
// (2) horizontale Achse - a long arm that slides THROUGH a clamp carriage,
// (3) vertikale Achse - the carriage rides up and down the tower,
// (4) Sauger - the suction cup hanging from the arm tip, pointing down.
//
// The turntable rotates the whole tower+arm assembly (the hollow-cylinder work
// envelope). Dimensions are millimetres scaled by VIEW.
//
//   base -> turntable(swivel) -> tower -> carriage(plunge) -> arm(reach) -> cup

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";
import { Carrier } from "./Carrier";

// mm
const TOWER = 44; // tower profile
const CLAMP_W = 64;
const CLAMP_H = 42;
const CLAMP_D = 60; // carriage clamp wraps the tower
const ARM = 26; // arm beam profile
const ARM_LEN = 200; // physical beam length; it telescopes through the clamp

export function Vgr({ scene }: { scene: SceneDescriptor }) {
  const swivel = useRef<THREE.Group>(null);
  const carriage = useRef<THREE.Group>(null);
  const armGroup = useRef<THREE.Group>(null);
  const tip = useRef<THREE.Group>(null);

  const dev = scene.devices.vgr;
  const base = v3a(dev.base);
  const plungeMax = dev.joints.plunge.limits[1];
  const towerH = (plungeMax + 160) * VIEW;

  useFrame(() => {
    const j = hot.joints;
    if (swivel.current) {
      swivel.current.rotation.y = -THREE.MathUtils.degToRad(j["vgr.swivel"] ?? 0);
    }
    if (carriage.current) carriage.current.position.y = (j["vgr.plunge"] ?? 0) * VIEW;
    const reach = (j["vgr.reach"] ?? 0) * VIEW;
    if (armGroup.current) {
      // the beam slides through the clamp: its centre trails the tip
      armGroup.current.position.z = reach - (ARM_LEN / 2) * VIEW;
    }
    if (tip.current) tip.current.position.z = reach;
  });

  return (
    <group position={base}>
      {/* fixed base plate */}
      <mesh position={[0, 6 * VIEW, 0]} receiveShadow>
        <cylinderGeometry args={[55 * VIEW, 60 * VIEW, 12 * VIEW, 28]} />
        <meshStandardMaterial color="#2f3e4e" metalness={0.5} roughness={0.5} />
      </mesh>

      {/* everything above rotates on the Drehkranz */}
      <group ref={swivel} position={[0, 12 * VIEW, 0]}>
        {/* turntable ring */}
        <mesh position={[0, 7 * VIEW, 0]}>
          <cylinderGeometry args={[42 * VIEW, 42 * VIEW, 14 * VIEW, 28]} />
          <meshStandardMaterial color="#46586b" metalness={0.6} roughness={0.4} />
        </mesh>

        {/* tower (the vertical axis) */}
        <mesh position={[0, towerH / 2, 0]} castShadow>
          <boxGeometry args={[TOWER * VIEW, towerH, TOWER * VIEW]} />
          <meshStandardMaterial color="#8a94a6" metalness={0.6} roughness={0.35} />
        </mesh>
        {/* tower cap */}
        <mesh position={[0, towerH + 6 * VIEW, 0]}>
          <boxGeometry args={[54 * VIEW, 12 * VIEW, 54 * VIEW]} />
          <meshStandardMaterial color="#57647f" metalness={0.5} roughness={0.5} />
        </mesh>

        {/* carriage riding the tower; the arm slides through its clamp */}
        <group ref={carriage}>
          <mesh position={[0, 70 * VIEW, 0]} castShadow>
            <boxGeometry args={[CLAMP_W * VIEW, CLAMP_H * VIEW, CLAMP_D * VIEW]} />
            <meshStandardMaterial color="#4aa3c8" metalness={0.3} roughness={0.6} />
          </mesh>

          {/* the horizontal arm beam, telescoping through the clamp */}
          <group ref={armGroup} position={[0, 70 * VIEW, 0]}>
            <mesh castShadow>
              <boxGeometry args={[ARM * VIEW, ARM * VIEW, ARM_LEN * VIEW]} />
              <meshStandardMaterial color="#9aa4b6" metalness={0.6} roughness={0.35} />
            </mesh>
          </group>

          {/* arm tip: suction stem + cup + carried tray, all pointing down */}
          <group ref={tip} position={[0, 70 * VIEW, 0]}>
            <mesh position={[0, -35 * VIEW, 0]}>
              <cylinderGeometry args={[6 * VIEW, 6 * VIEW, 44 * VIEW, 12]} />
              <meshStandardMaterial color="#222831" roughness={0.9} />
            </mesh>
            <mesh position={[0, -62 * VIEW, 0]}>
              <cylinderGeometry args={[16 * VIEW, 9 * VIEW, 14 * VIEW, 16]} />
              <meshStandardMaterial color="#1a1f26" roughness={0.9} />
            </mesh>
            <group position={[0, -84 * VIEW, 0]}>
              <Carrier holder="suction" />
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}
