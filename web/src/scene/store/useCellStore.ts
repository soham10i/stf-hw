// Layer 1 - the cell's state: what the 3D twin is doing, for the coordinator that writes it, the
// renderers that draw it and the panels that show it.
//
// Two kinds of state, two channels:
//
//   joints  the machine's pose this frame: every axis, the light barriers, the travelling
//           cookie. Written IN PLACE by the coordinator 60 times a second; the renderers read
//           it imperatively inside useFrame. Never copied, never React state: the objects are
//           created once, so the frame loop allocates nothing.
//   model   the material state and the orders: the rack, the order queue, the running cycle
//           and its caption. Changed by the coordinator and by the panels' actions.
//
// Subscribers are told about changes without polling:
//
//   subscribe       every model change at once, and the moving joints at most TELEMETRY_HZ
//                   times a second - for panels that show live values (progress, telemetry)
//   subscribeModel  only model changes - for what changes when an order moves on (the rack's
//                   meshes, the persistence)
//
// React reads either through useSyncExternalStore (useCell / useCellModel), so a panel
// re-renders at most at the telemetry rate and the 3D Canvas never re-renders because of it.
// The store is a class, not a module singleton: the twin uses the shared `cellStore`, a test
// makes its own.

import { createContext, useContext, useSyncExternalStore } from "react";
import * as THREE from "three";
import { FLOW_KEYS, type FlowState } from "../OvenFlow";

/** The slot the FIRST cycle lifts its raw cookie from when the rack has no raw one (review URLs). */
export const FROM = "B2";
export const TELEMETRY_HZ = 8;

export type Held = "shelf" | "fork" | "belt";
/** slot -> colour of the cookie in its mould (null = an empty mould). */
export type Rack = Record<string, string | null>;
/** One line of an order: `started` cookies have left the rack for it, `done` are back baked. */
export type OrderLine = { id: number; flavour: string; qty: number; started: number; done: number;
  /** cookies the inspection rejected for this line (made again), and the fault seen, if any */
  rejected?: number; fault?: Defect | "" };

/** A spindle-driven solid's axis values (parts.tsx turns screws and drums from these). */
export interface Drive {
  travel: number; lift: number; fork: number; belt: number;
  plunge: number; reach: number; swivel: number;
}

/** A colour a cookie mesh copies each frame - a THREE.Color, so no string is parsed per frame. */
export interface Tint { color: THREE.Color; baked: boolean }
const tint = (hex = "#D8B98C"): Tint => ({ color: new THREE.Color(hex), baked: false });

export interface CellJoints {
  /** the warehouse crane, mm, in its joint frame world -> travel(+X) -> lift(+Z) -> fork(+Y) */
  hbw: { travel: number; lift: number; fork: number; belt: number };
  /** the mould that circulates: who holds it, the slot it is stowed in, its cookie */
  load: { held: Held | null; slot: string; cookie: boolean; tint: Tint };
  /** the slot whose mould is out on a cycle (drawn as `load`, not from the rack); null at rest */
  out: string | null;
  /** light barrier tag -> broken */
  beams: Record<string, boolean>;
  /** the vacuum gripper robot: swivel deg, reach/plunge mm, spring compression mm, vacuum 0..1 */
  vgr: { swivel: number; reach: number; plunge: number; compress: number; seal: number; carry: string | null; tint: Tint };
  /** the oven and sorting stations' joints (OvenFlow), the belts' travel, the heating */
  oven: FlowState & { beltOven: number; beltSort: number; element: number; chamberC: number };
  /** the sorting line's ejector that fires (-1: none) */
  sort: { ejector: number };
  /** the one cookie travelling through the oven and the sorting line, factory mm; `defect`: the
      fault the simulation gave it (drawn once it is baked), `seed`: where the fault falls */
  workpiece: { visible: boolean; pos: [number, number, number]; tint: Tint; defect: Defect | null; seed: number };
  /** the inspection camera: ring light 0..1, and a photo to take this frame */
  camera: { lit: number; shots: number; pending: { n: number; label: string; truth: string } | null };
}

