// The sorting line: colour sensor, ejectors, Lagerstellen and the inspection camera.
//
// A renderer: the belt's travel, which ejector fires and how far, the ring light and the
// camera's exposures all come from `joints` (written by engine/CellCoordinator.ts). When the
// coordinator offers a capture (joints.camera.pending), this draws the photo from the camera's
// pose - the one thing that needs the scene - and hands the JPEG to `onPhoto`. While a dashboard
// watches (Vision QC), the same camera streams a live view to it, frame by frame, unstored.

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useJson } from "../shared/data";
import type { CadPart, CadDoc } from "../shared/model";
import type { CellJoints, Drive } from "./store/useCellStore";
import { MM, v, Solid, useBeltTexture } from "./parts";
import { FEED_MS, INSPECT_LAYER, expose, inspected, jpeg, visionChannel } from "../vision/photo";

/** the ring light's flash at the lens, candela: ~2 lx-equivalent on the cookie 27 mm below */
const FLASH = 0.004;
/** the ring light as the inspection camera sees it: six LEDs on a 20 mm ring around the lens,
    each lighting the field from 23° off the axis. Even light (a flat surface reads its own
    colour, whatever its height: the grey target and the cookie see the same light, which is
    what render.py assumes), and no glare straight back into the lens. */
const LEDS = 6, LED_TILT = Math.atan(20 / 46.5);
const LED_I = Math.PI / (LEDS * Math.cos(LED_TILT));
/** the grey reference target render.py draws in the image's top-left corner: 7.5 mm square, 50 %
    grey, on a bracket off the rear rail just upstream of the hood (the field's corners under the
    hood fall inside its walls) - in the field's corner, where the cookie never reaches */
const REF_MM = 7.5;
export type CameraDoc = { parts: CadPart[]; lens: [number, number, number]; fov_mm: number; optics: { roi_mm: number; lens_angle_deg: number } };
/** the parts under the lens that the inspection camera sees */
const HOOD = new Set(["belt_web", "belt_rail_F", "belt_rail_B"]);
export type SortJoints = Pick<CellJoints, "oven" | "sort" | "camera">;
type Shot = { n: number; label: string };

/** The sorting line: colour sensor, three pneumatic ejectors, three Lagerstellen and the
    inspection camera in the colour hood. */
