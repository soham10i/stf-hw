import { Worker } from "node:worker_threads";
import { describe, expect, it } from "vitest";

import {
  attachBridge, BridgeReader, BridgeWriter, bridgeLayout, createBridge, downcastForRender, H, INPUT_SET,
  makeSnapshot, SpinMutex, TRANSFORM_STRIDE,
} from "./SimulationBridge";

describe("layout", () => {
  it("puts every array on an 8-byte boundary and fits them all", () => {
    const l = bridgeLayout(37, 11);
    for (const o of Object.values(l.offsets)) expect(o % 8).toBe(0);
    expect(l.offsets.pinVolts - l.offsets.transforms).toBeGreaterThanOrEqual(37 * TRANSFORM_STRIDE * 8);
    expect(l.byteLength).toBeGreaterThanOrEqual(l.offsets.inputFlags + 11 * 4);
    expect(() => bridgeLayout(-1, 0)).toThrow(RangeError);
  });

  it("refuses a buffer that is not a bridge of this version", () => {
    const v = createBridge(2, 2);
    expect(attachBridge(v.buffer).layout).toEqual(v.layout);
    v.header[H.MAGIC] = 1;
    expect(() => attachBridge(v.buffer)).toThrow(/not a simulation bridge/);
  });
});

describe("seqlock", () => {
  it("round-trips float64 values, the step past 2^32 and the time exactly", () => {
    const v = createBridge(2, 1);
    expect(v.shared).toBe(true); // Node has SharedArrayBuffer without isolation
    const w = new BridgeWriter(v);
    w.publish(() => {
      w.setCounts(2, 1);
      v.transforms.set([0.1 + 0.2, 1e-12, 123456.789012345, 0, 0, Math.SQRT1_2, Math.SQRT1_2]);
      w.setStep(5_000_000_123);
      v.scalars[0] = 50_000_001.23;
    });
    const snap = makeSnapshot(v.layout);
    expect(new BridgeReader(v).read(snap)).toBe(true);
    expect(snap.transforms[0]).toBe(0.1 + 0.2);
    expect(snap.transforms[2]).toBe(123456.789012345);
    expect(snap.step).toBe(5_000_000_123);
    expect(snap.simTime).toBe(50_000_001.23);
    expect(snap.seq % 2).toBe(0);
  });

  it("never accepts a state while it is being written", () => {
    const v = createBridge(1, 0);
    const w = new BridgeWriter(v);
    const r = new BridgeReader(v);
    const snap = makeSnapshot(v.layout);
    w.publish(() => {
      w.setCounts(1, 0);
      v.transforms[0] = 7;
      expect(r.read(snap, 4)).toBe(false); // the sequence is odd mid-write
    });
    expect(r.read(snap)).toBe(true);
    expect(snap.transforms[0]).toBe(7);
  });

  it("gives a reader in one thread only whole frames from a writer in another", async () => {
    const parts = 64;
    const v = createBridge(parts, 0);
    const iters = 200_000;
    // the writer speaks the bridge's protocol on its own: sequence odd, every value k, sequence even
    const code = `
      const { workerData } = require("node:worker_threads");
      const { buf, tOff, n, iters } = workerData;
      const h = new Int32Array(buf, 0, 16);
      const t = new Float64Array(buf, tOff, n * 7);
      h[5] = n;
      for (let k = 1; k <= iters; k++) {
        Atomics.add(h, 2, 1);
        for (let i = 0; i < n * 7; i++) t[i] = k;
        Atomics.add(h, 2, 1);
      }`;
    const worker = new Worker(code, { eval: true, workerData: { buf: v.buffer, tOff: v.layout.offsets.transforms, n: parts, iters } });
    const done = new Promise((res) => worker.on("exit", res));
    const r = new BridgeReader(v);
    const snap = makeSnapshot(v.layout);
    let accepted = 0;
    let finished = false;
    void done.then(() => { finished = true; });
    while (!finished) {
      if (r.read(snap, 8, true) && snap.partCount === parts) {
        const k = snap.transforms[0];
        for (let i = 1; i < parts * TRANSFORM_STRIDE; i++) if (snap.transforms[i] !== k) throw new Error(`torn frame: ${k} and ${snap.transforms[i]}`);
        accepted++;
      }
      await new Promise((res) => setImmediate(res));
    }
    // the last frame, after the writer is gone, is whole and the newest
    expect(r.read(snap, 8, true)).toBe(true);
    expect(snap.transforms[parts * TRANSFORM_STRIDE - 1]).toBe(iters);
    expect(accepted).toBeGreaterThan(0); // frames were read while the other thread wrote
  }, 20_000);
});

