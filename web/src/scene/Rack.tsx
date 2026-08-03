// The 3x3 storage rack, drawn from the scene descriptor's slot poses. Slot poses
// are the opening plane (depth y=0); the bays extend BEHIND the opening (+depth),
// so the openings face the aisle where the crane runs. Nothing here is hardcoded
// geometry - re-pitching the rack in the layout re-draws it.

import { Edges, Text } from "@react-three/drei";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import type { SceneDescriptor } from "../types";
import { Carrier } from "./Carrier";

export function Rack({ scene }: { scene: SceneDescriptor }) {
  const { rack } = scene;
  const [ex, ey, ez] = rack.slot_envelope; // width(x), depth(y), height(z) in mm
  const w = ex * VIEW;
  const depth = ey * VIEW;
  const h = ez * VIEW;

  // Bounds of the shelf block, for the surrounding frame.
  const centres = Object.values(rack.slots).map(v3a);
  const box = new THREE.Box3().setFromPoints(centres);

  const midX = (box.min.x + box.max.x) / 2;
  const midY = (box.min.y + box.max.y) / 2;
  const frameW = box.max.x - box.min.x + w + 0.06;
  const frameH = box.max.y - box.min.y + h + 0.06;

  return (
    <group>
      {/* thin back panel behind the bays (open front faces the aisle) */}
      <mesh position={[midX, midY, box.max.z + depth]}>
        <boxGeometry args={[frameW, frameH, 0.015]} />
        <meshStandardMaterial color="#243b4e" roughness={0.85} />
      </mesh>

      {Object.entries(rack.slots).map(([name, pose]) => {
        const p = v3a(pose);
        const cz = p.z + depth / 2; // bay sits behind the opening plane
        return (
          <group key={name}>
            {/* bay: near-transparent so it reads as an open shelf, bright edges */}
            <mesh position={[p.x, p.y, cz]}>
              <boxGeometry args={[w, h, depth]} />
              <meshStandardMaterial
                color="#1b3a52"
                transparent
                opacity={0.12}
                roughness={0.9}
              />
              <Edges color="#5f8fc0" />
            </mesh>
            {/* bay label on the opening face, toward the aisle */}
            <Text
              position={[p.x - w / 2 + 0.05, p.y + h / 2 - 0.03, p.z - 0.01]}
              rotation={[0, Math.PI, 0]}
              fontSize={0.05}
              color="#9fc0e0"
              anchorX="center"
            >
              {name}
            </Text>
            {/* the carrier while it rests in this bay */}
            <group position={[p.x, p.y - h / 2 + 0.04, cz]}>
              <Carrier holder={`slot:${name}`} />
            </group>
          </group>
        );
      })}
    </group>
  );
}
