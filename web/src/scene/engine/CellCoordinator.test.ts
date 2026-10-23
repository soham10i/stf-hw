// The headless coordinator, tested without a canvas: a CellStore, the exported machine and the
// VGR's tours, a persistence in memory, and tick() called with a simulated clock. Everything the
// 3D view would draw is in store.joints; everything the panels show is in store.model.
import { describe, expect, it } from "vitest";
import { CellCoordinator, VERDICT_WAIT_S, WAITING } from "./CellCoordinator";
import { BELT_SPEED, RATE, SPEED } from "../timeline";
import { memoryPersistence } from "./persistence";
import { CellStore, TELEMETRY_HZ } from "../store/useCellStore";
import machine from "../../../public/hbw_parts_up12.json";
import toursDoc from "../../../public/vgr_tours.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const doc = machine as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const tours = (toursDoc as any).tours;
const CHOC = doc.pipeline.flavours.chocolate.colour as string;
const STRAW = doc.pipeline.flavours.strawberry.colour as string;
const RAW = doc.pipeline.raw_colour as string;
const DT = 1 / 30;

function cell(persistence = memoryPersistence(), speed = 1, qc = false) {
  const store = new CellStore();
  store.model.inspect.auto = qc;          // QC testing's random fault only where a test asks for it
  const coord = new CellCoordinator(doc, store, { tours, persistence });
  let t = 0;
  /** run the twin for `s` seconds, or until `until` holds */
  const run = (s: number, until?: () => boolean) => {
    const end = t + s;
    while (t < end) {
      t += DT * speed;
      coord.tick(t, DT);
      if (until?.()) return true;
    }
    return false;
  };
  const done = () => store.model.idle && store.model.queue.every((o) => o.done === o.qty);
  return { store, coord, persistence, run, done };
}

describe("orders", () => {
  it("starts at rest with twelve raw cookies, every mould in its slot", () => {
    const { store, run } = cell();
    run(1);
    expect(Object.values(store.model.rack)).toEqual(Array(12).fill(RAW));
    expect(store.model.idle).toBe(true);
    expect(store.model.step).toBe(WAITING);
    expect(store.joints.out).toBeNull();          // nothing circulates: no slot drawn empty
    expect(store.joints.load.held).toBeNull();
    expect(store.joints.workpiece.visible).toBe(false);
  });

  it("bakes an order of 3 chocolate + 1 strawberry into the top shelf, cookie by cookie", () => {
    const { store, run, done } = cell();
    expect(store.place("chocolate", 3)).toBe(true);
    expect(store.place("strawberry", 1)).toBe(true);
    expect(store.free()).toBe(8);
    expect(run(3600, done)).toBe(true);
    expect(store.model.rack).toMatchObject({ C1: CHOC, C2: CHOC, C3: CHOC, C4: STRAW });
    expect(Object.values(store.model.rack).filter((c) => c === RAW)).toHaveLength(8);
    expect(store.model.queue.map((o) => [o.flavour, o.done])).toEqual([["chocolate", 3], ["strawberry", 1]]);
  });

  it("refuses an order the rack cannot make", () => {
    const { store } = cell();
    expect(store.place("vanilla", 12)).toBe(true);
    expect(store.place("vanilla", 1)).toBe(false);
  });

  it("delivers the baked cookies and refills their moulds, once the cell is idle", () => {
    const { store, run, done } = cell();
    store.place("chocolate", 1);
    run(3600, done);
    store.deliver();
    run(0.5);
    expect(Object.values(store.model.rack).every((c) => c === RAW)).toBe(true);
    expect(store.model.delivered).toBe(1);
  });

  it("resets mid-cycle: twelve raw cookies, no orders, at rest, the saved state forgotten", () => {
    const { store, run, persistence } = cell();
    store.place("chocolate", 2);
    run(20);
    expect(store.model.idle).toBe(false);
    store.reset();
    run(0.5);
    expect(store.model.queue).toEqual([]);
    expect(Object.values(store.model.rack).every((c) => c === RAW)).toBe(true);
    expect(store.model.idle).toBe(true);
    expect(store.joints.out).toBeNull();
    expect(persistence.raw === null || !persistence.raw.includes("chocolate")).toBe(true);
  });
});

