import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import RAPIER from "@dimforge/rapier3d-deterministic-compat";
import { beforeAll, describe, expect, it } from "vitest";

import { compose, invert } from "../../core/math64";
import type { CadDoc } from "../../shared/model";
import { driveStep, PhysicsCore } from "../../workers/physicsCore";
import { cookieAt, PUSHER, sortingWorld, type SortingWorld } from "./sortingWorld";

const DOC = JSON.parse(readFileSync(resolve(__dirname, "../../../public/hbw_parts_up12.json"), "utf8")) as CadDoc;

beforeAll(async () => {
  await RAPIER.init();
});

/** a pose in the sorting line's own frame */
const inLine = (w: SortingWorld, p: [number, number, number]) => compose(invert(w.placement), { p, q: [0, 0, 0, 1] }).p;

describe("actuator drives", () => {
  it("move along a trapezoid: capped speed and acceleration, landing exactly on the target", () => {
    let pos = 0;
    let vel = 0;
    let moved = 0; // the speed it actually moved at, step to step
    let peak = 0;
    let steps = 0;
    while ((pos !== 90 || vel !== 0) && steps < 1000) {
      const from = pos;
      [pos, vel] = driveStep(pos, vel, 90, 900, 15000, 0.01);
      const speed = (pos - from) / 0.01;
      expect(Math.abs(speed - moved)).toBeLessThanOrEqual(15000 * 0.01 + 1e-6); // never more than amax
      moved = speed;
      peak = Math.max(peak, speed);
      steps++;
    }
    expect(moved).toBeLessThanOrEqual(150 + 1e-6); // it arrives slowly, at the last ramp step
    expect(pos).toBe(90);
    expect(peak).toBeLessThanOrEqual(900);
    expect(steps).toBeLessThan(25); // a pneumatic stroke: about a fifth of a second
    expect(driveStep(5, 0, 5, 1, 1, 0.01)).toEqual([5, 0]);
  });
});

describe("the sorting line from the CAD export", () => {
  it("builds: belt, rails, bays, three driven pushers, five light barriers", () => {
    const w = sortingWorld(DOC);
    const core = PhysicsCore.create(RAPIER, w.init);
    expect(core.pins.map((p) => p.instance_id)).toEqual(["I2", "I3", "I5", "I6", "I7"]);
    // the inlet lies on the belt, between its rails, above its top
    const at = inLine(w, w.inlet);
    expect(at[1]).toBeCloseTo(230, 6);
    expect(at[2]).toBeCloseTo(55.5, 6);
    core.dispose();
  });

  it.each([40, 60, 100])("carries a cookie past the barriers and the white ejector pushes it into its bay (belt %i mm/s)", (speed) => {
    const w = sortingWorld(DOC);
    const core = PhysicsCore.create(RAPIER, w.init);
    core.enqueue({ type: "conveyor", instance_id: "belt_web", speed_mm_s: speed });
    core.enqueue({ type: "spawn", part: cookieAt(w, 1, "weiss").part, role: { kind: "dynamic", friction: 0.4 } });
    const seen = new Map<string, number>();
    let fired = -1;
    for (let i = 0; i < 2600 && !seen.has("I5"); i++) {
      core.stepOnce();
      for (const [tag, k] of Object.entries(w.barrierPin)) if (core.pinVolts[k] === 24 && !seen.has(tag)) seen.set(tag, core.step);
      const x = inLine(w, core.pose("cookie_1")!.p)[0];
      // the ejector fires as the cookie's centre reaches the pusher's (x = 460 on the line)
      if (fired < 0 && x >= 459) {
        core.enqueue({ type: "pulse", joint: w.pusherJoint.weiss, value: PUSHER.stroke_mm, hold_s: 0.15 });
        fired = core.step;
      }
    }
    expect(seen.get("I2")).toBeLessThan(seen.get("I3")!); // inlet first, then after the colour sensor
    expect(fired).toBeGreaterThan(seen.get("I3")!);
    expect(seen.has("I5")).toBe(true); // the white bay's barrier saw it
    expect(seen.has("I6") || seen.has("I7")).toBe(false);
    for (let i = 0; i < 150; i++) core.stepOnce(); // let it settle
    const rest = inLine(w, core.pose("cookie_1")!.p);
    expect(rest[0]).toBeGreaterThan(410); // inside the white bay's walls
    expect(rest[0]).toBeLessThan(510);
    expect(rest[1]).toBeGreaterThan(38);
    expect(rest[1]).toBeLessThan(90); // run on to the back wall, across its barrier's beam
    expect(core.drive(w.pusherJoint.weiss)).toEqual({ pos: 0, vel: 0, target: 0 }); // back home
    core.dispose();
  });
});
