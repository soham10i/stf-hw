// The High-Bay Warehouse rendered from the CAD source of truth.
//
// web/public/hbw_parts.json is emitted by stf-cad/hbw/hbw_export.py from the
// SAME parameter table that generates STF_HBW.FCStd and the dimensioned
// drawings, and only after hbw_model.check() proves the machine has no
// interference and nothing floating. So this view cannot drift from the CAD:
// if a bracket moves in the model, it moves here on the next export.
//
// Parts arrive in LOCAL joint-frame coordinates and are nested
//   world -> travel(+X) -> lift(+Z) -> fork(+Y)
// which is exactly the App::Part hierarchy inside the FreeCAD file.
//
// Parts carrying a `mech` tag animate off the pose rather than being decoration:
//   thread:<joint>  a spindle - turns at travel / 4 mm pitch, the real lead
//   pulley | spin:* a drum or gear - turns with the belt it drives
//   belt            a belt strip - its surface scrolls with the belt
// so the screws visibly drive the axes and the motor visibly drives the belt.
//
// This is a renderer only. It draws the joints it is given - the crane's axes, where the
// circulating mould is, which light barrier is broken - and the rack's slots in the colours it
// is given. What the cell does (orders, cycles, sensors) is decided by the headless coordinator
// (engine/CellCoordinator.ts) and reaches here through the store (store/useCellStore.ts).

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { DragChain } from "./DragChain";
import { type CadPart, type CadDoc, boxSize, cylSpec } from "../shared/model";
import type { CellJoints, Drive, Rack } from "./store/useCellStore";
import { MM, v, AIM, Solid, Cookie, Mould } from "./parts";
import { HBW, RunningGear } from "./RunningGear";

/** What the warehouse draws from: its axes, the circulating mould, the slot that mould is out
    of, and the light barriers. */
export type HbwJoints = Pick<CellJoints, "hbw" | "load" | "out" | "beams">;

/** Toothed drive belt wrapped round the motor pulley and the drum pulley, running
    at the pulleys' pitch-line speed. Drawn as a real loop: two tangent straights
    and two half-wraps, teeth moving along it. */
