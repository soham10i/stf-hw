// Assembles the full scene: lights, floor grid, and the four subsystems, all
// positioned from the scene descriptor.

import { Grid, OrbitControls } from "@react-three/drei";
import { Conveyor } from "./Conveyor";
import { Hbw } from "./Hbw";
import { Rack } from "./Rack";
import { Vgr } from "./Vgr";
import type { SceneDescriptor } from "../types";

export function Factory({ scene }: { scene: SceneDescriptor }) {
  return (
    <>
      <color attach="background" args={["#0b0f14"]} />
      <ambientLight intensity={0.5} />
      <directionalLight position={[4, 6, 3]} intensity={1.1} castShadow />
      <directionalLight position={[-3, 4, -2]} intensity={0.4} />

      <Grid
        args={[12, 12]}
        cellSize={0.5}
        cellColor="#1c2a38"
        sectionSize={1}
        sectionColor="#2c4053"
        position={[2, 0, 1]}
        infiniteGrid
        fadeDistance={18}
      />

      <Rack scene={scene} />
      <Hbw scene={scene} />
      <Vgr scene={scene} />
      <Conveyor scene={scene} />

      <OrbitControls target={[2, 1.2, 1]} enableDamping />
    </>
  );
}
