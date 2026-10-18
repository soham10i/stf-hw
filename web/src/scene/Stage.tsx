// The stage around the factory: the table, lights, camera, the precise meshes and the overlays.

import { postRecord } from "../shared/records";
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
import { MM, RackBadge, TrimsCtx, v } from "./parts";
import { jointTrims } from "./joints";
import { useCellModel, useCellStore, type CellStore, type Drive } from "./store/useCellStore";
import { CellCoordinator } from "./engine/CellCoordinator";
import { localPersistence } from "./engine/persistence";
import { PLAYBACK } from "./timeline";
import { FOCUS, getViewInset, useFocus, type FocusId } from "./focus";
import { markStageReady } from "./stageReady";
import { keep } from "../vision/photo";
import { judge } from "../vision/inspect";
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

/** What a focus frames: the whole table, a module's rect on it, or a ?look= review point. */
function frameOf(doc: CadDoc, id: FocusId) {
  const [px, py] = doc.factory.plate;
  // review aid: ?look=x,y,r frames a factory point (mm) at radius r
  const lk = new URLSearchParams(window.location.search).get("look")?.split(",").map(Number);
  if (id === "overview" && lk && lk.length === 3 && lk.every(Number.isFinite)) {
    return { cx: lk[0] * MM, cy: lk[1] * MM, h: 0.4, w: lk[2] * MM, d: lk[2] * MM, k: 0.6, y: 0.3 };
  }
  const r = (doc.factory as unknown as Record<string, [number, number, number, number] | undefined>)[FOCUS.find((f) => f.id === id)?.rect ?? ""];
  if (r) {
    const [x, y, w, d] = r;
    return { cx: (x + w / 2) * MM, cy: (y + d / 2) * MM, h: 3, w: w * MM, d: d * MM, k: 0.5, y: 1 };
  }
  return { cx: px * MM * 0.5, cy: py * MM * 0.5, h: 5.6, w: px * MM, d: py * MM, k: 0.52, y: 1.9 };
}

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
const FLY_S = 0.8;

/** The camera: it frames the focus in the part of the view the floating chrome leaves clear,
    re-frames when the viewport resizes, and flies (in FLY_S, or at once under Reduce Motion)
    when the focus changes. The clear part's centre is made the lens centre with a view offset,
    eased as the panel opens and closes. Returns the orbit target the controls start from. */