function BeltLoop({ doc, drive }: { doc: CadDoc; drive: React.MutableRefObject<Drive> }) {
  const band = useRef<THREE.InstancedMesh>(null);
  const teeth = useRef<THREE.InstancedMesh>(null);
  const g = useMemo(() => {
    const a = doc.parts.find((p) => p.n === "M1_drive_pulley");
    const b = doc.parts.find((p) => p.n === "M1_drum_pulley");
    if (!a || !b) return null;
    const [, len, dia] = cylSpec(a);
    const r = dia / 2 + 1.0;
    const ax = a.p[1], ay = a.p[2], bx = b.p[1], by = b.p[2];
    const L1 = Math.hypot(bx - ax, by - ay), arc = Math.PI * r, total = 2 * L1 + 2 * arc;
    const dx = (bx - ax) / L1, dy = (by - ay) / L1;   // along the straight, A -> B
    const count = Math.round(total / 3);
    return { x: a.p[0] + len / 2, w: len - 1, r, ax, ay, bx, by, dx, dy, nx: -dy, ny: dx, L1, arc, total, count };
  }, [doc]);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  // a point on the loop and its tangent, written in place (no allocation per tooth per frame)
  const pt = useMemo(() => ({ px: 0, py: 0, tx: 0, ty: 0 }), []);
  const at = useMemo(() => (s0: number) => {
    if (!g) return;
    const s = ((s0 % g.total) + g.total) % g.total;
    const { ax, ay, bx, by, dx, dy, nx, ny, r, L1, arc } = g;
    if (s < L1) { pt.px = ax + nx * r + dx * s; pt.py = ay + ny * r + dy * s; pt.tx = dx; pt.ty = dy; return; }
    if (s < L1 + arc) {
      const th = (s - L1) / r, c = Math.cos(th), sn = Math.sin(th);
      pt.px = bx + nx * r * c + dx * r * sn; pt.py = by + ny * r * c + dy * r * sn;
      pt.tx = -nx * sn + dx * c; pt.ty = -ny * sn + dy * c;
      return;
    }
    if (s < 2 * L1 + arc) {
      const d = s - L1 - arc;
      pt.px = bx - nx * r - dx * d; pt.py = by - ny * r - dy * d; pt.tx = -dx; pt.ty = -dy;
      return;
    }
    const th = (s - 2 * L1 - arc) / r, c = Math.cos(th), sn = Math.sin(th);
    pt.px = ax - nx * r * c - dx * r * sn; pt.py = ay - ny * r * c - dy * r * sn;
    pt.tx = nx * sn - dx * c; pt.ty = ny * sn - dy * c;
  }, [g, pt]);
  useFrame(() => {
    if (!g || !band.current || !teeth.current) return;
    // the drum pulley shares the drum's axle, so the loop runs at the drum's
    // angular speed times the pulley radius
    const off = drive.current.belt * ((g.r - 1) / (doc.belt.pulley_d / 2));
    for (let i = 0; i < g.count; i++) {
      const s = (i * g.total) / g.count;
      for (let k = 0; k < 2; k++) {
        const mesh = k === 0 ? band.current : teeth.current;
        at(k === 0 ? s : s + off);
        // module (x, y, z) -> three (x, z, y), as v() does
        dummy.position.set(g.x * MM, pt.py * MM, pt.px * MM);
        dummy.rotation.set(Math.atan2(-pt.ty, pt.tx), 0, 0);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
      }
    }
    band.current.instanceMatrix.needsUpdate = true;
    teeth.current.instanceMatrix.needsUpdate = true;
  });
  if (!g) return null;
  const seg = g.total / g.count;
  return (
    <group>
      <instancedMesh ref={band} args={[undefined, undefined, g.count]} castShadow>
        <boxGeometry args={[g.w * MM, 1.6 * MM, seg * 1.05 * MM]} />
        <meshStandardMaterial color="#2a2d31" roughness={0.9} />
      </instancedMesh>
      <instancedMesh ref={teeth} args={[undefined, undefined, g.count]}>
        <boxGeometry args={[g.w * 0.96 * MM, 2.4 * MM, seg * 0.45 * MM]} />
        <meshStandardMaterial color="#5c636b" roughness={0.8} />
      </instancedMesh>
    </group>
  );
}

const BEAM_OK = new THREE.Color("#39d353"), BEAM_HIT = new THREE.Color("#ff3b30");

/** Each end-of-belt light barrier: LED on one side rail, phototransistor on the
    other, and the beam between them at mould-rim height. Broken beam = the
    receiver's indicator blinks and the beam flickers. */
function LightBarriers({ doc, beams }: { doc: CadDoc; beams: Record<string, boolean> }) {
  const pairs = useMemo(
    () =>
      doc.parts
        .filter((p) => p.mech === "beam:rx")
        .map((rx) => ({ rx, tx: doc.parts.find((p) => p.mech === "beam:tx" && p.tag === rx.tag)! }))
        .filter((q) => q.tx),
    [doc],
  );
  return (
    <group>
      {pairs.map(({ rx, tx }) => <Barrier key={rx.n} rx={rx} tx={tx} beams={beams} />)}
    </group>
  );
}