describe("persistence", () => {
  it("saves when the material state changes, not every frame", () => {
    const { store, run, done, persistence } = cell();
    store.place("chocolate", 1);
    expect(run(3600, done)).toBe(true);
    // place, the cycle's start and its end - a handful of saves over thousands of ticks
    expect(persistence.saves).toBeGreaterThanOrEqual(3);
    expect(persistence.saves).toBeLessThan(10);
    expect(JSON.parse(persistence.raw!).rack.C1).toBe(CHOC);
  });

  it("restores the rack and the orders after a reload, and resumes an unfinished order", () => {
    const first = cell();
    first.store.place("chocolate", 3);
    first.store.place("strawberry", 1);
    first.run(3600, () => first.store.model.queue[0].done === 2);    // closed mid-order
    const reloaded = cell(memoryPersistence(first.persistence.raw));
    expect(reloaded.store.model.rack).toMatchObject({ C1: CHOC, C2: CHOC });
    expect(reloaded.store.model.idle).toBe(false);                    // it carries on
    expect(reloaded.run(3600, reloaded.done)).toBe(true);
    expect(reloaded.store.model.rack).toMatchObject({ C1: CHOC, C2: CHOC, C3: CHOC, C4: STRAW });
  });

  it("ignores a saved state that does not fit this machine", () => {
    const { store } = cell(memoryPersistence(JSON.stringify({ rack: { Z9: "#000000" }, queue: [], seq: 0, delivered: 0 })));
    expect(Object.keys(store.model.rack)).toHaveLength(12);
  });
});

describe("the frame loop", () => {
  it("writes the joints in place: the same objects every tick", () => {
    const { store, run } = cell();
    const J = store.joints;
    const refs = [J.hbw, J.load, J.load.tint, J.load.tint.color, J.vgr, J.oven, J.workpiece, J.workpiece.pos, J.beams, J.camera];
    store.place("strawberry", 1);
    run(60);
    refs.forEach((r, i) => expect(r).toBe([J.hbw, J.load, J.load.tint, J.load.tint.color, J.vgr, J.oven, J.workpiece, J.workpiece.pos, J.beams, J.camera][i]));
  });

  it("tells panels about the moving joints at most TELEMETRY_HZ times a second", () => {
    const { store, run } = cell();
    store.place("chocolate", 1);
    let n = 0;
    const off = store.subscribe(() => n++);
    let model = 0;
    const offM = store.subscribeModel(() => model++);
    run(10);
    off(); offM();
    // 300 ticks in 10 s: the frame channel is throttled; model changes (captions) come through
    expect(n - model).toBeLessThanOrEqual(10 * TELEMETRY_HZ + 1);
    expect(n).toBeLessThan(300);
  });

  it("moves the crane continuously - no jump between frames", () => {
    const { store, run } = cell();
    run(1);                                   // at rest first: the order starts from the rest pose
    store.place("vanilla", 1);
    let prev = { ...store.joints.hbw }, worst = 0;
    for (let i = 0; i < 6000 && !(store.model.idle && store.model.queue[0].done); i++) {
      run(DT);
      const h = store.joints.hbw;
      worst = Math.max(worst, Math.abs(h.travel - prev.travel), Math.abs(h.lift - prev.lift), Math.abs(h.fork - prev.fork));
      prev = { ...h };
    }
    expect(worst).toBeLessThan(25);   // mm per 1/30 s
  });
});

