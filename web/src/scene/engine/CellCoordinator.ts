// Layer 2 - the headless cell coordinator: the one place that decides what the cell does.
//
// It runs the orders (queue, cycles, restock, reset), plays each cycle's choreography -
// the crane's script (timeline.ts) with the VGR's proven tour and the oven/sorting flow
// (OvenFlow.ts) - and writes every station's joints into the store (store/useCellStore.ts),
// in place, once per tick. It also derives what the machine's sensors see (the warehouse's
// light barriers, the camera's trigger) and the oven's heating, and saves the material state
// through a CellPersistence when it changes.
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
import { FROM, type CellStore, type OrderLine, type Rack } from "../store/useCellStore";
import type { CellPersistence } from "./persistence";

type Key = ReturnType<typeof script>[number];
type Leg = { a: Key; b: Key; dur: number; start: number };
type Plan = {
  from: string; to: string; legs: Leg[]; tOvenGo: number; flow: ReturnType<typeof buildFlow>; total: number;
  baked: string; flavour: string; collect: string | null; collectColour: string | null; bin: string;
};
type Cycle = Plan & { line: number };

export interface CoordinatorOptions {
  /** the VGR's tours per Lagerstelle (vgr_tours.json); null: the exported demo tour */
  tours: Record<string, PlanKey[]> | null;
  persistence?: CellPersistence;
  /** review aid (?t= / ?at=&n=): freeze the FIRST cycle at a time, or at the end of a step */
  review?: { t?: number | null; at?: string | null; n?: number };
}

