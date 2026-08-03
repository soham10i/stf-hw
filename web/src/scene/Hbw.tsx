// The High-Bay Warehouse stacker crane.
//
// Three nested groups, one per joint, each reading its live position from the
// mutable `hot` store inside useFrame - never through React state, so the crane
// animates at the render rate without re-rendering the component tree.
//
//   gantry (travel, +X)  ->  carriage (lift, +Z/up)  ->  fork (fork, +Y/depth)

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { VIEW } from "../coords";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";

export function Hbw({ scene }: { scene: SceneDescriptor }) {
  const gantry = useRef<THREE.Group>(null);
  const carriage = useRef<THREE.Group>(null);
  const fork = useRef<THREE.Group>(null);
  const forkMat = useRef<THREE.MeshStandardMaterial>(null);

  const dev = scene.devices.hbw;
  const liftMax = dev.joints.lift.limits[1];
  const travelMax = dev.joints.travel.limits[1];

  useFrame(() => {
    const j = hot.joints;
    if (gantry.current) gantry.current.position.x = (j["hbw.travel"] ?? 0) * VIEW;
    if (carriage.current) carriage.current.position.y = (j["hbw.lift"] ?? 0) * VIEW;
    if (fork.current) fork.current.position.z = (j["hbw.fork"] ?? 0) * VIEW;
    // Tint the fork when it is carrying tracking error - a worn motor lagging
    // its command shows up as the fork glowing amber.
    if (forkMat.current) {
      const err = Math.abs(hot.tracking_error["hbw.fork"] ?? 0);
      forkMat.current.emissive.setHex(err > 1 ? 0x664400 : 0x000000);
    }
  });

  const railH = liftMax * VIEW;
  const beamW = travelMax * VIEW;

  return (
    <group>
      {/* fixed horizontal beam the carriage travels along */}
      <mesh position={[beamW / 2, railH + 0.06, 0]}>
        <boxGeometry args={[beamW + 0.1, 0.05, 0.08]} />
        <meshStandardMaterial color="#44506a" metalness={0.6} roughness={0.4} />
      </mesh>

      {/* travelling gantry */}
      <group ref={gantry}>
        {/* vertical mast */}
        <mesh position={[0, railH / 2, 0]}>
          <boxGeometry args={[0.06, railH, 0.06]} />
          <meshStandardMaterial color="#5a6785" metalness={0.5} roughness={0.5} />
        </mesh>

        {/* lifting carriage */}
        <group ref={carriage}>
          <mesh>
            <boxGeometry args={[0.14, 0.1, 0.14]} />
            <meshStandardMaterial color="#e0a44a" metalness={0.3} roughness={0.6} />
          </mesh>

          {/* telescoping fork */}
          <group ref={fork}>
            <mesh position={[0, 0, 0.08]}>
              <boxGeometry args={[0.1, 0.03, 0.16]} />
              <meshStandardMaterial ref={forkMat} color="#c8783a" roughness={0.7} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}
