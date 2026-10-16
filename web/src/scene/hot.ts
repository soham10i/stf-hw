// The twin's shared live state: plain mutable objects that the cycle timeline (HbwCad)
// writes once per frame inside useFrame, and that the 3D modules and the side panels read.
// They are NOT React state on purpose: re-rendering React 60 times a second would stall the
// scene. Contract: only the timeline writes the *Hot objects; panels sample them on their own
// timer (a few times a second); twinOrders is also written by the Orders panel (place,
// restock), which the loop picks up on its next frame.







import { type FlowState, type Mode } from "./OvenFlow";
















/** The slot the FIRST cycle lifts its raw cookie from (review URLs rely on it). */
export const FROM = "B2";

/** One line of an order: a quantity of one flavour. `started` cycles have taken a raw cookie for
    it, `done` cookies of it have been baked and sorted into their Lagerstelle. */
export type OrderLine = { id: number; flavour: string; qty: number; started: number; done: number };

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
export type Rack = Record<string, string | null>;

/** live pose, read imperatively inside useFrame - never React state */
export interface Drive {
  travel: number; lift: number; fork: number; belt: number;
  plunge: number; reach: number; swivel: number;
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
/** The inspection camera (Upgrade 15, vision/mount.py): each cookie it photographs. Listeners
    (the Vision panel) get the cookie's flavour; `lit` drives the ring light's strobe. */
export const visionHot = {
  captures: 0, lit: 0,
  listeners: new Set<(c: { n: number; flavour: string; t: number }) => void>(),
};
export const bayHot: Record<string, { colour: string }> = { weiss: { colour: "#FBF8F1" }, rot: { colour: "#F4A6BF" }, blau: { colour: "#5C3A1E" } };
/** The oven + sorting flow: every joint of both stations, and the ONE cookie
    that travels through them (see OvenFlow.ts). Written once per frame. */
export const ovenHot = {
  s: null as FlowState | null,
  belts: { oven: 0, sort: 0 },
  mode: "tray" as Mode,
  visible: false,
  pos: [0, 0, 0] as [number, number, number],
  colour: "#D8B98C",
  /** chamber temperature at the K-type thermocouple, C, and the elements' glow 0..1
      (written by OvenModule's thermal model) */
  tempC: 25,
  heat: 0,
};
