import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { buildWindow, type Weights } from "../dashboard/ml";
import { flatten, packWeights } from "./tcnGpu";

// The WebGPU kernel reads the weights at offsets fixed in its WGSL (W1 .. BC); the packing here must
// put every tensor exactly there. The kernel itself needs a GPU: scripts/edge-bench.mjs checks its
// answers against the TypeScript forward pass in headless Chrome.
const W = JSON.parse(readFileSync(resolve(__dirname, "../../public/ml/weights.json"), "utf8")) as Weights;

describe("the WebGPU TCN's weight layout", () => {
  const nin = W.inputs.length, CH = W.ch;
  const off = (() => {
    const W1 = 0, B1 = W1 + CH * nin * 3, W2 = B1 + CH, B2 = W2 + CH * CH * 3, W3 = B2 + CH, B3 = W3 + CH * CH * 3,
      W4 = B3 + CH, B4 = W4 + CH * CH * 3, WF = B4 + CH, BF = WF + 64 * 64, WR = BF + 64, BR = WR + 64, WC = BR + 1, BC = WC + 3 * 64;
    return { W1, B1, W2, B4, WF, BF, WR, BR, WC, BC };
  })();
  const p = packWeights(W);

  it("has every parameter once, at the kernel's offsets", () => {
    expect(p.length).toBe(off.BC + 3);
    expect(p[off.W1 + (5 * nin + 2) * 3 + 1]).toBeCloseTo(W.conv[0].w[5][2][1], 6);
    expect(p[off.B1 + 7]).toBeCloseTo(W.conv[0].b[7], 6);
    expect(p[off.W2 + (31 * CH + 30) * 3 + 2]).toBeCloseTo(W.conv[1].w[31][30][2], 6);
    expect(p[off.B4 + 31]).toBeCloseTo(W.conv[3].b[31], 6);
    expect(p[off.WF + 9 * 64 + 40]).toBeCloseTo(W.fc.w[9][40], 6);
    expect(p[off.BR]).toBeCloseTo(W.rul.b[0], 6);
    expect(p[off.WC + 2 * 64 + 63]).toBeCloseTo(W.cls.w[2][63], 6);
    expect(p[off.BC + 2]).toBeCloseTo(W.cls.b[2], 6);
  });

  it("flattens a window input-major, as the kernel indexes it (c * 48 + t)", () => {
    const X = Array.from({ length: 60 }, (_, t) => W.features.map((_, j) => 1 + 0.01 * t + j * 1e-3));
    const w = buildWindow(W, X, 3, 59);
    const flat = new Float32Array(nin * W.window);
    flatten(w, flat, 0);
    expect(flat[0 * W.window + 47]).toBe(w[0][47]);
    expect(flat[2 * W.window + 10]).toBe(w[2][10]);
    expect(flat[(4 + 3) * W.window + 5]).toBe(1);                 // the component's one-hot channel
  });
});