function Barrier({ rx, tx, beams }: { rx: CadPart; tx: CadPart; beams: Record<string, boolean> }) {
  const beam = useRef<THREE.Mesh>(null);
  const led = useRef<THREE.MeshStandardMaterial>(null);
  const [sx, sy, sz] = boxSize(rx);
  const x0 = rx.p[0] + sx, x1 = tx.p[0];
  const yc = rx.p[1] + sy / 2, zc = rx.p[2] + sz / 2;
  useFrame(({ clock }) => {
    const hit = !!beams[rx.tag];
    const on = Math.floor(clock.getElapsedTime() * 8) % 2 === 0;
    if (beam.current) beam.current.visible = !hit || on;
    if (led.current) {
      led.current.color.copy(hit ? BEAM_HIT : BEAM_OK);
      led.current.emissive.copy(hit ? BEAM_HIT : BEAM_OK);
      led.current.emissiveIntensity = hit ? (on ? 3 : 0.2) : 0.9;
    }
  });
  return (
    <group>
      <mesh ref={beam} position={v((x0 + x1) / 2, yc, zc)} rotation={AIM.x}>
        <cylinderGeometry args={[0.9 * MM, 0.9 * MM, (x1 - x0) * MM, 8]} />
        <meshBasicMaterial color="#ff5a3c" transparent opacity={0.85} />
      </mesh>
      {/* LED lens on the transmitter */}
      <mesh position={v(tx.p[0] - 0.6, yc, zc)}>
        <sphereGeometry args={[2.4 * MM, 12, 12]} />
        <meshStandardMaterial color="#ffb347" emissive="#ff8a00" emissiveIntensity={2} />
      </mesh>
      {/* status LED on top of the receiver */}
      <mesh position={v(rx.p[0] + sx / 2, yc, rx.p[2] + sz + 2.5)}>
        <sphereGeometry args={[2.6 * MM, 12, 12]} />
        <meshStandardMaterial ref={led} color="#39d353" emissive="#39d353" emissiveIntensity={0.9} />
      </mesh>
    </group>
  );
}

/** The warehouse: crane, rack, belt and light barriers, posed from `joints`; the rack's slots
    drawn in the colours of `slots` (slot -> cookie colour, null = an empty mould). */
