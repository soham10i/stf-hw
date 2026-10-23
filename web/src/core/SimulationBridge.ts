// The memory the physics and circuit workers share with the renderer (Deliverable 1).
//
// One buffer holds everything the renderer needs each frame - every placed part's pose and every
// pin's state - laid out so both sides index it without serialising:
//
//   bytes      view                      contents
//   0..63      Int32[16]   header        magic, version, seqlock, capacities, counts, mode,
//                                        step (two words), flags, input mutex, input sequence
//   64..95     Float64[4]  scalars       simulation time (s), wall time of the publish (ms),
//                                        fixed timestep (s), real-time rate
//   96..       Float64[7n] transforms    per part: position x y z (mm), quaternion x y z w
//   ..         Float64[m]  pin volts     per pin: the voltage the solver set
//   ..         Int32[m]    pin flags     per pin: PIN_HIGH | PIN_FORCED | PIN_TELEMETRY | PIN_FAULT
//   ..         Float64[m]  input volts   per pin: a value the UI forces (a pressed button)
//   ..         Int32[m]    input flags   per pin: INPUT_SET while forced
//   ..         Float64[9a] axes          per motor axis: position, rpm, current, volts, encoder
//                                        count, task, last positioning error, crashes, homed
//
// Two ways to keep the halves consistent:
// - The state (header counts to pin flags) has ONE writer, the worker. It is published under a
//   seqlock: the writer makes the sequence odd, writes, makes it even again; a reader copies and
//   accepts the copy only if it saw the same even sequence before and after. Readers never block
//   the writer, and the renderer never waits on physics.
// - The input region has writers on both sides (the UI sets, the worker consumes), so it is
//   guarded by a mutex on an Int32 word: compare-and-exchange to take it, store and notify to
//   give it back. The worker may block on it (Atomics.wait); the main thread may not, so it only
//   ever tries, and retries on its next frame.
//
// Everything is float64 until the renderer: `downcastForRender` is the one place it becomes
// float32, for the vertex and transform buffers WebGL uses.
//
// Without cross-origin isolation (a static host that cannot send COOP/COEP headers) there is no
// SharedArrayBuffer: the same layout lives in an ordinary ArrayBuffer that the worker copies and
// transfers after each publish, and `BridgeReader.adopt` swaps it in.

export const BRIDGE_MAGIC = 0x53544642; // "STFB"
export const BRIDGE_VERSION = 2;

/** Header word indices (Int32). */
export const H = {
  MAGIC: 0,
  VERSION: 1,
  SEQ: 2,
  PART_CAPACITY: 3,
  PIN_CAPACITY: 4,
  PART_COUNT: 5,
  PIN_COUNT: 6,
  MODE: 7,
  STEP_LO: 8,
  STEP_HI: 9,
  FLAGS: 10,
  INPUT_LOCK: 11,
  INPUT_SEQ: 12,
  AXIS_CAPACITY: 13,
  AXIS_COUNT: 14,
} as const;
const HEADER_INTS = 16;

/** Scalar indices (Float64). */
export const S = { SIM_TIME: 0, PUBLISHED_MS: 1, DT: 2, RATE: 3 } as const;
const SCALARS = 4;

/** Doubles per transform: px py pz (mm), qx qy qz qw. */
export const TRANSFORM_STRIDE = 7;
/** Doubles per axis, and what each is. */
export const AXIS_STRIDE = 9;
export const AX = { POSITION: 0, RPM: 1, CURRENT: 2, VOLTS: 3, COUNT: 4, TASK: 5, ERROR: 6, CRASHES: 7, HOMED: 8 } as const;
/** AX.TASK's values */
export const TASKS = ["idle", "jog", "move", "home", "until", "done"] as const;

export const PIN_HIGH = 1 << 0; // the pin reads as logic 1
export const PIN_FORCED = 1 << 1; // the value came from the input region (the UI)
export const PIN_TELEMETRY = 1 << 2; // the value came from the live factory
export const PIN_FAULT = 1 << 3; // the circuit solver marked the pin (short, overvoltage)
export const INPUT_SET = 1 << 0;

