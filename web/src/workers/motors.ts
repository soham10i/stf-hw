// DC encoder motors, reference switches and the positioning block that drives them - the physics
// of the factory's axes. Thread-free and clock-free like physicsCore.ts, which runs them each
// fixed step.
//
// The motor: a permanent-magnet DC motor with its gearbox, reduced to the output shaft. Its speed-
// torque line is straight (the datasheet's T-N-I characteristic): at its rated voltage it turns at
// `noLoadRpm` with no load and stalls at `stallTorqueNm`; at another voltage the line shifts in
// proportion. Short-circuited (both leads on the same rail - the 24 V board's "off") the same back
// EMF brakes it. Against it act the load's Coulomb friction (a spindle's thread, which also makes
// the axis self-locking) and a constant load torque (a lift's weight). Between steps the voltage
// and the loads are constant, so the speed follows its exact exponential solution - no
// integration error, any step length, and the same result on every machine.
//
//   J dw/dt = Ts * V/Vr - k w - Tc sgn(w) - Tg,    k = Ts / w0,   tau = J / k
//
// The encoder counts output-shaft pulses (a quadrature encoder read by a counter input): the
// count is the whole pulses turned since power-up, in float64 underneath. A hard end stop halts
// the axis where the mechanism ends; reaching it is a crash, counted.
//
// The positioning block is what the PLC runs per axis (docs/plc): drive toward a target count,
// switch off a brake lead before it, and report where it came to rest; homing drives to the
// reference switch and zeroes the count there.

export const TAU = 2 * Math.PI;

export interface MotorSpec {
  noLoadRpm: number; // output shaft, at ratedV
  stallTorqueNm: number; // output shaft, at ratedV
  stallCurrentA: number;
  noLoadCurrentA: number;
  ratedV: number;
  /** rotor and load inertia reduced to the output shaft, kg m^2 */
  inertia: number;
  /** Coulomb friction of the load at the output shaft, N m (opposes motion; holds at rest) */
  frictionNm: number;
  /** a constant load torque, N m: positive resists positive motion (a lift's weight) */
  loadNm?: number;
}

/** The fischertechnik 24 V encoder motor 144643 (docs/144643-Encodermotor24V.pdf), driving a
    4 mm-lead spindle. Datasheet: 440 rpm no-load, 1800 g cm stall torque, 0.60 A, 2.03 W peak.
    The spindle's friction is set so the axis runs at the lab-calibrated 214 rpm (14.27 mm/s;
    docs/HARDWARE_MODEL.md): on a straight speed-torque line that is a load of 1 - 214/440 of
    stall. The no-load current follows from the booklet's 320 mA at that point. The inertia is
    not published: [assumed] 20 ms mechanical time constant. */
export const FT_ENCODER_MOTOR: MotorSpec = (() => {
  const stall = 1800 * 9.80665e-5; // g cm -> N m
  const w0 = (440 * TAU) / 60;
  const tau = 0.02;
  const loadShare = 1 - 214 / 440;
  const stallA = 0.6;
  const atA = 0.32; // booklet: 320 mA at the operating point
  return {
    noLoadRpm: 440,
    stallTorqueNm: stall,
    stallCurrentA: stallA,
    noLoadCurrentA: (atA - stallA * loadShare) / (1 - loadShare),
    ratedV: 24,
    inertia: (tau * stall) / w0,
    frictionNm: loadShare * stall,
  };
})();

/** The S-Motor 24V with its U-Getriebe (booklet 536634 p.9): 10 700 rpm no-load, 5 mNm, 300 mA,
    a 64.8:1 gearbox - 165 rpm at the output. It drives the belts; it has no encoder. The 5 mNm is
    read as its stall torque at the motor; through the gearbox at an [assumed] 50 % efficiency (a
    worm stage). The no-load current and the inertia are not published: [assumed] 40 mA and a
    20 ms time constant. With no load of its own: a belt sets `frictionNm`. */
export const S_MOTOR_24V: MotorSpec = (() => {
  const ratio = 64.8;
  const stall = 5e-3 * ratio * 0.5;
  const w0 = ((10_700 / ratio) * TAU) / 60;
  return { noLoadRpm: 10_700 / ratio, stallTorqueNm: stall, stallCurrentA: 0.3, noLoadCurrentA: 0.04, ratedV: 24, inertia: (0.02 * stall) / w0, frictionNm: 0 };
})();

/** A motor whose load holds it at `rpm` on 24 V: the Coulomb friction that puts its straight
    speed-torque line through that point (how the encoder motor's spindle friction is set). */
export const loadedTo = (spec: MotorSpec, rpm: number): MotorSpec => ({ ...spec, frictionNm: (1 - rpm / spec.noLoadRpm) * spec.stallTorqueNm });

export interface MotorState {
  angle: number; // output shaft, rad, since power-up (float64)
  speed: number; // rad/s
  volts: number; // across the leads now
  torque: number; // the motor's own torque now, N m
  current: number; // A
}

export const newMotor = (): MotorState => ({ angle: 0, speed: 0, volts: 0, torque: 0, current: 0 });

/** One step of `dt` seconds at a constant voltage across the motor. `hardStop` limits the angle
    (the mechanism's end): reaching it stops the shaft dead and reports it. */