/** A fault the simulation can give a cookie, for the inspection to catch. */
export type Defect = "burnt" | "underbaked" | "cracked";
export const DEFECTS: Defect[] = ["burnt", "underbaked", "cracked"];
/** The inspection's decision on a cookie (vision/inspect.ts): pass to its Lagerstelle, or reject
    (and an unsure one goes to a person: rejected too, held at the end of the line). */
export type Verdict = { n: number; verdict: "pass" | "reject" | "check"; condition: string; p: number; flavour: string; ae: number; anomaly: boolean };
/** One inspected cookie, as the Orders panel shows it. */
export type Inspected = Verdict & { truth: string; cookieFlavour: string };

export interface CellModel {
  rack: Rack;
  rawColour: string;
  queue: OrderLine[];
  seq: number;
  delivered: number;
  /** nothing to make: the cell rests */
  idle: boolean;
  /** a rejected cookie's mould is refilled with dough at once, so twelve cookies are always in the
      factory; off: the slot stays empty until a restock */
  dough: boolean;
  /** what the cell is doing, in words */
  step: string;
  /** the running cycle: its slot, its flavour, its Lagerstelle; t of total seconds */
  cycle: { from: string; to: string; total: number; t: number; flavour: string; collect: string };
  /** the inspection: the defect for the next cookie, the last decisions, the counts */
  inspect: { next: Defect | null; recent: Inspected[]; passed: number; rejected: number;
    /** QC testing: one cookie in every 12 started gets a random fault (the cookie and the fault
        drawn when the 12 begin), so the inspection is exercised every cycle */
    auto: boolean; batch: { pos: number; pick: number; fault: Defect } };
}

export type Capture = { n: number; flavour: string; truth: string };
/** What the twin did, for the database (the API's /twin/inspection and /twin/order). */
export type TwinRecord =
  | { kind: "inspection"; n: number; flavour: string; truth: string; condition: string; p: number; verdict: string; ae: number; unusual: boolean }
  | { kind: "order"; flavour: string; qty: number; baked: number; good: number; scrap: number; qc_fault: string };

function newJoints(): CellJoints {
  const oven = { beltOven: 0, beltSort: 0, element: 0, chamberC: 25 } as CellJoints["oven"];
  for (const k of FLOW_KEYS) oven[k] = 0;
  return {
    hbw: { travel: 0, lift: 0, fork: 0, belt: 0 },
    load: { held: null, slot: FROM, cookie: true, tint: tint() },
    out: null,
    beams: {},
    vgr: { swivel: 0, reach: 0, plunge: 500, compress: 0, seal: 0, carry: null, tint: tint() },
    oven,
    sort: { ejector: -1 },
    workpiece: { visible: false, pos: [0, 0, 0], tint: tint(), defect: null, seed: 0 },
    camera: { lit: 0, shots: 0, pending: null },
  };
}

export class CellStore {
  readonly joints: CellJoints = newJoints();
  readonly model: CellModel = {
    rack: {}, rawColour: "#D8B98C", queue: [], seq: 0, delivered: 0, idle: true, dough: true, step: "",
    cycle: { from: "", to: "", total: 0, t: 0, flavour: "", collect: "" },
    inspect: { next: null, recent: [], passed: 0, rejected: 0, auto: true, batch: { pos: 0, pick: -1, fault: "burnt" } },
  };
  /** requests the coordinator carries out on its next tick, in step with the machine */
  readonly requests = { restock: false, reset: false };
  /** the inspection's decisions, by camera shot, as they come back from the renderer */
  readonly verdicts = new Map<number, Verdict>();

  private version = 0;
  private modelVersion = 0;
  private lastPublish = -Infinity;
  private subs = new Set<() => void>();
  private modelSubs = new Set<(material: boolean) => void>();
  private captureSubs = new Set<(c: Capture) => void>();
  private recordSubs = new Set<(r: TwinRecord) => void>();

