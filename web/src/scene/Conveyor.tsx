// The belt bridging the two robots, plus its light-barrier and trail sensors.
// The belt body and sensor positions come from the scene descriptor; the sensor
// lamps and the travelling workpiece read live state from `hot`.

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { VIEW, v3a } from "../coords";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";

const AXIS_UNIT: Record<string, THREE.Vector3> = {
  "+y": new THREE.Vector3(0, 0, 1),
  "-y": new THREE.Vector3(0, 0, -1),
  "+x": new THREE.Vector3(1, 0, 0),
  "-x": new THREE.Vector3(-1, 0, 0),
};

export function Conveyor({ scene }: { scene: SceneDescriptor }) {
  const { conveyor } = scene;
  const origin = v3a(conveyor.pose);
  const dir = AXIS_UNIT[conveyor.axis] ?? AXIS_UNIT["-y"];
  const workpiece = useRef<THREE.Mesh>(null);
  const sensorLamps = useRef<Record<string, THREE.MeshStandardMaterial | null>>({});

  const len = conveyor.length * VIEW;
  const wid = conveyor.width * VIEW;

  // belt centre is half its length along the run direction from local 0
  const centre = origin.clone().add(dir.clone().multiplyScalar(len / 2));

  useFrame(() => {
    // workpiece rides the belt when one is present
    if (workpiece.current) {
      const s = hot.belt.object;
      if (s === null) {
        workpiece.current.visible = false;
      } else {
        workpiece.current.visible = true;
        const p = origin.clone().add(dir.clone().multiplyScalar(s * VIEW));
        workpiece.current.position.set(p.x, p.y + 0.05, p.z);
      }
    }
    // sensor lamps: red when triggered
    for (const [name, mat] of Object.entries(sensorLamps.current)) {
      if (mat) {
        const on = hot.sensors[name] ?? false;
        mat.color.setHex(on ? 0xff4444 : 0x224422);
        mat.emissive.setHex(on ? 0x551111 : 0x000000);
      }
    }
  });

  // Legs at each end so the raised belt stands on the table rather than floating.
  const legs = [origin, origin.clone().add(dir.clone().multiplyScalar(len))];

  return (
    <group>
      {/* belt body */}
      <mesh position={centre} castShadow>
        <boxGeometry args={[wid, 0.05, len]} />
        <meshStandardMaterial color="#2c3540" metalness={0.2} roughness={0.8} />
      </mesh>
      {/* side rails */}
      {[-1, 1].map((s) => {
        const off = new THREE.Vector3(dir.z, 0, -dir.x).multiplyScalar((s * wid) / 2);
        return (
          <mesh key={s} position={centre.clone().add(off).add(new THREE.Vector3(0, 0.03, 0))}>
            <boxGeometry args={[0.015, 0.04, len]} />
            <meshStandardMaterial color="#3a4658" metalness={0.4} roughness={0.6} />
          </mesh>
        );
      })}

      {/* support legs down to the table */}
      {legs.map((p, i) => (
        <mesh key={i} position={[p.x, p.y / 2, p.z]}>
          <boxGeometry args={[wid, p.y, 0.04]} />
          <meshStandardMaterial color="#212c38" roughness={0.9} />
        </mesh>
      ))}

      {/* workpiece on the belt */}
      <mesh ref={workpiece} visible={false} castShadow>
        <boxGeometry args={[0.06, 0.06, 0.06]} />
        <meshStandardMaterial color="#d9a441" />
      </mesh>

      {/* sensor lamps at their positions along the belt */}
      {Object.entries(conveyor.sensors).map(([name, s]) => {
        if (s.at_mm === null) return null;
        const p = origin.clone().add(dir.clone().multiplyScalar(s.at_mm * VIEW));
        return (
          <mesh key={name} position={[p.x, p.y + 0.06, p.z]}>
            <sphereGeometry args={[0.018, 12, 12]} />
            <meshStandardMaterial
              ref={(m) => (sensorLamps.current[name] = m)}
              color="#224422"
            />
          </mesh>
        );
      })}

    </group>
  );
}
