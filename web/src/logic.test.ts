// Unit tests for the logic the pages are built on: chart ticks, the health model, the degradation
// simulation, the part-size accessors, the rolling mean, the copilot's search and its refusal
// to guess, and the renderer's seeded random numbers.   npm test
import { describe, expect, it } from "vitest";
import { fmtNum, niceTicks } from "./dashboard/Plot";
import { roll } from "./dashboard/Month";
import { compAt } from "./shared/health";
import { DegradeSim, wear, type Law } from "./shared/degrade";
import { boxSize, cylSpec, type HealthComp } from "./shared/model";
import { Bm25, answer, tokens, type Ctx } from "./copilot/copilot";
import { Rng } from "./vision/render";
import { clean, cleanDeep } from "./shared/names";
import cases from "./shared/names_cases.json";

describe("chart axes", () => {
  it("niceTicks covers the range with 1-2-5 steps", () => {
    expect(niceTicks(0, 100, 5)).toEqual([0, 20, 40, 60, 80, 100]);
    expect(niceTicks(0, 1, 4)).toEqual([0, 0.25, 0.5, 0.75, 1]);
    const t = niceTicks(3.2, 47.9, 5);
    expect(t[0]).toBeGreaterThanOrEqual(3.2);
    expect(t[t.length - 1]).toBeLessThanOrEqual(47.9);
  });
  it("niceTicks of an empty range is one tick", () => {
    expect(niceTicks(5, 5)).toEqual([5]);
  });
  it("fmtNum shortens large numbers and keeps small ones precise", () => {
    expect(fmtNum(150000)).toBe("150k");
    expect(fmtNum(2500)).toBe("2.5k");
    expect(fmtNum(0.256)).toBe("0.26");
  });
});

describe("rolling mean", () => {
  it("averages the last n values and skips gaps", () => {
    expect(roll([1, 2, 3, 4], 2)).toEqual([1, 1.5, 2.5, 3.5]);
    expect(roll([2, null, 4], 3)).toEqual([2, 2, 3]);
  });
});

// a part that warns at 800 uses and fails at 1000, 100 uses per shift
const comp = {
  id: "x", name: "test part", per_shift: 100, warn: 800, fail: 1000, life: 1000,
  curve: [[0, 1, 100, null], [500, 1.2, 80, 500], [800, 1.6, 50, 200], [1000, 2, 0, 0]],
} as unknown as HealthComp;

describe("health model", () => {
  it("is healthy, then warned, then failed as the part ages", () => {
    expect(compAt(comp, 5).status).toBe("ok");
    expect(compAt(comp, 9).status).toBe("warn");
    expect(compAt(comp, 11).status).toBe("fail");
    expect(compAt(comp, 11).hi).toBe(0);
  });
  it("gives the remaining life in shifts", () => {
    expect(compAt(comp, 5).rulShifts).toBe(5);
  });
  it("with PM the part is renewed at each warning and never fails", () => {
    const s = compAt(comp, 30, true);
    expect(s.serviced).toBe(3);
    expect(s.status).toBe("ok");
    expect(s.n).toBe(600);
  });
});

const law: Law = {
  id: "t", p: 2, life: 4000, r_fail: 2, sigma: 0.02, per_shift: 100, rul_warn: 300,
  sigma_z: 0, soft_margin_sigma: 0, trend_margin_sigma: 0, n_soft_theory: 0, warn_sim: null, warn_by: null, fail_sim: null, lead_shifts: null,
};
describe("degradation simulation", () => {
  it("the wear law runs from 1 when new to r_f at the end of life", () => {
    expect(wear(law, 0)).toBe(1);
    expect(wear(law, law.life)).toBe(law.r_fail);
  });
  it("a wearing part warns before it fails", () => {
    const sim = new DegradeSim(law, { lambda: 0.02, soft: 0.5, window: 400, noise: 1, degrade: true, seed: 1 });
    while (!sim.done) sim.step(500);
    expect(sim.warn).not.toBeNull();
    expect(sim.fail).not.toBeNull();
    expect(sim.warn!.n).toBeLessThan(sim.fail!);
  });
  it("a healthy part never warns", () => {
    const sim = new DegradeSim(law, { lambda: 0.02, soft: 0.5, window: 400, noise: 1, degrade: false, seed: 1 });
    while (!sim.done) sim.step(500);
    expect(sim.warn).toBeNull();
    expect(sim.fail).toBeNull();
  });
});

