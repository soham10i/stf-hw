import { describe, expect, it } from "vitest";
import { AXIS_STRIDE, bridgeLayout, makeSnapshot, type Snapshot } from "./SimulationBridge";
import { SnapshotInterpolator } from "./SnapshotInterpolator";

const layout = bridgeLayout(4, 2, 1);
const DT = 0.01;

/** A part moving at 100 mm/s along x and turning about z at 1 rad/s, one state per 10 ms step. */
function state(step: number): Snapshot {
  const s = makeSnapshot(layout);
  const t = step * DT;
  s.seq = step * 2;
  s.step = step;
  s.simTime = t;
  s.partCount = 1;
  s.axisCount = 1;
  s.pinCount = 1;
  s.transforms.set([100 * t, 0, 0, 0, 0, Math.sin(t / 2), Math.cos(t / 2)]);
  s.axes[0] = 50 * t;
  s.pinVolts[0] = step % 2 ? 24 : 0;
  return s;
}

describe("SnapshotInterpolator", () => {
  it("draws motion evenly at 60 Hz from 100 Hz steps", () => {
    const ip = new SnapshotInterpolator(layout);
    const out = makeSnapshot(layout);
    const xs: number[] = [];
    let wall = 0;
    for (let frame = 0; frame < 120; frame++) {
      wall += 1 / 60;
      ip.push(state(Math.floor(wall / DT))); // what read() returns at this frame
      ip.sample(1 / 60, 1, true, out);
      xs.push(out.transforms[0]);
    }
    // after the clock settles, every frame advances about 100 mm/s * 1/60 s = 1.67 mm; drawn raw
    // the frames would alternate 1 and 2 steps (1 and 2 mm)
    const d = xs.slice(60).map((x, i, a) => (i ? x - a[i - 1] : NaN)).slice(1);
    for (const v of d) expect(v).toBeCloseTo(100 / 60, 1);
    const raw = Array.from({ length: 60 }, (_, i) => Math.floor(((i + 61) / 60) / DT) - Math.floor(((i + 60) / 60) / DT));
    expect(new Set(raw).size).toBeGreaterThan(1);
  });

  it("blends rotations along the shorter arc and keeps them unit length", () => {
    const ip = new SnapshotInterpolator(layout, 0.005);
    const a = state(0);
    const b = state(1);
    b.transforms.set([1, 0, 0, 0, 0, -0.005, -1]); // the same rotation as a, sign flipped
    ip.push(a);
    ip.push(b);
    const out = makeSnapshot(layout);
    ip.sample(0, 1, true, out);
    ip.sample(0, 1, true, out);
    const q = Array.from(out.transforms.subarray(3, 7));
    expect(Math.hypot(...q)).toBeCloseTo(1, 9);
    expect(Math.abs(q[3])).toBeGreaterThan(0.99); // not swung through the far side
  });

  it("interpolates axis positions only; pins come from the newest state", () => {
    const ip = new SnapshotInterpolator(layout, 0.005);
    ip.push(state(0));
    ip.push(state(1));
    const out = makeSnapshot(layout);
    ip.sample(0, 1, true, out);
    expect(out.axes[0]).toBeCloseTo(50 * 0.005, 9);
    expect(out.pinVolts[0]).toBe(24);
    expect(out.axes.length).toBe(AXIS_STRIDE);
  });

  it("shows the newest state when paused, and starts over after a reset", () => {
    const ip = new SnapshotInterpolator(layout);
    for (let i = 0; i < 5; i++) ip.push(state(i));
    const out = makeSnapshot(layout);
    ip.sample(1 / 60, 1, false, out);
    expect(out.simTime).toBe(0.04);
    expect(out.transforms[0]).toBeCloseTo(4, 9);
    ip.push(state(0)); // a step backwards: the world was reset
    ip.sample(1 / 60, 1, true, out);
    expect(out.transforms[0]).toBe(0);
  });

  it("never runs the clock backwards", () => {
    const ip = new SnapshotInterpolator(layout);
    const out = makeSnapshot(layout);
    let last = -1;
    for (let i = 0; i < 50; i++) {
      ip.push(state(i < 25 ? i : 25)); // the worker stalls half way
      ip.sample(1 / 60, 1, true, out);
      expect(ip.clock).toBeGreaterThanOrEqual(last);
      last = ip.clock;
    }
  });
});
