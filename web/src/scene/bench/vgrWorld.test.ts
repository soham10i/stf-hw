import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import RAPIER from "@dimforge/rapier3d-deterministic-compat";
import { beforeAll, describe, expect, it } from "vitest";

import type { CadDoc } from "../../shared/model";
import { PhysicsCore } from "../../workers/physicsCore";
import { PULSES_PER_REV, SWIVEL_DEG_PER_REV, vgrWorld, type VgrAxis } from "./vgrWorld";

const DOC = JSON.parse(readFileSync(resolve(__dirname, "../../../public/hbw_parts_up12.json"), "utf8")) as CadDoc;
beforeAll(async () => { await RAPIER.init(); });

const build = (powerUp: Partial<Record<VgrAxis, number>> = {}) => {
  const w = vgrWorld(DOC, powerUp);
  return { w, core: PhysicsCore.create(RAPIER, w.init) };
};
const settle = (core: PhysicsCore, ids: string[], max = 8000) => {
  let n = 0;
  for (; n < max; n++) {
    core.stepOnce();
    if (ids.every((id) => {
      const a = core.axis(id)!;
      return a.task.kind === "done" && a.rpm === 0 && (a.task.target === null || a.task.error !== null);
    })) break;
  }
  return n;
};
const homeAll = (core: PhysicsCore) => {
  for (const id of ["plunge", "reach", "swivel"]) core.enqueue({ type: "axis", id, command: { kind: "home" } });
  return settle(core, ["plunge", "reach", "swivel"]);
};

describe("the gripper's axes from the CAD export", () => {
  it("builds the R-P-P chain with the cup 168 mm out from the tower at reach 0", () => {
    const { w, core } = build({ swivel: 0, reach: 0 });
    expect(core.axisCount).toBe(3);
    expect(core.pins.map((p) => p.instance_id)).toEqual(["I3", "I1", "I2"]);
    const cup = core.pose("vgr_cup")!.p;
    const [cx, cy] = [w.placement.p[0] + DOC.vgr.centre[0], w.placement.p[1] + DOC.vgr.centre[1]];
    expect(cup[0] - cx).toBeCloseTo(0, 9);
    expect(cup[1] - cy).toBeCloseTo(-168, 9);
  });

  it("homes all three: plunge up to I1, reach back to I2, swivel counter-clockwise onto I3", () => {
    const { core } = build();
    const steps = homeAll(core);
    for (const id of ["swivel", "plunge", "reach"]) {
      expect(core.axis(id)!.homed).toBe(true);
      expect(core.axis(id)!.crashes).toBe(0);
    }
    // one 10 ms scan at 14 mm/s past the switch, and the coast: under a quarter of a millimetre
    expect(core.axis("plunge")!.position - 540).toBeLessThan(0.25);
    expect(core.axis("reach")!.position).toBeGreaterThan(-0.2);
    // the slow second approach: under one count (0.224 deg) past the cam's edge
    expect(core.axis("swivel")!.position).toBeLessThan(0.224);
    expect(core.axis("swivel")!.position).toBeGreaterThanOrEqual(0);
    // the slowest: the plunge's 240 mm at 14.27 mm/s, a little less against the weight
    expect(steps * 0.01).toBeGreaterThan(240 / 14.27);
    expect(steps * 0.01).toBeLessThan(240 / 13);
  });

  it("homes the swivel from the wrong side of its cam: off it first, then back onto it", () => {
    const { core } = build({ swivel: 60 });
    expect(core.axis("swivel")!.closed[0]).toBe(true); // the cam holds I3 closed above 0
    core.enqueue({ type: "axis", id: "swivel", command: { kind: "home" } });
    let peak = Infinity;
    for (let i = 0; i < 4000; i++) {
      core.stepOnce();
      peak = Math.min(peak, core.axis("swivel")!.position);
      if (core.axis("swivel")!.homed && core.axis("swivel")!.rpm === 0) break;
    }
    const a = core.axis("swivel")!;
    expect(a.homed).toBe(true);
    expect(peak).toBeLessThan(-0.5); // it went past the switch's differential travel
    expect(a.position).toBeGreaterThanOrEqual(0);
    expect(a.position).toBeLessThan(0.224);
  });

  it("puts the cup on the belt's hand-over point within its encoders' resolution", () => {
    const { w, core } = build();
    homeAll(core);
    const st = w.stations.belt;
    core.enqueue({ type: "axis", id: "swivel", command: { kind: "move", target: st.swivel } });
    core.enqueue({ type: "axis", id: "reach", command: { kind: "move", target: st.reach } });
    const n = settle(core, ["swivel", "reach"]);
    core.stepOnce(); // the kinematic bodies arrive a step after the joints
    const cup = core.pose("vgr_cup")!.p;
    const off = Math.hypot(cup[0] - st.target[0], cup[1] - st.target[1]);
    // one swivel count at 404.9 mm from the tower: 0.224 deg = 1.58 mm; one reach count 0.053 mm
    const swivelCount = ((SWIVEL_DEG_PER_REV / PULSES_PER_REV) * Math.PI / 180) * 404.857;
    // the PLC stops within two counts (a 10 ms scan is 2.7 counts of travel at full speed), and
    // the homing zero sits up to one creep scan (0.14 deg) past the cam's edge
    expect(Math.abs((core.axis("swivel")!.task as { error: number }).error)).toBeLessThanOrEqual(2);
    expect(off).toBeLessThan(2.7 * swivelCount);
    // the swing: 69 deg at 60 deg/s; the reach: 237 mm at 14.27 mm/s - the reach is the slower
    expect(n * 0.01).toBeCloseTo(236.857 / 14.27, 0);
  });

  it("stops every move within two encoder counts, most within one (24 targets)", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "swivel", command: { kind: "home" } });
    settle(core, ["swivel"]);
    const errs: number[] = [];
    for (let i = 0; i < 24; i++) {
      core.enqueue({ type: "axis", id: "swivel", command: { kind: "move", target: 10 + i * 4.37 } });
      settle(core, ["swivel"]);
      errs.push((core.axis("swivel")!.task as { error: number }).error);
    }
    expect(Math.max(...errs.map(Math.abs))).toBeLessThanOrEqual(2);
    expect(errs.filter((e) => Math.abs(e) <= 1).length / errs.length).toBeGreaterThanOrEqual(0.75);
  });

  it("lowers the plunge faster than it raises it, against the arm's weight", () => {
    const { core } = build();
    core.enqueue({ type: "axis", id: "plunge", command: { kind: "jog", dir: -1 } });
    for (let i = 0; i < 50; i++) core.stepOnce();
    const down = -core.axis("plunge")!.rpm;
    core.enqueue({ type: "axis", id: "plunge", command: { kind: "jog", dir: 1 } });
    for (let i = 0; i < 50; i++) core.stepOnce();
    const up = core.axis("plunge")!.rpm;
    expect(up).toBeLessThan(down);
  });

  it("is deterministic", () => {
    const run = () => {
      const { core } = build();
      homeAll(core);
      core.enqueue({ type: "axis", id: "swivel", command: { kind: "move", target: 69.013 } });
      for (let i = 0; i < 500; i++) core.stepOnce();
      return core.stateHash();
    };
    expect(run()).toBe(run());
  });
});