export const FLAG_RUNNING = 1 << 0;
export const FLAG_TELEMETRY_STALE = 1 << 1; // live mode, and no sample covers the current time

export const MODE_SIMULATION = 0;
export const MODE_LIVE_TELEMETRY = 1;

export interface BridgeLayout {
  partCapacity: number;
  pinCapacity: number;
  axisCapacity: number;
  byteLength: number;
  offsets: { header: 0; scalars: number; transforms: number; pinVolts: number; pinFlags: number; inputVolts: number; inputFlags: number; axes: number };
}

const align8 = (n: number) => (n + 7) & ~7;

/** The layout for a number of parts and pins: every array starts on an 8-byte boundary. */
export function bridgeLayout(partCapacity: number, pinCapacity: number, axisCapacity = 0): BridgeLayout {
  for (const c of [partCapacity, pinCapacity, axisCapacity]) {
    if (!Number.isInteger(c) || c < 0) throw new RangeError("capacities must be whole numbers >= 0");
  }
  const scalars = HEADER_INTS * 4;
  const transforms = align8(scalars + SCALARS * 8);
  const pinVolts = align8(transforms + partCapacity * TRANSFORM_STRIDE * 8);
  const pinFlags = align8(pinVolts + pinCapacity * 8);
  const inputVolts = align8(pinFlags + pinCapacity * 4);
  const inputFlags = align8(inputVolts + pinCapacity * 8);
  const axes = align8(inputFlags + pinCapacity * 4);
  const byteLength = align8(axes + axisCapacity * AXIS_STRIDE * 8);
  return { partCapacity, pinCapacity, axisCapacity, byteLength, offsets: { header: 0, scalars, transforms, pinVolts, pinFlags, inputVolts, inputFlags, axes } };
}

/** Typed views over one bridge buffer. */
export class BridgeViews {
  readonly header: Int32Array;
  readonly scalars: Float64Array;
  readonly transforms: Float64Array;
  readonly pinVolts: Float64Array;
  readonly pinFlags: Int32Array;
  readonly inputVolts: Float64Array;
  readonly inputFlags: Int32Array;
  readonly axes: Float64Array;

  constructor(readonly buffer: ArrayBuffer | SharedArrayBuffer, readonly layout: BridgeLayout) {
    if (buffer.byteLength < layout.byteLength) throw new RangeError("the buffer is smaller than its layout");
    const o = layout.offsets;
    this.header = new Int32Array(buffer, 0, HEADER_INTS);
    this.scalars = new Float64Array(buffer, o.scalars, SCALARS);
    this.transforms = new Float64Array(buffer, o.transforms, layout.partCapacity * TRANSFORM_STRIDE);
    this.pinVolts = new Float64Array(buffer, o.pinVolts, layout.pinCapacity);
    this.pinFlags = new Int32Array(buffer, o.pinFlags, layout.pinCapacity);
    this.inputVolts = new Float64Array(buffer, o.inputVolts, layout.pinCapacity);
    this.inputFlags = new Int32Array(buffer, o.inputFlags, layout.pinCapacity);
    this.axes = new Float64Array(buffer, o.axes, layout.axisCapacity * AXIS_STRIDE);
  }

  get shared(): boolean {
    return typeof SharedArrayBuffer !== "undefined" && this.buffer instanceof SharedArrayBuffer;
  }
}

/** SharedArrayBuffer is usable here: it exists and the page is cross-origin isolated (a worker
    of such a page is too). Node has it without isolation. */
export function canShare(): boolean {
  if (typeof SharedArrayBuffer === "undefined") return false;
  const g = globalThis as { crossOriginIsolated?: boolean; document?: unknown; importScripts?: unknown };
  const browser = typeof g.document !== "undefined" || typeof g.importScripts !== "undefined";
  return browser ? g.crossOriginIsolated === true : true;
}

