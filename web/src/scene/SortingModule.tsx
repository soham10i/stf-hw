// The sorting line: colour sensor, ejectors, Lagerstellen and the inspection camera.
//
// A renderer: the belt's travel, which ejector fires and how far, the ring light and the
// camera's exposures all come from `joints` (written by engine/CellCoordinator.ts). When the
// coordinator offers a capture (joints.camera.pending), this draws the photo from the camera's
// pose - the one thing that needs the scene - and hands the JPEG to `onPhoto`.

import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useJson } from "../shared/data";
import type { CadPart, CadDoc } from "../shared/model";
import type { CellJoints, Drive } from "./store/useCellStore";
import { MM, v, Solid, useBeltTexture } from "./parts";
import { photograph } from "../vision/photo";

/** the ring light's flash at the lens, candela: ~2 lx-equivalent on the cookie 27 mm below */
const FLASH = 0.004;
export type CameraDoc = { parts: CadPart[]; lens: [number, number, number]; optics: { roi_mm: number; lens_angle_deg: number } };
export type SortJoints = Pick<CellJoints, "oven" | "sort" | "camera">;
type Shot = { n: number; label: string };

/** The sorting line: colour sensor, three pneumatic ejectors, three Lagerstellen and the
    inspection camera in the colour hood. */
export function SortingModule({ doc, joints, onPhoto }: {
  doc: CadDoc; joints: SortJoints; onPhoto?: (jpeg: Blob, shot: Shot) => void;
}) {
  const pushes = [useRef<THREE.Group>(null), useRef<THREE.Group>(null), useRef<THREE.Group>(null)];
  const drive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  const cols = doc.sorting.colours;
  const sign = doc.sorting.joints.push.axis === "-y" ? -1 : 1;
  const byFrame = useMemo(() => {
    const m: Record<string, CadPart[]> = { world: [], push0: [], push1: [], push2: [] };
    for (const p of doc.sorting.parts) {
      if (cols.some((c) => p.n.startsWith(`wp_${c}_`))) continue;
      m[p.f].push(p);
    }
    return m;
  }, [doc, cols]);
  const tex = useBeltTexture();
  const { data: cam } = useJson<CameraDoc>("vision/camera.json");
  const ring = useRef<THREE.MeshStandardMaterial>(null);
  const cone = useRef<THREE.Mesh>(null), ringMesh = useRef<THREE.Mesh>(null);
  const flash = useRef<THREE.PointLight>(null);
  // the camera's pose as markers in the line's own frame: the lens, the belt below it, and the
  // belt's direction (the photo's "up"); their world positions place the photo camera
  const lens = useRef<THREE.Group>(null), aim = useRef<THREE.Group>(null), ahead = useRef<THREE.Group>(null);
  const shot = useRef<Shot | null>(null);
  const { gl, scene } = useThree();
  const W = useMemo(() => ({ eye: new THREE.Vector3(), at: new THREE.Vector3(), up: new THREE.Vector3() }), []);

  useFrame(() => {
    const c = joints.camera;
    // the photo of the cookie offered last frame (every part has moved to this frame's pose by
    // now), lit by the ring light's flash
    if (shot.current && cam && lens.current && aim.current && ahead.current) {
      const s = shot.current;
      shot.current = null;
      lens.current.getWorldPosition(W.eye);
      aim.current.getWorldPosition(W.at);
      ahead.current.getWorldPosition(W.up).sub(W.eye).normalize();
      if (flash.current) flash.current.intensity = FLASH;
      // the view cone and the ring light are drawn for the visitor, not seen by the camera
      if (cone.current) cone.current.visible = false;
      if (ringMesh.current) ringMesh.current.visible = false;
      const photo = photograph(gl, scene, W.eye, W.at, cam.optics.lens_angle_deg, W.up);
      if (cone.current) cone.current.visible = true;
      if (ringMesh.current) ringMesh.current.visible = true;
      photo
        .then((b) => { if (b) onPhoto?.(b, s); })
        .catch(() => { /* a lost photo is not worth an error */ });
    }
    if (c.pending) shot.current = c.pending;
    if (ring.current) ring.current.emissiveIntensity = 0.15 + 3 * c.lit;
    if (flash.current) flash.current.intensity = FLASH * c.lit;
    // the sorting belt starts when the cookie reaches it (I2) and stops after it has been
    // ejected; only the cookie's own ejector fires
    drive.current.belt = joints.oven.beltSort;
    for (let i = 0; i < 3; i++) {
      const g = pushes[i].current;
      if (g) g.position.z = sign * (i === joints.sort.ejector ? joints.oven.eject : 0) * MM;
    }
  });
  const P = (p: CadPart) => <Solid key={p.n} part={p} drive={drive} pitch={4} tex={tex} />;
  const belt = doc.sorting.parts.find((p) => p.n === "belt_web");
  const beltTop = belt ? belt.p[2] + (belt.s[2] as number) : 45;
  return (
    <group>
      {byFrame.world.map(P)}
      {cam && (
        <group>
          {cam.parts.filter((p) => p.n !== "cam_ring_light").map(P)}
          {/* the ring light, lit while the camera exposes */}
          <mesh ref={ringMesh} position={v(cam.lens[0], cam.lens[1], cam.lens[2] + 3)}>
            <cylinderGeometry args={[20 * MM, 20 * MM, 6 * MM, 32]} />
            <meshStandardMaterial ref={ring} color="#e8eef7" emissive="#cfe4ff" emissiveIntensity={0.15} />
          </mesh>
          {/* the ring light's flash: lights the inside of the hood for the exposure */}
          <pointLight ref={flash} position={v(cam.lens[0], cam.lens[1], cam.lens[2] - 4)} intensity={0} distance={0.25} decay={2} color="#eef4ff" />
          {/* the photo camera's pose: lens, the belt straight below it, the belt's direction */}
          <group ref={lens} position={v(cam.lens[0], cam.lens[1], cam.lens[2] - 0.5)} />
          <group ref={aim} position={v(cam.lens[0], cam.lens[1], beltTop)} />
          <group ref={ahead} position={v(cam.lens[0] + 10, cam.lens[1], cam.lens[2])} />
          {/* what the camera sees: from the lens down to the inspected area on the belt */}
          <mesh ref={cone} position={v(cam.lens[0], cam.lens[1], (cam.lens[2] + beltTop) / 2)} rotation={[0, Math.PI / 4, 0]}>
            <cylinderGeometry args={[4 * MM, (cam.optics.roi_mm / Math.SQRT2) * MM, (cam.lens[2] - beltTop) * MM, 4, 1, true]} />
            <meshBasicMaterial color="#7cc3f5" transparent opacity={0.12} side={THREE.DoubleSide} depthWrite={false} />
          </mesh>
        </group>
      )}
      {[0, 1, 2].map((i) => (
        <group key={i} ref={pushes[i]}>
          {byFrame[`push${i}`].map(P)}
        </group>
      ))}
    </group>
  );
}
