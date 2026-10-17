// The stage around the factory: the table, lights, camera, the precise meshes and the overlays.

import { Grid, OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";



import { HazardZones, PlcCabinet, SecurityOverlay, UpgradeParts, Wiring } from "./FactoryDetail";
import { Environment, Lightformer } from "@react-three/drei";
import { Suspense } from "react";

import { useJson } from "../shared/data";
import { PreciseLibCtx, PreciseLoader, PreciseScope, type PreciseLib } from "./Precise";

import type { CadDoc, PlanKey } from "../shared/model";
import { MM, RackBadge, v } from "./parts";
import { useCellModel, useCellStore, type CellStore, type Drive } from "./store/useCellStore";
import { CellCoordinator } from "./engine/CellCoordinator";
import { localPersistence } from "./engine/persistence";
import { PLAYBACK } from "./timeline";
import { keep } from "../vision/photo";
import type { CameraDoc } from "./SortingModule";

import { HbwCad } from "./HbwCad";
import { VgrModule } from "./VgrModule";
import { OvenModule, FlowCookie, FlowBarriers } from "./OvenModule";
import { SortingModule } from "./SortingModule";

/** The review aids in the URL: ?t=<s> or ?at=<step>[&n=2] freeze the first cycle. */
function reviewFromUrl() {
  const q = new URLSearchParams(window.location.search);
  const t = q.get("t");
  return { t: t !== null && Number.isFinite(Number(t)) ? Number(t) : null, at: q.get("at"), n: Number(q.get("n") ?? 1) };
}

/** The coordinator for this view: created once the machine and the VGR's tours are in, driven
    by ONE frame callback that runs before every renderer's (priority -1), disposed with the view.
    It keeps running the store's cell across a remount (the store outlives the view). */
function useCoordinator(doc: CadDoc, tours: Record<string, PlanKey[]> | null | undefined, store: CellStore) {
  const coord = useMemo(
    () => (tours === undefined ? null : new CellCoordinator(doc, store, { tours, persistence: localPersistence(), review: reviewFromUrl() })),
    [doc, tours, store],
  );
  useEffect(() => () => coord?.dispose(), [coord]);
  // the inspection camera's lens, in the factory frame, arms its trigger
  const { data: cam } = useJson<CameraDoc>("vision/camera.json");
  useEffect(() => {
    if (!coord || !cam) return;
    const [tx, ty] = doc.factory.sort_placement.translate;
    coord.setCamera([-cam.lens[1] + tx, cam.lens[0] + ty]);
  }, [coord, cam, doc]);
  useFrame(({ clock }, dt) => coord?.tick(clock.getElapsedTime() * PLAYBACK, dt), -1);
  return coord;
}

let visionChannel: BroadcastChannel | null = null;
/** Each capture is shown live in an open dashboard's inspection feed (Vision QC). */
function useCaptureFeed(store: CellStore) {
  useEffect(() => store.onCapture((c) => {
    try { visionChannel ??= new BroadcastChannel("stf-vision"); visionChannel.postMessage(c); } catch { /* no BroadcastChannel */ }
  }), [store]);
}

/** The white table, and on it each module's black fischertechnik base plate
    (perforated on the 15 mm ft grid), as in the booklet's cover photo. */
function FactoryTable({ doc }: { doc: CadDoc }) {
  const [fx, fy, ft] = doc.factory.plate;
  const h = 10 + ft;
  const holes = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 32; c.height = 32;
    const g = c.getContext("2d")!;
    g.fillStyle = "#2a2d31"; g.fillRect(0, 0, 32, 32);
    g.fillStyle = "#101214"; g.beginPath(); g.arc(16, 16, 6, 0, Math.PI * 2); g.fill();
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 4;
    return t;
  }, []);
  const F = doc.factory as unknown as Record<string, [number, number, number, number]>;
  const up = (doc.factory as unknown as { upgrade_rects?: Record<string, [number, number, number, number]> })
    .upgrade_rects ?? {};
  const rects = ["hbw_rect", "vgr_rect", "oven_rect", "sort_rect", "plc_rect"]
    .map((k, i) => ({ k, r: F[k], dz: i * 0.15 }))
    .concat(Object.entries(up).map(([k, r], i) => ({ k, r, dz: 0.75 + i * 0.15 })))
    .filter((q) => q.r);
  return (
    <group>
      <mesh position={v(fx / 2, fy / 2, -8 - h / 2)} receiveShadow>
        <boxGeometry args={[fx * MM, h * MM, fy * MM]} />
        <meshStandardMaterial color="#e9ebec" roughness={0.9} />
      </mesh>
      {rects.map(({ k, r, dz }) => {
        const [x, y, w, d] = r;
        const t = holes.clone();
        t.repeat.set(w / 15, d / 15);
        t.needsUpdate = true;
        return (
          <mesh key={k} position={v(x + w / 2, y + d / 2, -4 - dz)} receiveShadow>
            <boxGeometry args={[w * MM, 8 * MM, d * MM]} />
            <meshStandardMaterial map={t} color="#ffffff" roughness={0.75} />
          </mesh>
        );
      })}
    </group>
  );
}


