// Assembles the full scene: a coloured table-top platform, lights, the rack, the
// stacker crane in its aisle, the conveyor and the vacuum gripper - all
// positioned from the scene descriptor so the arrangement follows the layout.

import { Grid, OrbitControls, PerspectiveCamera } from "@react-three/drei";
import * as THREE from "three";
import { v3a } from "../coords";
import type { SceneDescriptor } from "../types";
import { Conveyor } from "./Conveyor";
import { Hbw } from "./Hbw";
import { Rack } from "./Rack";
import { Vgr } from "./Vgr";

// Ground footprint (in three units) spanning the whole machine, so the platform
// sits under the rack, the aisle, the conveyor and the gripper.
function footprint(scene: SceneDescriptor) {
  const pts: THREE.Vector3[] = [
    ...Object.values(scene.rack.slots).map(v3a),
    v3a(scene.conveyor.pose),
    ...Object.values(scene.devices).map((d) => v3a(d.base)),
  ];
  const box = new THREE.Box3().setFromPoints(pts);
  const pad = 0.6;
  return {
    minX: box.min.x - pad,
    maxX: box.max.x + pad,
    minZ: box.min.z - pad,
    maxZ: box.max.z + pad,
  };
}

export function Factory({ scene }: { scene: SceneDescriptor }) {
  const fp = footprint(scene);
  const w = fp.maxX - fp.minX;
  const d = fp.maxZ - fp.minZ;
  const cx = (fp.minX + fp.maxX) / 2;
  const cz = (fp.minZ + fp.maxZ) / 2;

  return (
    <>
      <color attach="background" args={["#0b0f14"]} />
      {/* View from the aisle/output side: the rack openings face the aisle
          (negative depth), so the camera sits on that side to look into the bays
          and down the flow crane -> conveyor -> gripper. */}
      <PerspectiveCamera
        makeDefault
        fov={40}
        position={[fp.maxX + 2.8, 4.6, fp.minZ - 2.8]}
      />
      <ambientLight intensity={0.6} />
      <directionalLight position={[4, 8, -4]} intensity={1.15} castShadow />
      <directionalLight position={[-3, 5, 3]} intensity={0.4} />

      {/* table-top platform under the whole warehouse */}
      <mesh position={[cx, -0.03, cz]} receiveShadow>
        <boxGeometry args={[w, 0.05, d]} />
        <meshStandardMaterial color="#182634" roughness={0.85} metalness={0.1} />
      </mesh>
      {/* subtle inset panel so the surface reads as a worktable */}
      <mesh position={[cx, 0.002, cz]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[w - 0.12, d - 0.12]} />
        <meshStandardMaterial color="#1e3346" roughness={0.7} />
      </mesh>

      <Grid
        args={[w, d]}
        position={[cx, 0.006, cz]}
        cellSize={0.5}
        cellColor="#243a4e"
        sectionSize={1}
        sectionColor="#31506a"
        fadeDistance={22}
        fadeStrength={1.5}
      />

      <Rack scene={scene} />
      <Hbw scene={scene} />
      <Vgr scene={scene} />
      <Conveyor scene={scene} />

      <OrbitControls target={[cx, 0.9, cz]} enableDamping maxPolarAngle={Math.PI / 2.05} />
    </>
  );
}
