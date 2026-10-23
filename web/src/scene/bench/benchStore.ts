// The Test bench's state, shared by its side panel (the page) and the 3D scene (the Canvas).
//
// The bench runs one module in the physics worker (core/PhysicsClient):
//   sorting    the sorting line - cookies on a moving belt, pneumatic ejectors, light barriers
//   warehouse  the high-bay warehouse's axes - DC encoder motors on spindles, reference switches,
//              and the PLC's positioning block - and its belt (an S-motor, two light barriers)
//   arm        the vacuum gripper's three encoder axes: swivel, plunge, reach
// The panel sends commands, the worker simulates, and the scene draws what the worker publishes,
// reading the shared bridge once per frame (BenchBodies). Nothing here steps physics.
//
// The physics engine (Rapier, ~4 MB) is loaded only when the bench starts.
import { useSyncExternalStore } from "react";

import type { PhysicsClient } from "../../core/PhysicsClient";
import { AXIS_STRIDE, type Snapshot } from "../../core/SimulationBridge";
import type { AxisCommand, WorkerStats } from "../../workers/protocol";
import type { CadDoc } from "../../shared/model";
import { setFocus } from "../focus";
import { BARRIERS, cookieAt, COLOURS, sortingWorld, type Colour, type SortingWorld } from "./sortingWorld";
import { AXES, mouldAt, warehouseWorld, type WarehouseWorld } from "./warehouseWorld";
import { VGR_AXES, vgrWorld, type VgrWorld } from "./vgrWorld";

export type BenchStatus = "off" | "starting" | "running" | "paused" | "error";
export type BenchModule = "sorting" | "warehouse" | "arm";
const MAX_COOKIES = 12; // the oldest leaves the bench when a 13th is added
/** each module's switches and sensors, in its pin order */
export const SWITCHES = { warehouse: ["I1", "I4", "I5", "I6", "I2", "I3"], arm: ["I3", "I1", "I2"] } as const;
const AXIS_IDS = { warehouse: AXES, arm: VGR_AXES } as const;

export interface AxisReading {
  position: number; // mm, where it really is
  rpm: number;
  current: number; // A
  count: number; // what the PLC reads
  task: string;
  error: number; // the last move's error as the PLC sees it, mm (NaN: none yet)
  crashes: number;
  homed: boolean;
}

export interface BenchView {
  module: BenchModule;
  status: BenchStatus;
  error: string | null;
  rate: number;
  beltSpeed: number;
  shared: boolean;
  rapier: string;
  stats: WorkerStats | null;
  cookies: number;
  /** the sorting line's barriers (updated a few times a second) */
  barriers: Record<(typeof BARRIERS)[number], boolean>;
  /** each pusher's stroke, mm */
  strokes: Record<Colour, number>;
  /** the warehouse's or the arm's axes, and its switches (high: closed, or a beam cut) */
  axes: Record<string, AxisReading> | null;
  switches: Record<string, boolean>;
  moulds: number;
  simTime: number;
}

/** What the scene reads every frame (mutable, no re-render). */
export const live = {
  client: null as PhysicsClient | null,
  module: "sorting" as BenchModule,
  world: null as SortingWorld | null,
  warehouse: null as WarehouseWorld | null,
  arm: null as VgrWorld | null,
  /** cookie instance -> its colour */
  colours: new Map<string, Colour>(),
  pusherMm: [0, 0, 0] as [number, number, number],
  beltTravel: 0,
  pins: new Float64Array(BARRIERS.length),
  /** each cookie's factory position (mm), for the beams */
  cookieXY: [] as [number, number][],
  /** the warehouse's axis positions, mm, and its belt's travel (for HbwCad) */
  hbw: { travel: 0, lift: 0, fork: 0, belt: 0 },
  /** the gripper's axis positions, deg and mm (for VgrModule) */
  vgr: { swivel: 0, plunge: 0, reach: 0 },
  axes: new Float64Array(0),
};

