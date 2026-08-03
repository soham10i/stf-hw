// The 3x3 storage rack, drawn from the scene descriptor's slot poses. Slots are
// the single source of truth from the layout - nothing here is hardcoded, so
// re-pitching the rack in YAML re-draws it here with no code change.

import { Edges, Text } from "@react-three/drei";
import { VIEW, v3a } from "../coords";
import type { SceneDescriptor } from "../types";

export function Rack({ scene }: { scene: SceneDescriptor }) {
  const { rack } = scene;
  const [ex, ey, ez] = rack.slot_envelope;

  return (
    <group>
      {Object.entries(rack.slots).map(([name, pose]) => {
        const p = v3a(pose);
        return (
          <group key={name} position={p}>
            <mesh>
              <boxGeometry args={[ex * VIEW, ez * VIEW, ey * VIEW]} />
              <meshStandardMaterial color="#16232f" transparent opacity={0.3} roughness={0.9} />
              <Edges color="#3d5a7a" />
            </mesh>
            <Text
              position={[0, (ez * VIEW) / 2 + 0.05, 0]}
              fontSize={0.06}
              color="#8fb3d9"
              anchorX="center"
            >
              {name}
            </Text>
          </group>
        );
      })}
    </group>
  );
}