describe("sensors", () => {
  it("the warehouse's light barriers see the mould on the belt", () => {
    const { store, run } = cell();
    store.place("chocolate", 1);
    const seen = new Set<string>();
    run(120, () => { for (const [k, v] of Object.entries(store.joints.beams)) if (v) seen.add(k); return false; });
    expect(seen.size).toBeGreaterThan(0);
  });

  it("the inspection camera fires once per cookie, with its flavour", () => {
    const { store, coord, run, done } = cell();
    const lens = [-230 + doc.factory.sort_placement.translate[0], 200 + doc.factory.sort_placement.translate[1]] as [number, number];
    coord.setCamera(lens);
    const shots: string[] = [];
    let pendingTicks = 0;
    store.onCapture((c) => shots.push(c.flavour));
    store.place("chocolate", 1);
    store.place("strawberry", 1);
    run(3600, () => { if (store.joints.camera.pending) pendingTicks++; return done(); });
    expect(shots).toEqual(["chocolate", "strawberry"]);
    expect(pendingTicks).toBe(2);                 // offered to the renderer for exactly one tick each
  });

  it("the camera still fires once per cookie at 20x playback, when a frame steps over the lens", () => {
    const { store, coord, run, done } = cell(memoryPersistence(), 20);
    const [tx, ty] = doc.factory.sort_placement.translate;
    coord.setCamera([-230 + tx, 200 + ty]);
    let shots = 0;
    store.onCapture(() => shots++);
    store.place("vanilla", 3);
    expect(run(3600, done)).toBe(true);
    expect(shots).toBe(3);
  });

  it("the camera photographs every cookie at one frame a second (a background window)", () => {
    for (const speed of [4, 8]) {
      const store = new CellStore();
      store.model.inspect.auto = false;
      const coord = new CellCoordinator(doc, store, { tours, persistence: memoryPersistence() });
      const [tx, ty] = doc.factory.sort_placement.translate;
      coord.setCamera([-230 + tx, 200 + ty]);
      let shots = 0;
      store.onCapture(() => shots++);
      store.place("chocolate", 1); store.place("vanilla", 1); store.place("strawberry", 1);
      let t = 0;
      while (t < 3600 && !(store.model.idle && store.model.queue.every((o) => o.done === o.qty))) { t += speed; coord.tick(t, 1); }
      expect(shots, `${speed}x`).toBe(3);
    }
  });

  it("the oven heats while it bakes and cools after", () => {
    const { store, run } = cell();
    store.place("chocolate", 1);
    let hottest = 0;
    run(3600, () => { hottest = Math.max(hottest, store.joints.oven.chamberC); return store.model.idle && store.model.queue[0].done === 1; });
    expect(hottest).toBeGreaterThan(100);
  });
});

describe("the inspection steers the line", () => {
  // the twin judges each photo (vision/inspect.ts); here the verdict is the simulation's truth
  const judgeByTruth = (store: CellStore) => store.onCapture((c) => store.decide({
    n: c.n, verdict: c.truth === "ok" ? "pass" : "reject", condition: c.truth, p: 0.99, flavour: c.flavour, ae: 0.3, anomaly: false,
  }));
  const lensOf = () => {
    const [tx, ty] = doc.factory.sort_placement.translate;
    return [-230 + tx, 200 + ty] as [number, number];
  };

  it("a rejected cookie is held at the end of the line, its mould is refilled with dough, and the order makes it again", () => {
    const { store, coord, run, done } = cell();
    coord.setCamera(lensOf());
    judgeByTruth(store);
    store.place("chocolate", 1);
    store.injectDefect("burnt");
    let ejectorFired = false, heldAtEnd = false;
    expect(run(3600, () => {
      const wp = store.joints.workpiece;
      // the burnt cookie, once the inspection has rejected it
      if (store.model.inspect.rejected && wp.visible && wp.defect === "burnt") {
        if (store.joints.sort.ejector >= 0 && store.joints.oven.eject > 0) ejectorFired = true;
        heldAtEnd = true;
      }
      return done();
    })).toBe(true);
    const rack = Object.values(store.model.rack);
    // the rejected cookie's mould came home empty and was refilled with dough at once:
    // no slot stands empty, and the order made its cookie again from the fresh dough
    expect(rack.filter((c) => c === null)).toHaveLength(0);
    expect(rack.filter((c) => c === CHOC)).toHaveLength(1);           // the one that passed
    expect(rack.filter((c) => c === RAW)).toHaveLength(11);
    expect(store.model.queue[0].done).toBe(1);
    expect(store.model.inspect).toMatchObject({ passed: 1, rejected: 1, next: null });
    expect(store.model.inspect.recent.map((r) => r.truth)).toEqual(["ok", "burnt"]);
    expect(ejectorFired).toBe(false);
    expect(heldAtEnd).toBe(true);
  });

  it("QC testing: in every 12 cookies started, exactly one gets a fault", () => {
    const { store, coord, run, done } = cell(memoryPersistence(), 8, true);
    coord.setCamera(lensOf());
    judgeByTruth(store);
    const truths: string[] = [];
    store.onCapture((c) => truths.push(c.truth));
    const records: { kind: string }[] = [];
    store.onRecord((r) => records.push(r));
    store.place("chocolate", 11);
    // the rejected cookie is made again: 11 good ones need 12 cookies, one rack's worth
    expect(run(12 * 3600, done)).toBe(true);
    expect(truths).toHaveLength(12);
    expect(truths.filter((t) => t !== "ok")).toHaveLength(1);
    expect(store.model.inspect).toMatchObject({ passed: 11, rejected: 1 });
    expect(store.model.queue[0].done).toBe(11);
    // what goes to the database: every judged cookie, and the finished line with its QC fault
    expect(records.filter((r) => r.kind === "inspection")).toHaveLength(12);
    expect(records.filter((r) => r.kind === "order")).toEqual([
      expect.objectContaining({ kind: "order", flavour: "chocolate", qty: 11, baked: 12, good: 11, scrap: 1 })]);
  });

  it("a good cookie passes to its Lagerstelle as before", () => {
    const { store, coord, run, done } = cell();
    coord.setCamera(lensOf());
    judgeByTruth(store);
    store.place("vanilla", 2);
    expect(run(3600, done)).toBe(true);
    expect(Object.values(store.model.rack).filter((c) => c === null)).toHaveLength(0);
    expect(store.model.inspect).toMatchObject({ passed: 2, rejected: 0 });
  });

  it("with no raw dough left, an order waits rather than take a baked cookie's slot", () => {
    const { store, coord, run } = cell();
    coord.setCamera(lensOf());
    store.model.dough = false;               // no automatic refill: a rejected mould stays empty
    store.onCapture((c) => store.decide({ n: c.n, verdict: "reject", condition: "burnt", p: 1, flavour: c.flavour, ae: 2, anomaly: true }));
    store.place("strawberry", 12);
    run(36000, () => store.model.idle && Object.values(store.model.rack).every((c) => c !== store.model.rawColour));
    expect(Object.values(store.model.rack).every((c) => c === null)).toBe(true);   // all rejected
    expect(store.model.queue[0].done).toBe(0);
    expect(store.model.idle).toBe(true);
  });
});