export function HbwCad({ doc, joints, slots }: { doc: CadDoc; joints: HbwJoints; slots: Rack }) {
  const gTravel = useRef<THREE.Group>(null);
  const gLift = useRef<THREE.Group>(null);
  const gFork = useRef<THREE.Group>(null);
  const gOnFork = useRef<THREE.Group>(null);
  const gOnBelt = useRef<THREE.Group>(null);
  const gStowed = useRef<THREE.Group>(null);
  const gCookieFork = useRef<THREE.Group>(null);
  const gCookieBelt = useRef<THREE.Group>(null);
  const gCookieShelf = useRef<THREE.Group>(null);
  const stowRef = useRef<THREE.Group>(null);
  // each slot's static mould + cookie; the slot whose mould is out is hidden (drawn as the load)
  const slotG = useRef<Record<string, THREE.Group | null>>({});
  const drive = useRef<Drive>({
    travel: doc.home.travel, lift: doc.home.lift, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0,
  });

  // every mould and cookie in the rack is drawn from `slots`, not from the part table
  const byFrame = useMemo(() => {
    const m: Record<string, CadPart[]> = { world: [], travel: [], lift: [], fork: [] };
    for (const p of doc.parts) {
      if (/^(mould|wp)_[A-Z]\d+_/.test(p.n)) continue;
      m[p.f].push(p);
    }
    return m;
  }, [doc]);

  const tex = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 8;
    c.height = 16;
    const g = c.getContext("2d")!;
    g.fillStyle = "#4a4f57";
    g.fillRect(0, 0, 8, 16);
    g.fillStyle = "#23272c";
    g.fillRect(0, 0, 8, 5);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return t;
  }, []);

  const mb = doc.moulds.size[2];
  // Where the load sits when it is on the fork, DERIVED from the fork table part
  // itself. This was a literal, and when the rail moved the carried mould stayed
  // 150 mm behind - drawn straight through the rack and the stored moulds.
  const seat = useMemo(() => {
    const t = doc.parts.find((p) => p.n === "fork_table");
    if (!t) return { y: 0, z: 10 };
    const [, dy, dz] = boxSize(t);
    return { y: t.p[1] + dy / 2, z: t.p[2] + dz };
  }, [doc]);

  useFrame(() => {
    const h = joints.hbw, load = joints.load, d = drive.current;
    d.travel = h.travel; d.lift = h.lift; d.fork = h.fork; d.belt = h.belt;
    if (gTravel.current) gTravel.current.position.x = h.travel * MM;
    if (gLift.current) gLift.current.position.y = h.lift * MM;
    if (gFork.current) gFork.current.position.z = h.fork * MM;

    const held = load.held;
    for (const q in slotG.current) {
      const g = slotG.current[q];
      if (g) g.visible = q !== joints.out;
    }
    if (gOnFork.current) gOnFork.current.visible = held === "fork";
    if (gOnBelt.current) {
      gOnBelt.current.visible = held === "belt";
      gOnBelt.current.position.z = h.belt * MM;
    }
    if (gStowed.current) gStowed.current.visible = held === "shelf";
    if (stowRef.current && held === "shelf") {
      const sp = doc.slots[load.slot];
      stowRef.current.position.set(sp[0] * MM, sp[2] * MM, sp[1] * MM);
    }
    const c = load.cookie;
    if (gCookieFork.current) gCookieFork.current.visible = c && held === "fork";
    if (gCookieBelt.current) gCookieBelt.current.visible = c && held === "belt";
    if (gCookieShelf.current) gCookieShelf.current.visible = c && held === "shelf";
  });

  const P = (p: CadPart) => <Solid key={p.n} part={p} drive={drive} pitch={doc.pitch_mm} tex={tex} drumD={doc.belt.pulley_d} />;
  const beltX = doc.stations.hbw_pick[0], beltZ = doc.stations.hbw_pick[2];

  return (
    <group>
      {byFrame.world.map(P)}
      <RunningGear all={doc.parts} frame="world" axes={HBW} />
      {doc.chains?.chains["hbw:travel"] && (
        <DragChain spec={doc.chains.chains["hbw:travel"]} joint={() => drive.current.travel} />
      )}
      {/* the rack's slots: a mould each, and its cookie in the given colour */}
      {Object.entries(slots).map(([q, col]) => {
        const sp = doc.slots[q];
        return (
          <group key={q} ref={(g) => { slotG.current[q] = g; }} position={[sp[0] * MM, sp[2] * MM, sp[1] * MM]}
            visible={q !== joints.out}>
            <Mould x={0} y={0} z={0} doc={doc} />
            {col && <Cookie x={0} y={0} z={mb} colour={col} />}
          </group>
        );
      })}
      <BeltLoop doc={doc} drive={drive} />
      <LightBarriers doc={doc} beams={joints.beams} />

      {/* the circulating mould, stowed in a slot */}
      <group ref={gStowed}>
        <group ref={stowRef}>
          <Mould x={0} y={0} z={0} doc={doc} />
          <group ref={gCookieShelf}>
            <Cookie x={0} y={0} z={mb} tint={joints.load.tint} />
          </group>
        </group>
      </group>

      {/* on the belt: translated along +Y by the belt position each frame */}
      <group ref={gOnBelt}>
        <Mould x={beltX} y={0} z={beltZ} doc={doc} />
        <group ref={gCookieBelt}>
          <Cookie x={beltX} y={0} z={beltZ + mb} tint={joints.load.tint} />
        </group>
      </group>

      <group ref={gTravel}>
        {byFrame.travel.map(P)}
        <RunningGear all={doc.parts} frame="travel" axes={HBW} />
        {doc.chains?.chains["hbw:lift"] && (
          <DragChain spec={doc.chains.chains["hbw:lift"]}
            joint={() => drive.current.lift + doc.chains!.chains["hbw:lift"].M[2]} />
        )}
        <group ref={gLift}>
          {byFrame.lift.map(P)}
          <RunningGear all={doc.parts} frame="lift" axes={HBW} />
          <group ref={gFork}>
            {byFrame.fork.map(P)}
            <RunningGear all={doc.parts} frame="fork" axes={HBW} />
            {/* seated on the fork table: local table top = lift + 10 -> z = 10 */}
            <group ref={gOnFork}>
              <Mould x={0} y={seat.y} z={seat.z} doc={doc} />
              <group ref={gCookieFork}>
                <Cookie x={0} y={seat.y} z={seat.z + mb} tint={joints.load.tint} />
              </group>
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}
