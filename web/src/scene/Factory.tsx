// Assembles the full scene: a coloured table-top platform, lights, the rack, the
// stacker crane in its aisle, the conveyor and the vacuum gripper - all
// positioned from the scene descriptor so the arrangement follows the layout.

import { Grid, OrbitControls, PerspectiveCamera } from "@react-three/drei";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import type { SceneDescriptor } from "../types";
import { Carrier } from "./Carrier";
import { Conveyor } from "./Conveyor";
import { Hbw } from "./Hbw";
import { Rack } from "./Rack";
import { Vgr } from "./Vgr";

// Where the VGR arm sets the carrier down at "delivery": its base, plus the arm
// tip (reach + plunge) rotated by the delivery swivel angle. Computed from the
// layout so the delivery pad tracks the arm's actual placement pose.
function deliveryPoint(scene: SceneDescriptor): THREE.Vector3 {
  const vgr = scene.devices.vgr;
  const swivelDeg = vgr.joints.swivel.positions.delivery ?? 0;
  const reach = (vgr.joints.reach.positions.conveyor ?? 0) * VIEW;
  const plunge = (vgr.joints.plunge.positions.pick ?? 0) * VIEW;
  const local = new THREE.Vector3(0, plunge, reach).applyAxisAngle(
    new THREE.Vector3(0, 1, 0),
    -THREE.MathUtils.degToRad(swivelDeg),
  );
  return v3a(vgr.base).add(local);
}

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

      {/* delivery stand where the gripper sets the finished carrier down */}
      {(() => {
        const dp = deliveryPoint(scene);
        return (
          <group>
            <mesh position={[dp.x, dp.y / 2, dp.z]}>
              <boxGeometry args={[0.12, dp.y, 0.12]} />
              <meshStandardMaterial color="#243b4e" roughness={0.85} />
            </mesh>
            <mesh position={[dp.x, dp.y + 0.01, dp.z]}>
              <boxGeometry args={[0.16, 0.02, 0.16]} />
              <meshStandardMaterial color="#31506a" roughness={0.7} />
            </mesh>
            <group position={[dp.x, dp.y + 0.04, dp.z]}>
              <Carrier holder="delivery" />
            </group>
          </group>
        );
      })()}

      <OrbitControls target={[cx, 0.9, cz]} enableDamping maxPolarAngle={Math.PI / 2.05} />
    </>
  );
}