describe("inputs", () => {
  it("takes the mutex once, and refuses to give back one it does not hold", () => {
    const v = createBridge(0, 1);
    const m = new SpinMutex(v.header, H.INPUT_LOCK);
    expect(m.tryLock()).toBe(true);
    expect(m.tryLock()).toBe(false);
    expect(m.lock(1)).toBe(false); // held: it gives up after the timeout
    m.unlock();
    expect(() => m.unlock()).toThrow(/not held/);
  });

  it("keeps an input while the worker holds the lock, and writes it on the next flush", () => {
    const v = createBridge(0, 3);
    const w = new BridgeWriter(v);
    w.publish(() => w.setCounts(0, 3));
    const r = new BridgeReader(v);
    const worker = new SpinMutex(v.header, H.INPUT_LOCK);
    expect(worker.tryLock()).toBe(true);
    r.setInput(2, 24);
    expect(v.inputFlags[2]).toBe(0); // not written while the lock is held
    worker.unlock();
    expect(r.flushInputs()).toBe(true);
    expect(v.inputFlags[2]).toBe(INPUT_SET);
    const seen: [number, number | null][] = [];
    expect(w.drainInputs((pin, volts) => seen.push([pin, volts]))).toBe(true);
    expect(seen).toEqual([[0, null], [1, null], [2, 24]]);
    expect(w.drainInputs(() => undefined)).toBe(false); // nothing new since
    r.setInput(2, null);
    w.drainInputs((pin, volts) => { if (pin === 2) expect(volts).toBeNull(); });
    expect(() => r.setInput(9, 1)).toThrow(RangeError);
    expect(() => r.setInput(0, Number.NaN)).toThrow(RangeError);
  });
});

describe("transfer fallback", () => {
  it("publishes into an ordinary buffer whose copies the reader adopts", () => {
    const worker = createBridge(1, 1, false);
    expect(worker.shared).toBe(false);
    const w = new BridgeWriter(worker);
    w.publish(() => {
      w.setCounts(1, 1);
      worker.transforms.set([10, 20, 30, 0, 0, 0, 1]);
      worker.pinVolts[0] = 24;
    });
    const r = new BridgeReader(createBridge(1, 1, false));
    r.adopt((worker.buffer as ArrayBuffer).slice(0));
    const snap = makeSnapshot(worker.layout);
    expect(r.read(snap)).toBe(true);
    expect([...snap.transforms.subarray(0, 3)]).toEqual([10, 20, 30]);
    expect(snap.pinVolts[0]).toBe(24);
  });
});

describe("render downcast", () => {
  it("is the one float32 step, made relative to an origin so far parts keep their precision", () => {
    const snap = makeSnapshot(bridgeLayout(1, 0));
    snap.partCount = 1;
    snap.transforms.set([1_000_000.0001, 2, 3, 0, 0, 0, 1]);
    const out = downcastForRender(snap, new Float32Array(7), 1, [1_000_000, 0, 0]);
    expect(out[0]).toBeCloseTo(0.0001, 7); // 1e6 + 1e-4 in float32 directly would be 1e6
    expect(out[6]).toBe(1);
    expect(() => downcastForRender(snap, new Float32Array(3))).toThrow(RangeError);
  });
});