describe("part sizes", () => {
  it("reads a box's size and a cylinder's spec, and refuses the wrong kind", () => {
    expect(boxSize({ n: "b", k: "box", s: [1, 2, 3] })).toEqual([1, 2, 3]);
    expect(cylSpec({ n: "c", k: "cyl", s: ["z", 10, 4] })).toEqual(["z", 10, 4]);
    expect(() => boxSize({ n: "c", k: "cyl", s: ["z", 10, 4] })).toThrow(/not a box/);
    expect(() => cylSpec({ n: "b", k: "box", s: [1, 2, 3] })).toThrow(/not a cylinder/);
  });
});

const passages = [
  { id: 0, doc: "UPGRADE_PLAN", path: ["Upgrade 9", "Ride-through"], text: "The battery keeps a ride-through reserve of 30 percent for mains outages." },
  { id: 1, doc: "SECURITY", path: ["Zones"], text: "Zones and conduits follow IEC 62443; every conduit has an allow-list." },
];
// the score threshold is set for the real knowledge base (~200 passages): pad the corpus so word
// frequencies are realistic
const filler = Array.from({ length: 40 }, (_, i) => ({ id: 100 + i, doc: "OTHER", path: [`part ${i}`],
  text: `the crane moves mould ${i} along the belt to the oven and the gripper, a cycle of the factory` }));
const corpus = [...passages, ...filler];
describe("copilot", () => {
  it("tokens drop stop words and plurals", () => {
    expect(tokens("What are the zones of the cell?")).toEqual(["zone", "cell"]);
  });
  it("BM25 ranks the passage that matches", () => {
    const hits = new Bm25(passages).search("ride-through reserve", 2);
    expect(hits[0].p.id).toBe(0);
  });
  it("says it does not know instead of guessing", async () => {
    const ctx: Ctx = { age: 0, pm: true, get: async <T,>() => ({ passages: corpus }) as T };
    const a = await answer("what is the price of bitcoin", ctx);
    expect(a.tool).toBe("none");
  });
  it("answers a covered question from the documents, with its source", async () => {
    const ctx: Ctx = { age: 0, pm: true, get: async <T,>() => ({ passages: corpus }) as T };
    const a = await answer("how big is the ride-through reserve", ctx);
    expect(a.tool).toBe("documents");
    expect(a.sources[0]).toContain("UPGRADE_PLAN");
  });
});

describe("renderer random numbers", () => {
  it("are the same for the same seed", () => {
    const a = new Rng(7), b = new Rng(7);
    expect([a.random(), a.normal(), a.u(2, 3)]).toEqual([b.random(), b.normal(), b.u(2, 3)]);
  });
});

describe("feature names instead of design-step numbers", () => {
  it("rewrites references and keeps sheet ids and encoded data", () => {
    expect(clean("force-guided contactor K1 (Upgrade 2)")).toBe("force-guided contactor K1");
    expect(clean("Upgrade 1 - central air, cookie buffer, stiff members")).toBe("Central air, cookie buffer, stiff members");
    expect(clean("carries the door cylinder - 20x20 aluminium profile (Upgrade 1: sag check)")).toBe("carries the door cylinder - 20x20 aluminium profile (sag check)");
    expect(clean("+ the VGR parks raw cookies in Upgrade 1's buffer while the oven is busy")).toBe("+ the VGR parks raw cookies in the buffer while the oven is busy");
    expect(clean("U6 warning: HBW belt")).toBe("Condition monitoring warning: HBW belt");
    expect(clean("travel stop (U5 accuracy)")).toBe("travel stop (accuracy)");
    expect(clean("on the I/O and the standards (U11-U12) here")).toBe("on the I/O and the standards here");
    expect(clean("Upgrade 12 interlock relay IL1: coil")).toBe("interlock relay IL1: coil".replace(/^i/, "I"));
    expect(clean("Guarding layout U2-02")).toBe("Guarding layout U2-02");
    expect(clean("STF-U12")).toBe("STF-01");
    expect(clean("stf-hw/virtual-site/bakery/line-1/cell-u12/hbw/inputs/hbw_I1_long_long_long_topic")).toBe("stf-hw/virtual-site/bakery/line-1/cell-01/hbw/inputs/hbw_I1_long_long_long_topic");
    expect(clean("Upgrades 5 and 7.")).toBe("Commissioning and lifecycle design.");
  });
  it("agrees with the Python cleaner on the shared cases", () => {
    for (const [inp, out] of cases as [string, string][]) expect(clean(inp)).toBe(out);
  });
  it("cleans values, not keys", () => {
    expect(cleanDeep({ U9: { what: "before (U9)" } })).toEqual({ U9: { what: "before" } });
  });
});
