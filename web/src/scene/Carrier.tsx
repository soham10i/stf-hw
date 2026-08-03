// The workpiece carrier (a tray holding a coloured "cookie"). One instance is
// parented into each place the carrier can be - fork, belt, suction, delivery,
// bay - and each shows itself only when the live carrier holder matches, reading
// hot.carrier inside useFrame so visibility tracks the sim without React.

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { hot } from "../store";

export const FLAVOR_COLOR: Record<string, string> = {
  CHOCO: "#7b4b2a",
  VANILLA: "#e6d08a",
  STRAWBERRY: "#d06074",
};

export function Carrier({ holder }: { holder: string }) {
  const group = useRef<THREE.Group>(null);
  const cookie = useRef<THREE.MeshStandardMaterial>(null);

  useFrame(() => {
    const c = hot.carrier;
    const show = c.holder === holder;
    if (group.current) group.current.visible = show;
    if (show && cookie.current && c.flavor) {
      cookie.current.color.set(FLAVOR_COLOR[c.flavor] ?? "#cccccc");
    }
  });

  return (
    <group ref={group} visible={false}>
      {/* tray */}
      <mesh castShadow>
        <boxGeometry args={[0.075, 0.025, 0.075]} />
        <meshStandardMaterial color="#cfd6dd" roughness={0.7} />
      </mesh>
      {/* cookie */}
      <mesh position={[0, 0.028, 0]} castShadow>
        <cylinderGeometry args={[0.026, 0.026, 0.02, 20]} />
        <meshStandardMaterial ref={cookie} color="#7b4b2a" roughness={0.6} />
      </mesh>
    </group>
  );
}
