// The High-Bay Warehouse stacker crane.
//
// The whole assembly is placed at the device base, which the layout offsets into
// the aisle IN FRONT of the rack (base.y = -55 mm). So the mast and carriage run
// in the aisle and never pass through a bay; only the Ausleger (the telescoping
// fork) reaches from the aisle into a bay toward the shelves (+depth).
//
// Nested groups, one per joint, each read imperatively from the hot store inside
// useFrame so the crane animates without re-rendering React:
//
//   base(aisle) -> gantry(travel, +X) -> carriage(lift, +up) -> fork(Ausleger, +depth)

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";
import { Carrier } from "./Carrier";

export function Hbw({ scene }: { scene: SceneDescriptor }) {
  const gantry = useRef<THREE.Group>(null);
  const carriage = useRef<THREE.Group>(null);
  const fork = useRef<THREE.Group>(null);
  const carriageMat = useRef<THREE.MeshStandardMaterial>(null);

  const dev = scene.devices.hbw;
  const base = v3a(dev.base);
  const railH = dev.joints.lift.limits[1] * VIEW;
  const beamW = dev.joints.travel.limits[1] * VIEW;

  useFrame(() => {
    const j = hot.joints;
    if (gantry.current) gantry.current.position.x = (j["hbw.travel"] ?? 0) * VIEW;
    if (carriage.current) carriage.current.position.y = (j["hbw.lift"] ?? 0) * VIEW;
    if (fork.current) fork.current.position.z = (j["hbw.fork"] ?? 0) * VIEW;
    // Amber glow when the carriage is lagging its command (worn/starting motor).
    if (carriageMat.current) {
      const err = Math.abs(hot.tracking_error["hbw.lift"] ?? 0) +
        Math.abs(hot.tracking_error["hbw.travel"] ?? 0);
      carriageMat.current.emissive.setHex(err > 1 ? 0x5a3a00 : 0x000000);
    }
  });

  return (
    <group position={base}>
      {/* top rail the mast travels along (fixed) */}
      <mesh position={[beamW / 2, railH + 0.05, 0]}>
        <boxGeometry args={[beamW + 0.12, 0.05, 0.07]} />
        <meshStandardMaterial color="#3c4860" metalness={0.6} roughness={0.4} />
      </mesh>
      {/* bottom rail */}
      <mesh position={[beamW / 2, 0.02, 0]}>
        <boxGeometry args={[beamW + 0.12, 0.04, 0.1]} />
        <meshStandardMaterial color="#2a3444" metalness={0.5} roughness={0.5} />
      </mesh>

      {/* travelling gantry (mast) */}
      <group ref={gantry}>
        <mesh position={[0, railH / 2, 0]} castShadow>
          <boxGeometry args={[0.07, railH, 0.07]} />
          <meshStandardMaterial color="#57647f" metalness={0.5} roughness={0.5} />
        </mesh>

        {/* lifting carriage */}
        <group ref={carriage}>
          <mesh castShadow>
            <boxGeometry args={[0.16, 0.11, 0.12]} />
            <meshStandardMaterial ref={carriageMat} color="#e0a44a" metalness={0.3} roughness={0.6} />
          </mesh>

          {/* Ausleger (telescoping fork) - a cantilever reaching toward the bays */}
          <group ref={fork}>
            <mesh position={[0, 0, 0.11]} castShadow>
              <boxGeometry args={[0.13, 0.03, 0.2]} />
              <meshStandardMaterial color="#c8783a" roughness={0.7} />
            </mesh>
            {/* two tines at the tip */}
            <mesh position={[-0.04, -0.02, 0.2]}>
              <boxGeometry args={[0.02, 0.02, 0.08]} />
              <meshStandardMaterial color="#b06a30" roughness={0.7} />
            </mesh>
            <mesh position={[0.04, -0.02, 0.2]}>
              <boxGeometry args={[0.02, 0.02, 0.08]} />
              <meshStandardMaterial color="#b06a30" roughness={0.7} />
            </mesh>
            {/* the carrier when the fork is holding it */}
            <group position={[0, 0.03, 0.2]}>
              <Carrier holder="fork" />
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}