const smooth = (u: number) => THREE.MathUtils.smoothstep(u, 0, 1);

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

  private cyc: { c: Cycle; t0: number };
  private lens: [number, number] | null = null;
  /** the travelling cookie's position along the belt relative to the lens's axis, last tick */
  private along = NaN;
  /** the first tick announces the restored cell (the constructor runs inside a React render,
      where notifying other components is not allowed) */
  private announced = false;
  private legIdx = -1;
  private flowSay = "";
  private thermo = { element: 0, chamber: 25 };

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

    this.cyc = { c: this.start(), t0: 0 };
    this.frozen = this.review(opts.review);
    this.unsubscribe = store.subscribeModel((material) => {
      if (!material || !this.persistence) return;
      const m = store.model;
      this.persistence.save({ rack: m.rack, queue: m.queue, seq: m.seq, delivered: m.delivered });
    });
  }

  dispose() { this.unsubscribe(); }

  /** The inspection camera's lens axis in the factory frame (mm), once vision/camera.json is in. */
  setCamera(lens: [number, number] | null) { this.lens = lens; }

  // ------------------------------------------------------------------ planning
  private colour(hex: string) {
    const k = hex.toLowerCase();
    let c = this.palette.get(k);
    if (!c) { c = new THREE.Color(hex); this.palette.set(k, c); }
    return c;
  }

  /** One cycle: the crane's script with the VGR's tour, timed; the oven/sorting flow; the VGR's
      wait for its cookie. Cached per (slot, flavour, Lagerstelle). */
  private plan(from: string, to: string, flavour: string, collect: string | null): Plan {
    const key = `${from}>${to}>${flavour}>${collect}`;
    const hit = this.plans.get(key);
    if (hit) return hit;
    const doc = this.doc;
    const tour = this.tours?.[collect ?? "none"] ?? doc.vgr.plan.keys;
    const keys = script(doc, from, to, tour, collect);
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
      const hold = { a, b: { ...a, say: "VGR: holds clear while the cookie is baked and sorted" }, dur: wait, start: legs[iH].start };
      for (const l of legs.slice(iH)) l.start += wait;
      legs.splice(iH, 0, hold);
    }
    const total = Math.max(legs.reduce((q, l) => q + l.dur, 0), tOvenGo + flow.total + 3);
    const baked = doc.pipeline.flavours[flavour]?.colour ?? this.RAW;
    this.colour(baked);
    const collectColour = collect ? binColour(doc, collect) : null;
    if (collectColour) this.colour(collectColour);
    const p: Plan = { from, to, legs, tOvenGo, flow, total, baked, flavour, collect, collectColour, bin: flow.bin };
    this.plans.set(key, p);
    return p;
  }

  private freshRack(): Rack {
    const r: Rack = {};
    for (const q of Object.keys(this.doc.slots)) r[q] = this.RAW;
    return r;
  }
  private rawIn(r: Rack) { return this.order.filter((q) => r[q] === this.RAW); }
  /** The next ordered cookie, if any: its order line, one more of it started. */
  private nextWork(): OrderLine | null {
    const line = this.store.model.queue.find((o) => o.started < o.qty);
    if (!line) return null;
    line.started++;
    return line;
  }
  /** The first raw cookie goes out and comes back baked into the same slot. */
  private begin(r: Rack, line: OrderLine): Cycle {
    const from = this.rawIn(r)[0] ?? FROM;
    const bin = this.doc.pipeline.flavours[line.flavour]?.bin ?? null;
    return { ...this.plan(from, from, line.flavour, bin), line: line.id };
  }
  /** The pose the cell rests in: a finished cycle with no cookie to fetch. */
  private rest(r: Rack): Cycle {
    const from = this.rawIn(r)[0] ?? FROM;
    return { ...this.plan(from, from, Object.keys(this.doc.pipeline.flavours)[0], null), line: -1 };
  }

  /** The cell as it was: the store's (a remounted view) or the saved one (a reload), else fresh.
      A cookie that was out on its cycle is dough in its slot again and is baked again. */
  private start(): Cycle {
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
    const line = this.nextWork();
    m.idle = !line;
    return line ? this.begin(m.rack, line) : this.rest(m.rack);
  }

  private review(r: CoordinatorOptions["review"]): number | null {
    if (!r) return null;
    const { legs, total, flow, tOvenGo } = this.cyc.c;
    if (r.t != null && Number.isFinite(r.t)) return r.t % total;
    if (!r.at) return null;
    const at = r.at.toLowerCase();
    const hits = legs.filter((l) => l.b.say.toLowerCase().includes(at));
    const l = hits[Math.max(0, (r.n ?? 1) - 1)];
    if (l) return l.start + l.dur - 1e-3;
    const st = flow.steps.find((x) => x.say.toLowerCase().includes(at));
    return st ? tOvenGo + st.t0 + st.d - 1e-3 : null;
  }

  // ------------------------------------------------------------------ the tick
  /** Advance to twin time `t` (s, playback-scaled); `dt` is the wall-clock frame time (s). */
  tick(t: number, dt: number) {
    const store = this.store, m = store.model, J = store.joints;
    const live = this.frozen === null;
    if (!this.announced) { this.announced = true; store.commit(false); }

    if (store.requests.reset && live) this.doReset(t);
    if (live && !m.idle && t - this.cyc.t0 >= this.cyc.c.total) this.complete();
    if (live && m.idle && store.requests.restock) this.restock();
    if (live && m.idle) {
      const line = this.nextWork();
      if (line) {
        this.cyc = { c: this.begin(m.rack, line), t0: t };
        m.idle = false;
        this.legIdx = -1;
        store.commit();
      }
    }

    const C = this.cyc.c;
    const resting = m.idle && live;
    const tc = this.frozen ?? (m.idle ? C.total : t - this.cyc.t0);
    const cy = m.cycle;
    cy.from = C.from; cy.to = C.to; cy.total = C.total; cy.t = tc; cy.flavour = C.flavour; cy.collect = C.collect ?? "";

    // the leg of the script at tc, and how far along it (eased)
    const legs = C.legs;
    let li = legs.length - 1;
    for (let i = 0; i < legs.length; i++) if (tc < legs[i].start + legs[i].dur) { li = i; break; }
    const leg = legs[li];
    const s = smooth((tc - leg.start) / leg.dur);
    const a = leg.a, b = leg.b;

    // the warehouse crane and its belt
    const h = J.hbw;
    h.travel = a.t + (b.t - a.t) * s;
    h.lift = a.l + (b.l - a.l) * s;
    h.fork = a.f + (b.f - a.f) * s;
    h.belt = a.b + (b.b - a.b) * s;
    // the circulating mould: at rest every mould is in its slot, drawn from the rack
    const held = resting ? null : a.held;
    J.load.held = held;
    J.load.slot = a.slot;
    J.load.cookie = a.cookie;
    J.load.tint.color.copy(this.colour(a.cc));
    J.load.tint.baked = a.cc.toLowerCase() !== this.RAW.toLowerCase();
    J.out = resting ? null : C.from;

    // the VGR: every axis rides the same interpolation, the spring stem included
    const vg = J.vgr;
    vg.swivel = a.vs + (b.vs - a.vs) * s;
    vg.reach = a.vr + (b.vr - a.vr) * s;
    vg.plunge = a.vp + (b.vp - a.vp) * s;
    vg.compress = a.vc + (b.vc - a.vc) * s;
    // vacuum builds (or bleeds off) across the step where Q8 switches
    vg.seal = (a.cup ? 1 : 0) + ((b.cup ? 1 : 0) - (a.cup ? 1 : 0)) * s;
    vg.carry = a.carry;
    const cupHex = a.carry === "baked" ? (C.collectColour ?? this.RAW) : this.RAW;
    vg.tint.color.copy(this.colour(cupHex));
    vg.tint.baked = a.carry === "baked";

    // the oven and the sorting line: idle until the VGR has delivered and left, then the one
    // cookie runs its whole journey (OvenFlow.ts)
    const f = C.flow.sample(tc - C.tOvenGo, this.flow);
    const o = J.oven;
    const fs = f.s;
    o.slider = fs.slider; o.door = fs.door; o.turn = fs.turn; o.sauger = fs.sauger; o.lower = fs.lower;
    o.push = fs.push; o.lamp = fs.lamp; o.saw = fs.saw; o.vac = fs.vac; o.baked = fs.baked;
    o.ly = fs.ly; o.eject = fs.eject; o.chute = fs.chute;
    o.beltOven = C.flow.beltOven(fs.ly);
    o.beltSort = C.flow.beltSort(fs.ly);
    this.heat(fs.lamp > 0.5, dt);
    J.sort.ejector = this.colours.indexOf(C.bin);
    const wp = J.workpiece;
    wp.visible = !m.idle && (tc >= C.tOvenGo || a.ovenIn) && !a.taken;
    wp.pos[0] = f.pos[0]; wp.pos[1] = f.pos[1]; wp.pos[2] = f.pos[2];
    wp.tint.color.lerpColors(this.rawColor, this.colour(C.baked), fs.baked);
    wp.tint.baked = fs.baked > 0.5;

    this.sensors(held);
    this.camera(dt, C.flavour);

    // the caption: rebuilt only when the step changes
    if (li !== this.legIdx || f.say !== this.flowSay || (resting && m.step !== WAITING)) {
      this.legIdx = li;
      this.flowSay = f.say;
      const say = resting ? WAITING : f.say ? `${b.say}   ·   ${f.say}` : b.say;
      if (say !== m.step) { m.step = say; store.commit(false); }
    }
    store.publishFrame(t);
  }

  /** The cycle is done: its cookie is back in its slot, baked. */
  private complete() {
    const m = this.store.model, done = this.cyc.c;
    m.rack = { ...m.rack, [done.to]: done.baked };
    const line = m.queue.find((q) => q.id === done.line);
    if (line) line.done++;
    m.idle = true;
    this.store.commit();
  }

  /** The baked cookies are delivered and their moulds refilled with dough. */
  private restock() {
    const m = this.store.model, r = { ...m.rack };
    for (const q of Object.keys(r)) if (r[q] !== this.RAW) { r[q] = this.RAW; m.delivered++; }
    m.rack = r;
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
    this.cyc = { c: this.rest(m.rack), t0: t };
    this.legIdx = -1;
    this.persistence?.clear();
    store.commit();
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
  private sensors(held: string | null) {
    const J = this.store.joints, h = J.hbw, doc = this.doc;
    let yc = NaN, zb = NaN;
    if (held === "belt") { yc = h.belt; zb = doc.belt.surface; }
    else if (held === "fork" && Math.abs(h.travel - doc.belt.x) < 5) { yc = this.seat.y + h.fork; zb = this.seat.z + h.lift; }
    const r = this.mouldD / 2;
    for (let i = 0; i < this.beams.length; i++) {
      const bm = this.beams[i];
      J.beams[bm.tag] = !Number.isNaN(yc) && yc + r > bm.y0 && yc - r < bm.y1 && bm.z > zb && bm.z < zb + this.loadH;
    }
  }

  /** The inspection camera fires as the travelling cookie CROSSES its lens's axis - a change of
      side between two ticks, so a fast playback that steps over the axis still triggers it. A
      capture is offered to the renderer for exactly one tick (camera.pending), and to listeners. */
  private camera(dt: number, flavour: string) {
    const cam = this.store.joints.camera, wp = this.store.joints.workpiece;
    cam.pending = null;
    cam.lit = Math.max(0, cam.lit - dt * 4);
    if (!this.lens) return;
    // the sorting belt runs along the factory's +Y here; across it, the cookie must be under the lens
    const on = wp.visible && Math.abs(wp.pos[0] - this.lens[0]) < 15;
    const along = on ? wp.pos[1] - this.lens[1] : NaN;
    if (along >= 0 && this.along < 0) {
      cam.shots++;
      cam.lit = 1;
      cam.pending = { n: cam.shots, label: flavour };
      this.store.emitCapture({ n: cam.shots, flavour });
    }
    this.along = along;
  }
}

export const WAITING = "Waiting for an order";
