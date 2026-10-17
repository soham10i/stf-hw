// The sorting line: colour sensor, ejectors, Lagerstellen and the inspection camera.


import { useFrame, useThree } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";







import { useJson } from "../shared/data";


import type { CadPart, CadDoc } from "../shared/model";
import { twinOrders, cycleHot, Drive, sortHot, visionHot, bayHot, ovenHot } from "./hot";
import { MM, v, Solid, Cookie, useBeltTexture } from "./parts";
import { binColour } from "./timeline";
import { keep, photograph } from "../vision/photo";




let visionChannel: BroadcastChannel | null = null;
/** the ring light's flash at the lens, candela: ~2 lx-equivalent on the cookie 27 mm below */
const FLASH = 0.004;
type CameraDoc = { parts: CadPart[]; lens: [number, number, number]; optics: { roi_mm: number; lens_angle_deg: number } };
/** The sorting line: colour sensor, three pneumatic ejectors, three Lagerstellen.
    Its belt runs with the travelling cookie and only the ejector of the cookie's
    own bin fires. The cookie the VGR collects leaves its Lagerstelle. */
export function SortingModule({ doc }: { doc: CadDoc }) {
  const pushes = [useRef<THREE.Group>(null), useRef<THREE.Group>(null), useRef<THREE.Group>(null)];
  const stock = useRef<Record<string, THREE.Group | null>>({});
  const drive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  const cols = doc.sorting.colours;
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
  const near = useRef(false);
  // the camera's pose as markers in the line's own frame: the lens, the belt below it, and the
  // belt's direction (the photo's "up"); their world positions place the photo camera
  const lens = useRef<THREE.Group>(null), aim = useRef<THREE.Group>(null), ahead = useRef<THREE.Group>(null);
  const shot = useRef<{ flavour: string; n: number } | null>(null);
  const { gl, scene } = useThree();
  const W = useMemo(() => ({ eye: new THREE.Vector3(), at: new THREE.Vector3(), up: new THREE.Vector3() }), []);
  // the lens in the factory frame (sorting -> factory: x' = -y + tx, y' = x + ty)
  const lensF = useMemo(() => cam && [-cam.lens[1] + doc.factory.sort_placement.translate[0],
    cam.lens[0] + doc.factory.sort_placement.translate[1]], [cam, doc]);
  useFrame((_, dt) => {
    // the photo of the cookie that crossed the lens's axis last frame (every part has moved
    // to this frame's pose by now), lit by the ring light's flash
    if (shot.current && cam && lens.current && aim.current && ahead.current) {
      const { flavour, n } = shot.current;
      shot.current = null;
      lens.current.getWorldPosition(W.eye);
      aim.current.getWorldPosition(W.at);
      ahead.current.getWorldPosition(W.up).sub(W.eye).normalize();
      if (flash.current) flash.current.intensity = FLASH;
      // the view cone and the ring light are drawn for the visitor, not seen by the camera
      const hide = [cone.current, ringMesh.current].filter((m): m is THREE.Mesh => !!m);
      hide.forEach((m) => { m.visible = false; });
      const photo = photograph(gl, scene, W.eye, W.at, cam.optics.lens_angle_deg, W.up);
      hide.forEach((m) => { m.visible = true; });
      photo
        .then((b) => { if (b) void keep(b, flavour, n); })
        .catch(() => { /* a lost photo is not worth an error */ });
    }
    // a capture: the travelling cookie crosses the lens's axis on the sorting belt
    if (lensF) {
      const [x, y] = ovenHot.pos;
      const under = ovenHot.visible && Math.hypot(x - lensF[0], y - lensF[1]) < 6;
      if (under && !near.current) {
        visionHot.captures++;
        visionHot.lit = 1;
        const c = { n: visionHot.captures, flavour: twinOrders.cycle.flavour, t: performance.now() };
        visionHot.listeners.forEach((f) => f(c));
        shot.current = { flavour: c.flavour, n: c.n };
        // an open dashboard shows this cookie in its live inspection feed
        try { visionChannel ??= new BroadcastChannel("stf-vision"); visionChannel.postMessage({ flavour: c.flavour, n: c.n }); } catch { /* no BroadcastChannel */ }
      }
      near.current = under;
      visionHot.lit = Math.max(0, visionHot.lit - dt * 4);
      if (ring.current) ring.current.emissiveIntensity = 0.15 + 3 * visionHot.lit;
      if (flash.current) flash.current.intensity = FLASH * visionHot.lit;
    }
    const s = ovenHot.s;
    // the sorting belt starts when the cookie reaches it (I2) and stops after it
    // has been ejected; before that it stands still
    drive.current.belt = ovenHot.belts.sort;
    pushes.forEach((r, i) => {
      if (r.current) r.current.position.x = 0;
      const sign = doc.sorting.joints.push.axis === "-y" ? -1 : 1;
      if (r.current) r.current.position.z = sign * (s && cols[i] === cycleHot.bin ? s.eject : 0) * MM;
    });
    // a Lagerstelle shows its oldest finished cookie, unless the VGR has just collected it
    for (const c of cols) {
      const g = stock.current[c];
      const left = (twinOrders.bays[c] ?? []).length - (sortHot.taken === c ? 1 : 0);
      if (g) g.visible = left > 0;
      bayHot[c].colour = binColour(doc, c);
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
      {cols.map((c) => {
        const body = doc.sorting.parts.find((p) => p.n === `wp_${c}_body`);
        if (!body) return null;
        return (
          <group key={c} ref={(g) => { stock.current[c] = g; }} visible={false}>
            <Cookie x={body.p[0]} y={body.p[1]} z={body.p[2]} hot={bayHot[c]} />
          </group>
        );
      })}
      {[0, 1, 2].map((i) => (
        <group key={i} ref={pushes[i]}>
          {byFrame[`push${i}`].map(P)}
        </group>
      ))}
    </group>
  );
}