export function stepMotor(
  m: MotorState, spec: MotorSpec, volts: number, dt: number, hardStop?: [number, number],
): { crashed: boolean } {
  const w0 = (spec.noLoadRpm * TAU) / 60;
  const k = spec.stallTorqueNm / w0;
  const drive = spec.stallTorqueNm * (volts / spec.ratedV); // torque at zero speed
  const Tg = spec.loadNm ?? 0;
  const Tc = spec.frictionNm;
  const tau = spec.inertia / k;
  m.volts = volts;

  let w = m.speed;
  let a = m.angle;
  let left = dt;
  // at rest, it starts only if the drive beats friction (and the load) in some direction
  if (w === 0) {
    const net = drive - Tg;
    if (Math.abs(net) <= Tc) {
      left = 0;
    }
  }
  // up to two pieces: moving one way, and (if friction stops it) at rest for the remainder
  while (left > 0) {
    const s = w !== 0 ? Math.sign(w) : Math.sign(drive - Tg);
    const wss = (drive - Tg - Tc * s) / k; // where the speed is heading
    const e = Math.exp(-left / tau);
    const wEnd = wss + (w - wss) * e;
    if (Math.sign(wEnd) === s || wEnd === 0 || Math.sign(wss) === s) {
      a += wss * left + (w - wss) * tau * (1 - Math.exp(-left / tau));
      w = Math.sign(wEnd) === s ? wEnd : 0;
      left = 0;
    } else {
      // friction (or braking) brings it to rest within the step: where the speed crosses zero
      const t0 = Math.min(left, -tau * Math.log(Math.min(1, Math.max(Number.MIN_VALUE, -wss / (w - wss)))));
      a += wss * t0 + (w - wss) * tau * (1 - Math.exp(-t0 / tau));
      w = 0;
      left -= t0;
      if (Math.abs(drive - Tg) <= Tc) left = 0; // and stays there
    }
  }
  let crashed = false;
  if (hardStop && (a < hardStop[0] || a > hardStop[1])) {
    a = Math.min(hardStop[1], Math.max(hardStop[0], a));
    w = 0;
    crashed = true;
  }
  m.angle = a;
  m.speed = w;
  m.torque = drive - k * w;
  const share = Math.abs(m.torque) / spec.stallTorqueNm;
  m.current = volts === 0 && w === 0 ? 0 : Math.sign(m.torque || 1) * (spec.noLoadCurrentA + (spec.stallCurrentA - spec.noLoadCurrentA) * share);
  return { crashed };
}

// ------------------------------------------------------------------ switches
/** A reference switch (the Mini-Taster 37783) on an axis: it closes as the axis passes `at` going
    `toward` it, and opens again `hysteresis` mm back (the switch's differential travel). */
export interface LimitSwitch {
  at: number;
  toward: "up" | "down";
  hysteresis: number;
}

export function switchState(sw: LimitSwitch, value: number, wasClosed: boolean): boolean {
  if (sw.toward === "up") return wasClosed ? value > sw.at - sw.hysteresis : value >= sw.at;
  return wasClosed ? value < sw.at + sw.hysteresis : value <= sw.at;
}

// ------------------------------------------------------------------ positioning
/** What the PLC's positioning block is doing for one axis. */
export type Task =
  | { kind: "idle" }
  | { kind: "jog"; dir: 1 | -1 }
  | { kind: "move"; target: number; lead: number }
  /** `leave`: it is on the switch - first off it (against `dir`), then back onto it, so the count
      is always zeroed where the switch closes coming from the same side. `creep`: after reaching
      the switch at full speed, back off and come onto it again `slow` - one scan's travel at full
      speed would otherwise be the homing error (a fast swivel turns 0.6 deg in 10 ms) */
  | { kind: "home"; dir: 1 | -1; leave?: boolean; creep?: boolean; slow?: boolean }
  | { kind: "until"; dir: 1 | -1 } // to a switch, without zeroing (an axis without an encoder)
  | { kind: "done"; target: number | null; error: number | null; steps: number };

/** One scan of the positioning block: the direction to drive (1, -1, or 0 = brake) from the task,
    the count and the reference switch, and whether at the creep speed. Returns the next task. */
export function scan(task: Task, count: number, refClosed: boolean, steps: number): { dir: -1 | 0 | 1; next: Task; slow?: boolean } {
  switch (task.kind) {
    case "idle":
    case "done":
      return { dir: 0, next: task };
    case "jog":
      return { dir: task.dir, next: task };
    case "move": {
      const remaining = task.target - count;
      // switch off a brake lead early: the axis coasts the rest of the way
      if (Math.abs(remaining) <= task.lead) return { dir: 0, next: { kind: "done", target: task.target, error: null, steps } };
      return { dir: remaining > 0 ? 1 : -1, next: task };
    }
    case "home": {
      const back = task.dir === 1 ? -1 : 1;
      if (task.leave) {
        if (refClosed) return { dir: back, next: task };
        const next: Task = { kind: "home", dir: task.dir, creep: task.creep, slow: task.creep };
        return { dir: task.dir, next, slow: next.slow };
      }
      if (refClosed) {
        if (task.creep && !task.slow) return { dir: back, next: { ...task, leave: true } };
        return { dir: 0, next: { kind: "done", target: null, error: null, steps } };
      }
      return { dir: task.dir, next: task, slow: task.slow };
    }
    case "until":
      if (refClosed) return { dir: 0, next: { kind: "done", target: null, error: null, steps } };
      return { dir: task.dir, next: task };
  }
}
