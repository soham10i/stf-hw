// Smooth motion between physics steps: the renderer draws an interpolated state, not the newest.
//
// The worker steps at a fixed 100 Hz and publishes the newest state; the screen draws at 60, 120
// or 144 Hz. Drawn as it comes, a part moves one step on some frames and two on others (at 60 Hz:
// 1, 2, 2, 1, 2, ...) - visible judder however smooth the physics is. The cure is the one from
// "Fix Your Timestep" (Fiedler): draw the state at a render time a little behind the simulation,
// blended from the two published states either side of it.
//
//   push(snap)       every frame, after PhysicsClient.read(): keeps the states it has not seen
//   sample(dt, ...)  the state at the render clock, written into `out` (the newest when paused)
//
// The render clock advances with the frame's own time (times the run rate) and is pulled gently
// towards `newest - delay`, so it neither jumps when a publish comes late nor drifts. `delay`
// (default 25 ms at real time, times the run rate) is the latency bought: one display frame plus
// one worker tick, so a state on each side of the render time has always arrived. Positions are blended linearly,
// rotations by normalised quaternion lerp along the shorter arc, axis positions linearly; pins,
// flags and every other axis field come from the newest state - only motion is interpolated, a
// switch is never shown half on. A part added or removed between the two states is drawn at its
// newest pose.
import { AX, AXIS_STRIDE, TRANSFORM_STRIDE, makeSnapshot, type BridgeLayout, type Snapshot } from "./SimulationBridge";

const RING = 8;
const SNAP_IF_OFF_S = 0.25; // render clock this far from its target (a pause, a seek): jump
const PULL = 0.02; // share of the clock's error corrected each frame (±PULL of a step's motion per frame)

function copyInto(dst: Snapshot, src: Snapshot): void {
  dst.seq = src.seq;
  dst.step = src.step;
  dst.simTime = src.simTime;
  dst.mode = src.mode;
  dst.flags = src.flags;
  dst.partCount = src.partCount;
  dst.pinCount = src.pinCount;
  dst.axisCount = src.axisCount;
  dst.transforms.set(src.transforms.subarray(0, src.partCount * TRANSFORM_STRIDE));
  dst.pinVolts.set(src.pinVolts.subarray(0, src.pinCount));
  dst.pinFlags.set(src.pinFlags.subarray(0, src.pinCount));
  dst.axes.set(src.axes.subarray(0, src.axisCount * AXIS_STRIDE));
}

export class SnapshotInterpolator {
  /** the render clock, in simulation seconds */
  clock = Number.NaN;
  private ring: Snapshot[];
  private count = 0; // states held, newest at ring[(head + count - 1) % RING]
  private head = 0;

  constructor(layout: BridgeLayout, readonly delay = 0.025) {
    this.ring = Array.from({ length: RING }, () => makeSnapshot(layout));
  }

  private at(i: number): Snapshot {
    return this.ring[(this.head + i) % RING];
  }

  newest(): Snapshot | null {
    return this.count ? this.at(this.count - 1) : null;
  }

  /** Keeps `snap` if it is a step not seen yet; a step backwards (a reset) starts over. */
  push(snap: Snapshot): void {
    const last = this.newest();
    if (last && snap.step === last.step && snap.seq === last.seq) return;
    if (last && snap.step < last.step) this.reset();
    if (this.count === RING) {
      this.head = (this.head + 1) % RING;
      this.count--;
    }
    copyInto(this.at(this.count), snap);
    this.count++;
  }

  reset(): void {
    this.count = 0;
    this.head = 0;
    this.clock = Number.NaN;
  }

  /** The state at the render clock after a frame of `frameS` seconds, written into `out`. False
      when nothing has been pushed yet. */
  sample(frameS: number, rate: number, running: boolean, out: Snapshot): boolean {
    const newest = this.newest();
    if (!newest) return false;
    // the buffer is in simulation time: at 8x a frame and a worker tick span 8x the simulation,
    // so the render clock stays that much further behind to always have a state either side
    const target = newest.simTime - this.delay * Math.min(16, Math.max(1, rate));
    if (!running || !Number.isFinite(this.clock) || Math.abs(this.clock - target) > SNAP_IF_OFF_S * Math.max(1, rate)) {
      this.clock = running ? target : newest.simTime;
    } else {
      // forwards only: a clock running ahead is slowed down, never turned back
      const next = this.clock + Math.max(0, frameS) * rate;
      this.clock = Math.max(this.clock, next + (target - next) * PULL);
      // never past the newest state: when the worker stalls, the picture holds rather than guesses
      this.clock = Math.min(this.clock, newest.simTime);
    }
    copyInto(out, newest);
    if (!running || this.count < 2) return true;
    // the two states either side of the clock (the oldest or newest when it is outside them)
    let a = this.at(0);
    let b = a;
    for (let i = 1; i < this.count; i++) {
      b = this.at(i);
      if (b.simTime >= this.clock) break;
      a = b;
    }
    if (b === a || b.simTime <= a.simTime) return true;
    const t = Math.min(1, Math.max(0, (this.clock - a.simTime) / (b.simTime - a.simTime)));
    out.simTime = a.simTime + (b.simTime - a.simTime) * t;
    blendTransforms(a, b, t, out);
    blendAxes(a, b, t, out);
    return true;
  }
}

/** Poses between `a` and `b` at `t`; parts beyond either state's count keep the newest pose. */
export function blendTransforms(a: Snapshot, b: Snapshot, t: number, out: Snapshot): void {
  const n = Math.min(a.partCount, b.partCount, out.partCount);
  const A = a.transforms, B = b.transforms, O = out.transforms;
  for (let i = 0; i < n; i++) {
    const k = i * TRANSFORM_STRIDE;
    O[k] = A[k] + (B[k] - A[k]) * t;
    O[k + 1] = A[k + 1] + (B[k + 1] - A[k + 1]) * t;
    O[k + 2] = A[k + 2] + (B[k + 2] - A[k + 2]) * t;
    // q and -q are the same rotation: blend towards the nearer one
    const s = A[k + 3] * B[k + 3] + A[k + 4] * B[k + 4] + A[k + 5] * B[k + 5] + A[k + 6] * B[k + 6] < 0 ? -1 : 1;
    let x = A[k + 3] + (s * B[k + 3] - A[k + 3]) * t;
    let y = A[k + 4] + (s * B[k + 4] - A[k + 4]) * t;
    let z = A[k + 5] + (s * B[k + 5] - A[k + 5]) * t;
    let w = A[k + 6] + (s * B[k + 6] - A[k + 6]) * t;
    const len = Math.hypot(x, y, z, w) || 1;
    x /= len; y /= len; z /= len; w /= len;
    O[k + 3] = x; O[k + 4] = y; O[k + 5] = z; O[k + 6] = w;
  }
}

/** Each axis's position between `a` and `b`; its counts, current and task stay the newest. */
export function blendAxes(a: Snapshot, b: Snapshot, t: number, out: Snapshot): void {
  const n = Math.min(a.axisCount, b.axisCount, out.axisCount);
  for (let i = 0; i < n; i++) {
    const k = i * AXIS_STRIDE + AX.POSITION;
    out.axes[k] = a.axes[k] + (b.axes[k] - a.axes[k]) * t;
  }
}
