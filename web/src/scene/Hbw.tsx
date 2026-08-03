// The High-Bay Warehouse stacker crane (Hochregalbediengeraet).
//
// Per Abbildung 7: the rack is at the back, the crane travels in the middle
// lane, and the conveyor runs parallel along the front. The mast rides a bottom
// rail and a top rail (visible connections at both ends); the carriage is a
// housing that WRAPS the mast; the Ausleger is a cantilever table centred under
// the carriage that slides both ways - forward (+depth) into a rack bay,
// backward (-depth) over the belt.
//
// All dimensions are millimetres scaled by VIEW, so proportions stay honest.
//
//   base(lane) -> gantry(travel, +X) -> carriage(lift, up) -> table(fork, +/-depth)

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";
import { Carrier } from "./Carrier";

// mm
const MAST = 30; // mast profile
const RAIL_W = 60; // bottom rail width (depth direction)
const CAR_W = 96;
const CAR_H = 44;
const CAR_D = 46; // carriage housing wraps the 30mm mast
const TABLE_W = 84;
const TABLE_T = 8;
const TABLE_D = 90; // cantilever table

export function Hbw({ scene }: { scene: SceneDescriptor }) {
  const gantry = useRef<THREE.Group>(null);
  const carriage = useRef<THREE.Group>(null);
  const fork = useRef<THREE.Group>(null);
  const housingMat = useRef<THREE.MeshStandardMaterial>(null);

  const dev = scene.devices.hbw;
  const base = v3a(dev.base);
  const travelMax = dev.joints.travel.limits[1];
  const liftMax = dev.joints.lift.limits[1];

  const mastH = (liftMax + 140) * VIEW;
  const railLen = (travelMax + 140) * VIEW;
  const railMid = (travelMax / 2) * VIEW;

  useFrame(() => {
    const j = hot.joints;
    if (gantry.current) gantry.current.position.x = (j["hbw.travel"] ?? 0) * VIEW;
    if (carriage.current) carriage.current.position.y = (j["hbw.lift"] ?? 0) * VIEW;
    if (fork.current) fork.current.position.z = (j["hbw.fork"] ?? 0) * VIEW;
    if (housingMat.current) {
      const err =
        Math.abs(hot.tracking_error["hbw.lift"] ?? 0) +
        Math.abs(hot.tracking_error["hbw.travel"] ?? 0);
      housingMat.current.emissive.setHex(err > 1 ? 0x5a3a00 : 0x000000);
    }
  });

  return (
    <group position={base}>
      {/* bottom rail the mast foot rides */}
      <mesh position={[railMid, 12 * VIEW, 0]} receiveShadow>
        <boxGeometry args={[railLen, 24 * VIEW, RAIL_W * VIEW]} />
        <meshStandardMaterial color="#2a3444" metalness={0.5} roughness={0.5} />
      </mesh>
      {/* top rail the mast head glides along */}
      <mesh position={[railMid, mastH + 12 * VIEW, 0]}>
        <boxGeometry args={[railLen, 24 * VIEW, 30 * VIEW]} />
        <meshStandardMaterial color="#3c4860" metalness={0.6} roughness={0.4} />
      </mesh>

      {/* travelling gantry */}
      <group ref={gantry}>
        {/* mast column */}
        <mesh position={[0, mastH / 2, 0]} castShadow>
          <boxGeometry args={[MAST * VIEW, mastH, MAST * VIEW]} />
          <meshStandardMaterial color="#8a94a6" metalness={0.6} roughness={0.35} />
        </mesh>
        {/* foot shoe on the bottom rail */}
        <mesh position={[0, 26 * VIEW, 0]} castShadow>
          <boxGeometry args={[70 * VIEW, 28 * VIEW, (RAIL_W + 14) * VIEW]} />
          <meshStandardMaterial color="#57647f" metalness={0.5} roughness={0.5} />
        </mesh>
        {/* head glider clamped to the top rail */}
        <mesh position={[0, mastH + 12 * VIEW, 0]}>
          <boxGeometry args={[54 * VIEW, 30 * VIEW, 44 * VIEW]} />
          <meshStandardMaterial color="#57647f" metalness={0.5} roughness={0.5} />
        </mesh>

        {/* lifting carriage: housing wraps the mast */}
        <group ref={carriage}>
          <mesh position={[0, (CAR_H / 2 + TABLE_T) * VIEW, 0]} castShadow>
            <boxGeometry args={[CAR_W * VIEW, CAR_H * VIEW, CAR_D * VIEW]} />
            <meshStandardMaterial
              ref={housingMat}
              color="#e0a44a"
              metalness={0.3}
              roughness={0.6}
            />
          </mesh>
          {/* slide guide under the housing that the table runs in */}
          <mesh position={[0, (TABLE_T + 3) * VIEW, 0]}>
            <boxGeometry args={[(TABLE_W + 10) * VIEW, 6 * VIEW, 40 * VIEW]} />
            <meshStandardMaterial color="#7a5a2a" roughness={0.7} />
          </mesh>

          {/* Ausleger: cantilever table, slides +/- depth; tray rides centred */}
          <group ref={fork}>
            <mesh position={[0, -TABLE_T / 2 * VIEW, 0]} castShadow>
              <boxGeometry args={[TABLE_W * VIEW, TABLE_T * VIEW, TABLE_D * VIEW]} />
              <meshStandardMaterial color="#c8783a" roughness={0.7} />
            </mesh>
            <group position={[0, 14 * VIEW, 0]}>
              <Carrier holder="fork" />
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}
