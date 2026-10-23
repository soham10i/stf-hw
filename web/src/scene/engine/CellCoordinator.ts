// Layer 2 - the headless cell coordinator: the one place that decides what the cell does.
//
// It runs the orders (queue, cycles, restock, reset) and plays each cookie's choreography -
// the crane's script (timeline.ts) with the VGR's proven tour and the oven/sorting flow
// (OvenFlow.ts) - writing every station's joints into the store (store/useCellStore.ts),
// in place, once per tick. It also derives what the machine's sensors see (the warehouse's
// light barriers, the camera's trigger) and the oven's heating, and saves the material state
// through a CellPersistence when it changes.
//
// Pipelining: the cell works TWO cookies at once. While cookie k rides the oven flow and the
// VGR collects it, the crane already delivers raw cookie k+1 to the belt, the VGR picks it,
// and the crane stows the empty mould - so the next cookie is staged before the current one
// is even collected. Each cookie's legs are split into segments (deliver / pick / stow /
// oven-tour / fetch / collect / retrieve) that are scheduled on three resources (the crane,
// the VGR, the oven line) with a small greedy scheduler. The invariant: 12 cookies are always
// in the factory - every rack slot always holds dough or a cookie, and a rejected cookie's
// mould is refilled automatically (store.model.dough; off = the slot stays empty).
//
// It is a plain class: no React, no three.js scene, no WebGL. The twin drives it from one
// useFrame (Stage.tsx); a test drives it by calling tick() (CellCoordinator.test.ts).
//
// The pose source is the scripted cycle. The live API's physics kernel streams frames too, but
// in the original machine's joint convention; feeding those into this geometry would draw a
// pose the CAD does not have, so that bridge waits for the kernel's layout to be regenerated
// from the same parameter table.
//
// The tick allocates nothing: every joint, colour and caption buffer is created up front, and
// a caption string is rebuilt only when the step changes.

import * as THREE from "three";
import { boxSize, type CadDoc, type PlanKey } from "../../shared/model";
import { buildFlow, newSample, type FlowSample } from "../OvenFlow";
import { binColour, script, SPEED, BELT_SPEED, RATE } from "../timeline";
import { DEFECTS, FROM, type CellStore, type Defect, type OrderLine, type Rack, type Verdict } from "../store/useCellStore";
import type { CellPersistence } from "./persistence";

type Key = ReturnType<typeof script>[number];
type Leg = { a: Key; b: Key; dur: number; start: number };
/** A segment template: a contiguous run of a plan's legs with one set of resource owners. */
type SegT = {
  kind: "a" | "p" | "s" | "c" | "f" | "g" | "e" | "all";
  legs: Leg[];
  /** cumulative durations, one longer than legs: cum[i] is legs[i]'s start within the segment */
  cum: number[];
  dur: number;
  /** owns the crane's axes + belt */
  c: boolean;
  /** owns the VGR's axes */
  v: boolean;
  /** the circulating mould is visible in this segment (J.load / J.out follow it) */
  mould: boolean;
  /** the segment's first leg's start in the plan's cycle time (flow offsets are relative to it) */
  cStart: number;
};
/** A scheduled instance of a segment in one flight. `lead`: the repositioning legs put in front
    of the script's own when the resource was left somewhere else (its legs/cum/dur include them). */
type Seg = SegT & { abs0: number; li: number; fl: Flight | null; lead: number };
type Plan = {
  from: string; to: string; legs: Leg[]; tOvenGo: number; flow: ReturnType<typeof buildFlow>; total: number;
  baked: string; flavour: string; collect: string | null; collectColour: string | null; bin: string;
  /** the same journey for a cookie the inspection rejects: to the end of the line, held there */
  rflow: ReturnType<typeof buildFlow>;
  segs: SegT[];
  /** time from the g segment's start until the VGR has the baked cookie in its cup (bay travel) */
  bayDur: number;
};
/** QC testing: one damaged cookie in every BATCH started (a rack's worth). */
export const BATCH = 12;
/** A small seeded generator (mulberry32): the same seed, the same draws. */
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A cycle: its plan, its order line, and its cookie's inspection - the fault the simulation gave
    it, the camera shot that photographed it, and the verdict on that photo once it is in. */
type Cycle = Plan & { line: number; defect: Defect | null; seed: number; shot: number; verdict: Verdict | null;
  /** the slot whose bay this cycle leaves the crane resting at (the next cycle's pick), or null */
  restAt: string | null };

/** One cookie in flight: its cycle and its segments, scheduled on the cell's resources. */
interface Flight {
  cyc: Cycle;
  segs: Seg[];
  /** next segment to start (segments are chronological per flight) */
  idx: number;
  /** the flow's absolute start (set when the c segment is scheduled); -1 until then */
  flowAbs0: number;
  /** end times of scheduled segments, by kind */
  ends: Partial<Record<SegT["kind"], number>>;
  /** kinds already queued or scheduled (a segment is scheduled exactly once) */
  queued: Set<SegT["kind"]>;
  /** the rejected flow is playing (the verdict came in) */
  rejected: boolean;
  /** the VGR has taken the baked cookie off the line (the workpiece hides) */
  wpTaken: boolean;
  /** the cookie is committed to its journey (pass or reject) at the end of the colour reading;
      `rejected` never changes after that, so a late verdict cannot move a cookie off the belt */
  decided: boolean;
  /** wall seconds the belt has been held at the decision point, waiting for the verdict */
  waited: number;
  /** the belt is holding this cookie at the decision point now */
  held: boolean;
}

export interface CoordinatorOptions {
  /** the VGR's tours per Lagerstelle (vgr_tours.json); null: the exported demo tour */
  tours: Record<string, PlanKey[]> | null;
  persistence?: CellPersistence;
  /** review aid (?t= / ?at=&n=): freeze the FIRST cycle at a time, or at the end of a step */
  review?: { t?: number | null; at?: string | null; n?: number };
}

const smooth = (u: number) => THREE.MathUtils.smoothstep(u, 0, 1);
/** how far past the lens's axis a cookie can be and still be photographed whole (half the field) */
const LENS_WINDOW_MM = 30;
const HOLD_SAY = "VGR: holds clear while the cookie is baked and sorted";
/** The FSM's longest step (s of twin time): a long frame (fast-forward, a slow machine) is cut
    into steps this short, so every transition fires in order, at its own time. */
const FSM_STEP = 0.05;
const MAX_FSM_STEPS = 4000;
/** A frame longer than this (s of wall time) is not caught up: a throttled window (1-2 fps)
    keeps running at its rate, a stopped one (a hidden tab, a debugger) pauses rather than jump. */
const MAX_FRAME_S = 1;
/** How long (wall s) the sorting belt waits at the decision point for the inspection's verdict
    before the cookie goes on un-inspected, to its Lagerstelle - the line never stops for good. */
export const VERDICT_WAIT_S = 4;
const HELD_SAY = "Sortierstrecke: the belt holds at the colour lock until the inspection's verdict is in";

