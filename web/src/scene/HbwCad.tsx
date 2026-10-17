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


import { useFrame } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";


import { buildFlow } from "./OvenFlow";



import { DragChain } from "./DragChain";



import { type CadPart, type CadDoc, type PlanKey, boxSize, cylSpec } from "../shared/model";
import { FROM, OrderLine, twinOrders, cycleHot, Rack, Drive, vgrHot, hbwCookieHot, hbwHot, sortHot, ovenHot } from "./hot";
import { MM, v, AIM, Solid, RackBadge, Cookie, Mould } from "./parts";
import { binColour, script, SPEED, BELT_SPEED, RATE, PLAYBACK } from "./timeline";
import { HBW, RunningGear } from "./RunningGear";
import { clearCell, loadCell, saveCell } from "./cellStore";





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
  const [sx, sy, sz] = boxSize(rx);
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
      // The VGR collects THIS cookie from its Lagerstelle. While it bakes, the crane brings the
      // empty mould back to the belt (timeline.ts); then the VGR holds clear until the cookie
      // has been sorted and has come to rest, and fetches it.
      // The VGR sets off for the Lagerstelle only once the cookie is at rest there.
      const pick = legs.find((l) => !l.a.taken && l.b.taken === flow.bin);
      const iH = Math.max(i0, legs.findIndex((l) => l.b.bayGo));
      const wait = pick && i0 >= 0 ? Math.max(0, tOvenGo + flow.arrive + 0.5 - legs[iH].start) : 0;
      if (wait > 0) {
        const a = legs[iH].a;
        const hold = { a, b: { ...a, say: "VGR: holds clear while the cookie is baked and sorted" }, dur: wait, start: legs[iH].start };
        for (const l of legs.slice(iH)) l.start += wait;
        legs.splice(iH, 0, hold);
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
  // the top shelf first (C, then B, then A), left to right: the baked cookies of an order are
  // stored where the view sees them, not behind the crane's beam on the bottom shelf
  const order = useMemo(() => Object.keys(doc.slots)
    .sort((a, b) => b[0].localeCompare(a[0]) || Number(a.slice(1)) - Number(b.slice(1))), [doc]);
  const rawIn = (r: Rack) => order.filter((q) => r[q] === RAW);
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
    // no order is placed for the visitor: the cell rests until one is placed in the Orders panel
    for (const c of doc.sorting.colours) twinOrders.bays[c] ??= [];
    // The rack outlives this view (switching to a component and back remounts it): keep it.
    // A cookie that was in the oven line goes back to dough in its slot and is baked again.
    let saved = Object.keys(twinOrders.rack).length === Object.keys(doc.slots).length ? { ...twinOrders.rack } : null;
    // ...and outlives a reload: the rack and the orders this browser saved (cellStore.ts)
    if (!saved) {
      const kept = loadCell(Object.keys(doc.slots));
      if (kept) {
        saved = kept.rack;
        twinOrders.queue = kept.queue;
        twinOrders.seq = Math.max(kept.seq, ...kept.queue.map((o) => o.id), 0);
        twinOrders.delivered = kept.delivered;
      }
    }
    for (const o of twinOrders.queue) o.started = o.done;
    const r0 = saved ?? { ...freshRack() };
    const line = nextWork();
    twinOrders.idle = !line;
    if (!line) {                                     // every order done: rest in the pose of a finished cycle
      const from = rawIn(r0)[0] ?? FROM;
      return { c: { ...planCycle(from, from, Object.keys(doc.pipeline.flavours)[0], null), line: -1 }, r: r0 };
    }
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
          const [, sy, sz] = boxSize(p);
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
    const [, dy, dz] = boxSize(t);
    return { y: t.p[1] + dy / 2, z: t.p[2] + dz };
  }, [doc]);
  const phase = useRef("");
  // each rack slot's static mould + cookie; the slot whose mould is out on its cycle is hidden
  // while the cycle runs (the circulating mould is drawn instead) and shown again at rest
  const slotG = useRef<Record<string, THREE.Group | null>>({});
  const saveAt = useRef(0);

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
    if (twinOrders.reset && frozen === null) {
      // the visitor reset the rack: twelve raw cookies, no orders, the cell at rest
      twinOrders.reset = false;
      for (const o of twinOrders.queue) o.started = o.done = o.qty;
      twinOrders.queue = [];
      twinOrders.delivered = 0;
      twinOrders.restock = false;
      const r = freshRack();
      rackRef.current = r;
      setRack(r);
      twinOrders.raw = rawIn(r);
      const from = rawIn(r)[0] ?? FROM;
      const c = { ...planCycle(from, from, Object.keys(doc.pipeline.flavours)[0], null), line: -1 };
      cyc.current = { c, t0: el };
      setCur(c);
      twinOrders.idle = true;
      clearCell();
    }
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
    if (twinOrders.idle && frozen === null) say = "Waiting for an order";

    if (gTravel.current) gTravel.current.position.x = d.travel * MM;
    if (gLift.current) gLift.current.position.y = d.lift * MM;
    if (gFork.current) gFork.current.position.z = d.fork * MM;

    // at rest every mould is in its slot and drawn from the rack; nothing circulates
    const held = twinOrders.idle && frozen === null ? null : leg.a.held;
    for (const [q, g] of Object.entries(slotG.current)) if (g) g.visible = q !== C.from || held === null;
    if (gOnFork.current) gOnFork.current.visible = held === "fork";
    if (gOnBelt.current) {
      gOnBelt.current.visible = held === "belt";
      gOnBelt.current.position.z = d.belt * MM;
    }
    if (gStowed.current) gStowed.current.visible = held === "shelf";
    if (frozen === null && el - saveAt.current > 1) {
      saveAt.current = el;
      saveCell({ rack: rackRef.current, queue: twinOrders.queue, seq: twinOrders.seq, delivered: twinOrders.delivered });
    }
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
      <RunningGear all={doc.parts} frame="world" axes={HBW} />
      {doc.chains?.chains["hbw:travel"] && (
        <DragChain spec={doc.chains.chains["hbw:travel"]} joint={() => drive.current.travel} />
      )}
      {/* the rack as it stands after every cycle so far - the circulating
          mould's own slot is drawn by the stowed group below */}
      {Object.entries(rack).map(([q, col]) => {
        const sp = doc.slots[q];
        return (
          <group key={q} ref={(g) => { slotG.current[q] = g; }} position={[sp[0] * MM, sp[2] * MM, sp[1] * MM]} visible={q !== cur.from}>
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
                <Cookie x={0} y={seat.y} z={seat.z + mb} hot={hbwCookieHot} />
              </group>
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}