// The precise meshes (stf-cad's web_precise export) were made from Upgrade 7's geometry.
// Upgrade 12 changes no part they hold - except the I/O nodes, which it re-placed to fit
// the interlock relays: those are drawn from the export itself (module "io-own").
const PRECISE_GLB = "precise_up7.glb";

// ?cam=x,y,z overrides the overview direction (three.js axes) for review shots
function camDir() {
  const c = new URLSearchParams(window.location.search).get("cam");
  const v = c?.split(",").map(Number);
  return v && v.length === 3 && v.every(Number.isFinite)
    // default: the booklet cover's viewpoint, from the front-left corner
    ? new THREE.Vector3(v[0], v[1], v[2]) : new THREE.Vector3(-0.78, 0.62, -0.62);
}

export function HbwCadStage({ doc, showZones = false, netZones = false, showCover = true }: {
  doc: CadDoc; showZones?: boolean; netZones?: boolean; showCover?: boolean;
}) {
  const [px, py] = doc.factory.plate;
  const [precise, setPrecise] = useState<PreciseLib | null>(null);
  // the VGR's tours for order mode (stf-cad/hbw/twin_tours.py); without them, the exported demo tour
  const { data: toursDoc, error: toursErr } = useJson<{ tours: Record<string, PlanKey[]> }>("vgr_tours.json");
  const tours = toursDoc ? toursDoc.tours : toursErr ? null : undefined;
  const store = useCellStore();
  const coord = useCoordinator(doc, tours, store);
  useCaptureFeed(store);
  const J = store.joints;
  // the rack's meshes re-render only when the rack changes
  const rack = useCellModel((m) => m.rack);
  const raw = useCellModel((m) => m.rawColour);
  const vgrDrive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  // What the camera frames: the whole table (or a ?look= review point).
  const frame = useMemo(() => {
    // review aid: ?look=x,y,r frames a factory point (mm) at radius r
    const lk = new URLSearchParams(window.location.search).get("look")?.split(",").map(Number);
    if (lk && lk.length === 3 && lk.every(Number.isFinite)) {
      return { cx: lk[0] * MM, cy: lk[1] * MM, h: 0.4, w: lk[2] * MM, d: lk[2] * MM, dir: camDir(), k: 0.6 };
    }
    return { cx: px * MM * 0.5, cy: py * MM * 0.5, h: 5.6, w: px * MM, d: py * MM,
             dir: camDir(), k: 0.52 };
  }, [px, py]);
  // The whole stage below is built in "factory-as-three" coordinates, v(x,y,z)
  // = (x, z, y). Swapping two axes is a REFLECTION, so without correction the
  // twin rendered the mirror image of the CAD model and of the real machine.
  // One mirror (scale z -1) around the stage undoes it; world z = -factory y.
  const target: [number, number, number] = [frame.cx, frame.h === 0.4 ? 0.3 : 1.9, -frame.cy];
  // Drive the Canvas' own camera rather than mounting a second one: the twin
  // view owns a <PerspectiveCamera makeDefault>, and two of them in one Canvas
  // race on mount and leave whichever lost pointing at the origin.
  const { camera, size } = useThree();
  useEffect(() => {
    const c = camera as THREE.PerspectiveCamera;
    c.fov = 42;
    c.near = 0.05;
    c.far = 200;
    // Frame the chosen envelope on BOTH axes: the viewport is much taller than
    // it is wide once the sidebar is out, so fitting on vertical fov alone puts
    // the camera inside the rack.
    const centre = new THREE.Vector3(frame.cx, frame.h * 0.42, -frame.cy);
    const radius = frame.k * Math.hypot(frame.w, frame.d, frame.h);
    const vFov = (c.fov * Math.PI) / 180;
    const aspect = Math.max(0.2, size.width / Math.max(1, size.height));
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect);
    const dist = 1.02 * Math.max(radius / Math.tan(vFov / 2), radius / Math.tan(hFov / 2));
    c.position.copy(centre).addScaledVector(frame.dir.clone().normalize(), dist);
    c.lookAt(...target);
    c.updateProjectionMatrix();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, frame, size.width, size.height]);
  return (
    <>
      <OrbitControls makeDefault target={target} enableDamping />
      <hemisphereLight args={["#dfe6ea", "#4a4a4a", 1.2]} />
      {/* studio light panels for the physically based component materials */}
      <Environment resolution={256}>
        <Lightformer intensity={2.2} position={[0, 6, 3]} scale={[12, 4, 1]} />
        <Lightformer intensity={1.2} position={[-8, 3, -2]} rotation-y={Math.PI / 2} scale={[8, 4, 1]} />
        <Lightformer intensity={1.2} position={[8, 3, 2]} rotation-y={-Math.PI / 2} scale={[8, 4, 1]} />
      </Environment>
      <directionalLight position={[7, 9, 5]} intensity={2.1} castShadow />
      <directionalLight position={[-5, 4, -4]} intensity={0.5} />
      <Grid
        args={[24, 24]}
        position={[px * MM * 0.5, -0.101, -py * MM * 0.5]}
        cellColor="#c9d0d4"
        sectionColor="#98a2a8"
        fadeDistance={26}
        infiniteGrid
      />
      {doc.upgrade && (
        <Suspense fallback={null}>
          <PreciseLoader url={`${import.meta.env.BASE_URL}${PRECISE_GLB}`} onLib={setPrecise} />
        </Suspense>
      )}
      <PreciseLibCtx.Provider value={doc.upgrade ? precise : null}>
      <group scale={[1, 1, -1]}>
      <FactoryTable doc={doc} />
      <group position={[doc.factory.vgr_at[0] * MM, 0, doc.factory.vgr_at[1] * MM]}>
        <PreciseScope module="vgr"><VgrModule doc={doc} drive={vgrDrive} joints={J.vgr} /></PreciseScope>
      </group>
      {/* the oven is rotated +90 about the factory Z like the sorting line:
          its Ofenschieber points back at the VGR, its belt runs to the front */}
      <group
        position={[doc.factory.oven_placement.translate[0] * MM, 0, doc.factory.oven_placement.translate[1] * MM]}
        rotation={[0, THREE.MathUtils.degToRad(-doc.factory.oven_placement.rotate_deg), 0]}
      >
        <PreciseScope module="oven"><OvenModule doc={doc} joints={J.oven} /></PreciseScope>
      </group>
      <group
        position={[
          doc.factory.sort_placement.translate[0] * MM, 0,
          doc.factory.sort_placement.translate[1] * MM,
        ]}
        rotation={[0, -Math.PI / 2, 0]}
      >
        <PreciseScope module="sorting">
          <SortingModule doc={doc} joints={J} onPhoto={(b, s) => void keep(b, s.label, s.n)} />
        </PreciseScope>
      </group>
      <FlowCookie workpiece={J.workpiece} />
      <FlowBarriers doc={doc} workpiece={J.workpiece} />
      <PlcCabinet parts={doc.plc.parts as never} at={doc.plc.at} />
      {doc.upgrade && <PreciseScope module="upgrade"><UpgradeParts parts={doc.upgrade.parts as never} module="upgrade" /></PreciseScope>}
      {/* the enclosure: guard frame, panels, doors and what is mounted on them */}
      {doc.safety && showCover && <UpgradeParts parts={doc.safety.parts as never} module="safety" />}
      {doc.io3 && <UpgradeParts parts={doc.io3.parts as never} module="io-own" />}
      {doc.safety && showZones && <HazardZones hazards={doc.safety.hazards} />}
      {netZones && doc.io3 && doc.safety && (
        <SecurityOverlay io={doc.io3.parts as never} plc={doc.plc as never} safety={doc.safety.parts as never}
          ips={{ hbw: "192.168.10.11", vgr: "192.168.10.12", oven: "192.168.10.13", sorting: "192.168.10.14" }} />
      )}
      <Wiring w={doc.wiring} cover={showCover} />
      {/* Rigid placement of the proven module onto the table: +90 deg about the
          factory Z, which in three is -90 deg about Y, then translate. */}
      <group
        position={[doc.factory.placement.translate[0] * MM, 0, doc.factory.placement.translate[1] * MM]}
        rotation={[0, -Math.PI / 2, 0]}
      >
        {coord && (
          <>
            <PreciseScope module="hbw"><HbwCad doc={doc} joints={J} slots={rack} /></PreciseScope>
            <RackBadge doc={doc} rack={rack} raw={raw} />
          </>
        )}
      </group>
      </group>
      </PreciseLibCtx.Provider>
    </>
  );
}
