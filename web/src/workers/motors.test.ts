import { describe, expect, it } from "vitest";

import { FT_ENCODER_MOTOR, newMotor, scan, stepMotor, switchState, TAU, type MotorSpec } from "./motors";

const rpm = (w: number) => (w * 60) / TAU;
const run = (spec: MotorSpec, volts: number, seconds: number, dt = 0.01) => {
  const m = newMotor();
  for (let t = 0; t < seconds - 1e-9; t += dt) stepMotor(m, spec, volts, dt);
  return m;
};

describe("the encoder motor against its datasheet and the lab", () => {
  it("runs at 440 rpm with no load, drawing its no-load current", () => {
    const m = run({ ...FT_ENCODER_MOTOR, frictionNm: 0 }, 24, 0.5);
    expect(rpm(m.speed)).toBeCloseTo(440, 6);
    expect(m.current).toBeCloseTo(FT_ENCODER_MOTOR.noLoadCurrentA, 6);
  });

  it("turns a 4 mm spindle at the lab's 214 rpm = 14.27 mm/s, at the booklet's 320 mA", () => {
    const m = run(FT_ENCODER_MOTOR, 24, 0.5);
    expect(rpm(m.speed)).toBeCloseTo(214, 6);
    expect((m.speed / TAU) * 4).toBeCloseTo(14.27, 2);
    expect(m.current).toBeCloseTo(0.32, 6);
    // its output there is the datasheet's peak, 2.03 W (the middle of a straight T-N line)
    expect((FT_ENCODER_MOTOR.stallTorqueNm * (1 - 214 / 440)) * m.speed).toBeCloseTo(2.03, 1);
  });

  it("draws its stall current when held still", () => {
    const m = run({ ...FT_ENCODER_MOTOR, frictionNm: 0, loadNm: FT_ENCODER_MOTOR.stallTorqueNm }, 24, 0.3);
    expect(m.speed).toBe(0);
    expect(m.current).toBeCloseTo(0.6, 6);
  });

  it("is half as fast at half the voltage with no load", () => {
    expect(rpm(run({ ...FT_ENCODER_MOTOR, frictionNm: 0 }, 12, 0.5).speed)).toBeCloseTo(220, 6);
  });
});

describe("its dynamics", () => {
  it("brakes to a stop when its leads are shorted, and the spindle holds it there", () => {
    const m = run(FT_ENCODER_MOTOR, 24, 0.5);
    const from = m.angle;
    for (let i = 0; i < 20; i++) stepMotor(m, FT_ENCODER_MOTOR, 0, 0.01);
    expect(m.speed).toBe(0);
    const coastRev = (m.angle - from) / TAU;
    expect(coastRev).toBeGreaterThan(0);
    expect(coastRev * 75).toBeLessThan(3); // under 3 encoder pulses: about 0.15 mm on the spindle
    const held = m.angle;
    for (let i = 0; i < 50; i++) stepMotor(m, FT_ENCODER_MOTOR, 0, 0.01);
    expect(m.angle).toBe(held);
  });

  it("is self-locking: a lift's weight cannot turn the spindle back", () => {
    const lift = { ...FT_ENCODER_MOTOR, loadNm: 0.25 * 9.81 * 0.004 / TAU };
    const m = run(lift, 0, 1);
    expect(m.angle).toBe(0);
    expect(rpm(run(lift, 24, 0.5).speed)).toBeLessThan(214); // and lifting it is a little slower
  });

  it("gives the same motion whatever the step length (the exact solution)", () => {
    const coarse = run(FT_ENCODER_MOTOR, 24, 0.3, 0.01);
    const fine = run(FT_ENCODER_MOTOR, 24, 0.3, 0.001);
    expect(fine.angle).toBeCloseTo(coarse.angle, 9);
    expect(fine.speed).toBeCloseTo(coarse.speed, 9);
  });

  it("stops dead at the mechanism's end and says so", () => {
    const m = newMotor();
    let crashed = false;
    for (let i = 0; i < 100; i++) crashed = stepMotor(m, FT_ENCODER_MOTOR, 24, 0.01, [0, 10]).crashed || crashed;
    expect(crashed).toBe(true);
    expect(m.angle).toBe(10);
    expect(m.speed).toBe(0);
  });

  it("reverses when the voltage does", () => {
    const m = run(FT_ENCODER_MOTOR, 24, 0.3);
    for (let i = 0; i < 30; i++) stepMotor(m, FT_ENCODER_MOTOR, -24, 0.01);
    expect(rpm(m.speed)).toBeCloseTo(-214, 3);
  });
});

describe("switches and the positioning block", () => {
  it("a reference switch closes at its point and opens half a millimetre back", () => {
    const sw = { at: 665, toward: "up" as const, hysteresis: 0.5 };
    expect(switchState(sw, 664.9, false)).toBe(false);
    expect(switchState(sw, 665, false)).toBe(true);
    expect(switchState(sw, 664.6, true)).toBe(true);
    expect(switchState(sw, 664.5, true)).toBe(false);
    const down = { at: 0, toward: "down" as const, hysteresis: 0.5 };
    expect(switchState(down, 0, false)).toBe(true);
    expect(switchState(down, 0.4, true)).toBe(true);
  });

  it("drives toward a target and switches off a brake lead early; homes to its switch", () => {
    expect(scan({ kind: "move", target: 100, lead: 2 }, 50, false, 0).dir).toBe(1);
    expect(scan({ kind: "move", target: 100, lead: 2 }, 150, false, 0).dir).toBe(-1);
    expect(scan({ kind: "move", target: 100, lead: 2 }, 98, false, 7).next).toEqual({ kind: "done", target: 100, error: null, steps: 7 });
    expect(scan({ kind: "home", dir: 1 }, 0, false, 0).dir).toBe(1);
    expect(scan({ kind: "home", dir: 1 }, 0, true, 0)).toEqual({ dir: 0, next: { kind: "done", target: null, error: null, steps: 0 } });
  });
});