export function SortingModule({ doc, joints, onPhoto }: {
  doc: CadDoc; joints: SortJoints; onPhoto?: (jpeg: Blob, empty: Blob | null, shot: Shot) => void;
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
  // direction across the belt (the photo's "up": the belt runs left to right, as in render.py's
  // images); their world positions place the photo camera
  const lens = useRef<THREE.Group>(null), aim = useRef<THREE.Group>(null), ahead = useRef<THREE.Group>(null);
  const shot = useRef<Shot | null>(null);
  const { gl, scene } = useThree();
  const W = useMemo(() => ({ eye: new THREE.Vector3(), at: new THREE.Vector3(), up: new THREE.Vector3() }), []);
  // what the inspection camera sees: the belt and its rails under the lens (the cookie puts
  // itself on the layer, FlowCookie), and the ring light, which lights only that
  const refTarget = useRef<THREE.Group>(null);
  useEffect(() => {
    const g = [hood.current, refTarget.current].filter((o): o is THREE.Group => !!o);
    g.forEach((o) => inspected.add(o));
    return () => g.forEach((o) => inspected.delete(o));
  });
  const hood = useRef<THREE.Group>(null), leds = useRef<THREE.Group>(null);
  useEffect(() => {
    leds.current?.children.forEach((l) => {
      l.layers.set(INSPECT_LAYER);
      if (aim.current) (l as THREE.DirectionalLight).target = aim.current;
    });
  });
  // the live feed: on while a dashboard says it watches (every 2 s), never stored
  const feed = useRef({ until: 0, last: 0, busy: false });
  useEffect(() => {
    const ch = visionChannel();
    if (!ch) return;
    const on = (e: MessageEvent) => { if (e.data?.type === "watch") feed.current.until = Date.now() + 5000; };
    ch.addEventListener("message", on);
    return () => ch.removeEventListener("message", on);
  }, []);

  useFrame(() => {
    const c = joints.camera;
    const now = Date.now(), F = feed.current;
    const live = now < F.until && !F.busy && now - F.last >= FEED_MS;
    // the photo of the cookie offered last frame (every part has moved to this frame's pose by
    // now), and the live view's next frame
    if ((shot.current || live) && cam && lens.current && aim.current && ahead.current) {
      lens.current.getWorldPosition(W.eye);
      aim.current.getWorldPosition(W.at);
      ahead.current.getWorldPosition(W.up).sub(W.eye).normalize();
      const field = cam.fov_mm * MM;
      const s = shot.current;
      shot.current = null;
      const img = expose(gl, scene, W.eye, W.at, W.up, field);
      if (img && s) {
        if (flash.current) flash.current.intensity = FLASH;
        // the photo, then the empty hood at the same instant (the canvas is copied as each is encoded)
        const photo = jpeg(img, 0.9);
        const plate = expose(gl, scene, W.eye, W.at, W.up, field, true);
        const empty = plate ? jpeg(plate, 0.9) : Promise.resolve(null);
        Promise.all([photo, empty]).then(([b, e]) => { if (b) onPhoto?.(b, e, s); }).catch(() => { /* a lost photo is not worth an error */ });
      } else if (img) {
        F.last = now; F.busy = true;
        // a frame of the live view: shown by the dashboard, then dropped
        jpeg(img, 0.75).then((b) => { if (b) visionChannel()?.postMessage({ type: "frame", jpeg: b, t: now, lit: c.lit > 0 }); })
          .catch(() => { /* a dropped frame */ }).finally(() => { F.busy = false; });
      }
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
      {byFrame.world.filter((p) => !HOOD.has(p.n)).map(P)}
      <group ref={hood}>{byFrame.world.filter((p) => HOOD.has(p.n)).map(P)}</group>
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
          {/* the ring light as the inspection camera sees it (its own layer: the visitor's view is untouched) */}
          <group ref={leds}>
            {Array.from({ length: LEDS }, (_, i) => {
              const a = (2 * Math.PI * i) / LEDS;
              return <directionalLight key={i} intensity={LED_I} color="#ffffff"
                position={v(cam.lens[0] + 20 * Math.cos(a), cam.lens[1] + 20 * Math.sin(a), cam.lens[2] - 1)} />;
            })}
          </group>
          {/* the grey reference target and its bracket */}
          <group ref={refTarget}>
            <mesh position={v(cam.lens[0] - cam.fov_mm / 2 + REF_MM / 2, cam.lens[1] + cam.fov_mm / 2 - REF_MM / 2, beltTop + 1.5)}>
              <boxGeometry args={[REF_MM * MM, 1 * MM, REF_MM * MM]} />
              <meshStandardMaterial color="#808080" roughness={1} metalness={0} />
            </mesh>
          </group>
          <mesh position={v(cam.lens[0] - cam.fov_mm / 2 + REF_MM / 2, cam.lens[1] + 30 + (cam.fov_mm / 2 - 30) / 2 - 1, beltTop + 0.5)}>
            <boxGeometry args={[REF_MM * MM, 1 * MM, (cam.fov_mm / 2 - 30 + 2) * MM]} />
            <meshStandardMaterial color="#9aa3ac" roughness={0.5} metalness={0.6} />
          </mesh>
          {/* the photo camera's pose: lens, the belt straight below it, the belt's direction */}
          <group ref={lens} position={v(cam.lens[0], cam.lens[1], cam.lens[2] - 0.5)} />
          <group ref={aim} position={v(cam.lens[0], cam.lens[1], beltTop)} />
          <group ref={ahead} position={v(cam.lens[0], cam.lens[1] + 10, cam.lens[2])} />
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