export class CellCoordinator {
  private readonly doc: CadDoc;
  private readonly store: CellStore;
  private readonly tours: Record<string, PlanKey[]> | null;
  private readonly persistence: CellPersistence | null;
  private readonly RAW: string;
  /** slots, the top shelf first (C, B, A), left to right: an order's cookies end up in view */
  private readonly order: string[];
  private readonly plans = new Map<string, Plan>();
  private readonly palette = new Map<string, THREE.Color>();
  private readonly rawColor: THREE.Color;
  private readonly beams: { tag: string; y0: number; y1: number; z: number }[];
  private readonly seat: { y: number; z: number };
  private readonly mouldD: number;
  private readonly loadH: number;
  private readonly colours: string[];
  private readonly flow: FlowSample = newSample();
  private readonly frozen: number | null;
  private readonly unsubscribe: () => void;

  /** the cookie(s) in flight, oldest first; at most two (one staged, one in the oven) */
  private flights: Flight[] = [];
  /** crane / VGR job queues, in priority order (oldest flight first) */
  private craneQ: Seg[] = [];
  private vgrQ: Seg[] = [];
  /** when each resource is free next */
  private craneAt = 0;
  private vgrAt = 0;
  private lineAt = 0;
  /** raw slots already promised to a flight (their rack slot stays RAW until the flight ends) */
  private readonly claimed = new Set<string>();
  /** the pose the cell rests in: a finished cycle with no cookie to fetch */
  private restCyc: Cycle;
  /** review aid: one synthetic flight over the first cycle's whole leg array */
  private readonly frozenFlight: Flight | null = null;
  /** the cycle the review aid freezes (built without claiming anything) */
  private frozenCyc: Cycle | null = null;
  /** ticks where the crane and the VGR worked on different cookies (the pipeline, for tests) */
  overlapped = 0;
  /** the travelling cookie's position along the belt relative to the lens's axis, last tick */
  private along = NaN;
  /** the first tick announces the restored cell (the constructor runs inside a React render,
      where notifying other components is not allowed) */
  private announced = false;
  private thermo = { element: 0, chamber: 25 };
  /** the twin's own clock (s, playback-scaled): it only runs forwards, at the rate asked for
      frame by frame, so a change of speed changes how fast it runs - never where it is */
  private now = 0;
  /** the time the FSM last stepped to */
  private lastT = Number.NaN;
  /** a running count, so each faulty cookie's fault falls somewhere else */
  private seeds = 0;
  /** QC testing's draws: a fixed seed, so a run (and a test) is repeatable */
  private qcSeed = 1912;

  constructor(doc: CadDoc, store: CellStore, opts: CoordinatorOptions) {
    this.doc = doc;
    this.store = store;
    this.tours = opts.tours;
    this.persistence = opts.persistence ?? null;
    this.RAW = doc.pipeline.raw_colour;
    this.rawColor = this.colour(this.RAW);
    this.colours = doc.sorting.colours;
    this.order = Object.keys(doc.slots)
      .sort((a, b) => b[0].localeCompare(a[0]) || Number(a.slice(1)) - Number(b.slice(1)));
    for (const f of Object.values(doc.pipeline.flavours)) this.colour(f.colour);
    // the light barriers at the belt's ends: the stretch of belt each watches and its height
    this.beams = doc.parts.filter((p) => p.mech === "beam:rx").map((p) => {
      const [, sy, sz] = boxSize(p);
      return { tag: p.tag, y0: p.p[1], y1: p.p[1] + sy, z: p.p[2] + sz / 2 };
    });
    for (const b of this.beams) store.joints.beams[b.tag] = false;
    // where the load sits on the fork, from the fork table part itself
    const table = doc.parts.find((p) => p.n === "fork_table");
    if (table) {
      const [, dy, dz] = boxSize(table);
      this.seat = { y: table.p[1] + dy / 2, z: table.p[2] + dz };
    } else this.seat = { y: 0, z: 10 };
    const [, md, mb] = doc.moulds.size;
    this.mouldD = md;
    this.loadH = mb + doc.moulds.rim_h + 8; // the mould plus the cookie standing above its rim

    this.start();
    this.restCyc = this.rest(this.store.model.rack);
    this.frozen = this.review(opts.review);
    if (this.frozen !== null && this.frozenCyc) this.frozenFlight = this.wholeFlight(this.frozenCyc);
    this.unsubscribe = store.subscribeModel((material) => {
      if (!material || !this.persistence) return;
      const m = store.model;
      this.persistence.save({ rack: m.rack, queue: m.queue, seq: m.seq, delivered: m.delivered });
    });
  }

  dispose() { this.unsubscribe(); }

  /** The inspection camera's lens axis in the factory frame (mm), once vision/camera.json is in. */
  setCamera(lens: [number, number] | null) { this.lens = lens; }
  private lens: [number, number] | null = null;

  // ------------------------------------------------------------------ planning
  private colour(hex: string) {
    const k = hex.toLowerCase();
    let c = this.palette.get(k);
    if (!c) { c = new THREE.Color(hex); this.palette.set(k, c); }
    return c;
  }

  /** One cycle's choreography split into schedulable segments, by the script's own markers:
      the deliver's hood run, the VGR's pick, the empty mould's stow, the oven tour, the fetch,
      the collect (hold + bay + place) and the retrieve. A plan without a fetch (no Lagerstelle:
      the rest pose) is one serial segment. */
  private segments(legs: Leg[]): { segs: SegT[]; bayDur: number } {
    const mk = (kind: SegT["kind"], from: number, to: number, c: boolean, v: boolean, mould: boolean): SegT => {
      const part = legs.slice(from, to + 1);
      const cum: number[] = [0];
      for (const l of part) cum.push(cum[cum.length - 1] + l.dur);
      return { kind, legs: part, cum, dur: cum[cum.length - 1], c, v, mould, cStart: part[0]?.start ?? 0 };
    };
    const iHood = legs.findIndex((l) => l.b.say.includes("through the hood"));
    const iStow = legs.findIndex((l) => l.b.say.includes("empty mould rides back"));
    // the crane's rest after stowing: the park key, or the rest-at-bay key when the next pick is known
    const iPark = legs.findIndex((l) => l.b.say === "return to park" || l.b.say.startsWith("next order waiting: rest at"));
    const iFetch = legs.findIndex((l) => l.b.say.includes("fetch the empty mould"));
    const iWait = legs.findIndex((l) => l.b.say.includes("waits at the VGR point"));
    const iFinal = legs.findIndex((l) => l.b.say.includes("the finished cookie"));
    if (iHood < 0 || iStow < 0 || iPark < 0 || iFetch < 0 || iWait < 0 || iFinal < 0 || iStow <= iHood + 1 || iFinal <= iWait + 1)
      return { segs: [mk("all", 0, legs.length - 1, true, true, true)], bayDur: 0 };
    const segs = [
      mk("a", 0, iHood, true, false, true),                    // crane delivers the raw mould to the belt's VGR point
      mk("p", iHood + 1, iStow - 1, false, true, true),        // the VGR lifts the raw cookie off the mould
      mk("s", iStow, iPark, true, false, true),                // the belt returns the empty mould; the crane stows it
      mk("c", iPark + 1, iFetch - 1, false, true, false),      // the VGR's tour to the oven; the cookie is inserted
      mk("f", iFetch, iWait, true, false, true),               // the crane brings the empty mould back to the VGR point
      // the collect: the VGR waits for the baked cookie, fetches it from its Lagerstelle and sets
      // it into the mould; the scheduler re-times the wait, so the script's own hold leg is dropped
      (() => {
        const part = legs.slice(iWait + 1, iFinal).filter((l) => l.b.say !== HOLD_SAY);
        const cum: number[] = [0];
        for (const l of part) cum.push(cum[cum.length - 1] + l.dur);
        return { kind: "g" as const, legs: part, cum, dur: cum[cum.length - 1], c: false, v: true, mould: true,
                 cStart: part[0]?.start ?? 0 };
      })(),
      // the belt returns the mould; the crane stows it. The VGR is already home (the collect ends
      // there) and is free for the next cookie's pick: e does not claim it
      mk("e", iFinal, legs.length - 1, true, false, true),
    ];
    // how long from the collect's start until the VGR holds the baked cookie (for its timing)
    const g = segs[5];
    let bayDur = g.dur;
    for (let i = 0; i < g.legs.length; i++) {
      if (g.legs[i].b.taken) { bayDur = g.cum[i + 1]; break; }
    }
    return { segs, bayDur };
  }