describe("the pipeline", () => {
  it("twelve cookies are in the factory at every tick: every slot always holds one", () => {
    const { store, run, done } = cell();
    store.place("chocolate", 4);
    let ticks = 0;
    expect(run(3600, () => {
      ticks++;
      const rack = Object.values(store.model.rack);
      expect(rack).toHaveLength(12);
      expect(rack.every((c) => c !== null)).toBe(true);   // raw, cooking or cooked - never empty
      return done();
    })).toBe(true);
    expect(ticks).toBeGreaterThan(1000);
    expect(Object.values(store.model.rack).filter((c) => c === CHOC)).toHaveLength(4);
  });

  it("the crane and the VGR work on different cookies at the same time", () => {
    const { store, coord, run, done } = cell();
    store.place("chocolate", 4);
    expect(run(3600, done)).toBe(true);
    // hundreds of ticks per order where the crane served one cookie while the VGR served another
    expect(coord.overlapped).toBeGreaterThan(500);
  });
});


describe("fast-forward: nothing teleports", () => {
  const lens = () => {
    const [tx, ty] = doc.factory.sort_placement.translate;
    return [-230 + tx, 200 + ty] as [number, number];
  };
  // the fastest any joint may move, in twin time: the scripted rate at the easing's peak (1.5x)
  const AXIS = SPEED * RATE * 1.5 * 1.01;        // mm/s - crane and VGR spindles
  const SWIVEL = AXIS / 2;                       // deg/s - the swivel is timed at 2 mm per degree
  const BELT = BELT_SPEED * RATE * 1.5 * 1.01;   // mm/s - the warehouse belt
  const COOKIE = 400;                            // mm/s - the workpiece on the oven / sorting line

  /** Drive the twin at 60 fps through `rates` (one every 5 s of wall time), the inspection's
      verdict arriving `lagFrames` after each photo; returns the fastest move of each joint. */
  function drive(rates: number[], lagFrames: number, verdictOf: (n: number) => "pass" | "reject") {
    const store = new CellStore();
    store.model.inspect.auto = false;
    const coord = new CellCoordinator(doc, store, { tours, persistence: memoryPersistence() });
    coord.setCamera(lens());
    const due: [number, number][] = [];
    store.onCapture((c) => due.push([c.n, lagFrames]));
    store.place("chocolate", 2);
    store.place("vanilla", 1);
    const J = store.joints, w = J.workpiece;
    const fast: Record<string, number> = {};
    const ejectedRejects: number[] = [];
    let held = false;
    let prev: number[] | null = null, seed = -1, vis = false, frames = 0;
    const done = () => store.model.idle && store.model.queue.every((o) => o.done === o.qty);
    for (let fr = 0; fr < 60 * 3600 && !(fr > 10 && done()); fr++) {
      const rate = rates[Math.floor(fr / 300) % rates.length];
      for (const d of due) if (d[1]-- === 0) store.decide({ n: d[0], verdict: verdictOf(d[0]), condition: "", p: 1, flavour: "", ae: 0, anomaly: false });
      coord.advance(1 / 60, rate);
      if (store.model.step.includes("holds at the colour lock")) held = true;
      if (w.visible && J.oven.eject > 0 && verdictOf(w.seed) === "reject") ejectedRejects.push(w.seed);
      const cur = [J.hbw.travel, J.hbw.lift, J.hbw.fork, J.hbw.belt, J.vgr.swivel, J.vgr.reach, J.vgr.plunge, w.pos[0], w.pos[1], w.pos[2]];
      // the first frame leaves the store's zero pose; a new cookie's flow is another workpiece
      if (prev && fr > 1 && w.seed === seed && w.visible === vis) {
        ["travel", "lift", "fork", "belt", "swivel", "reach", "plunge", "x", "y", "z"].forEach((k, i) => {
          if (i >= 7 && !w.visible) return;
          fast[k] = Math.max(fast[k] ?? 0, Math.abs(cur[i] - prev![i]) / (rate / 60));
        });
      }
      prev = cur; seed = w.seed; vis = w.visible; frames = fr;
    }
    return { store, fast, held, ejectedRejects, frames, done: done() };
  }
  const limits = (fast: Record<string, number>) => {
    for (const k of ["travel", "lift", "fork", "reach", "plunge"]) expect(fast[k], k).toBeLessThanOrEqual(AXIS);
    expect(fast.swivel).toBeLessThanOrEqual(SWIVEL);
    expect(fast.belt).toBeLessThanOrEqual(BELT);
    for (const k of ["x", "y", "z"]) expect(fast[k], k).toBeLessThanOrEqual(COOKIE);
  };

  it("switching between 1x, 8x, 2x and 4x mid-order moves every joint at its own speed - no jumps", () => {
    const r = drive([1, 8, 2, 4, 8, 1], 0, () => "pass");
    expect(r.done).toBe(true);
    limits(r.fast);
  });

  it("the crane and VGR reposition between pipelined cookies instead of jumping, at every speed", () => {
    for (const rate of [1, 2, 4, 8]) {
      const r = drive([rate], 0, () => "pass");
      expect(r.done, `${rate}x`).toBe(true);
      limits(r.fast);
    }
  });

  it("at 8x a slow verdict holds the belt at the colour lock: a rejected cookie is never ejected or moved back", () => {
    // 1.5 s of wall time to judge each photo - at 8x that is 12 s of the line
    const r = drive([8], 90, (n) => (n === 1 ? "reject" : "pass"));
    expect(r.done).toBe(true);
    expect(r.held).toBe(true);
    expect(r.ejectedRejects).toEqual([]);
    expect(r.store.model.inspect).toMatchObject({ passed: 3, rejected: 1 });
    limits(r.fast);
  });

  it("with no verdict at all the line waits VERDICT_WAIT_S, then the cookie goes on un-inspected", () => {
    const r = drive([4], Number.POSITIVE_INFINITY, () => "pass");
    expect(r.done).toBe(true);
    expect(r.held).toBe(true);
    expect(r.store.model.inspect).toMatchObject({ passed: 0, rejected: 0 });
    // three cookies, each held about VERDICT_WAIT_S of wall time
    expect(VERDICT_WAIT_S).toBeGreaterThan(1);
  });

  it("a stalled frame (a background tab) pauses the twin instead of jumping it ahead", () => {
    const store = new CellStore();
    const coord = new CellCoordinator(doc, store, { tours, persistence: memoryPersistence() });
    store.place("chocolate", 1);
    coord.advance(1 / 60, 8);
    const before = store.model.cycle.t;
    coord.advance(30, 8);            // 30 s away: counts as one 1 s frame
    expect(store.model.cycle.t - before).toBeLessThanOrEqual(8 + 1e-9);
  });
});
