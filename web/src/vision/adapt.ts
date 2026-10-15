// Upgrade 15, step 3: adapting the inspection CNN to a changed line, live and without labels.
// The network of stf-cad/hbw/vision/adapt.py with its batch norms kept as layers
// (public/vision/adapt.json). AdaBN: each batch norm normalises with statistics of the frames
// the line delivers now instead of the training images'. The browser estimates them online,
// cookie by cookie: the training statistics count as a prior of PRIOR frames, and once
// WINDOW frames have been seen the estimate becomes a moving average, so it keeps following
// the line. Each frame is classified first and only then added (causal).
import { f32 } from "./ae";

type Layer = { shape: number[]; w: Float32Array; b: Float32Array };
type Stats = { mean: Float32Array; var: Float32Array };
export type Domain = "old line" | "new line" | "new line, as delivered";
type Score = { condition_acc: number; flavour_acc: number; false_reject: number; escape_rate: number; to_person: number; recall: Record<string, number> };
export type AdaptNet = {
  classes: { flavour: string[]; condition: string[] }; size: number; ref: number; pass_p: number; sure_p: number;
  layers: Record<"c1" | "c2" | "c3" | "c4" | "fc" | "flav" | "cond", Layer>;
  bn: (Stats & { gamma: Float32Array; beta: Float32Array; eps: number })[];
  adabn: Stats[];
  parity: { images: string[]; source: number[][][]; adabn: number[][][] };
  results: Record<string, Record<Domain, Score>>;
  curve: ({ k: number; labels: number; sd: Record<Domain, number> } & Record<Domain, { condition_acc: number; false_reject: number; escape_rate: number }>)[];
  tradeoff: Record<"deployed" | "source" | "retrained", { p: number; escapes: number; false_rejects: number }[]>;
  guard: Record<"deployed" | "source", Record<"CNN alone" | "CNN + autoencoder", { escapes: number; false_rejects: number; to_person: number; good_to_person: number }>>;
  meta: { u_n: number; defect_rate: number; self_kept: number; predicted_mix: number[]; ks: number[]; repeats: number; methods: Record<string, string>; limits: string };
};

export function decodeAdapt(raw: any): AdaptNet {                      // eslint-disable-line @typescript-eslint/no-explicit-any
  const layers = Object.fromEntries(Object.entries(raw.layers as Record<string, { shape: number[]; w: string; b: string }>)
    .map(([k, l]) => [k, { shape: l.shape, w: f32(l.w), b: f32(l.b) }]));
  const bn = raw.bn.map((b: Record<string, string | number>) => ({ gamma: f32(b.gamma as string), beta: f32(b.beta as string),
    mean: f32(b.mean as string), var: f32(b.var as string), eps: b.eps as number }));
  const adabn = raw.adabn.map((b: Record<string, string>) => ({ mean: f32(b.mean), var: f32(b.var) }));
  return { ...raw, layers, bn, adabn } as AdaptNet;
}

/** 3x3 convolution, padding 1, no activation. */
function conv(x: Float32Array, C: number, H: number, W: number, l: Layer) {
  const O = l.shape[0], y = new Float32Array(O * H * W);
  for (let o = 0; o < O; o++) {
    const yo = o * H * W;
    y.fill(l.b[o], yo, yo + H * W);
    for (let c = 0; c < C; c++) {
      const xc = c * H * W, wk = (o * C + c) * 9;
      for (let ky = 0; ky < 3; ky++) for (let kx = 0; kx < 3; kx++) {
        const w = l.w[wk + ky * 3 + kx];
        if (w === 0) continue;
        const dy = ky - 1, dx = kx - 1;
        for (let i = Math.max(0, -dy); i < Math.min(H, H - dy); i++) {
          const yr = yo + i * W, xr = xc + (i + dy) * W + dx;
          for (let j = Math.max(0, -dx); j < Math.min(W, W - dx); j++) y[yr + j] += w * x[xr + j];
        }
      }
    }
  }
  return y;
}

function pool(x: Float32Array, C: number, H: number, W: number) {
  const h = H >> 1, w = W >> 1, y = new Float32Array(C * h * w);
  for (let c = 0; c < C; c++) for (let i = 0; i < h; i++) for (let j = 0; j < w; j++) {
    const a = c * H * W + 2 * i * W + 2 * j;
    y[c * h * w + i * w + j] = Math.max(x[a], x[a + 1], x[a + W], x[a + W + 1]);
  }
  return y;
}

