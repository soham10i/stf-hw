import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import RAPIER from "@dimforge/rapier3d-deterministic-compat";
import { beforeAll, describe, expect, it } from "vitest";

import type { CadDoc } from "../../shared/model";
import { PhysicsCore } from "../../workers/physicsCore";
import { BELT_MM_S, mouldAt, warehouseWorld } from "./warehouseWorld";

const DOC = JSON.parse(readFileSync(resolve(__dirname, "../../../public/hbw_parts_up12.json"), "utf8")) as CadDoc;
beforeAll(async () => { await RAPIER.init(); });

const build = () => {
  const w = warehouseWorld(DOC, { travel: 430, lift: 210, fork: 30 });
  return { w, core: PhysicsCore.create(RAPIER, w.init) };
};
/** steps until the axis's task is done and it has stopped (or the limit) */
const settle = (core: PhysicsCore, id: string, max = 6000) => {
  let n = 0;
  for (; n < max; n++) {
    core.stepOnce();
    const a = core.axis(id)!;
    if (a.task.kind === "done" && a.rpm === 0 && (a.task.target === null || a.task.error !== null)) break;
  }
  return n;
};

describe("the warehouse axes from the CAD export", () => {
  it("builds four motor axes, their four switches and the belt's two light barriers", () => {
    const { core } = build();
    expect(core.axisCount).toBe(4);
    expect(core.pins.map((p) => p.instance_id)).toEqual(["I1", "I4", "I5", "I6", "I2", "I3"]);
    expect(core.axis("travel")!.position).toBe(430);
  });

  it("homes the travel axis to I1 at the lab's 14.27 mm/s and zeroes its count there", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "travel", command: { kind: "home" } });
    const steps = settle(core, "travel");
    const a = core.axis("travel")!;
    expect(steps * 0.01).toBeCloseTo((665 - 430) / 14.27, 0); // ~16.5 s
    expect(a.homed).toBe(true);
    expect(a.closed[0]).toBe(true);
    expect(core.pinVolts[0]).toBe(24); // I1's pin
    expect(a.position).toBeGreaterThanOrEqual(665); // it coasts past the switch's point...
    expect(a.position - 665).toBeLessThan(0.2); // ...a fraction of a millimetre
    expect(a.crashes).toBe(0);
    expect(Math.abs(a.count)).toBeLessThanOrEqual(3); // the count the PLC reads, from 0 at the switch
  });

  it("positions the travel axis to a bay within one encoder count", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "travel", command: { kind: "home" } });
    settle(core, "travel");
    core.enqueue({ type: "axis", id: "travel", command: { kind: "move", target: 240 } }); // bay 2
    const steps = settle(core, "travel");
    const a = core.axis("travel")!;
    expect(steps * 0.01).toBeCloseTo((665 - 240) / 14.27, 0); // ~29.8 s
    // what the PLC sees: within one encoder count (1 / 18.75 mm)
    expect(Math.abs(a.lastError)).toBeLessThanOrEqual(1 / 18.75 + 1e-9);
    // where it really is also carries the homing offset: the count was zeroed a scan after the
    // switch closed, while the axis coasted on - about a tenth of a millimetre, as on the machine
    expect(Math.abs(a.position - 240)).toBeLessThan(0.2);
  });

  it("stops every move within two encoder counts, most within one (24 targets)", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "travel", command: { kind: "home" } });
    settle(core, "travel");
    const errs: number[] = [];
    for (let i = 0; i < 24; i++) {
      core.enqueue({ type: "axis", id: "travel", command: { kind: "move", target: 640 - i * 21.3 } });
      settle(core, "travel");
      errs.push((core.axis("travel")!.task as { error: number }).error);
    }
    // a 10 ms scan is 2.7 counts of travel at 14.27 mm/s: where the PLC switches off spreads
    expect(Math.max(...errs.map(Math.abs))).toBeLessThanOrEqual(2);
    expect(errs.filter((e) => Math.abs(e) <= 1).length / errs.length).toBeGreaterThanOrEqual(0.75);
  });

  it("lifts against the carriage's weight a little slower than it lowers, and positions", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "lift", command: { kind: "home" } }); // up to I4 at the top
    for (let i = 0; i < 50; i++) core.stepOnce();
    const up = core.axis("lift")!.rpm;
    settle(core, "lift");
    expect(core.axis("lift")!.homed).toBe(true);
    core.enqueue({ type: "axis", id: "lift", command: { kind: "move", target: 120 } }); // row A, down
    for (let i = 0; i < 50; i++) core.stepOnce();
    const down = -core.axis("lift")!.rpm;
    settle(core, "lift");
    expect(up).toBeLessThan(down);
    expect(Math.abs(core.axis("lift")!.lastError)).toBeLessThanOrEqual(1 / 18.75 + 1e-9);
    expect(Math.abs(core.axis("lift")!.position - 120)).toBeLessThan(0.2);
  });

  it("drives the fork, which has no encoder, by its switches", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "fork", command: { kind: "until", dir: 1, switch: 1 } }); // to I5, front
    settle(core, "fork");
    expect(core.axis("fork")!.position).toBeGreaterThanOrEqual(115);
    expect(core.axis("fork")!.closed[2]).toBe(true);
    core.enqueue({ type: "axis", id: "fork", command: { kind: "until", dir: -1, switch: 0 } }); // to I6, back
    settle(core, "fork");
    expect(core.axis("fork")!.position).toBeLessThanOrEqual(0);
    expect(core.axis("fork")!.position).toBeGreaterThan(-0.2);
  });

  it("refuses to position before homing, and a jog past the switch crashes into the end", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "travel", command: { kind: "move", target: 240 } });
    expect(() => core.flush()).toThrow(/not homed/);
    core.enqueue({ type: "axis", id: "travel", command: { kind: "jog", dir: 1 } });
    for (let i = 0; i < 2000; i++) core.stepOnce();
    const a = core.axis("travel")!;
    expect(a.crashes).toBe(1);
    expect(a.position).toBe(668); // the mechanism's end, 3 mm past the switch
    expect(a.task.kind).toBe("idle"); // the crash stopped the block
  });

  it("runs the belt at 50 mm/s on its S-motor, and stops a mould at the far light barrier", () => {
    const { w, core } = build();
    core.enqueue({ type: "spawn", part: mouldAt(w, 1), role: { kind: "dynamic", friction: 0.5 } });
    for (let i = 0; i < 30; i++) core.stepOnce(); // let it settle on the belt
    const p0 = core.pose("mould_1")!.p;
    expect(Math.hypot(p0[0] - w.handover[0], p0[1] - w.handover[1])).toBeLessThan(0.5); // it lies where it was set
    core.enqueue({ type: "axis", id: "belt", command: { kind: "until", dir: 1, switch: 1 } }); // -> I3
    for (let i = 0; i < 100; i++) core.stepOnce();
    expect(core.axis("belt")!.rpm * Math.PI * 20 / 60).toBeCloseTo(BELT_MM_S, 6); // surface speed
    const n = settle(core, "belt");
    const a = core.axis("belt")!;
    expect(a.task.kind).toBe("done");
    expect(core.pinVolts[w.switchPin.I3]).toBe(24); // the mould is in the beam
    // from the hand-over (y 350) until its front edge (+32) cuts the beam's near edge (578):
    // 196 mm, and it coasts a little with the belt as the motor brakes
    const travelled = Math.hypot(...core.pose("mould_1")!.p.map((v, i) => v - w.handover[i]));
    expect(travelled).toBeGreaterThan(196);
    expect(travelled).toBeLessThan(198);
    expect((n + 100) * 0.01).toBeCloseTo(196 / BELT_MM_S, 0); // ~3.9 s
    // and back to the crane's light barrier
    core.enqueue({ type: "axis", id: "belt", command: { kind: "until", dir: -1, switch: 0 } });
    settle(core, "belt");
    expect(core.pinVolts[w.switchPin.I2]).toBe(24);
    expect(core.pinVolts[w.switchPin.I3]).toBe(0);
  });

  it("refuses a belt speed for a motor-driven belt, and a home for the belt", () => {
    const { core } = build();
    core.enqueue({ type: "conveyor", instance_id: "hbw_belt", speed_mm_s: 40 });
    expect(() => core.flush()).toThrow(/driven by its motor/);
    core.enqueue({ type: "axis", id: "belt", command: { kind: "home" } });
    expect(() => core.flush()).toThrow(/no reference/);
  });

  it("is deterministic", () => {
    const run = () => {
      const { core } = build();
      core.enqueue({ type: "axis", id: "travel", command: { kind: "home" } });
      core.enqueue({ type: "axis", id: "lift", command: { kind: "home" } });
      for (let i = 0; i < 1800; i++) core.stepOnce();
      return core.stateHash();
    };
    expect(run()).toBe(run());
  });
});