/** A new bridge: shared when possible (or when asked and possible), else an ordinary buffer. */
export function createBridge(partCapacity: number, pinCapacity: number, preferShared = true, axisCapacity = 0): BridgeViews {
  const layout = bridgeLayout(partCapacity, pinCapacity, axisCapacity);
  const shared = preferShared && canShare();
  const buffer = shared ? new SharedArrayBuffer(layout.byteLength) : new ArrayBuffer(layout.byteLength);
  const v = new BridgeViews(buffer, layout);
  v.header[H.MAGIC] = BRIDGE_MAGIC;
  v.header[H.VERSION] = BRIDGE_VERSION;
  v.header[H.PART_CAPACITY] = partCapacity;
  v.header[H.PIN_CAPACITY] = pinCapacity;
  v.header[H.AXIS_CAPACITY] = axisCapacity;
  return v;
}

/** Views over a buffer another thread created, after checking it is a bridge of this version. */
export function attachBridge(buffer: ArrayBuffer | SharedArrayBuffer): BridgeViews {
  const head = new Int32Array(buffer, 0, HEADER_INTS);
  if (head[H.MAGIC] !== BRIDGE_MAGIC) throw new Error("not a simulation bridge buffer");
  if (head[H.VERSION] !== BRIDGE_VERSION) throw new Error(`bridge version ${head[H.VERSION]}, expected ${BRIDGE_VERSION}`);
  return new BridgeViews(buffer, bridgeLayout(head[H.PART_CAPACITY], head[H.PIN_CAPACITY], head[H.AXIS_CAPACITY]));
}

// Atomics need a shared Int32Array; on an ordinary buffer (the transfer fallback, one thread per
// copy) plain reads and writes are already consistent.
const load = (a: Int32Array, i: number, shared: boolean) => (shared ? Atomics.load(a, i) : a[i]);
const store = (a: Int32Array, i: number, v: number, shared: boolean) => { if (shared) Atomics.store(a, i, v); else a[i] = v; };
const add = (a: Int32Array, i: number, v: number, shared: boolean) => {
  if (shared) return Atomics.add(a, i, v);
  const old = a[i];
  a[i] = (old + v) | 0;
  return old;
};

/** The main thread may not block (Atomics.wait throws there). */
const MAIN_THREAD = typeof (globalThis as { document?: unknown }).document !== "undefined";

// ------------------------------------------------------------------ the mutex
/** A mutex on one Int32 word of a shared buffer: 0 free, 1 held. */
export class SpinMutex {
  constructor(private readonly word: Int32Array, private readonly index: number, private readonly shared = true) {}

  tryLock(): boolean {
    if (!this.shared) {
      if (this.word[this.index] !== 0) return false;
      this.word[this.index] = 1;
      return true;
    }
    return Atomics.compareExchange(this.word, this.index, 0, 1) === 0;
  }

  /** Takes the lock, spinning a little and then (off the main thread) sleeping until it is given
      back; false when it was not free within `timeoutMs`. On the main thread it only spins. */
  lock(timeoutMs = 2): boolean {
    const end = performance.now() + timeoutMs;
    for (let spins = 0; ; spins++) {
      if (this.tryLock()) return true;
      if (performance.now() >= end) return false;
      if (spins > 64 && this.shared && !MAIN_THREAD) {
        Atomics.wait(this.word, this.index, 1, Math.max(0, end - performance.now()));
      }
    }
  }

  unlock(): void {
    if (!this.shared) {
      if (this.word[this.index] !== 1) throw new Error("unlock of a mutex that is not held");
      this.word[this.index] = 0;
      return;
    }
    if (Atomics.compareExchange(this.word, this.index, 1, 0) !== 1) throw new Error("unlock of a mutex that is not held");
    Atomics.notify(this.word, this.index, 1);
  }
}

// ------------------------------------------------------------------ the writer (worker)
/** The worker's side: publishes the state under the seqlock and drains the UI's inputs. */
export class BridgeWriter {
  private readonly shared: boolean;
  private readonly inputs: SpinMutex;
  private lastInputSeq = -1;

  constructor(readonly views: BridgeViews) {
    this.shared = views.shared;
    this.inputs = new SpinMutex(views.header, H.INPUT_LOCK, this.shared);
  }