function useCameraRig(doc: CadDoc): [number, number, number] {
  const [focus, seq] = useFocus();
  const { camera, size, controls } = useThree();
  const orbit = controls as unknown as { target: THREE.Vector3; update: () => void } | null;
  const dir = useMemo(camDir, []);
  const lens = useRef({ left: 0, top: 0, w: 0, h: 0 });
  /** the lens centred on the clear part of a W x H view whose left/top px are covered */
  const applyLens = (left: number, top: number) => {
    const c = camera as THREE.PerspectiveCamera;
    const { width: W, height: H } = size;
    lens.current = { left, top, w: W, h: H };
    c.aspect = (W + left) / Math.max(1, H + top);
    c.setViewOffset(W + left, H + top, 0, 0, W, H);
    c.updateProjectionMatrix();
  };
  // the pose for a focus at this viewport size
  const pose = (id: FocusId) => {
    const f = frameOf(doc, id);
    const c = camera as THREE.PerspectiveCamera;
    const { left, top } = getViewInset();
    // Frame the envelope on BOTH axes of the clear part: it is much taller than it is wide once
    // the panel is out, so fitting on vertical fov alone puts the camera inside the rack.
    const centre = new THREE.Vector3(f.cx, f.h * 0.42, -f.cy);
    const radius = f.k * Math.hypot(f.w, f.d, f.h);
    const focal = (size.height + top) / 2 / Math.tan((c.fov * Math.PI) / 360);
    const tanV = Math.max(40, size.height - top) / 2 / focal;
    const tanH = Math.max(40, size.width - left) / 2 / focal;
    const dist = 1.02 * Math.max(radius / tanV, radius / tanH);
    return { pos: centre.addScaledVector(dir.clone().normalize(), dist), at: new THREE.Vector3(f.cx, f.y, -f.cy) };
  };
  const first = useMemo(() => frameOf(doc, "overview"), [doc]);
  const fly = useRef<{ t: number; from: THREE.Vector3; fromAt: THREE.Vector3; to: THREE.Vector3; toAt: THREE.Vector3 } | null>(null);
  const lastSeq = useRef(seq);
  useEffect(() => {
    const c = camera as THREE.PerspectiveCamera;
    c.fov = 42; c.near = 0.05; c.far = 200;
    const { left, top } = getViewInset();
    applyLens(left, top);
    const p = pose(focus);
    const moved = seq !== lastSeq.current;
    lastSeq.current = seq;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (moved && orbit && !still) {
      fly.current = { t: 0, from: c.position.clone(), fromAt: orbit.target.clone(), to: p.pos, toAt: p.at };
      return;
    }
    fly.current = null;
    c.position.copy(p.pos);
    if (orbit) { orbit.target.copy(p.at); orbit.update(); } else c.lookAt(p.at);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, orbit, doc, focus, seq, size.width, size.height]);
  useFrame((_, dt) => {
    // the lens follows the chrome: eased when the panel opens or closes
    const want = getViewInset(), l = lens.current;
    if (l.w !== size.width || l.h !== size.height) applyLens(l.left, l.top);
    if (Math.abs(want.left - l.left) > 0.5 || Math.abs(want.top - l.top) > 0.5) {
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      const k = still ? 1 : 1 - Math.exp(-dt * 12);
      applyLens(l.left + (want.left - l.left) * k, l.top + (want.top - l.top) * k);
    }
    const f = fly.current;
    if (!f || !orbit) return;
    f.t = Math.min(1, f.t + dt / FLY_S);
    const k = ease(f.t);
    camera.position.lerpVectors(f.from, f.to, k);
    orbit.target.lerpVectors(f.fromAt, f.toAt, k);
    orbit.update();
    if (f.t >= 1) fly.current = null;
  });
  return useMemo(() => [first.cx, first.y, -first.cy], [first]);
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
  // what the twin does goes to the database, as this visitor's (shared/records.ts)
  useEffect(() => store.onRecord(postRecord), [store]);
  const J = store.joints;
  // the rack's meshes re-render only when the rack changes
  const rack = useCellModel((m) => m.rack);
  const raw = useCellModel((m) => m.rawColour);
  const vgrDrive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  const target = useCameraRig(doc);
  // each module's joints, drawn trimmed where one part is slotted into another (joints.ts)
  const trims = useMemo(() => ({ hbw: jointTrims(doc.parts), vgr: jointTrims(doc.vgr.parts), oven: jointTrims(doc.oven.parts),
    sorting: jointTrims(doc.sorting.parts) }), [doc]);
  // the loading screen lifts once the precise meshes are in (or when there are none to wait for)
  useEffect(() => { if (precise || !doc.upgrade) markStageReady(); }, [precise, doc.upgrade]);
  return (
    <>
      {/* the camera stays above the table: from below, the parts that reach through the plates
          showed through it, and no one inspects a machine from under its table */}
      <OrbitControls makeDefault target={target} enableDamping maxPolarAngle={Math.PI / 2 - 0.06} />
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
        <TrimsCtx.Provider value={trims.vgr}><PreciseScope module="vgr"><VgrModule doc={doc} drive={vgrDrive} joints={J.vgr} /></PreciseScope></TrimsCtx.Provider>
      </group>
      {/* the oven is rotated +90 about the factory Z like the sorting line:
          its Ofenschieber points back at the VGR, its belt runs to the front */}
      <group
        position={[doc.factory.oven_placement.translate[0] * MM, 0, doc.factory.oven_placement.translate[1] * MM]}
        rotation={[0, THREE.MathUtils.degToRad(-doc.factory.oven_placement.rotate_deg), 0]}
      >
        <TrimsCtx.Provider value={trims.oven}><PreciseScope module="oven"><OvenModule doc={doc} joints={J.oven} /></PreciseScope></TrimsCtx.Provider>
      </group>
      <group
        position={[
          doc.factory.sort_placement.translate[0] * MM, 0,
          doc.factory.sort_placement.translate[1] * MM,
        ]}
        rotation={[0, -Math.PI / 2, 0]}
      >
        <TrimsCtx.Provider value={trims.sorting}><PreciseScope module="sorting">
          <SortingModule doc={doc} joints={J} onPhoto={(b, e, s) => {
            void keep(b, e, s.label, s.n, s.truth);
            // the inspection judges the photo, and the cell acts on its verdict
            judge(s.n, b, e).then((v) => store.decide(v)).catch(() => store.decide({ n: s.n, verdict: "check", condition: "no verdict", p: 0, flavour: "", ae: 0, anomaly: true }));
          }} />
        </PreciseScope></TrimsCtx.Provider>
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
            <TrimsCtx.Provider value={trims.hbw}><PreciseScope module="hbw"><HbwCad doc={doc} joints={J} slots={rack} /></PreciseScope></TrimsCtx.Provider>
            <RackBadge doc={doc} rack={rack} raw={raw} />
          </>
        )}
      </group>
      </group>
      </PreciseLibCtx.Provider>
    </>
  );
}
