// U-B: jerk-limited (S-curve) drives - the roadmap's acceptance: the jerk is bounded by jmax at
// every step, the move time matches the closed-form S-curve time within one step, and a drive
// without a jerk limit is the trapezoid it was.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import RAPIER from "@dimforge/rapier3d-deterministic-compat";
import { beforeAll, describe, expect, it } from "vitest";

import type { CadDoc } from "../shared/model";
import { PUSHER, sortingWorld } from "../scene/bench/sortingWorld";
import { PhysicsCore, sCurveStep } from "./physicsCore";
import { planMove, sampleMove } from "./scurve";

const DT = 0.01;
const DOC = JSON.parse(readFileSync(resolve(__dirname, "../../public/hbw_parts_up12.json"), "utf8")) as CadDoc;

beforeAll(async () => {
  await RAPIER.init();
});

type Drive = Parameters<typeof sCurveStep>[0];
const drive = (vmax: number, amax: number, jmax: number, start = 0): Drive =>
  ({ pos: start, vel: 0, acc: 0, target: start, move: null, moveT: 0, cfg: { vmax, amax, jmax } });

/** Run a drive to rest on its target; every step's state. */
function run(d: Drive, target: number, maxSteps = 100000) {
  d.target = target;
  const states: { pos: number; vel: number; acc: number }[] = [{ pos: d.pos, vel: d.vel, acc: d.acc }];
  for (let i = 0; i < maxSteps; i++) {
    sCurveStep(d, DT);
    states.push({ pos: d.pos, vel: d.vel, acc: d.acc });
    if (d.pos === d.target && !d.move) break;
  }
  return states;
}

// a servo axis (mm): 200 mm/s, 1000 mm/s^2, 20000 mm/s^3 - reaches amax in 50 ms
const V = 200, A = 1000, J = 20000;

describe("seven-segment S-curve", () => {
  it.each([
    ["long: cruises at vmax", 300],
    ["medium: reaches amax, not vmax", 40],
    ["short: reaches neither", 1.5],
  ])("%s - jerk, acceleration and speed stay within their limits, landing exactly", (_, D) => {
    const s = run(drive(V, A, J), D);
    for (let k = 1; k < s.length; k++) {
      expect(Math.abs(s[k].acc - s[k - 1].acc) / DT).toBeLessThanOrEqual(J * (1 + 1e-9));
      expect(Math.abs(s[k].acc)).toBeLessThanOrEqual(A * (1 + 1e-9));
      expect(Math.abs(s[k].vel)).toBeLessThanOrEqual(V * (1 + 1e-9));
      expect(s[k].pos).toBeGreaterThanOrEqual(s[k - 1].pos - 1e-12);   // never backs up
      expect(s[k].pos).toBeLessThanOrEqual(D + 1e-12);                 // never overshoots
    }
    const end = s[s.length - 1];
    expect(end).toEqual({ pos: D, vel: 0, acc: 0 });
  });

  it("takes the closed-form time, to within one step", () => {
    // with a cruise and amax reached: T = D/V + V/A + A/J
    const D = 300;
    const T = D / V + V / A + A / J;
    expect(planMove(0, D, V, A, J).T).toBeCloseTo(T, 9);
    expect(Math.abs(run(drive(V, A, J), D).length - 1 - T / DT)).toBeLessThanOrEqual(1);
    // reaching neither: four jerk phases of t = (D / 2J)^(1/3)
    const d = 1.5, tj = Math.cbrt(d / (2 * J));
    expect(planMove(0, d, V, A, J).T).toBeCloseTo(4 * tj, 9);
    expect(Math.abs(run(drive(V, A, J), d).length - 1 - (4 * tj) / DT)).toBeLessThanOrEqual(1);
  });

  it("runs backwards just the same, and samples the plan in closed form", () => {
    const m = planMove(50, -250, V, A, J);
    const out: [number, number, number] = [0, 0, 0];
    expect(sampleMove(m, m.T / 2, out)[0]).toBeCloseTo(-100, 9);   // symmetric: halfway at half time
    expect(out[1]).toBeCloseTo(-V, 9);
    expect(sampleMove(m, m.T + 1, out)).toEqual([-250, 0, 0]);
  });

  it("a target changed during a move is taken up once that move has stopped (buffered)", () => {
    const d = drive(V, A, J);
    d.target = 100;
    for (let i = 0; i < 20; i++) sCurveStep(d, DT);
    const s = run(d, 20);     // ask for 20 while heading for 100
    expect(Math.max(...s.map((x) => x.pos))).toBeCloseTo(100, 9);
    expect(s[s.length - 1]).toEqual({ pos: 20, vel: 0, acc: 0 });
    for (let k = 1; k < s.length; k++) expect(Math.abs(s[k].acc - s[k - 1].acc) / DT).toBeLessThanOrEqual(J * (1 + 1e-9));
  });
});

describe("drives in the physics core", () => {
  it("a pusher given a jerk limit strokes on an S-curve; without one it is the trapezoid it was", () => {
    const strokes: Record<string, number[]> = {};
    for (const jmax of [0, 2e6]) {
      const w = sortingWorld(DOC);
      w.init.drives = w.init.drives!.map((d) => ({ ...d, jmax }));
      const core = PhysicsCore.create(RAPIER, w.init);
      core.enqueue({ type: "pulse", joint: w.pusherJoint.weiss, value: PUSHER.stroke_mm, hold_s: 0.1 });
      const pos: number[] = [];
      for (let i = 0; i < 60; i++) { core.stepOnce(); pos.push(core.drive(w.pusherJoint.weiss)!.pos); }
      strokes[jmax] = pos;
      core.dispose();
    }
    const out = strokes[0], s = strokes[2e6];
    expect(Math.max(...out)).toBe(PUSHER.stroke_mm);
    expect(Math.max(...s)).toBe(PUSHER.stroke_mm);
    expect(s[s.length - 1]).toBe(0);                               // back home
    // the S-curve starts more gently than the trapezoid (its acceleration ramps up)
    expect(s[0]).toBeLessThan(out[0]);
    // and arrives later, by what the jerk ramps cost
    expect(s.indexOf(PUSHER.stroke_mm)).toBeGreaterThanOrEqual(out.indexOf(PUSHER.stroke_mm));
  });

  it("refuses a negative jerk limit", () => {
    const w = sortingWorld(DOC);
    w.init.drives = w.init.drives!.map((d) => ({ ...d, jmax: -1 }));
    expect(() => PhysicsCore.create(RAPIER, w.init)).toThrow(/jmax/);
  });
});
