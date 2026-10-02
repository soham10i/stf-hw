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
// The pose driver is a scripted cycle. It switches to the live kernel once
// factory.layout.yaml is regenerated from the same table - today the backend
// still speaks the old joint convention, and driving new geometry with old
// joint values would render a lie.

import { Grid, Html, OrbitControls } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { VIEW } from "../coords";
import { ThreadedRod } from "./ThreadedRod";
import { buildFlow, type FlowState, type Mode } from "./OvenFlow";
import { HazardZones, PcbBoard, PlcCabinet, PreciseComp, ProfileBox, SecurityOverlay, UpgradeParts, Wiring } from "./FactoryDetail";
import { Environment, Lightformer } from "@react-three/drei";
import { Suspense } from "react";
import { DragChain } from "./DragChain";
import { useJson } from "../shared/data";
import { MM_TO_SCENE, PreciseLibCtx, PreciseLoader, PreciseMesh, PreciseScope, usePrecise, type PreciseLib } from "./Precise";

import type { CadPart, CadDoc, PlanKey } from "../shared/model";

const MM = VIEW;


/** The slot the FIRST cycle lifts its raw cookie from (review URLs rely on it). */
const FROM = "B2";

/** One line of an order: a quantity of one flavour. `started` cycles have taken a raw cookie for
    it, `done` cookies of it have been baked and sorted into their Lagerstelle. */
export type OrderLine = { id: number; flavour: string; qty: number; started: number; done: number; demo?: boolean };

/** The orders and the material state, shared between the 3D loop and the Orders panel.
    The cell holds exactly 12 cookies, one in each slot's mould, raw or baked. A cycle takes one
    raw cookie out, bakes it in the ordered flavour, sorts it, and the VGR brings it straight back
    into the same slot; an order line is done when all its cookies are in the rack. The loop
    idles when every line is done. */
export const twinOrders = {
  raw: [] as string[],
  /** set by the panel; the loop swaps the baked cookies for fresh dough while idle */
  restock: false,
  delivered: 0,
  /** what the cell is doing right now, in words */
  step: "",
  // the rack as the 3D view draws it (slot -> cookie colour, null = empty mould, absent = no mould),
  // the dough colour, and the running cycle - read by the Orders panel
  rack: {} as Record<string, string | null>, rawColour: "",
  cycle: { from: "", to: "", total: 0, t: 0, flavour: "", collect: "" as string },
  queue: [] as OrderLine[],
  idle: false,
  /** the Lagerstellen: bin -> the cookie resting there until the VGR collects it */
  bays: {} as Record<string, string[]>,
  seq: 0,
  /** raw cookies not yet promised to an order (the one in the oven is still raw in the rack map) */
  free() {
    const promised = this.queue.reduce((n, o) => n + o.qty - o.done, 0);
    return Math.max(0, this.raw.length - promised);
  },
  /** Queue an order line; false when the rack has too few raw cookies for it. */
  place(flavour: string, qty: number) {
    const n = Math.max(1, Math.min(12, Math.round(qty)));
    if (n > this.free()) return false;
    this.queue.push({ id: ++this.seq, flavour, qty: n, started: 0, done: 0 });
    return true;
  },
};
/** The cycle running now: whose cookie is being baked, and into which bin. */
export const cycleHot = { from: FROM, to: "", bin: "" };

/** slot -> colour of the cookie in its mould (null = empty mould). A slot that
    is not in the map holds no mould - that is the free slot. */
type Rack = Record<string, string | null>;

/** live pose, read imperatively inside useFrame - never React state */
export interface Drive {
  travel: number; lift: number; fork: number; belt: number;
  plunge: number; reach: number; swivel: number;
}

/** factory (x,y,z) mm -> three (x, z, y) scene units */
const v = (x: number, y: number, z: number) =>
  new THREE.Vector3(x * MM, z * MM, y * MM);

/** rotation that aims a locally-+Y part along a factory axis */
const AIM: Record<string, [number, number, number]> = {
  z: [0, 0, 0],            // factory +Z -> three +Y
  x: [0, 0, -Math.PI / 2], // factory +X -> three +X
  y: [Math.PI / 2, 0, 0],  // factory +Y -> three +Z
};

function centreOf(part: CadPart) {
  const [px, py, pz] = part.p;
  if (part.k === "box") {
    const [dx, dy, dz] = part.s as [number, number, number];
    return v(px + dx / 2, py + dy / 2, pz + dz / 2);
  }
  const [axis, len] = part.s as [string, number, number];
  const h = len / 2;
  return axis === "x" ? v(px + h, py, pz) : axis === "y" ? v(px, py + h, pz) : v(px, py, pz + h);
}

function Mat({ part }: { part: CadPart }) {
  const metal = part.c === "#d6d9da" || part.c === "#aeb4b8";
  return (
    <meshStandardMaterial
      color={part.c}
      roughness={part.g === "workpiece" ? 0.45 : metal ? 0.3 : 0.62}
      metalness={metal ? 0.7 : 0.1}
    />
  );
}

/** A spindle: real 4 mm lead, turning at exactly translation / pitch. */
function Spindle({ part, drive, pitch }: { part: CadPart; drive: React.MutableRefObject<Drive>; pitch: number }) {
  const spin = useRef<THREE.Group>(null);
  const [axis, len, dia] = part.s as [string, number, number];
  const joint = part.mech.split(":")[1] as keyof Drive;
  useFrame(() => {
    // `?? 0`: a spindle whose joint the drive does not carry used to get NaN,
    // and three.js silently stops drawing an object with a NaN transform - which
    // is how the VGR's plunge spindle and spring stem went invisible.
    if (spin.current) spin.current.rotation.y = ((drive.current[joint] ?? 0) / pitch) * Math.PI * 2;
  });
  return (
    <group position={centreOf(part)} rotation={AIM[axis]}>
      <group ref={spin}>
        <ThreadedRod length={len * MM} radius={(dia / 2) * MM} color={part.c} />
      </group>
    </group>
  );
}