  /** Writes one consistent state: `write` runs between the two sequence bumps. The sequence is
      odd while it runs, so no reader accepts a half-written state. */
  publish(write: (v: BridgeViews) => void): void {
    const h = this.views.header;
    add(h, H.SEQ, 1, this.shared); // odd: writing
    try {
      write(this.views);
      this.views.scalars[S.PUBLISHED_MS] = performance.now();
    } finally {
      add(h, H.SEQ, 1, this.shared); // even: stable
      if (this.shared) Atomics.notify(h, H.SEQ);
    }
  }

  setCounts(parts: number, pins: number, axes = 0): void {
    const l = this.views.layout;
    if (parts > l.partCapacity || pins > l.pinCapacity || axes > l.axisCapacity) {
      throw new RangeError(`${parts} parts / ${pins} pins / ${axes} axes exceed the bridge's ${l.partCapacity} / ${l.pinCapacity} / ${l.axisCapacity}`);
    }
    this.views.header[H.PART_COUNT] = parts;
    this.views.header[H.PIN_COUNT] = pins;
    this.views.header[H.AXIS_COUNT] = axes;
  }

  /** The step counter as two 32-bit words (exact to 2^53 steps). */
  setStep(step: number): void {
    this.views.header[H.STEP_LO] = step % 0x1_0000_0000 | 0;
    this.views.header[H.STEP_HI] = Math.floor(step / 0x1_0000_0000);
  }

  /** The UI's forced inputs, if they changed since the last call: `apply(pin, volts | null)` for
      every pin (null = not forced). Taken under the input mutex; skipped (and retried at the next
      step) if the UI holds it. */
  drainInputs(apply: (pin: number, volts: number | null) => void): boolean {
    const h = this.views.header;
    const seq = load(h, H.INPUT_SEQ, this.shared);
    if (seq === this.lastInputSeq) return false;
    if (!this.inputs.lock(1)) return false;
    try {
      const n = h[H.PIN_COUNT];
      for (let i = 0; i < n; i++) apply(i, this.views.inputFlags[i] & INPUT_SET ? this.views.inputVolts[i] : null);
      this.lastInputSeq = seq;
    } finally {
      this.inputs.unlock();
    }
    return true;
  }
}

// ------------------------------------------------------------------ the reader (renderer)
export interface Snapshot {
  seq: number;
  step: number;
  simTime: number;
  mode: number;
  flags: number;
  partCount: number;
  pinCount: number;
  axisCount: number;
  transforms: Float64Array; // partCount * 7 valid
  pinVolts: Float64Array;
  pinFlags: Int32Array;
  axes: Float64Array; // axisCount * AXIS_STRIDE valid
}

/** A snapshot sized for a bridge, to read into again and again without allocating. */
export function makeSnapshot(layout: BridgeLayout): Snapshot {
  return {
    seq: -1, step: 0, simTime: 0, mode: 0, flags: 0, partCount: 0, pinCount: 0, axisCount: 0,
    transforms: new Float64Array(layout.partCapacity * TRANSFORM_STRIDE),
    pinVolts: new Float64Array(layout.pinCapacity),
    pinFlags: new Int32Array(layout.pinCapacity),
    axes: new Float64Array(layout.axisCapacity * AXIS_STRIDE),
  };
}

/** The renderer's side: consistent copies of the state, and the UI's forced inputs. */
export class BridgeReader {
  views: BridgeViews;
  private inputs: SpinMutex;
  private pending = new Map<number, number | null>();

  constructor(views: BridgeViews) {
    this.views = views;
    this.inputs = new SpinMutex(views.header, H.INPUT_LOCK, views.shared);
  }

  /** The transfer fallback: a new copy from the worker replaces the current one. */
  adopt(buffer: ArrayBuffer): void {
    const next = new BridgeViews(buffer, this.views.layout);
    this.views = next;
    this.inputs = new SpinMutex(next.header, H.INPUT_LOCK, false);
  }

