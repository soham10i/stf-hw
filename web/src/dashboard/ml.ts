// Upgrade 8: the trained network, run in the browser. The same forward pass as
// stf-cad/hbw/ml/model.py - causal dilated Conv1d x4 (zero left-padding per
// layer), ReLU, a residual from block 2, [last step, mean over time] -> ReLU(fc)
// -> sigmoid(rul) x cap and class logits. Weights from web/public/ml/weights.json.

type Conv = { w: number[][][]; b: number[]; dil: number };
type Lin = { w: number[][]; b: number[] };
export type Weights = {
  features: string[]; components: string[]; inputs: string[]; window: number; rul_cap: number; ch: number;
  r_fail: number[]; ctx_mu: number[]; ctx_sd: number[]; i_temp: number; i_vac: number; i_ot: number;
  alarm_rul: number; alarm_run: number; conv: Conv[]; fc: Lin; rul: Lin; cls: Lin;
};

function conv(x: Float32Array[], c: Conv): Float32Array[] {
  const T = x[0].length, out: Float32Array[] = [];
  const pad = 2 * c.dil;
  for (let o = 0; o < c.w.length; o++) {
    const y = new Float32Array(T).fill(c.b[o]);
    const wo = c.w[o];
    for (let i = 0; i < x.length; i++) {
      const xi = x[i], w = wo[i];
      for (let k = 0; k < 3; k++) {
        const wk = w[k], off = k * c.dil - pad;
        if (wk === 0) continue;
        for (let t = Math.max(0, -off); t < T; t++) y[t] += wk * xi[t + off];
      }
    }
    out.push(y);
  }
  return out;
}

const relu = (a: Float32Array[]) => { for (const r of a) for (let i = 0; i < r.length; i++) if (r[i] < 0) r[i] = 0; return a; };

function linear(x: number[], l: Lin) {
  return l.w.map((row, o) => row.reduce((s, w, i) => s + w * x[i], l.b[o]));
}

/** One window (inputs x time) -> remaining life (orders) and class probabilities. */
export function forward(W: Weights, x: Float32Array[]): { rul: number; p: number[] } {
  const h1 = relu(conv(x, W.conv[0]));
  const h2 = relu(conv(h1, W.conv[1]));
  const h3 = relu(conv(h2, W.conv[2]));
  const h4 = relu(conv(h3, W.conv[3]));
  const T = h4[0].length;
  const z: number[] = [];
  for (let c = 0; c < h4.length; c++) { h4[c] = h4[c].map((v, t) => v + h2[c][t]); z.push(h4[c][T - 1]); }
  for (let c = 0; c < h4.length; c++) z.push(h4[c].reduce((a, b) => a + b, 0) / T);
  const f = linear(z, W.fc).map((v) => Math.max(0, v));
  const rul = W.rul_cap / (1 + Math.exp(-linear(f, W.rul)[0]));
  const lg = linear(f, W.cls);
  const m = Math.max(...lg), e = lg.map((v) => Math.exp(v - m)), s = e.reduce((a, b) => a + b, 0);
  return { rul, p: e.map((v) => v / s) };
}

/** Build component c's input window ending at order t from the raw per-order features. */
export function buildWindow(W: Weights, X: number[][], c: number, t: number): Float32Array[] {
  const T = W.window, n = W.inputs.length;
  const ch = Array.from({ length: n }, () => new Float32Array(T));
  for (let j = 0; j < T; j++) {
    const row = X[Math.max(0, t - T + 1 + j)];
    ch[0][j] = (row[c] - 1) / (W.r_fail[c] - 1);
    ch[1][j] = (row[W.i_temp] - W.ctx_mu[0]) / W.ctx_sd[0];
    ch[2][j] = row[W.i_vac];
    ch[3][j] = (row[W.i_ot] - W.ctx_mu[1]) / W.ctx_sd[1];
    ch[4 + c][j] = 1;
  }
  return ch;
}

export function predictAt(W: Weights, X: number[][], t: number) {
  return W.components.map((_, c) => forward(W, buildWindow(W, X, c, t)));
}