function linear(x: Float32Array, l: Layer) {
  const [O, I] = l.shape, y = new Float32Array(O);
  for (let o = 0; o < O; o++) { let s = l.b[o]; for (let i = 0; i < I; i++) s += l.w[o * I + i] * x[i]; y[o] = s; }
  return y;
}
const softmax = (z: Float32Array) => { const m = Math.max(...z), e = Array.from(z, (v) => Math.exp(v - m)), s = e.reduce((a, b) => a + b, 0); return e.map((v) => v / s); };

/** One frame's per-channel mean and mean square at each batch norm's input. */
export type Moments = { m: Float32Array; s: Float32Array }[];

/** Forward pass with batch norms using `stats` (per layer mean/var); also returns the frame's
    moments at every batch norm, for the online estimator. image: 3 x N x N, 0..1. */
export function forwardBn(net: AdaptNet, image: Float32Array, stats: Stats[]) {
  const N = net.size, L = net.layers, moments: Moments = [];
  let x = image;
  const g = [0, 1, 2].map((c) => {
    let a = 0;
    for (let i = 0; i < net.ref; i++) for (let j = 0; j < net.ref; j++) a += image[c * N * N + i * N + j];
    return a / (net.ref * net.ref);
  });
  x = image.map((v, k) => v * (0.5 / (g[Math.floor(k / (N * N))] + 1e-3)) - 0.5);
  const block = (x: Float32Array, C: number, H: number, l: Layer, i: number) => {
    const y = conv(x, C, H, H, l), O = l.shape[0], HW = H * H, b = net.bn[i], st = stats[i];
    const m = new Float32Array(O), s = new Float32Array(O);
    for (let o = 0; o < O; o++) {
      let a = 0, q = 0;
      for (let k = 0; k < HW; k++) { const v = y[o * HW + k]; a += v; q += v * v; }
      m[o] = a / HW; s[o] = q / HW;
      const sc = b.gamma[o] / Math.sqrt(st.var[o] + b.eps), sh = b.beta[o] - st.mean[o] * sc;
      for (let k = 0; k < HW; k++) { const v = y[o * HW + k] * sc + sh; y[o * HW + k] = v > 0 ? v : 0; }
    }
    moments.push({ m, s });
    return y;
  };
  x = pool(block(x, 3, N, L.c1, 0), 16, N, N);
  x = pool(block(x, 16, N / 2, L.c2, 1), 32, N / 2, N / 2);
  x = pool(block(x, 32, N / 4, L.c3, 2), 64, N / 4, N / 4);
  const s = N / 8, h = block(x, 64, s, L.c4, 3), gap = new Float32Array(64);
  for (let c = 0; c < 64; c++) { let a = 0; for (let k = 0; k < s * s; k++) a += h[c * s * s + k]; gap[c] = a / (s * s); }
  const f = linear(gap, L.fc).map((v) => Math.max(0, v));
  const lf = linear(f, L.flav), lc = linear(f, L.cond);
  return { flavourLogits: lf, conditionLogits: lc, flavour: softmax(lf), condition: softmax(lc), moments };
}

export const PRIOR = 8, WINDOW = 300;

/** Online AdaBN: running per-channel mean and mean square at each batch norm. */
export class OnlineBn {
  n = 0;
  private m: Float64Array[]; private s: Float64Array[];
  constructor(private net: AdaptNet) {
    this.m = net.bn.map((b) => Float64Array.from(b.mean));
    this.s = net.bn.map((b) => Float64Array.from(b.var, (v, i) => v + b.mean[i] ** 2));
  }
  /** The statistics to normalise with now. */
  stats(): Stats[] {
    return this.m.map((m, i) => ({ mean: Float32Array.from(m), var: Float32Array.from(m, (v, c) => Math.max(1e-6, this.s[i][c] - v * v)) }));
  }
  /** Add one frame's moments: a weighted average with the prior, then a moving average. */
  add(mo: Moments) {
    this.n++;
    const w = 1 / Math.min(this.n + PRIOR, WINDOW);
    mo.forEach(({ m, s }, i) => {
      for (let c = 0; c < m.length; c++) { this.m[i][c] += w * (m[c] - this.m[i][c]); this.s[i][c] += w * (s[c] - this.s[i][c]); }
    });
  }
  /** How far the statistics have moved from training: mean |shift| of the first layer, in training std units. */
  shift() {
    const b = this.net.bn[0];
    let a = 0;
    for (let c = 0; c < b.mean.length; c++) a += Math.abs(this.m[0][c] - b.mean[c]) / Math.sqrt(b.var[c] + b.eps);
    return a / b.mean.length;
  }
}

export function verdictOf(net: AdaptNet, p: number[]): "pass" | "reject" | "check" {
  if (Math.max(...p) < net.sure_p) return "check";
  return p[net.classes.condition.indexOf("ok")] >= net.pass_p ? "pass" : "reject";
}