  /** Copies one consistent state into `out`; false if the writer kept it busy for `retries`
      attempts (the caller keeps the previous frame - it is never torn). Copies only when the
      sequence moved, unless `force`. */
  read(out: Snapshot, retries = 32, force = false): boolean {
    const v = this.views;
    const h = v.header;
    const shared = v.shared;
    for (let attempt = 0; attempt < retries; attempt++) {
      const s1 = load(h, H.SEQ, shared);
      if (s1 & 1) continue; // being written
      if (s1 === out.seq && !force) return true; // nothing new
      const parts = h[H.PART_COUNT];
      const pins = h[H.PIN_COUNT];
      const axes = h[H.AXIS_COUNT];
      out.transforms.set(v.transforms.subarray(0, parts * TRANSFORM_STRIDE));
      out.pinVolts.set(v.pinVolts.subarray(0, pins));
      out.pinFlags.set(v.pinFlags.subarray(0, pins));
      out.axes.set(v.axes.subarray(0, axes * AXIS_STRIDE));
      out.partCount = parts;
      out.pinCount = pins;
      out.axisCount = axes;
      out.mode = h[H.MODE];
      out.flags = h[H.FLAGS];
      out.step = (h[H.STEP_HI] >>> 0) * 0x1_0000_0000 + (h[H.STEP_LO] >>> 0);
      out.simTime = v.scalars[S.SIM_TIME];
      const s2 = load(h, H.SEQ, shared);
      if (s1 === s2) {
        out.seq = s1;
        return true;
      }
    }
    return false;
  }

  /** Forces a pin to `volts` (a pressed button, a jumper), or releases it with null. Written under
      the input mutex when it is free; otherwise kept and written on the next `flushInputs`. */
  setInput(pin: number, volts: number | null): void {
    if (pin < 0 || pin >= this.views.layout.pinCapacity) throw new RangeError(`pin ${pin} is outside the bridge`);
    if (volts !== null && !Number.isFinite(volts)) throw new RangeError("a forced voltage must be finite");
    this.pending.set(pin, volts);
    this.flushInputs();
  }

  /** Writes the pending inputs if the mutex is free now (never blocks); true when none are left. */
  flushInputs(): boolean {
    if (this.pending.size === 0) return true;
    if (!this.inputs.tryLock()) return false;
    const v = this.views;
    try {
      for (const [pin, volts] of this.pending) {
        if (volts === null) {
          v.inputFlags[pin] = 0;
          v.inputVolts[pin] = 0;
        } else {
          v.inputVolts[pin] = volts;
          v.inputFlags[pin] = INPUT_SET;
        }
      }
      add(v.header, H.INPUT_SEQ, 1, v.shared);
      this.pending.clear();
    } finally {
      this.inputs.unlock();
    }
    return true;
  }

  /** The inputs not yet written (the transfer fallback posts these to the worker). */
  takePending(): [number, number | null][] {
    const out = [...this.pending];
    this.pending.clear();
    return out;
  }
}

/** The one place float64 becomes float32: a snapshot's transforms for the GPU, positions scaled
    (mm to the scene's unit) and expressed relative to `origin` first, so the float32 values stay
    small and keep their precision far from the world origin. */
export function downcastForRender(snap: Snapshot, out: Float32Array, scale = 0.001, origin: readonly [number, number, number] = [0, 0, 0]): Float32Array {
  const n = snap.partCount;
  if (out.length < n * TRANSFORM_STRIDE) throw new RangeError("the output is smaller than the snapshot");
  const t = snap.transforms;
  for (let i = 0; i < n; i++) {
    const k = i * TRANSFORM_STRIDE;
    out[k] = (t[k] - origin[0]) * scale;
    out[k + 1] = (t[k + 1] - origin[1]) * scale;
    out[k + 2] = (t[k + 2] - origin[2]) * scale;
    out[k + 3] = t[k + 3];
    out[k + 4] = t[k + 4];
    out[k + 5] = t[k + 5];
    out[k + 6] = t[k + 6];
  }
  return out;
}

export const _test = { load, store, HEADER_INTS, SCALARS };