  // ---- subscriptions (arrow functions: stable references for useSyncExternalStore) ----
  subscribe = (fn: () => void) => { this.subs.add(fn); return () => { this.subs.delete(fn); }; };
  subscribeModel = (fn: (material: boolean) => void) => { this.modelSubs.add(fn); return () => { this.modelSubs.delete(fn); }; };
  onCapture = (fn: (c: Capture) => void) => { this.captureSubs.add(fn); return () => { this.captureSubs.delete(fn); }; };
  onRecord = (fn: (r: TwinRecord) => void) => { this.recordSubs.add(fn); return () => { this.recordSubs.delete(fn); }; };
  subscribeModelChange = (fn: () => void) => this.subscribeModel(() => fn());
  getVersion = () => this.version;
  getModelVersion = () => this.modelVersion;

  /** The model changed. `material`: the rack or the orders (worth saving), not just the caption. */
  commit(material = true) {
    this.modelVersion++;
    this.version++;
    this.modelSubs.forEach((f) => f(material));
    this.subs.forEach((f) => f());
  }
  /** The joints moved (every frame): panels hear of it at most TELEMETRY_HZ times a second. */
  publishFrame(now: number) {
    if (now - this.lastPublish < 1 / TELEMETRY_HZ) return;
    this.lastPublish = now;
    this.version++;
    this.subs.forEach((f) => f());
  }
  emitCapture(c: Capture) { this.captureSubs.forEach((f) => f(c)); }
  emitRecord(r: TwinRecord) { this.recordSubs.forEach((f) => f(r)); }

  // ---- queries ----
  /** raw cookies in the rack not yet promised to an order */
  free() {
    const raw = this.model.rawColour.toLowerCase();
    const n = Object.values(this.model.rack).filter((c) => c?.toLowerCase() === raw).length;
    const promised = this.model.queue.reduce((k, o) => k + o.qty - o.done, 0);
    return Math.max(0, n - promised);
  }

  // ---- actions (the Orders panel) ----
  /** The order book holds at most this many lines; a further order is rejected. */
  static readonly MAX_ORDERS = 12;
  /** Queue an order line; false when the rack has too few raw cookies for it or the book is full. */
  place(flavour: string, qty: number) {
    const n = Math.max(1, Math.min(12, Math.round(qty)));
    if (this.model.queue.length >= CellStore.MAX_ORDERS || n > this.free()) return false;
    this.model.queue.push({ id: ++this.model.seq, flavour, qty: n, started: 0, done: 0 });
    this.commit();
    return true;
  }
  /** Hand the baked cookies over and refill their moulds with dough (once the cell is idle). */
  deliver() { this.requests.restock = true; }
  /** Give the next cookie a fault, for the inspection to catch (null: a good one). */
  injectDefect(d: Defect | null) { this.model.inspect.next = d; this.commit(false); }
  /** QC testing on or off: one damaged cookie in every 12. */
  autoDefects(on: boolean) { this.model.inspect.auto = on; this.commit(false); }
  /** The inspection decided on camera shot `v.n` (vision/inspect.ts, after the photo). */
  decide(v: Verdict) { this.verdicts.set(v.n, v); }
  /** Twelve raw cookies, no orders, at once. */
  reset() { this.requests.reset = true; }
}

/** The twin's store. */
export const cellStore = new CellStore();
export const CellStoreContext = createContext<CellStore>(cellStore);
export const useCellStore = () => useContext(CellStoreContext);

/** A value from the store, re-read on every model change and at the telemetry rate. */
export function useCell<T>(select: (s: CellStore) => T): T {
  const s = useCellStore();
  useSyncExternalStore(s.subscribe, s.getVersion);
  return select(s);
}

/** A value from the model, re-read only when the model changes (an order moves on). */
export function useCellModel<T>(select: (m: CellModel) => T): T {
  const s = useCellStore();
  useSyncExternalStore(s.subscribeModelChange, s.getModelVersion);
  return select(s.model);
}