let view: BenchView = {
  module: "sorting", status: "off", error: null, rate: 1, beltSpeed: 40, shared: false, rapier: "", stats: null, cookies: 0,
  barriers: { I2: false, I3: false, I5: false, I6: false, I7: false },
  strokes: { weiss: 0, rot: 0, blau: 0 },
  axes: null, switches: {}, moulds: 0,
  simTime: 0,
};
const listeners = new Set<() => void>();
function set(patch: Partial<BenchView>) {
  view = { ...view, ...patch };
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

export function useBench(): BenchView {
  return useSyncExternalStore(subscribe, () => view);
}
export const benchActive = () => view.status === "running" || view.status === "paused";
/** the bench is running this module (the scene's renderers ask before they hand over) */
export const benchOn = (m: BenchModule) => benchActive() && live.module === m;

let counter = 0;
const order: string[] = [];
// the panel's readings come from the bridge on their own timer, not from the 3D view's frames:
// a hidden tab stops rendering, but the panel's numbers (and anyone reading them) carry on
let poll: ReturnType<typeof setInterval> | null = null;
let snap: Snapshot | null = null;

/** Chooses the module (stops a running bench of the other one). */
export function chooseModule(m: BenchModule): void {
  if (m === view.module) return;
  if (benchActive() || view.status === "starting") stopBench();
  set({ module: m });
}

/** Starts the bench on the chosen module: builds its world from the CAD export, starts the worker. */
export async function startBench(doc: CadDoc): Promise<void> {
  if (view.status === "starting" || benchActive()) return;
  set({ status: "starting", error: null });
  try {
    const { PhysicsClient } = await import("../../core/PhysicsClient");
    const m = view.module;
    const sorting = m === "sorting" ? sortingWorld(doc) : null;
    const warehouse = m === "warehouse" ? warehouseWorld(doc) : null;
    const arm = m === "arm" ? vgrWorld(doc) : null;
    const client = await PhysicsClient.start((sorting ?? warehouse ?? arm)!.init, {
      onStats: (stats) => set({ stats }),
      onError: (message) => set({ error: message }),
    });
    live.client = client;
    live.module = m;
    live.world = sorting;
    live.warehouse = warehouse;
    live.arm = arm;
    live.axes = new Float64Array(0);
    if (warehouse) live.hbw = { ...warehouse.powerUp, belt: 0 };
    if (arm) live.vgr = { ...arm.powerUp };
    if (sorting) client.setConveyor("belt_web", view.beltSpeed);
    client.run(true, view.rate);
    snap = client.snapshot();
    poll = setInterval(readings, 200);
    set({ status: "running", shared: client.shared, rapier: client.rapierVersion });
    setFocus(m === "sorting" ? "sort" : m === "arm" ? "vgr" : "hbw");
  } catch (e) {
    set({ status: "error", error: e instanceof Error ? e.message : String(e) });
  }
}

export function stopBench(): void {
  if (poll) clearInterval(poll);
  poll = null;
  snap = null;
  live.client?.dispose();
  live.client = null;
  live.world = null;
  live.warehouse = null;
  live.arm = null;
  live.colours.clear();
  live.cookieXY = [];
  live.pusherMm = [0, 0, 0];
  order.length = 0;
  mouldOrder.length = 0;
  set({ status: "off", stats: null, cookies: 0, moulds: 0, simTime: 0, axes: null, switches: {}, error: null });
}

export function pauseBench(paused: boolean): void {
  if (!live.client) return;
  live.client.run(!paused, view.rate);
  set({ status: paused ? "paused" : "running" });
}

/** How fast the bench runs against real time (the steps stay 10 ms: only more of them a second). */
export function setRate(rate: number): void {
  set({ rate });
  if (live.client && view.status === "running") live.client.run(true, rate);
}

// ------------------------------------------------------------------ sorting line
/** A cookie of a colour onto the belt at the inlet. */
export function addCookie(colour: Colour): void {
  const { client, world } = live;
  if (!client || !world) return;
  const { part } = cookieAt(world, ++counter, colour);
  client.spawn(part, { kind: "dynamic", friction: 0.4 });
  live.colours.set(part.instance_id, colour);
  order.push(part.instance_id);
  if (order.length > MAX_COOKIES) {
    const old = order.shift()!;
    client.remove(old);
    live.colours.delete(old);
  }
  set({ cookies: order.length });
}

/** One stroke of a colour's ejector. */
export function eject(colour: Colour): void {
  const { client, world } = live;
  if (!client || !world) return;
  client.pulse(world.pusherJoint[colour], 90, 0.15);
}

export function setBeltSpeed(mmPerS: number): void {
  live.client?.setConveyor("belt_web", mmPerS);
  set({ beltSpeed: mmPerS });
}

// ------------------------------------------------------------------ warehouse
/** Tells an axis's positioning block what to do (the warehouse's or the arm's). */
export function axis(id: string, command: AxisCommand): void {
  if (!live.client || !(live.warehouse || live.arm)) return;
  if (view.error) set({ error: null }); // a refused command's message gives way to the next one
  live.client.axis(id, command);
}

/** Homes the module: the warehouse's fork back to I6, lift up to I4, travel to I1; the arm's
    plunge up to I1, reach back to I2, swivel onto I3. */
export function homeAll(): void {
  if (live.arm) {
    for (const id of VGR_AXES) axis(id, { kind: "home" });
    return;
  }
  axis("fork", { kind: "until", dir: -1, switch: 0 });
  axis("lift", { kind: "home" });
  axis("travel", { kind: "home" });
}

let moulds = 0;
const mouldOrder: string[] = [];
/** A mould (workpiece carrier) set on the warehouse's belt at the crane's hand-over. */
export function addMould(): void {
  const { client, warehouse } = live;
  if (!client || !warehouse) return;
  const part = mouldAt(warehouse, ++moulds);
  client.spawn(part, { kind: "dynamic", friction: 0.5 });
  mouldOrder.push(part.instance_id);
  if (mouldOrder.length > 4) client.remove(mouldOrder.shift()!);
  set({ moulds: mouldOrder.length });
}

/** Sends the arm to a solved station: the swivel and the reach together. */
export function armTo(station: string): void {
  const st = live.arm?.stations[station];
  if (!st) return;
  axis("swivel", { kind: "move", target: st.swivel });
  axis("reach", { kind: "move", target: st.reach });
}

// ------------------------------------------------------------------ readings
const TASK_NAMES = ["idle", "jog", "move", "home", "until", "done"];

/** What the panel shows, from the bridge, five times a second. */
function readings(): void {
  const c = live.client;
  if (!c || !snap || !c.read(snap)) return;
  const s = snap;
  if (live.module === "sorting") {
    const w = live.world!;
    const barriers = Object.fromEntries(BARRIERS.map((t) => [t, s.pinVolts[w.barrierPin[t]] >= 15])) as BenchView["barriers"];
    const strokes = Object.fromEntries(COLOURS.map((col, i) => [col, Math.round(live.pusherMm[i])])) as BenchView["strokes"];
    set({ barriers, strokes, simTime: s.simTime });
    return;
  }
  const m = live.module;
  const ids = AXIS_IDS[m];
  const a = s.axes;
  if (s.axisCount < ids.length) return;
  const axes = Object.fromEntries(ids.map((id, i) => {
    const k = i * AXIS_STRIDE;
    return [id, {
      position: a[k], rpm: a[k + 1], current: a[k + 2], count: a[k + 4], task: TASK_NAMES[a[k + 5]] ?? "?",
      error: a[k + 6], crashes: a[k + 7], homed: a[k + 8] === 1,
    }];
  }));
  const switches = Object.fromEntries(SWITCHES[m].map((t, i) => [t, s.pinVolts[i] >= 15]));
  set({ axes, switches, simTime: s.simTime });
}