/** A drum or gear driven by the belt: one turn per pi*D of belt travel. */
function Roller({ part, drive, drumD, precise }: {
  part: CadPart; drive: React.MutableRefObject<Drive>; drumD?: number; precise?: THREE.Mesh[];
}) {
  const spin = useRef<THREE.Group>(null);
  // a precise mesh is in module mm: undo the roller's own placement so it
  // spins about the part's axis and sits exactly on its box
  const inner = useMemo(() => {
    if (!precise) return null;
    const [ax] = part.s as [string, number, number];
    const R = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(...AIM[ax]));
    const c = centreOf(part);
    return R.invert().multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z)).multiply(MM_TO_SCENE);
  }, [precise, part]);
  const [axis, len, dia] = part.s as [string, number, number];
  // The drive pulleys sit on the drum's axle, so they turn at the DRUM's rate,
  // not at the rate their own diameter would give.
  const d0 = part.mech === "spin:belt_x" && drumD ? drumD : dia;
  useFrame(() => {
    if (spin.current) spin.current.rotation.y = (drive.current.belt / (Math.PI * d0)) * Math.PI * 2;
  });
  const r = (dia / 2) * MM;
  if (precise && inner)
    return (
      <group position={centreOf(part)} rotation={AIM[axis]}>
        <group ref={spin}><PreciseMesh meshes={precise} matrix={inner} /></group>
      </group>
    );
  return (
    <group position={centreOf(part)} rotation={AIM[axis]}>
      <group ref={spin}>
        <mesh castShadow>
          <cylinderGeometry args={[r, r, len * MM, 20]} />
          <Mat part={part} />
        </mesh>
        {/* A key on each END face, so the drum's rotation is readable without
            putting a bump on the running surface the workpiece rides. */}
        {[-1, 1].map((sgn) => (
          <mesh key={sgn} position={[0, (sgn * len * MM) / 2, r * 0.52]}>
            <boxGeometry args={[r * 0.3, 0.004, r * 0.86]} />
            <meshStandardMaterial color="#9aa2ab" metalness={0.4} roughness={0.5} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

/** A belt strip whose surface scrolls with the belt. */
function BeltStrip({
  part, drive, tex,
}: { part: CadPart; drive: React.MutableRefObject<Drive>; tex: THREE.Texture }) {
  const [dx, dy, dz] = part.s as [number, number, number];
  // "belt" runs along Y, "belt:z" is the vertical drive belt from the motor up
  // to the drum - same texture, different long axis.
  // a belt runs along its LONG horizontal side: the sorting line's runs along X
  const alongX = part.mech !== "belt:z" && dx > dy;
  const runLen = part.mech === "belt:z" ? dz : alongX ? dx : dy;
  const map = useMemo(() => {
    const t = tex.clone();
    // One band per BAND_MM of belt, so the ridges are at a fixed real spacing
    // whatever the length. Without this the whole strip is one band and the
    // belt reads as static.
    if (alongX) {
      t.rotation = Math.PI / 2;
      t.repeat.set(1, runLen / BAND_MM);
    } else t.repeat.set(1, runLen / BAND_MM);
    t.needsUpdate = true;
    return t;
  }, [tex, runLen, alongX]);
  // Offset moves the sample point, so it runs OPPOSITE the surface: negate it
  // and the ridges travel with the workpiece.
  useFrame(() => {
    map.offset.y = (alongX ? 1 : -1) * drive.current.belt / BAND_MM;
  });
  return (
    <mesh position={centreOf(part)} castShadow receiveShadow>
      <boxGeometry args={[dx * MM, dz * MM, dy * MM]} />
      <meshStandardMaterial map={map} color="#c8ccd2" roughness={0.85} />
    </mesh>
  );
}

const BAND_MM = 10; // one texture band per 10 mm of belt

function Solid({ part, drive, pitch, tex, drumD }: {
  part: CadPart; drive: React.MutableRefObject<Drive>; pitch: number; tex: THREE.Texture;
  drumD?: number;
}) {
  const precise = usePrecise(part.n);
  // module plates are replaced by the one continuous base (FactoryTable)
  if (part.g === "frame") return null;
  // the drive belt's box is its envelope for the checker; BeltLoop draws the loop
  if (part.mech === "belt:loop") return null;
  // a drag chain's envelope box is for the proofs; DragChain draws the chain
  if (part.mech.startsWith("chain:")) return null;
  // I/O parts are drawn as the precise FreeCAD component they are
  if (part.fit) return <Suspense fallback={null}><PreciseComp fit={part.fit} /></Suspense>;
  // the adapter PCB's own renderer (headers, relays, terminals) is richer than its CAD block
  if (/pcb/i.test(part.n) && part.k === "box")
    return <PcbBoard p={part.p} s={part.s as [number, number, number]} />;
  // Upgrade 1: the exact CAD shape (web_precise.py), where one was exported
  if (precise) {
    if (part.mech === "pulley" || part.mech.startsWith("spin:"))
      return <Roller part={part} drive={drive} drumD={drumD} precise={precise} />;
    return <PreciseMesh meshes={precise} />;
  }
  if (/pcb/i.test(part.n) && part.k === "box")
    return <PcbBoard p={part.p} s={part.s as [number, number, number]} />;
  if (part.mech.startsWith("thread:")) return <Spindle part={part} drive={drive} pitch={pitch} />;
  if (part.mech === "pulley" || part.mech.startsWith("spin:")) return <Roller part={part} drive={drive} drumD={drumD} />;
  if (part.mech.startsWith("belt")) return <BeltStrip part={part} drive={drive} tex={tex} />;
  if (part.k === "box" && /^profile(:20)?$/.test(part.mech))
    return <ProfileBox p={part.p as [number, number, number]} s={part.s as [number, number, number]} />;

  if (part.k === "box") {
    const [dx, dy, dz] = part.s as [number, number, number];
    return (
      <mesh position={centreOf(part)} castShadow receiveShadow>
        <boxGeometry args={[dx * MM, dz * MM, dy * MM]} />
        <Mat part={part} />
      </mesh>
    );
  }
  const [axis, len, dia] = part.s as [string, number, number];
  return (
    <mesh position={centreOf(part)} rotation={AIM[axis]} castShadow receiveShadow>
      <cylinderGeometry args={[(dia / 2) * MM, (dia / 2) * MM, len * MM, 24]} />
      <Mat part={part} />
    </mesh>
  );
}

/** The cookie: one 20 mm puck. z = its underside. Its colour can follow a hot
    object, so the same mesh shows raw dough and then the baked flavour. */

const DOUGH = "#D8B98C";

/** A constant-size badge over the rack: which slots hold a baked cookie. The
    cookies themselves are a few pixels wide from across the table. */
function RackBadge({ doc, rack, raw }: { doc: CadDoc; rack: Record<string, string | null>; raw: string }) {
  const baked = Object.entries(rack).filter(([, c]) => c && c.toLowerCase() !== raw.toLowerCase()).map(([q]) => q).sort();
  const pos = useMemo(() => {
    const ps = Object.values(doc.slots);
    const cx = ps.reduce((a, p) => a + p[0], 0) / ps.length, cy = ps.reduce((a, p) => a + p[1], 0) / ps.length;
    const top = Math.max(...ps.map((p) => p[2]));
    return [cx * MM, (top + 150) * MM, cy * MM] as [number, number, number];
  }, [doc]);
  const col = baked.length ? rack[baked[0]]! : raw;
  return (
    <Html position={pos} center zIndexRange={[5, 0]}>
      <span className="zone-tag rack-badge" style={{ borderColor: col }}>
        <i style={{ background: col }} />{baked.length ? `${baked.length} baked · ${baked.join(" ")}` : "rack: raw dough only"}
      </span>
    </Html>
  );
}

/** A cookie. Raw dough is pale and matt; a BAKED one has its flavour colour with
    a faint glow, so it still reads deep in a mould. */
function Cookie({
  x, y, z, colour = DOUGH, dynamic = false, hot,
}: {
  x: number; y: number; z: number; colour?: string; dynamic?: boolean;
  hot?: { colour: string };
}) {
  const r = 22.5 * MM;
  const mat = useRef<THREE.MeshStandardMaterial>(null);
  const paint = (c: string) => {
    if (!mat.current) return;
    const baked = c.toLowerCase() !== DOUGH.toLowerCase();
    mat.current.color.set(c);
    mat.current.emissive.set(baked ? c : "#000000");
    mat.current.emissiveIntensity = baked ? 0.18 : 0;
  };
  useFrame(() => {
    if (hot) paint(hot.colour);
    else if (dynamic) paint(vgrHot.cupColour);
  });
  useEffect(() => { if (!hot && !dynamic) paint(colour); });
  return (
    <group position={v(x, y, z)}>
      <mesh position={[0, 10 * MM, 0]} castShadow>
        <cylinderGeometry args={[r, r, 20 * MM, 32]} />
        <meshStandardMaterial ref={mat} color={colour} roughness={0.5} />
      </mesh>
    </group>
  );
}

// ---- mutable "hot" state, written once per frame by the timeline ----------
/** The VGR's live pose. `compress` is the spring stem: how far the carriage has
    over-travelled past the point where the cup met the cookie. */
export const vgrHot = {
  swivel: 0, plunge: 500, reach: 0, compress: 0, seal: 0,
  cup: false, carry: null as string | null, cupColour: "#D8B98C",
};
/** The colour of the cookie riding in the warehouse's circulating mould. */
export const hbwCookieHot = { colour: "#D8B98C" };
/** Which light barriers are broken right now (I2 / I3), and the crane's axes in mm. */
export const hbwHot = {
  blocked: {} as Record<string, boolean>,
  axes: { travel: 0, lift: 0, fork: 0, belt: 0 },
};
/** The Lagerstelle whose cookie the VGR has collected. */
export const sortHot = { taken: null as string | null };
/** The colour each Lagerstelle's cookie is drawn in. */
const bayHot: Record<string, { colour: string }> = { weiss: { colour: "#FBF8F1" }, rot: { colour: "#F4A6BF" }, blau: { colour: "#5C3A1E" } };
/** The oven + sorting flow: every joint of both stations, and the ONE cookie
    that travels through them (see OvenFlow.ts). Written once per frame. */
export const ovenHot = {
  s: null as FlowState | null,
  belts: { oven: 0, sort: 0 },
  mode: "tray" as Mode,
  visible: false,
  pos: [0, 0, 0] as [number, number, number],
  colour: "#D8B98C",
};

/** The mould (Werkstuecktraeger): base + four rim bars, matching the model.
    x,y = its centre; z = its underside (the face the fork lifts). */
function Mould({ x, y, z, doc }: { x: number; y: number; z: number; doc: CadDoc }) {
  const [mw, md, mb] = doc.moulds.size;
  const rt = 5, rh = doc.moulds.rim_h;
  const bar = (w: number, d: number, ox: number, oy: number) => (
    <mesh position={v(ox, oy, z + mb + rh / 2)} castShadow receiveShadow>
      <boxGeometry args={[w * MM, rh * MM, d * MM]} />
      <meshStandardMaterial color="#9aa3ac" metalness={0.5} roughness={0.42} />
    </mesh>
  );
  return (
    <group>
      <mesh position={v(x, y, z + mb / 2)} castShadow receiveShadow>
        <boxGeometry args={[mw * MM, mb * MM, md * MM]} />
        <meshStandardMaterial color="#9aa3ac" metalness={0.5} roughness={0.42} />
      </mesh>
      {bar(rt, md, x - mw / 2 + rt / 2, y)}
      {bar(rt, md, x + mw / 2 - rt / 2, y)}
      {bar(mw - 2 * rt, rt, x, y - md / 2 + rt / 2)}
      {bar(mw - 2 * rt, rt, x, y + md / 2 - rt / 2)}
    </group>
  );
}

// --- the cycle -----------------------------------------------------------------
// One timeline drives the whole table:
//   crane lifts the mould (raw cookie) out of B2 -> hands it to the belt -> belt
//   carries it to the VGR point -> the VGR plays its PROVEN tour
//   (stf-cad/hbw/vgr_path.py: belt -> oven -> rot Lagerstelle -> belt, every leg
//   swept against every module) -> the belt brings the mould, now holding a
//   BAKED cookie, back to the crane -> the crane stows it in C4.
// The VGR waypoints are the exported plan, not typed in here: if the geometry
// changes, the planner re-plans and this view follows.
type Held = "shelf" | "fork" | "belt";
type Key = {
  t: number; l: number; f: number; b: number;
  held: Held; slot: string; cookie: boolean; cc: string;
  vs: number; vr: number; vp: number; vc: number; cup: boolean; carry: string | null;
  taken: string | null; ovenIn: boolean; ovenGo: boolean;
  say: string;
};

/** The flavour colour of a Lagerstelle's cookies: every Lagerstelle holds one flavour. */
function binColour(doc: CadDoc, bin: string | null) {
  const fl = Object.values(doc.pipeline.flavours).find((f) => f.bin === bin);
  return fl?.colour ?? doc.pipeline.raw_colour;
}

/** One cycle's choreography. `plan` is the VGR's tour (vgr_tours.json: belt -> oven, then the
    oldest finished cookie's Lagerstelle -> belt, or nothing); `collect` is that Lagerstelle. */
function script(doc: CadDoc, FROM: string, free: string, plan: PlanKey[], collect: string | null): Key[] {
  const T = doc.joints.travel.stops, L = doc.joints.lift.stops, F = doc.joints.fork.stops;
  const hb = doc.stations.hbw_pick[1], vg = doc.stations.vgr_pick[1];
  const RAW = doc.pipeline.raw_colour;
  const BAKED = binColour(doc, collect);
  const colourOf = (c: string | null) => (c === "baked" ? BAKED : RAW);
  // "B2" = shelf row B, bay column 2; every crane stop comes from the export
  const fr = FROM[0], fc = FROM.slice(1), tr = free[0], tcol = free.slice(1);
  const TF = T[`bay${fc}`], TT = T[`bay${tcol}`];
  const LFu = L[`row${fr}_under`], LFl = L[`row${fr}_lift`];
  const LTu = L[`row${tr}_under`], LTl = L[`row${tr}_lift`];

  const home = plan[0];
  const V0 = { vs: home.sw, vr: home.rr, vp: home.pz, vc: 0, cup: false, carry: null };
  const st = { cookie: true, cc: RAW, taken: null as string | null, ovenIn: false, ovenGo: false };
  const out: Key[] = [];
  const k = (
    t: number, l: number, f: number, b: number, held: Held, slot: string,
    vv: { vs: number; vr: number; vp: number; vc: number; cup: boolean; carry: string | null },
    say: string,
  ) => out.push({ t, l, f, b, held, slot, cookie: st.cookie, cc: st.cc, ...vv,
                  taken: st.taken, ovenIn: st.ovenIn, ovenGo: st.ovenGo, say });

  // ---- warehouse -> belt -> VGR point (raw cookie) ----
  k(T.conveyor, L.transit, F.retracted, hb, "shelf", FROM, V0, "park at the conveyor");
  k(TF, L.transit, F.retracted, hb, "shelf", FROM, V0, `travel to bay column ${fc}`);
  k(TF, LFu, F.retracted, hb, "shelf", FROM, V0, `lift spindle: drop 10 mm below shelf ${fr}`);
  k(TF, LFu, F.bay, hb, "shelf", FROM, V0, `Ausleger into ${FROM}, under the mould`);
  k(TF, LFl, F.bay, hb, "fork", FROM, V0, "lift 10 mm — mould off the brackets");
  k(TF, LFl, F.retracted, hb, "fork", FROM, V0, "retract clear of the rack face");
  k(TF, L.transit, F.retracted, hb, "fork", FROM, V0, "raise to transit");
  k(T.conveyor, L.transit, F.retracted, hb, "fork", FROM, V0, "travel to the conveyor");
  k(T.conveyor, L.belt_lift, F.retracted, hb, "fork", FROM, V0, "descend to the hand-over height");
  k(T.conveyor, L.belt_lift, F.conveyor, hb, "fork", FROM, V0, "Ausleger out over the belt — the mould breaks light barrier I2");
  k(T.conveyor, L.belt_under, F.conveyor, hb, "belt", FROM, V0, "table through the belt gap — mould released");
  k(T.conveyor, L.belt_under, F.retracted, hb, "belt", FROM, V0, "retract");
  k(T.conveyor, L.transit, F.retracted, hb, "belt", FROM, V0, "raise clear");
  k(T.conveyor, L.transit, F.retracted, vg, "belt", FROM, V0, "Q1 belt forward — through the hood to I3 at the VGR point");

  // ---- the VGR's proven tour ----
  for (let i = 1; i < plan.length; i++) {
    const p = plan[i], q = plan[i - 1];
    const picked = !q.carry && !!p.carry, placed = !!q.carry && !p.carry;
    if (p.station === "belt" && picked) st.cookie = false;
    if (p.station === "belt" && placed) { st.cookie = true; st.cc = colourOf(q.carry); }
    if (p.station?.startsWith("bay_") && picked) st.taken = p.station.slice(4);
    if (p.station === "oven" && placed) st.ovenIn = true;
    // the bake starts once the arm is clear of the oven: back at transit height (the original
    // path), or on its way to the next station (Upgrade 10's blended path never climbs to transit)
    if (st.ovenIn && !st.ovenGo && (p.station !== "oven" || p.pz >= doc.vgr.plan.transit - 0.5))
      st.ovenGo = true;
    k(T.conveyor, L.transit, F.retracted, vg, "belt", FROM,
      { vs: p.sw, vr: p.rr, vp: p.pz, vc: p.compress, cup: p.cup, carry: p.carry }, `VGR: ${p.say}`);
  }

  // ---- the BAKED cookie goes back into the rack in its mould ----
  const back = collect ? "the finished cookie" : "the empty mould";
  k(T.conveyor, L.transit, F.retracted, hb, "belt", FROM, V0, `Q2 belt reverse — ${back} rides back to the crane`);
  k(T.conveyor, L.belt_under, F.retracted, hb, "belt", FROM, V0, "descend below the mould");
  k(T.conveyor, L.belt_under, F.conveyor, hb, "belt", FROM, V0, "Ausleger under the mould");
  k(T.conveyor, L.belt_lift, F.conveyor, hb, "fork", FROM, V0, `lift — ${back} off the belt`);
  k(T.conveyor, L.belt_lift, F.retracted, hb, "fork", FROM, V0, "retract");
  k(T.conveyor, L.transit, F.retracted, hb, "fork", FROM, V0, "raise to transit");
  k(TT, L.transit, F.retracted, hb, "fork", FROM, V0, `travel to bay column ${tcol} — ${free} is free`);
  k(TT, LTl, F.retracted, hb, "fork", FROM, V0, `descend to shelf ${tr}`);
  k(TT, LTl, F.bay, hb, "fork", FROM, V0, "Ausleger into the empty bay");
  k(TT, LTu, F.bay, hb, "shelf", free, V0, `lower — ${back} is stored in ${free}`);
  k(TT, LTu, F.retracted, hb, "shelf", free, V0, "retract");
  k(TT, L.transit, F.retracted, hb, "shelf", free, V0, "raise to transit");
  k(T.conveyor, L.transit, F.retracted, hb, "shelf", free, V0, "return to park — cycle complete");
  return out;
}

const SPEED = 14.27; // mm/s, the real encoder-motor rate
const BELT_SPEED = 25; // mm/s - slowed so the hand-over reads clearly
export const RATE = 4; // playback speedup
/** Review aid: ?speed=N plays the cell N times faster still (e.g. to watch a whole order). */
const PLAYBACK = Math.max(0.1, Math.min(50, Number(new URLSearchParams(window.location.search).get("speed")) || 1));

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
    const [, len, dia] = a.s as [string, number, number];
    const r = dia / 2 + 1.0;
    const A = new THREE.Vector2(a.p[1], a.p[2]), B = new THREE.Vector2(b.p[1], b.p[2]);
    const d = B.clone().sub(A).normalize();
    const n = new THREE.Vector2(-d.y, d.x);
    const L1 = A.distanceTo(B), arc = Math.PI * r, total = 2 * L1 + 2 * arc;
    const count = Math.round(total / 3);
    return { x: a.p[0] + len / 2, w: len - 1, r, A, B, d, n, L1, arc, total, count };
  }, [doc]);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  useFrame(() => {
    if (!g || !band.current || !teeth.current) return;
    const at = (s0: number) => {
      const s = ((s0 % g.total) + g.total) % g.total;
      const { A, B, d, n, r, L1, arc } = g;
      if (s < L1) return { p: A.clone().addScaledVector(n, r).addScaledVector(d, s), t: d.clone() };
      if (s < L1 + arc) {
        const th = (s - L1) / r;
        return { p: B.clone().addScaledVector(n, r * Math.cos(th)).addScaledVector(d, r * Math.sin(th)),
                 t: n.clone().multiplyScalar(-Math.sin(th)).addScaledVector(d, Math.cos(th)) };
      }
      if (s < 2 * L1 + arc)
        return { p: B.clone().addScaledVector(n, -r).addScaledVector(d, -(s - L1 - arc)), t: d.clone().negate() };
      const th = (s - 2 * L1 - arc) / r;
      return { p: A.clone().addScaledVector(n, -r * Math.cos(th)).addScaledVector(d, -r * Math.sin(th)),
               t: n.clone().multiplyScalar(Math.sin(th)).addScaledVector(d, -Math.cos(th)) };
    };
    // the drum pulley shares the drum's axle, so the loop runs at the drum's
    // angular speed times the pulley radius
    const off = drive.current.belt * ((g.r - 1) / (doc.belt.pulley_d / 2));
    for (let i = 0; i < g.count; i++) {
      const s = (i * g.total) / g.count;
      for (const [mesh, sh] of [[band.current, 0], [teeth.current, off]] as const) {
        const { p, t } = at(s + sh);
        dummy.position.copy(v(g.x, p.x, p.y));
        dummy.rotation.set(Math.atan2(-t.y, t.x), 0, 0);
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

/** Each end-of-belt light barrier: LED on one side rail, phototransistor on the
    other, and the beam between them at mould-rim height. Broken beam = the
    receiver's indicator blinks and the beam flickers. */
function LightBarriers({ doc }: { doc: CadDoc }) {
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
      {pairs.map(({ rx, tx }) => <Barrier key={rx.n} rx={rx} tx={tx} />)}
    </group>
  );
}

function Barrier({ rx, tx }: { rx: CadPart; tx: CadPart }) {
  const beam = useRef<THREE.Mesh>(null);
  const led = useRef<THREE.MeshStandardMaterial>(null);
  const [sx, sy, sz] = rx.s as [number, number, number];
  const x0 = rx.p[0] + sx, x1 = tx.p[0];
  const yc = rx.p[1] + sy / 2, zc = rx.p[2] + sz / 2;
  useFrame(({ clock }) => {
    const hit = !!hbwHot.blocked[rx.tag];
    const on = Math.floor(clock.getElapsedTime() * 8) % 2 === 0;
    if (beam.current) beam.current.visible = !hit || on;
    if (led.current) {
      led.current.color.set(hit ? "#ff3b30" : "#39d353");
      led.current.emissive.set(hit ? "#ff3b30" : "#39d353");
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

export function HbwCad({ doc, onPhase, tours }: {
  doc: CadDoc; onPhase?: (s: string) => void; tours?: Record<string, PlanKey[]> | null;
}) {
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
  const drive = useRef<Drive>({
    travel: doc.home.travel, lift: doc.home.lift, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0,
  });

  // Each cycle bakes one ordered cookie: a raw cookie leaves its slot, is baked in the order's
  // flavour and sorted into that flavour's Lagerstelle. The VGR waits for it there, carries it
  // back to the belt and the crane stores it in the slot it came from. No order: the cell idles.
  const planCycle = useMemo(() => {
    const cache = new Map<string, ReturnType<typeof plan1>>();
    function plan1(from: string, to: string, flavour: string, collect: string | null) {
      const tour = tours?.[collect ?? "none"] ?? doc.vgr.plan.keys;
      const keys = script(doc, from, to, tour, collect);
      let t0 = 0;
      const legs = keys.slice(1).map((b, i) => {
        const a = keys[i];
        const axes = Math.abs(b.t - a.t) + Math.abs(b.l - a.l) + Math.abs(b.f - a.f);
        const belt = Math.abs(b.b - a.b);
        // the VGR's own axes, swivel counted at ~2 mm of arc per degree
        const vgr = Math.abs(b.vs - a.vs) * 2 + Math.abs(b.vr - a.vr) + Math.abs(b.vp - a.vp);
        const pause = (a.cup !== b.cup ? 1.0 : 0) + (a.vc !== b.vc ? 0.5 : 0);
        const dur = Math.max(0.4, (axes + vgr) / (SPEED * RATE) + belt / (BELT_SPEED * RATE) + pause);
        const leg = { a, b, dur, start: t0 };
        t0 += dur;
        return leg;
      });
      // the bake cycle starts once the VGR is back at transit height, clear of the oven
      const i0 = legs.findIndex((l) => l.a.ovenGo);
      const tOvenGo = i0 >= 0 ? legs[i0].start : Infinity;
      const flow = buildFlow(doc, flavour);
      // The VGR collects THIS cookie from its Lagerstelle, so it holds clear of the oven until
      // the cookie has been baked and sorted, then fetches it (1.5 s after it lands).
      const pick = legs.find((l) => !l.a.taken && l.b.taken === flow.bin);
      const wait = pick && i0 >= 0 ? Math.max(0, tOvenGo + flow.arrive + 1.5 - pick.start) : 0;
      if (wait > 0) {
        const a = legs[i0].a;
        const hold = { a, b: { ...a, say: "VGR: holds clear of the oven while the cookie is baked and sorted" }, dur: wait, start: tOvenGo };
        for (const l of legs.slice(i0)) l.start += wait;
        legs.splice(i0, 0, hold);
      }
      const total = Math.max(legs.reduce((q, l) => q + l.dur, 0), tOvenGo + flow.total + 3);
      const baked = doc.pipeline.flavours[flavour]?.colour ?? doc.pipeline.raw_colour;
      return { from, to, legs, tOvenGo, flow, total, baked, flavour, collect,
               collectColour: collect ? binColour(doc, collect) : null, bin: flow.bin as string };
    }
    return (from: string, to: string, flavour: string, collect: string | null) => {
      const key = `${from}>${to}>${flavour}>${collect}`;
      if (!cache.has(key)) cache.set(key, plan1(from, to, flavour, collect));
      return cache.get(key)!;
    };
  }, [doc, tours]);
  type Cycle = ReturnType<typeof planCycle> & { line: number };
  const RAW = doc.pipeline.raw_colour;
  // twelve slots, twelve moulds, twelve cookies of raw dough
  const freshRack = useMemo(() => () => {
    const r: Rack = {};
    for (const q of Object.keys(doc.slots)) r[q] = RAW;
    return r;
  }, [doc, RAW]);
  const rawIn = (r: Rack) => Object.keys(doc.slots).filter((q) => r[q] === RAW);
  /** The next ordered cookie, if any: its flavour and its order line. */
  const nextWork = () => {
    const line = twinOrders.queue.find((o) => o.started < o.qty);
    if (!line) return null;
    line.started++;
    return line;
  };
  /** Plan the next cycle: the first raw cookie goes out and comes back baked into the same slot. */
  const begin = (r: Rack, line: OrderLine): { c: Cycle; r: Rack } => {
    const from = rawIn(r)[0] ?? FROM;
    const bin = doc.pipeline.flavours[line.flavour]?.bin ?? null;
    return { c: { ...planCycle(from, from, line.flavour, bin), line: line.id }, r };
  };
  const start = useMemo(() => {
    if (!twinOrders.queue.length) {
      // what a visitor sees first: one cookie of each flavour, then the cell waits for an order
      for (const f of Object.keys(doc.pipeline.flavours)) {
        twinOrders.queue.push({ id: ++twinOrders.seq, flavour: f, qty: 1, started: 0, done: 0, demo: true });
      }
    }
    for (const c of doc.sorting.colours) twinOrders.bays[c] ??= [];
    const r0 = { ...freshRack() };
    const line = nextWork()!;
    return begin(r0, line);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, planCycle]);
  const rackRef = useRef<Rack>(start.r);
  const [rack, setRack] = useState<Rack>(rackRef.current);
  const first = start.c;
  const cyc = useRef<{ c: Cycle; t0: number }>({ c: first, t0: 0 });
  const [cur, setCur] = useState<Cycle>(first);
  twinOrders.raw = rawIn(rack);
  twinOrders.rack = rack;
  twinOrders.rawColour = RAW;
  const { legs, tOvenGo, flow, total } = first;   // ?at= / ?t= review the first cycle

  // The mould and cookie that circulate are drawn dynamically; hide the static
  // copies of the slot they start in.
  const byFrame = useMemo(() => {
    const m: Record<string, CadPart[]> = { world: [], travel: [], lift: [], fork: [] };
    for (const p of doc.parts) {
      // every mould and cookie in the rack is drawn from the live rack state
      if (/^(mould|wp)_[A-Z]\d+_/.test(p.n)) continue;
      m[p.f].push(p);
    }
    return m;
  }, [doc]);

  // light-barrier beams: which belt stretch each one watches, and at what height
  const beams = useMemo(
    () =>
      doc.parts
        .filter((p) => p.mech === "beam:rx")
        .map((p) => {
          const [, sy, sz] = p.s as [number, number, number];
          return { tag: p.tag, y0: p.p[1], y1: p.p[1] + sy, z: p.p[2] + sz / 2 };
        }),
    [doc],
  );

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

  const [, md, mb] = doc.moulds.size;
  const load = mb + doc.moulds.rim_h + 8; // mould plus the cookie standing above its rim
  // Where the load sits when it is on the fork, DERIVED from the fork table part
  // itself. This was a literal, and when the rail moved the carried mould stayed
  // 150 mm behind - drawn straight through the rack and the stored moulds.
  const seat = useMemo(() => {
    const t = doc.parts.find((p) => p.n === "fork_table");
    if (!t) return { y: 0, z: 10 };
    const [, dy, dz] = t.s as [number, number, number];
    return { y: t.p[1] + dy / 2, z: t.p[2] + dz };
  }, [doc]);
  const phase = useRef("");

  // Review aid: ?at=<phrase>[&n=2] freezes the cycle at the END of the n-th step
  // whose caption contains <phrase> (e.g. ?at=cup%20meets&n=2), so any single
  // moment of the choreography can be inspected up close.
  const frozen = useMemo(() => {
    const q = new URLSearchParams(window.location.search);
    const t = q.get("t");
    if (t !== null && Number.isFinite(Number(t))) return Number(t) % total;
    const at = q.get("at");
    if (!at) return null;
    const hits = legs.filter((l) => l.b.say.toLowerCase().includes(at.toLowerCase()));
    const l = hits[Math.max(0, Number(q.get("n") ?? 1) - 1)];
    if (l) return l.start + l.dur - 1e-3;
    // ...or a step of the oven/sorting flow
    const st = flow.steps.find((x) => x.say.toLowerCase().includes(at.toLowerCase()));
    return st ? tOvenGo + st.t0 + st.d - 1e-3 : null;
  }, [legs, total, flow, tOvenGo]);

  useFrame(({ clock }) => {
    const el = clock.getElapsedTime() * PLAYBACK;
    if (frozen === null && !twinOrders.idle && el - cyc.current.t0 >= cyc.current.c.total) {
      // the cycle is complete: the cookie baked in it is back in its slot
      const done = cyc.current.c;
      const r: Rack = { ...rackRef.current };
      r[done.to] = done.baked;
      const line = twinOrders.queue.find((o) => o.id === done.line);
      if (line) line.done++;
      rackRef.current = r;
      setRack(r);
      twinOrders.idle = true;                      // until there is another cookie to make
    }
    if (twinOrders.idle && frozen === null && twinOrders.restock) {
      // the finished cookies are delivered and their moulds refilled with fresh dough
      const r: Rack = { ...rackRef.current };
      for (const q of Object.keys(r)) if (r[q] !== RAW) { r[q] = RAW; twinOrders.delivered++; }
      twinOrders.restock = false;
      rackRef.current = r;
      setRack(r);
      twinOrders.raw = rawIn(r);
    }
    if (twinOrders.idle && frozen === null) {
      const line = nextWork();
      if (line) {
        const nx = begin(rackRef.current, line);
        if (nx.r !== rackRef.current) { rackRef.current = nx.r; setRack(nx.r); }
        cyc.current = { c: nx.c, t0: el };
        setCur(nx.c);
        twinOrders.idle = false;
      }
    }
    const C = cyc.current.c;
    const legs = C.legs, flow = C.flow, tOvenGo = C.tOvenGo;
    // idle: the cell rests in the pose its last cycle ended in
    const tc = frozen ?? (twinOrders.idle ? C.total : el - cyc.current.t0);
    cycleHot.from = C.from; cycleHot.to = C.to; cycleHot.bin = C.bin;
    twinOrders.cycle = { from: C.from, to: C.to, total: C.total, t: tc, flavour: C.flavour, collect: C.collect ?? "" };
    let leg = legs[legs.length - 1];
    for (const l of legs) {
      if (tc < l.start + l.dur) { leg = l; break; }
    }
    const s = THREE.MathUtils.smoothstep((tc - leg.start) / leg.dur, 0, 1);
    const mix = (a: number, b: number) => a + (b - a) * s;
    const d = drive.current;
    d.travel = mix(leg.a.t, leg.b.t);
    d.lift = mix(leg.a.l, leg.b.l);
    d.fork = mix(leg.a.f, leg.b.f);
    d.belt = mix(leg.a.b, leg.b.b);
    const ax = hbwHot.axes;                          // in place: no allocation per frame
    ax.travel = d.travel; ax.lift = d.lift; ax.fork = d.fork; ax.belt = d.belt;

    // VGR: every axis rides the same interpolation, including the spring stem
    vgrHot.swivel = mix(leg.a.vs, leg.b.vs);
    vgrHot.reach = mix(leg.a.vr, leg.b.vr);
    vgrHot.plunge = mix(leg.a.vp, leg.b.vp);
    vgrHot.compress = mix(leg.a.vc, leg.b.vc);
    vgrHot.cup = leg.a.cup;
    // vacuum builds (or bleeds off) across the step where Q8 switches
    vgrHot.seal = mix(leg.a.cup ? 1 : 0, leg.b.cup ? 1 : 0);
    vgrHot.carry = leg.a.carry;
    vgrHot.cupColour = leg.a.carry === "baked" ? (C.collectColour ?? RAW) : RAW;
    hbwCookieHot.colour = leg.a.cc;
    sortHot.taken = twinOrders.idle ? null : leg.a.taken;

    // oven + sorting: idle and ready until the VGR has delivered and left, then
    // the one cookie runs its whole journey (OvenFlow.ts)
    let say = leg.b.say;
    const f = flow.at(tc - tOvenGo);
    ovenHot.s = f.s;
    ovenHot.mode = f.mode;
    // once the cycle is done, its cookie is part of the Lagerstelle's stock (SortingModule draws it)
    // ...until the VGR lifts it out of its Lagerstelle
    ovenHot.visible = !twinOrders.idle && (tc >= tOvenGo || leg.a.ovenIn) && !leg.a.taken;
    ovenHot.pos = flow.pos(f.s, f.mode);
    ovenHot.belts = flow.belts(f.s.ly);
    ovenHot.colour = new THREE.Color(RAW).lerp(new THREE.Color(C.baked), f.s.baked).getStyle();
    if (f.say) say = `${say}   ·   ${f.say}`;

    if (gTravel.current) gTravel.current.position.x = d.travel * MM;
    if (gLift.current) gLift.current.position.y = d.lift * MM;
    if (gFork.current) gFork.current.position.z = d.fork * MM;

    const held = leg.a.held;
    if (gOnFork.current) gOnFork.current.visible = held === "fork";
    if (gOnBelt.current) {
      gOnBelt.current.visible = held === "belt";
      gOnBelt.current.position.z = d.belt * MM;
    }
    if (gStowed.current) gStowed.current.visible = held === "shelf";
    if (stowRef.current && held === "shelf") {
      const sp = doc.slots[leg.a.slot];
      stowRef.current.position.set(sp[0] * MM, sp[2] * MM, sp[1] * MM);
    }
    const c = leg.a.cookie;
    if (gCookieFork.current) gCookieFork.current.visible = c && held === "fork";
    if (gCookieBelt.current) gCookieBelt.current.visible = c && held === "belt";
    if (gCookieShelf.current) gCookieShelf.current.visible = c && held === "shelf";

    // light barriers: is the mould (or the cookie in it) across a beam?
    let yc = NaN, zb = NaN;
    if (held === "belt") { yc = d.belt; zb = doc.belt.surface; }
    else if (held === "fork" && Math.abs(d.travel - doc.belt.x) < 5) { yc = seat.y + d.fork; zb = seat.z + d.lift; }
    for (const bm of beams) {
      hbwHot.blocked[bm.tag] = !Number.isNaN(yc)
        && yc + md / 2 > bm.y0 && yc - md / 2 < bm.y1
        && bm.z > zb && bm.z < zb + load;
    }
    if (phase.current !== say) { phase.current = say; twinOrders.step = say; onPhase?.(say); }
    // priority -1: this timeline writes the shared "hot" state BEFORE the parts
    // that read it (cookie colours) run their own frame callbacks - otherwise a
    // cookie shows the previous cycle's colour for one frame
  }, -1);

  const P = (p: CadPart) => <Solid key={p.n} part={p} drive={drive} pitch={doc.pitch_mm} tex={tex} drumD={doc.belt.pulley_d} />;
  const beltX = doc.stations.hbw_pick[0], beltZ = doc.stations.hbw_pick[2];

  return (
    <group>
      {byFrame.world.map(P)}
      {doc.chains?.chains["hbw:travel"] && (
        <DragChain spec={doc.chains.chains["hbw:travel"]} joint={() => drive.current.travel} />
      )}
      {/* the rack as it stands after every cycle so far - the circulating
          mould's own slot is drawn by the stowed group below */}
      {Object.entries(rack).filter(([q]) => q !== cur.from).map(([q, col]) => {
        const sp = doc.slots[q];
        return (
          <group key={q} position={[sp[0] * MM, sp[2] * MM, sp[1] * MM]}>
            <Mould x={0} y={0} z={0} doc={doc} />
            {col && <Cookie x={0} y={0} z={mb} colour={col} />}
          </group>
        );
      })}
      <RackBadge doc={doc} rack={rack} raw={RAW} />
      <BeltLoop doc={doc} drive={drive} />
      <LightBarriers doc={doc} />

      {/* the circulating mould, stowed in a slot */}
      <group ref={gStowed}>
        <group ref={stowRef}>
          <Mould x={0} y={0} z={0} doc={doc} />
          <group ref={gCookieShelf}>
            <Cookie x={0} y={0} z={mb} hot={hbwCookieHot} />
          </group>
        </group>
      </group>

      {/* on the belt: translated along +Y by the belt position each frame */}
      <group ref={gOnBelt}>
        <Mould x={beltX} y={0} z={beltZ} doc={doc} />
        <group ref={gCookieBelt}>
          <Cookie x={beltX} y={0} z={beltZ + mb} hot={hbwCookieHot} />
        </group>
      </group>

      <group ref={gTravel}>
        {byFrame.travel.map(P)}
        {doc.chains?.chains["hbw:lift"] && (
          <DragChain spec={doc.chains.chains["hbw:lift"]}
            joint={() => drive.current.lift + doc.chains!.chains["hbw:lift"].M[2]} />
        )}
        <group ref={gLift}>
          {byFrame.lift.map(P)}
          <group ref={gFork}>
            {byFrame.fork.map(P)}
            {/* seated on the fork table: local table top = lift + 10 -> z = 10 */}
            <group ref={gOnFork}>
              <Mould x={0} y={seat.y} z={seat.z} doc={doc} />
              <group ref={gCookieFork}>
                <Cookie x={0} y={seat.y} z={seat.z + mb} hot={hbwCookieHot} />
              </group>
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}


/** App owns the fetch so it can render a plain-HTML HUD outside the Canvas. */

/** Compression spring round the stem: a real helix whose pitch closes up as the
    carriage over-travels past the cookie's top face. */
function Coil({ h, r }: { h: number; r: number }) {
  const geo = useMemo(() => {
    const turns = 7, n = 160;
    const pts = Array.from({ length: n + 1 }, (_, i) => {
      const t = i / n, a = t * turns * Math.PI * 2;
      return new THREE.Vector3(Math.cos(a) * r, t * h, Math.sin(a) * r);
    });
    return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), n, 0.9 * MM, 6, false);
  }, [h, r]);
  return (
    <mesh geometry={geo} castShadow>
      <meshStandardMaterial color="#c9ced3" metalness={0.8} roughness={0.3} />
    </mesh>
  );
}

/** The VGR: cylindrical R-P-P, so the first joint is a ROTATION.
    world -> swivel(Rz about the tower axis) -> plunge(+Z) -> reach(-Y). Both
    linear axes are spindles (4 mm lead) that turn with the axis they drive. The
    cup rides a spring stem: at contact the carriage over-travels, the spring
    closes, the cup stays on the cookie's top face and flattens as it seals. */
function VgrModule({ doc, drive }: { doc: CadDoc; drive: React.MutableRefObject<Drive> }) {
  const gSwivel = useRef<THREE.Group>(null);
  const gPlunge = useRef<THREE.Group>(null);
  const gReach = useRef<THREE.Group>(null);
  const gCup = useRef<THREE.Group>(null);
  const gCupBody = useRef<THREE.Group>(null);
  const gCoil = useRef<THREE.Group>(null);
  const onCup = useRef<THREE.Group>(null);
  const [cx, cy] = doc.vgr.centre;
  const A = doc.vgr.authoring;
  const over = doc.vgr.plan.overtravel;
  const byFrame = useMemo(() => {
    const m: Record<string, CadPart[]> = { world: [], swivel: [], plunge: [], reach: [] };
    for (const p of doc.vgr.parts) {
      if (p.n === "suction_cup" || p.n === "suction_stem") continue; // drawn below
      m[p.f].push(p);
    }
    return m;
  }, [doc]);
  const cup = doc.vgr.parts.find((p) => p.n === "suction_cup")!;
  const stem = doc.vgr.parts.find((p) => p.n === "suction_stem")!;
  const [, cupH, cupD] = cup.s as [string, number, number];
  const [, stemL] = stem.s as [string, number, number];
  const cupZ = cup.p[2];                 // cup underside, authoring pose
  const cupTop = cupZ + cupH;
  const headZ = stem.p[2] + stemL;       // underside of the suction head
  const coilL = headZ - cupTop;
  const tex = useMemo(() => new THREE.Texture(), []);

  useFrame(() => {
    if (gSwivel.current) gSwivel.current.rotation.y = -THREE.MathUtils.degToRad(vgrHot.swivel);
    // parts are emitted at doc.vgr.authoring; the groups carry only the DELTA
    if (gPlunge.current) gPlunge.current.position.y = (vgrHot.plunge - A.plunge) * MM;
    if (gReach.current) gReach.current.position.z = -(vgrHot.reach - A.reach) * MM;
    drive.current.plunge = vgrHot.plunge;
    drive.current.reach = vgrHot.reach;
    drive.current.swivel = vgrHot.swivel;
    const c = vgrHot.compress;
    if (gCup.current) gCup.current.position.y = c * MM;
    if (gCoil.current) {
      gCoil.current.position.y = c * MM;
      gCoil.current.scale.y = (coilL - c) / coilL;
    }
    // the rubber cup flattens while it is sucked onto the cookie
    const seal = vgrHot.seal * Math.min(1, c / over);
    if (gCupBody.current) gCupBody.current.scale.y = 1 - 0.3 * seal;
    if (onCup.current) onCup.current.visible = vgrHot.carry !== null;
  });

  const P = (p: CadPart) => <Solid key={p.n} part={p} drive={drive} pitch={doc.vgr.pitch_mm} tex={tex} />;
  const back = v(-cx, -cy, 0);
  const [px, py] = [cup.p[0], cup.p[1]];
  const R = (cupD / 2) * MM;
  return (
    <group>
      {byFrame.world.map(P)}
      <group position={v(cx, cy, 0)}>
        <group ref={gSwivel}>
          <group position={back}>
            {byFrame.swivel.map(P)}
            {doc.chains?.chains["vgr:plunge"] && (
              <DragChain spec={doc.chains.chains["vgr:plunge"]}
                joint={() => vgrHot.plunge + doc.chains!.chains["vgr:plunge"].M[2]} />
            )}
            <group ref={gPlunge}>
              {byFrame.plunge.map(P)}
              {doc.chains?.chains["vgr:reach"] && (
                <DragChain spec={doc.chains.chains["vgr:reach"]} zBase={A.plunge}
                  joint={() => doc.chains!.chains["vgr:reach"].M[1] - vgrHot.reach} />
              )}
              <group ref={gReach}>
                {byFrame.reach.map(P)}
                {/* spring: from the cup's top up to the underside of the head */}
                <group position={v(px, py, cupTop)}>
                  <group ref={gCoil}>
                    <Coil h={coilL * MM} r={7 * MM} />
                  </group>
                </group>
                <group ref={gCup}>
                  {/* guide rod: rides with the cup and slides up into the head */}
                  <mesh position={v(px, py, cupTop + (coilL + 4) / 2)} castShadow>
                    <cylinderGeometry args={[2.6 * MM, 2.6 * MM, (coilL + 4) * MM, 12]} />
                    <meshStandardMaterial color="#aeb4b8" metalness={0.8} roughness={0.3} />
                  </mesh>
                  {/* the rubber cup - pivots at its lip so it squashes onto the cookie */}
                  <group ref={gCupBody} position={v(px, py, cupZ)}>
                    <mesh position={[0, (cupH / 2) * MM, 0]} castShadow>
                      <cylinderGeometry args={[R * 0.45, R, cupH * MM, 28, 1, true]} />
                      <meshStandardMaterial color="#1c1d20" roughness={0.85} side={THREE.DoubleSide} />
                    </mesh>
                    <mesh position={[0, cupH * MM, 0]}>
                      <cylinderGeometry args={[R * 0.45, R * 0.45, 2 * MM, 20]} />
                      <meshStandardMaterial color="#1c1d20" roughness={0.85} />
                    </mesh>
                  </group>
                  {/* held cookie: its top face on the cup lip */}
                  <group ref={onCup}>
                    <Cookie x={px} y={py} z={cupZ - 20} dynamic />
                  </group>
                </group>
              </group>
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}

/** The oven station, rebuilt to Abb. 9: Ofenschieber (+X), Ofentuer (+Z),
    the station's own Sauger (+Y) with its one-stroke lowering cylinder (-Z),
    the Drehtisch (Rz), the Saege and the Auswerfer (+Y). Every joint is read
    from ovenHot, which the one shared timeline writes. The cookie itself is
    drawn once, at factory level (FlowCookie), not per holder. */
function OvenModule({ doc }: { doc: CadDoc }) {
  const g = {
    slider: useRef<THREE.Group>(null), door: useRef<THREE.Group>(null),
    turn: useRef<THREE.Group>(null), sauger: useRef<THREE.Group>(null),
    lower: useRef<THREE.Group>(null), push: useRef<THREE.Group>(null),
  };
  const lamp = useRef<THREE.MeshStandardMaterial>(null);
  const lampLight = useRef<THREE.PointLight>(null);
  const cup = useRef<THREE.MeshStandardMaterial>(null);
  const beltDrive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  const sawDrive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  const [tx, ty] = doc.oven.turntable;
  const A = doc.oven.authoring;
  const byFrame = useMemo(() => {
    const m: Record<string, CadPart[]> = {
      world: [], slider: [], door: [], turn: [], sauger: [], lower: [], push: [],
    };
    for (const p of doc.oven.parts) if (p.n !== "Q9_oven_lamp") (m[p.f] ??= []).push(p);
    return m;
  }, [doc]);
  const lampPart = doc.oven.parts.find((p) => p.n === "Q9_oven_lamp");
  const tex = useBeltTexture();

  useFrame(() => {
    const s = ovenHot.s;
    if (!s) return;
    // module frame = factory axes: +X -> three x, +Y -> three z, +Z -> three y
    if (g.slider.current) g.slider.current.position.x = (s.slider - A.slider) * MM;
    if (g.door.current) g.door.current.position.y = (s.door - A.door) * MM;
    if (g.turn.current) g.turn.current.rotation.y = -THREE.MathUtils.degToRad(s.turn - A.turn);
    if (g.sauger.current) g.sauger.current.position.z = (s.sauger - A.sauger) * MM;
    if (g.lower.current) g.lower.current.position.y = -(s.lower - A.lower) * MM;
    if (g.push.current) g.push.current.position.z = (s.push - A.push) * MM;
    if (lamp.current) {
      lamp.current.emissiveIntensity = 0.05 + 4 * s.lamp;
      lamp.current.color.set(s.lamp > 0.5 ? "#ffb13b" : "#6f6a5e");
    }
    if (lampLight.current) lampLight.current.intensity = 3 * s.lamp;
    if (cup.current) cup.current.emissiveIntensity = 0.6 * s.vac;
    beltDrive.current.belt = ovenHot.belts.oven;
    sawDrive.current.belt = s.saw * 20;
  });

  const P = (p: CadPart) => {
    const drive = p.mech === "spin:saw" ? sawDrive : beltDrive;
    // the disc turns with its group; drawn as a plain solid, not a belt roller
    const part = p.mech === "spin:turn" ? { ...p, mech: "" } : p;
    if (p.n === "Q11_suction_cup") {
      const [, len, dia] = p.s as [string, number, number];
      return (
        <mesh key={p.n} position={centreOf(p)} castShadow>
          <cylinderGeometry args={[(dia / 2) * MM * 0.55, (dia / 2) * MM, len * MM, 24]} />
          <meshStandardMaterial ref={cup} color={p.c} roughness={0.8} emissive="#3aa0ff" emissiveIntensity={0} />
        </mesh>
      );
    }
    return <Solid key={p.n} part={part} drive={drive} pitch={4} tex={tex} />;
  };
  return (
    <group>
      {byFrame.world.map(P)}
      {lampPart && (() => {
        // Q9 "Leuchte Ofen": a lamp on the roof you can see from anywhere -
        // dark when idle, glowing amber (and lighting the chamber) while baking
        const [dx, dy, dz] = lampPart.s as [number, number, number];
        const [px, py, pz] = lampPart.p;
        return (
          <group>
            <mesh position={centreOf(lampPart)} castShadow>
              <boxGeometry args={[dx * MM, dz * MM, dy * MM]} />
              <meshStandardMaterial color="#2a2b2e" roughness={0.6} />
            </mesh>
            <mesh position={v(px + dx / 2, py + dy / 2, pz + dz + 7)}>
              <sphereGeometry args={[8 * MM, 20, 16]} />
              <meshStandardMaterial ref={lamp} color="#6f6a5e" emissive="#ff7a00" emissiveIntensity={0.05} toneMapped={false}
                transparent opacity={0.92} />
            </mesh>
            <pointLight ref={lampLight} position={v(200, 100, 150)} color="#ff9a3c" intensity={0} distance={4} decay={2} />
          </group>
        );
      })()}
      <group ref={g.slider}>{byFrame.slider.map(P)}</group>
      <group ref={g.door}>{byFrame.door.map(P)}</group>
      <group ref={g.push}>{byFrame.push.map(P)}</group>
      <group ref={g.sauger}>
        {byFrame.sauger.map(P)}
        <group ref={g.lower}>{byFrame.lower.map(P)}</group>
      </group>
      <group position={v(tx, ty, 0)}>
        <group ref={g.turn}>
          <group position={v(-tx, -ty, 0)}>{byFrame.turn.map(P)}</group>
        </group>
      </group>
    </group>
  );
}

/** The one travelling cookie, in FACTORY coordinates: wherever the flow says it
    is, in whatever colour the bake has given it. */
function FlowCookie() {
  const grp = useRef<THREE.Group>(null);
  const hot = useMemo(() => ({ colour: "#D8B98C" }), []);
  useFrame(() => {
    if (!grp.current) return;
    grp.current.visible = ovenHot.visible;
    const [x, y, z] = ovenHot.pos;
    grp.current.position.set(x * MM, z * MM, y * MM);
    hot.colour = ovenHot.colour;
  });
  return (
    <group ref={grp}>
      <Cookie x={0} y={0} z={0} hot={hot} />
    </group>
  );
}

/** Light barriers on the oven and the sorting line: a beam from each LED to
    its phototransistor; when the travelling cookie (or a cookie resting in a
    Lagerstelle) cuts it, the beam flickers and the receiver blinks red. */
function FlowBarriers({ doc }: { doc: CadDoc }) {
  const pairs = useMemo(() => {
    const [ox, oy] = doc.factory.oven_placement.translate;
    const [stx, sty] = doc.factory.sort_placement.translate;
    const out: { tag: string; a: THREE.Vector3; b: THREE.Vector3; bin?: string }[] = [];
    const centre = (p: CadPart): [number, number, number] => {
      const [dx, dy, dz] = p.s as [number, number, number];
      return [p.p[0] + dx / 2, p.p[1] + dy / 2, p.p[2] + dz / 2];
    };
    const add = (parts: CadPart[], tf: (x: number, y: number) => [number, number]) => {
      // a barrier is a TAGGED rx/tx pair - the posts they stand on are named
      // *_post_rx / *_post_tx too, and were drawn as a beam under the tray
      for (const rx of parts.filter((p) => p.n.endsWith("_rx") && p.k === "box" && p.tag)) {
        const tx = parts.find((p) => p.n === rx.n.replace(/_rx$/, "_tx"));
        if (!tx) continue;
        const [ax, ay, az] = centre(rx), [bx, by, bz] = centre(tx);
        const [fax, fay] = tf(ax, ay), [fbx, fby] = tf(bx, by);
        const bin = doc.sorting.colours.find((c) => rx.n.includes(`bay_${c}`));
        out.push({ tag: rx.tag, a: new THREE.Vector3(fax, fay, az), b: new THREE.Vector3(fbx, fby, bz), bin });
      }
    };
    add(doc.oven.parts, (x, y) => [-y + ox, x + oy]);
    add(doc.sorting.parts, (x, y) => [-y + stx, x + sty]);
    return out;
  }, [doc]);
  const stock = useMemo(() => {
    const [stx, sty] = doc.factory.sort_placement.translate;
    return Object.fromEntries(
      Object.entries(doc.sorting.handovers).map(([c, h]) => [c, [-h[1] + stx, h[0] + sty] as [number, number]]),
    );
  }, [doc]);
  const beams = useRef<(THREE.Mesh | null)[]>([]);
  const leds = useRef<(THREE.MeshStandardMaterial | null)[]>([]);
  useFrame(({ clock }) => {
    const on = Math.floor(clock.getElapsedTime() * 8) % 2 === 0;
    const cookies: [number, number][] = [];
    if (ovenHot.visible) cookies.push([ovenHot.pos[0], ovenHot.pos[1]]);
    for (const [c, xy] of Object.entries(stock)) {
      if ((twinOrders.bays[c] ?? []).length - (sortHot.taken === c ? 1 : 0) > 0) cookies.push(xy);
    }
    pairs.forEach((pr, i) => {
      // where along the beam (0 = receiver, 1 = LED) a cookie blocks it: the
      // light from the LED stops at the cookie's near face, it never passes through
      let stop = 0;
      const ab = new THREE.Vector2(pr.b.x - pr.a.x, pr.b.y - pr.a.y);
      const L = ab.length();
      for (const [cx, cy] of cookies) {
        const ac = new THREE.Vector2(cx - pr.a.x, cy - pr.a.y);
        const u = ac.dot(ab) / (L * L);
        const d = ac.clone().sub(ab.clone().multiplyScalar(u)).length();
        if (u < 0 || u > 1 || d >= 22.5 || !(pr.a.z > 55 && pr.a.z < 85)) continue;
        stop = Math.max(stop, u + Math.sqrt(22.5 * 22.5 - d * d) / L);
      }
      const hit = stop > 0;
      const m = beams.current[i], l = leds.current[i];
      if (m) {
        const keep = Math.max(0.001, 1 - Math.min(1, stop));
        m.scale.set(1, keep, 1);
        const p = pr.b.clone().lerp(pr.a, keep / 2);
        m.position.copy(v(p.x, p.y, p.z));
      }
      if (l) {
        l.color.set(hit ? "#ff3b30" : "#39d353");
        l.emissive.set(hit ? "#ff3b30" : "#39d353");
        l.emissiveIntensity = hit ? (on ? 3 : 0.2) : 0.9;
      }
    });
  });
  return (
    <group>
      {pairs.map((pr, i) => {
        const mid = pr.a.clone().add(pr.b).multiplyScalar(0.5);
        const len = pr.a.distanceTo(pr.b);
        const ang = Math.atan2(pr.b.y - pr.a.y, pr.b.x - pr.a.x);
        return (
          <group key={i}>
            <mesh ref={(m) => { beams.current[i] = m; }} position={v(mid.x, mid.y, mid.z)}
                  rotation={[0, -ang, Math.PI / 2]}>
              <cylinderGeometry args={[0.9 * MM, 0.9 * MM, len * MM, 8]} />
              <meshBasicMaterial color="#ff5a3c" transparent opacity={0.85} />
            </mesh>
            <mesh position={v(pr.a.x, pr.a.y, pr.a.z + 10)}>
              <sphereGeometry args={[2.6 * MM, 12, 12]} />
              <meshStandardMaterial ref={(m) => { leds.current[i] = m; }} color="#39d353" emissive="#39d353" emissiveIntensity={0.9} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}

/** The sorting line: colour sensor, three pneumatic ejectors, three Lagerstellen.
    Its belt runs with the travelling cookie and only the ejector of the cookie's
    own bin fires. The cookie the VGR collects leaves its Lagerstelle. */
function SortingModule({ doc }: { doc: CadDoc }) {
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
  useFrame(() => {
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
  return (
    <group>
      {byFrame.world.map(P)}
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

/** The ridged belt texture, shared by every belt. */
function useBeltTexture() {
  return useMemo(() => {
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

export function HbwCadStage({ doc, onPhase, showZones = false, netZones = false }: {
  doc: CadDoc; onPhase: (s: string) => void; showZones?: boolean; netZones?: boolean;
}) {
  const [px, py] = doc.factory.plate;
  const [precise, setPrecise] = useState<PreciseLib | null>(null);
  // the VGR's tours for order mode (stf-cad/hbw/twin_tours.py); without them, the exported demo tour
  const { data: toursDoc, error: toursErr } = useJson<{ tours: Record<string, PlanKey[]> }>("vgr_tours.json");
  const tours = toursDoc ? toursDoc.tours : toursErr ? null : undefined;
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
        <PreciseScope module="vgr"><VgrModule doc={doc} drive={vgrDrive} /></PreciseScope>
      </group>
      {/* the oven is rotated +90 about the factory Z like the sorting line:
          its Ofenschieber points back at the VGR, its belt runs to the front */}
      <group
        position={[doc.factory.oven_placement.translate[0] * MM, 0, doc.factory.oven_placement.translate[1] * MM]}
        rotation={[0, THREE.MathUtils.degToRad(-doc.factory.oven_placement.rotate_deg), 0]}
      >
        <PreciseScope module="oven"><OvenModule doc={doc} /></PreciseScope>
      </group>
      <group
        position={[
          doc.factory.sort_placement.translate[0] * MM, 0,
          doc.factory.sort_placement.translate[1] * MM,
        ]}
        rotation={[0, -Math.PI / 2, 0]}
      >
        <PreciseScope module="sorting"><SortingModule doc={doc} /></PreciseScope>
      </group>
      <FlowCookie />
      <FlowBarriers doc={doc} />
      <PlcCabinet parts={doc.plc.parts as never} at={doc.plc.at} />
      {doc.upgrade && <PreciseScope module="upgrade"><UpgradeParts parts={doc.upgrade.parts as never} module="upgrade" /></PreciseScope>}
      {doc.safety && <UpgradeParts parts={doc.safety.parts as never} module="safety" />}
      {doc.io3 && <UpgradeParts parts={doc.io3.parts as never} module="io-own" />}
      {doc.safety && showZones && <HazardZones hazards={doc.safety.hazards} />}
      {netZones && doc.io3 && doc.safety && (
        <SecurityOverlay io={doc.io3.parts as never} plc={doc.plc as never} safety={doc.safety.parts as never}
          ips={{ hbw: "192.168.10.11", vgr: "192.168.10.12", oven: "192.168.10.13", sorting: "192.168.10.14" }} />
      )}
      <Wiring w={doc.wiring} />
      {/* Rigid placement of the proven module onto the table: +90 deg about the
          factory Z, which in three is -90 deg about Y, then translate. */}
      <group
        position={[doc.factory.placement.translate[0] * MM, 0, doc.factory.placement.translate[1] * MM]}
        rotation={[0, -Math.PI / 2, 0]}
      >
        {tours !== undefined && <PreciseScope module="hbw"><HbwCad doc={doc} onPhase={onPhase} tours={tours} /></PreciseScope>}
      </group>
      </group>
      </PreciseLibCtx.Provider>
    </>
  );
}