  /** One cycle: the crane's script with the VGR's tour, timed; the oven/sorting flow; the VGR's
      wait for its cookie. Cached per (slot, flavour, Lagerstelle, rest, fromRest). `rest`: the
      slot whose bay the crane rests at after stowing the empty mould (the next order's pick,
      when known — else it parks at the conveyor). `fromRest`: this cycle's crane starts already
      resting at `from`'s bay (the previous cycle brought it there). */
  private plan(from: string, to: string, flavour: string, collect: string | null, rest: string | null = null, fromRest = false): Plan {
    const key = `${fromRest ? "r" : "p"}:${rest ?? ""}:${from}>${to}>${flavour}>${collect}`;
    const hit = this.plans.get(key);
    if (hit) return hit;
    const doc = this.doc;
    const tour = this.tours?.[collect ?? "none"] ?? doc.vgr.plan.keys;
    const keys = script(doc, from, to, tour, collect, rest, fromRest);
    let t0 = 0;
    const legs: Leg[] = keys.slice(1).map((b, i) => {
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
    // the bake starts once the VGR is back at transit height, clear of the oven
    const i0 = legs.findIndex((l) => l.a.ovenGo);
    const tOvenGo = i0 >= 0 ? legs[i0].start : Infinity;
    const flow = buildFlow(doc, flavour);
    // While the cookie bakes the crane brings the empty mould back to the belt (timeline.ts);
    // the VGR sets off for the Lagerstelle only once the cookie is at rest there.
    const pick = legs.find((l) => !l.a.taken && l.b.taken === flow.bin);
    const iH = Math.max(i0, legs.findIndex((l) => l.b.bayGo));
    const wait = pick && i0 >= 0 ? Math.max(0, tOvenGo + flow.arrive + 0.5 - legs[iH].start) : 0;
    if (wait > 0) {
      const a = legs[iH].a;
      const hold = { a, b: { ...a, say: HOLD_SAY }, dur: wait, start: legs[iH].start };
      for (const l of legs.slice(iH)) l.start += wait;
      legs.splice(iH, 0, hold);
    }
    const total = Math.max(legs.reduce((q, l) => q + l.dur, 0), tOvenGo + flow.total + 3);
    const baked = doc.pipeline.flavours[flavour]?.colour ?? this.RAW;
    this.colour(baked);
    const collectColour = collect ? binColour(doc, collect) : null;
    if (collectColour) this.colour(collectColour);
    const rflow = buildFlow(doc, flavour, 0, true);
    const { segs, bayDur } = this.segments(legs);
    const p: Plan = { from, to, legs, tOvenGo, flow, rflow, total, baked, flavour, collect, collectColour, bin: flow.bin, segs, bayDur };
    this.plans.set(key, p);
    return p;
  }

  private freshRack(): Rack {
    const r: Rack = {};
    for (const q of Object.keys(this.doc.slots)) r[q] = this.RAW;
    return r;
  }
  private rawIn(r: Rack) { return this.order.filter((q) => r[q] === this.RAW); }
  /** The next ordered cookie, if any - and if there is raw dough left to make it from: its order
      line, one more of it started. */
  private nextWork(): OrderLine | null {
    if (!this.rawIn(this.store.model.rack).length) return null;
    const line = this.store.model.queue.find((o) => o.started < o.qty);
    if (!line) return null;
    line.started++;
    return line;
  }
  /** A slot's raw dough no order has claimed yet. */
  private freeRaw(r: Rack): string {
    return this.rawIn(r).find((q) => !this.claimed.has(q)) ?? FROM;
  }
  /** True when another cookie could start: an unfinished line and unclaimed raw dough. */
  private workPending() {
    return !!this.store.model.queue.find((o) => o.started < o.qty) &&
      this.rawIn(this.store.model.rack).some((q) => !this.claimed.has(q));
  }
  /** One cookie's flight: its plan's segments as scheduled instances, unscheduled. */
  private wholeFlight(cyc: Cycle): Flight {
    return {
      cyc,
      segs: cyc.segs.map((s) => ({ ...s, abs0: -1, li: 0, fl: null, lead: 0 })),
      idx: 0, flowAbs0: -1, ends: {}, queued: new Set(), rejected: false, wpTaken: false, decided: false, waited: 0, held: false,
    };
  }

  /** Restore the cell's material state; the scheduler begins the first flight on the first tick. */
  private start() {
    const m = this.store.model, slots = Object.keys(this.doc.slots);
    m.rawColour = this.RAW;
    if (Object.keys(m.rack).length !== slots.length) {
      const kept = this.persistence?.load(slots) ?? null;
      if (kept) {
        m.rack = kept.rack;
        m.queue = kept.queue;
        m.seq = Math.max(kept.seq, ...kept.queue.map((o) => o.id), 0);
        m.delivered = kept.delivered;
      } else m.rack = this.freshRack();
    }
    for (const o of m.queue) o.started = o.done;
    m.idle = !this.workPending();
  }

  /** Begin a cookie in an already-chosen, already-claimed slot (the chaining lives in
      beginFlights): draw its fault, build its flight. The cookie comes back baked into the
      same slot. */
  private begin(line: OrderLine, from: string, rest: string | null, fromRest: boolean): Cycle {
    const bin = this.doc.pipeline.flavours[line.flavour]?.bin ?? null;
    // the fault asked for the next cookie (the Orders panel) goes to this one; otherwise, QC
    // testing: in every 12 cookies started, one drawn at random gets a random fault
    const ins = this.store.model.inspect, b = ins.batch;
    if (b.pos % BATCH === 0) {
      const r = rng(this.qcSeed + b.pos);
      b.pick = Math.floor(r() * BATCH);
      b.fault = DEFECTS[Math.floor(r() * DEFECTS.length)];
    }
    const defect = ins.next ?? (ins.auto && b.pos % BATCH === b.pick ? b.fault : null);
    b.pos++;
    ins.next = null;
    this.seeds++;
    return { ...this.plan(from, from, line.flavour, bin, rest, fromRest), line: line.id, defect, seed: this.seeds,
             shot: 0, verdict: null, restAt: rest };
  }
  /** The pose the cell rests in: a finished cycle with no cookie to fetch. */
  private rest(r: Rack): Cycle {
    const from = this.rawIn(r)[0] ?? FROM;
    return { ...this.plan(from, from, Object.keys(this.doc.pipeline.flavours)[0], null), line: -1, defect: null,
             seed: 0, shot: 0, verdict: null, restAt: null };
  }

  /** The review aid's cycle: the first pending order's plan (nothing claimed), else the rest pose. */
  private review(r: CoordinatorOptions["review"]): number | null {
    if (!r) return null;
    const m = this.store.model;
    const line = m.queue.find((o) => o.started < o.qty);
    const from = this.rawIn(m.rack)[0] ?? FROM;
    const cyc: Cycle = line
      ? { ...this.plan(from, from, line.flavour, this.doc.pipeline.flavours[line.flavour]?.bin ?? null),
          line: line.id, defect: null, seed: 0, shot: 0, verdict: null, restAt: null }
      : this.rest(m.rack);
    this.frozenCyc = cyc;
    const { legs, total, flow, tOvenGo } = cyc;
    if (r.t != null && Number.isFinite(r.t)) return r.t % total;
    if (!r.at) return null;
    const at = r.at.toLowerCase();
    const hits = legs.filter((l) => l.b.say.toLowerCase().includes(at));
    const l = hits[Math.max(0, (r.n ?? 1) - 1)];
    if (l) return l.start + l.dur - 1e-3;
    const st = flow.steps.find((x) => x.say.toLowerCase().includes(at));
    return st ? tOvenGo + st.t0 + st.d - 1e-3 : null;
  }

  // ------------------------------------------------------------------ scheduling
  /** Enqueue a flight's segment on its resource. */
  private enqueue(f: Flight, kind: SegT["kind"]) {
    const seg = f.segs.find((s) => s.kind === kind)!;
    seg.fl = f;
    f.queued.add(kind);
    (seg.c && !seg.v ? this.craneQ : seg.v && !seg.c ? this.vgrQ : null)?.push(seg) ??
      (seg.c ? this.craneQ : this.vgrQ).push(seg);
  }

  /** A segment's earliest start, from its dependencies. */
  private readyAt(seg: Seg): number {
    const f = seg.fl!, e = f.ends;
    const i = this.flights.indexOf(f);
    switch (seg.kind) {
      case "a": {
        // the previous cookie's mould is home (stowed) and its slot of the belt point is free
        const prev = this.flights[i - 1];
        return prev ? (prev.ends.s ?? Infinity) : 0;
      }
      case "p": return e.a ?? Infinity;
      case "s": return e.p ?? Infinity;
      case "c": return Math.max(e.p ?? Infinity, this.lineAt);
      case "f": {
        // the mould fetches to the VGR point once the next mould has left it (stowed home);
        // a last cookie fetches its own once its empty mould is home
        const next = this.flights[i + 1];
        return next ? (next.ends.s ?? Infinity) : (e.s ?? Infinity);
      }
      case "g": {
        // the VGR sets off for the Lagerstelle once the cookie's journey is decided
        if (!f.decided) return Infinity;
        const flow = f.rejected ? f.cyc.rflow : f.cyc.flow;
        return Math.max(e.f ?? Infinity, this.vgrAt, f.flowAbs0 + flow.arrive - f.cyc.bayDur);
      }
      case "e": return e.g ?? Infinity;
      default: return 0;
    }
  }

  /** Assign start times to queued jobs whose dependencies are met by `t`, oldest first. A job
      that became ready since the last step (`from`) starts when it became ready, not at `t`:
      the schedule does not depend on the frame rate. */
  private schedule(t: number, from: number) {
    for (;;) {
      const cq = this.craneQ[0];
      if (cq && this.readyAt(cq) <= t) {
        this.craneQ.shift();
        cq.abs0 = Math.max(this.readyAt(cq), this.craneAt, from);
        this.bridgeCrane(cq);
        this.craneAt = cq.abs0 + cq.dur;
        cq.fl!.ends[cq.kind] = this.craneAt;
        this.onScheduled(cq);
        continue;
      }
      const vq = this.vgrQ[0];
      if (vq && this.readyAt(vq) <= t) {
        this.vgrQ.shift();
        vq.abs0 = Math.max(this.readyAt(vq), this.vgrAt, from);
        this.bridgeVgr(vq);
        this.vgrAt = vq.abs0 + vq.dur;
        vq.fl!.ends[vq.kind] = this.vgrAt;
        this.onScheduled(vq);
        continue;
      }
      break;
    }
  }

  /** Where each resource is left by the last segment scheduled on it (null: at its rest pose). */
  private craneEnd: Key | null = null;
  private vgrEnd: Key | null = null;

  /** A leg's time, by the same rule as the plan's (plan()). */
  private legDur(a: Key, b: Key) {
    const axes = Math.abs(b.t - a.t) + Math.abs(b.l - a.l) + Math.abs(b.f - a.f);
    const vgr = Math.abs(b.vs - a.vs) * 2 + Math.abs(b.vr - a.vr) + Math.abs(b.vp - a.vp);
    return Math.max(0.4, (axes + vgr) / (SPEED * RATE) + Math.abs(b.b - a.b) / (BELT_SPEED * RATE));
  }

  /** Put `moves` (each a partial pose, applied in turn from `from`) in front of the segment's legs.
      Every other field of the moved-through keys is the segment's first key's, so the mould,
      cookie and captions read as the segment's own. */
  private lead(seg: Seg, from: Key, moves: Partial<Key>[], say: string) {
    const first = seg.legs[0].a;
    const keys: Key[] = [{ ...first, t: from.t, l: from.l, f: from.f, b: from.b, vs: from.vs, vr: from.vr, vp: from.vp, vc: from.vc, say }];
    for (const mv of moves) {
      const prev = keys[keys.length - 1];
      const next = { ...prev, ...mv, say };
      if (Math.abs(next.t - prev.t) + Math.abs(next.l - prev.l) + Math.abs(next.f - prev.f) + Math.abs(next.b - prev.b) +
          Math.abs(next.vs - prev.vs) + Math.abs(next.vr - prev.vr) + Math.abs(next.vp - prev.vp) + Math.abs(next.vc - prev.vc) > 1e-6)
        keys.push(next);
    }
    if (keys.length < 2) return;
    const extra: Leg[] = [];
    for (let i = 1; i < keys.length; i++) extra.push({ a: keys[i - 1], b: keys[i], dur: this.legDur(keys[i - 1], keys[i]), start: 0 });
    // the last move ends exactly at the segment's first key
    extra[extra.length - 1].b = first;
    seg.legs = [...extra, ...seg.legs];
    const cum: number[] = [0];
    for (const l of seg.legs) cum.push(cum[cum.length - 1] + l.dur);
    seg.cum = cum;
    seg.lead = cum[extra.length];
    seg.dur = cum[cum.length - 1];
  }

  /** The crane starts each segment where the last one left it: when pipelining put it somewhere
      the script did not expect (another cookie's bay, the park), it first moves there - fork in,
      up to transit height, across, down, fork out - and the belt runs to the mould's place. */
  private bridgeCrane(seg: Seg) {
    const from = this.craneEnd, to = seg.legs[0].a;
    this.craneEnd = seg.legs[seg.legs.length - 1].b;
    if (!from) return;
    const off = Math.abs(from.t - to.t) + Math.abs(from.l - to.l) + Math.abs(from.f - to.f) + Math.abs(from.b - to.b);
    if (off < 0.5) return;
    const J = this.doc.joints, T = J.travel.stops, L = J.lift.stops, F = J.fork.stops;
    const across = Math.abs(from.t - to.t) > 0.5;
    this.lead(seg, from, [
      { f: from.f !== to.f || across ? F.retracted : from.f },
      across ? { l: L.transit } : {},
      { t: to.t, b: to.b },
      { l: to.l },
      { f: to.f },
    ], `crane: repositions to ${Math.abs(to.t - T.conveyor) < 0.5 ? "the conveyor" : "its next job"}`);
    this.craneEnd = seg.legs[seg.legs.length - 1].b;
  }

  /** The same for the VGR, by the proven tours' own pattern: retract, rise to transit height,
      swing, descend, extend. */
  private bridgeVgr(seg: Seg) {
    const from = this.vgrEnd, to = seg.legs[0].a;
    this.vgrEnd = seg.legs[seg.legs.length - 1].b;
    if (!from) return;
    const off = Math.abs(from.vs - to.vs) + Math.abs(from.vr - to.vr) + Math.abs(from.vp - to.vp) + Math.abs(from.vc - to.vc);
    if (off < 0.5) return;
    const transit = this.doc.vgr.joints.plunge.stops.transit;
    const swing = Math.abs(from.vs - to.vs) > 0.5;
    this.lead(seg, from, [
      { vc: 0 },
      swing ? { vr: 0 } : {},
      swing ? { vp: transit } : {},
      { vs: to.vs },
      { vp: to.vp },
      { vr: to.vr, vc: to.vc },
    ], "VGR: repositions for its next job");
    this.vgrEnd = seg.legs[seg.legs.length - 1].b;
  }

  /** Queue the segments that a scheduled segment unlocks. */
  private onScheduled(seg: Seg) {
    const f = seg.fl!, k = seg.kind, at = f.ends[k]!;
    const i = this.flights.indexOf(f);
    if (k === "a") this.enqueue(f, "p");
    else if (k === "p") {
      this.enqueue(f, "s");
      this.enqueue(f, "c");
      // the pipeline: the next cookie starts while this one is still in the oven
      this.beginFlights(at);
    } else if (k === "s") {
      const prev = this.flights[i - 1];
      if (prev && !prev.queued.has("f")) this.enqueue(prev, "f");
      if (!this.flights[i + 1] && !this.workPending() && !f.queued.has("f")) this.enqueue(f, "f");
    } else if (k === "c") {
      f.flowAbs0 = seg.abs0 + seg.lead + (f.cyc.tOvenGo - seg.cStart);
      this.lineAt = f.flowAbs0 + f.cyc.flow.total;
    } else if (k === "f") this.enqueue(f, "g");
    else if (k === "g") this.enqueue(f, "e");
  }

  /** Start a flight for the next ordered cookie while the pipeline has room for it. The next one
      may go once this one's mould is delivered and picked (its p segment has a start time), so the
      belt point holds exactly one waiting mould. The crane chains: when a further cookie is
      waiting, this cycle rests at that one's pick bay after stowing (the previous cycle may
      already have brought the crane there), so the crane travels the shortest path between
      jobs instead of detouring to the conveyor each time. */
  private beginFlights(_t: number) {
    for (;;) {
      const last = this.flights[this.flights.length - 1];
      const pSeg = last?.segs.find((s) => s.kind === "p");
      if (this.flights.length >= 2 || (last && (!pSeg || pSeg.abs0 < 0))) break;
      const line = this.nextWork();
      if (!line) break;
      const rack = this.store.model.rack;
      // the slot: the previous cycle's rest bay when it picked ahead, else the first free raw
      const from = last?.cyc.restAt ?? this.freeRaw(rack);
      const fromRest = !!last?.cyc.restAt;
      // and where this cycle leaves the crane: at the next order's pick bay, when one is waiting
      this.claimed.add(from);
      const freeRaw = this.rawIn(rack).filter((q) => !this.claimed.has(q));
      const rest = this.store.model.queue.some((o) => o.started < o.qty) && freeRaw.length > 0 ? freeRaw[0] : null;
      const cyc = this.begin(line, from, rest, fromRest);
      const f = this.wholeFlight(cyc);
      this.flights.push(f);
      this.enqueue(f, "a");
      this.store.model.idle = false;
      this.store.commit();
      if (this.flights.length >= 2) break;
    }
  }

  /** The flight is done: its cookie is back in its slot, baked - or its mould refilled with dough. */
  private complete(f: Flight) {
    const m = this.store.model, done = f.cyc;
    this.claimed.delete(done.from);
    const line = m.queue.find((q) => q.id === done.line);
    if (done.verdict && done.verdict.verdict !== "pass") {
      // rejected: its mould came home empty, and the order makes this cookie again; the slot is
      // refilled with dough at once, so twelve cookies are always in the factory
      m.rack = { ...m.rack, [done.to]: m.dough ? this.RAW : null };
      if (line) {
        line.started--;
        line.rejected = (line.rejected ?? 0) + 1;
        if (done.defect) line.fault = done.defect;
      }
    } else {
      m.rack = { ...m.rack, [done.to]: done.baked };
      if (line) {
        line.done++;
        if (line.done === line.qty) {
          const rej = line.rejected ?? 0;
          this.store.emitRecord({ kind: "order", flavour: line.flavour, qty: line.qty, baked: line.qty + rej, good: line.qty,
            scrap: rej, qc_fault: line.fault ?? "" });
        }
      }
    }
    this.store.commit();
  }

  /** The baked cookies are delivered and their moulds refilled with dough. */
  private restock() {
    const m = this.store.model, r = { ...m.rack };
    for (const q of Object.keys(r)) if (r[q] !== this.RAW) { if (r[q] !== null) m.delivered++; r[q] = this.RAW; }
    m.rack = r;
    m.queue = m.queue.filter((o) => o.done < o.qty);
    this.store.requests.restock = false;
    this.store.commit();
  }

  /** Twelve raw cookies, no orders, the cell at rest; the saved state is forgotten. */
  private doReset(t: number) {
    const store = this.store, m = store.model;
    store.requests.reset = false;
    store.requests.restock = false;
    m.queue = [];
    m.delivered = 0;
    m.rack = this.freshRack();
    m.idle = true;
    this.flights = [];
    this.craneQ = [];
    this.vgrQ = [];
    this.craneAt = this.vgrAt = this.lineAt = t;
    this.craneEnd = this.vgrEnd = null;
    this.claimed.clear();
    this.overlapped = 0;
    this.restCyc = this.rest(m.rack);
    this.persistence?.clear();
    store.commit();
  }

  // ------------------------------------------------------------------ the tick
  /** One display frame: `dt` wall seconds at `rate` times real time. The twin's clock advances
      by dt x rate; a frame over MAX_FRAME_S counts as MAX_FRAME_S. */
  advance(dt: number, rate: number) {
    const d = Math.min(MAX_FRAME_S, Math.max(0, dt));
    this.now += d * Math.max(0, rate);
    this.tick(this.now, d);
  }

  /** Advance to twin time `t` (s, playback-scaled); `dt` is the wall-clock frame time (s). The
      FSM steps from the last time to `t` in steps of at most FSM_STEP; the joints are drawn
      once, at `t`. */
  tick(t: number, dt: number) {
    const store = this.store, m = store.model;
    const live = this.frozen === null;
    if (!this.announced) { this.announced = true; store.commit(false); }

    if (live) {
      if (store.requests.reset) this.doReset(t);
      const from = Number.isFinite(this.lastT) && this.lastT < t ? this.lastT : t;
      const n = Math.min(MAX_FSM_STEPS, Math.max(1, Math.ceil((t - from) / FSM_STEP - 1e-9)));
      let prev = from;
      for (let i = 1; i <= n; i++) {
        const s = i === n ? t : from + ((t - from) * i) / n;
        this.step(s, prev, dt / n);
        prev = s;
      }
      this.lastT = t;
    }

    if (this.frozen !== null && this.frozenFlight) {
      // the frozen flight's flow starts at its plan's own oven-go
      if (this.frozenFlight.flowAbs0 < 0 && Number.isFinite(this.frozenFlight.cyc.tOvenGo))
        this.frozenFlight.flowAbs0 = this.frozenFlight.cyc.tOvenGo;
      this.renderAll(this.frozen, dt, [this.frozenFlight]);
      const C = this.frozenFlight.cyc, cy = m.cycle;
      cy.from = C.from; cy.to = C.to; cy.total = C.total; cy.t = this.frozen;
      cy.flavour = C.flavour; cy.collect = C.collect ?? "";
    } else if (this.flights.length) {
      this.renderAll(t, dt, this.flights);
      // the panel follows the oldest flight: its cookie is closest to done
      const panel = this.flights[0], C = panel.cyc, cy = m.cycle, a0 = panel.segs[0].abs0;
      cy.from = C.from; cy.to = C.to; cy.total = C.total;
      cy.t = a0 >= 0 ? Math.max(0, Math.min(C.total, t - a0)) : 0;
      cy.flavour = C.flavour; cy.collect = C.collect ?? "";
      if (live) {
        // count the ticks where the crane and the VGR served different cookies
        const cf = this.owner(t, "c"), vf = this.owner(t, "v");
        if (cf && vf && cf !== vf) this.overlapped++;
      }
      m.idle = false;
    } else {
      m.idle = true;
      this.renderRest(t, dt);
    }
    this.caption(t, dt);
    store.publishFrame(t);
  }
  private retire: Flight[] = [];

  /** One FSM step, from `from` to `t` (twin s); `wall` is its share of the frame's wall time. */
  private step(t: number, from: number, wall: number) {
    const store = this.store, m = store.model;
    // retire finished segments, oldest flight first; a flight ends with its e segment
    for (const f of this.flights) {
      let seg = f.segs[f.idx];
      while (seg && seg.abs0 >= 0 && t >= seg.abs0 + seg.dur - 1e-9) {
        f.ends[seg.kind] = seg.abs0 + seg.dur;
        f.idx++;
        if (seg.kind === "e") this.retire.push(f);
        seg = f.segs[f.idx];
      }
    }
    for (const f of this.retire) {
      this.flights.splice(this.flights.indexOf(f), 1);
      this.complete(f);
    }
    this.retire.length = 0;
    this.schedule(t, from);
    if (!this.flights.length && store.requests.restock &&
        m.queue.every((o) => o.done === o.qty)) this.restock();
    this.beginFlights(t);
    this.pollVerdicts();
    this.decide(t, wall);
  }

  /** The sorting line's decision: at the end of the colour reading each cookie is committed to
      its Lagerstelle or to the end of the line. With a camera installed the belt holds there
      (its flow's clock stands still) until the cookie has been photographed and judged - at any
      playback rate, the verdict is in before the paths part. After VERDICT_WAIT_S of wall time
      without one, the cookie goes on un-inspected. */
  private decide(t: number, wall: number) {
    for (const f of this.flights) {
      if (f.decided || f.flowAbs0 < 0) continue;
      const at = f.flowAbs0 + f.cyc.flow.decide;
      if (t < at) continue;
      const C = f.cyc;
      const pending = this.lens !== null && (!C.shot || !C.verdict);
      if (pending && f.waited < VERDICT_WAIT_S) {
        // hold: the flow (and the line it occupies) is pushed back by the time it waited
        const late = t - at;
        const owns = Math.abs(this.lineAt - (f.flowAbs0 + C.flow.total)) < 1e-6;
        f.flowAbs0 += late;
        if (owns) this.lineAt += late;
        f.waited += wall;
        f.held = true;
        continue;
      }
      f.decided = true;
      f.held = false;
      f.rejected = !!C.verdict && C.verdict.verdict !== "pass";
      if (f.rejected && Math.abs(this.lineAt - (f.flowAbs0 + C.flow.total)) < 1e-6)
        this.lineAt = f.flowAbs0 + C.rflow.total;
    }
  }

  /** The flight whose segment owns a resource (crane / VGR) at time t. */
  private owner(t: number, res: "c" | "v"): Flight | null {
    for (const f of this.flights) {
      for (let i = f.idx; i < f.segs.length; i++) {
        const seg = f.segs[i];
        if (seg.abs0 < 0) break;
        if (seg.abs0 <= t && t < seg.abs0 + seg.dur && seg[res]) return f;
      }
    }
    return null;
  }

  /** The inspection's verdict on a flight's cookie, once its photo has been judged; a cookie
      that does not pass is not ejected to its Lagerstelle: it stays on the belt to the end of the
      line, the VGR finds its bay empty, and its mould goes home empty. */
  private pollVerdicts() {
    for (const f of this.flights) {
      const C = f.cyc;
      if (!C.shot || C.verdict) continue;
      const v = this.store.verdicts.get(C.shot);
      if (!v) continue;
      this.store.verdicts.delete(C.shot);
      C.verdict = v;
      const m = this.store.model, ins = m.inspect;
      ins.recent = [{ ...v, truth: C.defect ?? "ok", cookieFlavour: C.flavour }, ...ins.recent].slice(0, 8);
      if (v.verdict === "pass") ins.passed++; else ins.rejected++;
      this.store.emitRecord({ kind: "inspection", n: v.n, flavour: C.flavour, truth: C.defect ?? "ok", condition: v.condition,
        p: v.p, verdict: v.verdict, ae: v.ae, unusual: v.anomaly });
      this.store.commit(false);
    }
  }

  // ------------------------------------------------------------------ rendering
  /** The leg of a segment at local time lt, and the eased fraction along it, written into `out`
      (nothing is allocated per frame). */
  private legAt(seg: Seg, lt: number, out: { a: Key; b: Key; u: number }) {
    const n = seg.legs.length;
    let i = seg.li;
    if (i > n - 1) i = n - 1;
    while (i < n - 1 && lt >= seg.cum[i + 1]) i++;
    seg.li = i;
    const leg = seg.legs[i];
    out.a = leg.a; out.b = leg.b;
    out.u = smooth(Math.min(1, Math.max(0, (lt - seg.cum[i]) / leg.dur)));
  }
  private readonly poseC = { a: null as unknown as Key, b: null as unknown as Key, u: 0 };
  private readonly poseV = { a: null as unknown as Key, b: null as unknown as Key, u: 0 };
  private readonly poseM = { a: null as unknown as Key, b: null as unknown as Key, u: 0 };

  /** Write every station's joints for time t: the segments active at t, on every flight. Only
      the axes a segment owns are written; every other joint keeps its pose, so a resource that
      is between jobs waits frozen - and two cookies are on the floor at once. */
  private renderAll(t: number, dt: number, flights: Flight[]) {
    const J = this.store.joints;
    let crane: Seg | null = null, vgr: Seg | null = null, mould: Seg | null = null, mouldF: Flight | null = null;
    let flowF: Flight | null = null;
    for (const f of flights) {
      for (let i = f.idx; i < f.segs.length; i++) {
        const seg = f.segs[i];
        if (seg.abs0 < 0) break;
        if (t < seg.abs0 || t >= seg.abs0 + seg.dur) continue;
        if (seg.c && !crane) crane = seg;
        if (seg.v && !vgr) {
          vgr = seg;
          // remember the tour's taken flag, so the workpiece hides once the VGR has the cookie
          this.legAt(seg, t - seg.abs0, this.poseV);
          if (this.poseV.a.taken) f.wpTaken = true;
        }
        if (seg.mould && !mould) { mould = seg; mouldF = f; }
      }
      if (f.flowAbs0 >= 0 && f.flowAbs0 <= t && (!flowF || f.flowAbs0 > flowF.flowAbs0)) flowF = f;
    }
    this.mouldHeld = null;

    // the warehouse crane and its belt
    if (crane) {
      this.legAt(crane, t - crane.abs0, this.poseC);
      const { a, b, u } = this.poseC;
      const h = J.hbw;
      h.travel = a.t + (b.t - a.t) * u;
      h.lift = a.l + (b.l - a.l) * u;
      h.fork = a.f + (b.f - a.f) * u;
      h.belt = a.b + (b.b - a.b) * u;
    }
    // the circulating mould: at rest every mould is in its slot, drawn from the rack
    if (mould && mouldF) {
      this.legAt(mould, t - mould.abs0, this.poseM);
      const { a } = this.poseM;
      J.load.held = a.held;
      J.load.slot = a.slot;
      J.load.cookie = a.cookie;
      if (mouldF.rejected && a.cc.toLowerCase() !== this.RAW.toLowerCase()) J.load.cookie = false;
      J.load.tint.color.copy(this.colour(a.cc));
      J.load.tint.baked = a.cc.toLowerCase() !== this.RAW.toLowerCase();
      J.out = mouldF.cyc.from;
      this.mouldHeld = a.held;
    } else {
      J.out = null;
      J.load.held = null;
    }

    // the VGR: every axis rides the same interpolation, the spring stem included
    if (vgr) {
      const { a, b, u } = this.poseV;
      const vg = J.vgr, vf = vgr.fl!;
      vg.swivel = a.vs + (b.vs - a.vs) * u;
      vg.reach = a.vr + (b.vr - a.vr) * u;
      vg.plunge = a.vp + (b.vp - a.vp) * u;
      vg.compress = a.vc + (b.vc - a.vc) * u;
      // vacuum builds (or bleeds off) across the step where Q8 switches
      vg.seal = (a.cup ? 1 : 0) + ((b.cup ? 1 : 0) - (a.cup ? 1 : 0)) * u;
      vg.carry = vf.rejected && a.carry === "baked" ? null : a.carry;
      const cupHex = a.carry === "baked" ? (vf.cyc.collectColour ?? this.RAW) : this.RAW;
      vg.tint.color.copy(this.colour(cupHex));
      vg.tint.baked = a.carry === "baked";
    }

    // the oven and the sorting line: one cookie runs its whole journey (OvenFlow.ts); the newest
    // flow under way wins the workpiece - an older cookie waits at its Lagerstelle, still drawn
    this.flowFlight = flowF;
    if (flowF) this.renderFlow(flowF, t, dt, false);
  }

  /** The flow's share of the joints for its flight: oven, belts, ejector, the workpiece. */
  private renderFlow(f: Flight, t: number, dt: number, frozen: boolean) {
    const J = this.store.joints;
    const flow = f.rejected ? f.cyc.rflow : f.cyc.flow;
    const ft = Math.min(Math.max(0, t - f.flowAbs0), flow.total);
    const fs = flow.sample(ft, this.flow).s;
    const o = J.oven;
    o.slider = fs.slider; o.door = fs.door; o.turn = fs.turn; o.sauger = fs.sauger; o.lower = fs.lower;
    o.push = fs.push; o.lamp = fs.lamp; o.saw = fs.saw; o.vac = fs.vac; o.baked = fs.baked;
    o.ly = fs.ly; o.eject = fs.eject; o.chute = fs.chute;
    o.beltOven = flow.beltOven(fs.ly);
    o.beltSort = flow.beltSort(fs.ly);
    this.heat(fs.lamp > 0.5, dt);
    J.sort.ejector = f.rejected ? -1 : this.colours.indexOf(f.cyc.bin);
    const wp = J.workpiece;
    // a rejected cookie stays where the line left it, at its end, until the cycle is over
    wp.visible = frozen || f.rejected || !f.wpTaken;
    wp.pos[0] = this.flow.pos[0]; wp.pos[1] = this.flow.pos[1]; wp.pos[2] = this.flow.pos[2];
    // its fault shows as it bakes: underbaked takes only part of its colour, burnt goes dark
    wp.tint.color.lerpColors(this.rawColor, this.colour(f.cyc.baked), fs.baked * (f.cyc.defect === "underbaked" ? 0.3 : 1));
    if (f.cyc.defect === "burnt") wp.tint.color.multiplyScalar(1 - 0.55 * fs.baked);
    wp.tint.baked = fs.baked > 0.5;
    wp.defect = f.cyc.defect;
    wp.seed = f.cyc.seed;
  }
  private mouldHeld: string | null = null;
  private flowFlight: Flight | null = null;

  /** The rest pose: the finished cycle's last key, the flow at rest, nothing circulating. */
  private renderRest(_t: number, dt: number) {
    const C = this.restCyc;
    const cy = this.store.model.cycle;
    cy.from = C.from; cy.to = C.to; cy.total = C.total; cy.t = C.total;
    cy.flavour = C.flavour; cy.collect = C.collect ?? "";
    const legs = C.legs;
    const leg = legs[legs.length - 1];
    const h = this.store.joints.hbw;
    h.travel = leg.b.t; h.lift = leg.b.l; h.fork = leg.b.f; h.belt = leg.b.b;
    this.store.joints.load.held = null;
    this.store.joints.out = null;
    this.mouldHeld = null;
    const fs = C.flow.sample(C.total, this.flow).s;
    const o = this.store.joints.oven;
    o.slider = fs.slider; o.door = fs.door; o.turn = fs.turn; o.sauger = fs.sauger; o.lower = fs.lower;
    o.push = fs.push; o.lamp = fs.lamp; o.saw = fs.saw; o.vac = fs.vac; o.baked = fs.baked;
    o.ly = fs.ly; o.eject = fs.eject; o.chute = fs.chute;
    o.beltOven = C.flow.beltOven(fs.ly);
    o.beltSort = C.flow.beltSort(fs.ly);
    this.heat(fs.lamp > 0.5, dt);
    const vg = this.store.joints.vgr;
    vg.swivel = leg.b.vs; vg.reach = leg.b.vr; vg.plunge = leg.b.vp; vg.compress = leg.b.vc;
    vg.seal = leg.b.cup ? 1 : 0;
    vg.carry = null;
    this.store.joints.workpiece.visible = false;
    this.flowFlight = null;
  }

  /** The caption: the active segments' current step (the VGR's first - it is the show), with the
      flow's when it runs; the sensors and the camera ride along. */
  private caption(t: number, dt: number) {
    const store = this.store, m = store.model;
    const list = this.flights.length ? this.flights : this.frozen !== null && this.frozenFlight ? [this.frozenFlight] : [];
    const resting = !list.length && this.frozen === null;
    let segSay = "", vgrSay = "";
    for (const f of list) {
      for (let i = f.idx; i < f.segs.length; i++) {
        const seg = f.segs[i];
        if (seg.abs0 < 0 || t < seg.abs0 || t >= seg.abs0 + seg.dur) continue;
        const lt = t - seg.abs0;
        let li = 0;
        while (li < seg.legs.length - 1 && lt >= seg.cum[li + 1]) li++;
        if (!vgrSay && seg.v) vgrSay = seg.legs[li].b.say;
        if (!segSay) segSay = seg.legs[li].b.say;
      }
    }
    const say = vgrSay || segSay;
    const flowSay = this.flowFlight?.held ? HELD_SAY : this.flow.say;
    const want = resting ? WAITING : flowSay ? `${say}   ·   ${flowSay}` : say;
    if (want && want !== m.step) { m.step = want; store.commit(false); }
    this.sensors();
    this.camera(dt);
  }

  /** The heating: first-order lags - the sheath glows within seconds, the chamber air follows
      over a minute (wall-clock, so a bake at any playback rate shows the whole curve). */
  private heat(on: boolean, dt: number) {
    const h = this.thermo, k = Math.min(0.1, Math.max(0, dt)), u = on ? 1 : 0;
    h.element += (u - h.element) * (1 - Math.exp(-k / 0.6));
    h.chamber += ((on ? 182 : 25) - h.chamber) * (1 - Math.exp(-k / 2.5));
    this.store.joints.oven.element = h.element;
    this.store.joints.oven.chamberC = h.chamber;
  }

  /** The warehouse's light barriers: is the mould (or the cookie in it) across a beam? */
  private sensors() {
    const J = this.store.joints, h = J.hbw, doc = this.doc;
    const held = this.mouldHeld;
    let yc = NaN, zb = NaN;
    if (held === "belt") { yc = h.belt; zb = doc.belt.surface; }
    else if (held === "fork" && Math.abs(h.travel - doc.belt.x) < 5) { yc = this.seat.y + h.fork; zb = this.seat.z + h.lift; }
    const r = this.mouldD / 2;
    for (let i = 0; i < this.beams.length; i++) {
      const bm = this.beams[i];
      J.beams[bm.tag] = !Number.isNaN(yc) && yc + r > bm.y0 && yc - r < bm.y1 && bm.z > zb && bm.z < zb + this.loadH;
    }
  }

  /** The inspection camera fires once per cookie as it CROSSES its lens's axis - a change of side
      between two ticks, so a fast playback that steps over the axis still triggers it - or, when a
      slow frame rate brought it onto the belt already past the axis, on its first tick in the
      field. A capture is offered to the renderer for exactly one tick (camera.pending), and to
      listeners. */
  private camera(dt: number) {
    const cam = this.store.joints.camera, wp = this.store.joints.workpiece;
    cam.pending = null;
    cam.lit = Math.max(0, cam.lit - dt * 4);
    const f = this.flowFlight;
    if (!f || !this.lens) { this.along = NaN; return; }
    const flavour = f.cyc.flavour;
    // the sorting belt runs along the factory's +Y here; across it, the cookie must be under the lens
    const on = wp.visible && Math.abs(wp.pos[0] - this.lens[0]) < 15;
    const along = on ? wp.pos[1] - this.lens[1] : NaN;
    // the photo, once per cookie: as it crosses the lens's axis between two ticks, or - when a
    // slow frame rate (a background window, fast playback) brought it onto the belt already
    // past the axis - on the first tick it is in the field
    const prev = this.along;
    this.along = along;
    if (!f.cyc.shot && along >= 0 && (prev < 0 || along < LENS_WINDOW_MM)) {
      cam.shots++;
      cam.lit = 1;
      const truth = f.cyc.defect ?? "ok";
      cam.pending = { n: cam.shots, label: flavour, truth };
      if (!f.cyc.shot) f.cyc.shot = cam.shots;
      this.store.emitCapture({ n: cam.shots, flavour, truth });
    }
  }
}

export const WAITING = "Waiting for an order";
