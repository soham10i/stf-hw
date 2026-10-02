// Upgrade 15: the inspection CNN, run in the browser. The same forward pass as
// stf-cad/hbw/vision/train.py (Net): four 3x3 convolutions with ReLU, 2x2 max-pool
// after the first three, global average pooling, a 64-unit layer, two heads; first, the
// image is divided by the grey reference target's reading (the light level and colour).
// Weights from public/vision/weights.json (float32, base64).

type Layer = { shape: number[]; w: Float32Array; b: Float32Array };
export type Cnn = {
  classes: { flavour: string[]; condition: string[] }; size: number; pass_p: number; sure_p: number;
  ref: number;     // the grey reference target's size in px (0: the network does not use it)
  layers: Record<"c1" | "c2" | "c3" | "c4" | "fc" | "flav" | "cond", Layer>;
};
type Raw = Omit<Cnn, "layers"> & { layers: Record<string, { shape: number[]; w: string; b: string }> };

function f32(b64: string) {
  const s = atob(b64), u = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
  return new Float32Array(u.buffer);
}

export function decode(raw: Raw): Cnn {
  const layers = Object.fromEntries(Object.entries(raw.layers).map(([k, l]) => [k, { shape: l.shape, w: f32(l.w), b: f32(l.b) }]));
  return { ...raw, layers } as Cnn;
}

/** 3x3 convolution, padding 1, then ReLU. x: C x H x W. */
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
  for (let i = 0; i < y.length; i++) if (y[i] < 0) y[i] = 0;
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

/** image: 3 x N x N, 0..1 -> logits and probabilities of both heads. */
export function forward(net: Cnn, image: Float32Array) {
  const N = net.size, L = net.layers;
  let x = image;
  if (net.ref) {                       // divide out the light: the grey target reads 0.5
    const g = [0, 1, 2].map((c) => {
      let a = 0;
      for (let i = 0; i < net.ref; i++) for (let j = 0; j < net.ref; j++) a += image[c * N * N + i * N + j];
      return a / (net.ref * net.ref);
    });
    x = image.map((v, k) => v * (0.5 / (g[Math.floor(k / (N * N))] + 1e-3)));
  }
  x = x.map((v) => v - 0.5);
  x = pool(conv(x, 3, N, N, L.c1), 16, N, N);
  x = pool(conv(x, 16, N / 2, N / 2, L.c2), 32, N / 2, N / 2);
  x = pool(conv(x, 32, N / 4, N / 4, L.c3), 64, N / 4, N / 4);
  const s = N / 8, h = conv(x, 64, s, s, L.c4), g = new Float32Array(64);
  for (let c = 0; c < 64; c++) { let a = 0; for (let k = 0; k < s * s; k++) a += h[c * s * s + k]; g[c] = a / (s * s); }
  const f = linear(g, L.fc).map((v) => Math.max(0, v));
  const lf = linear(f, L.flav), lc = linear(f, L.cond);
  return { flavourLogits: lf, conditionLogits: lc, flavour: softmax(lf), condition: softmax(lc) };
}

export type Verdict = "pass" | "reject" | "check";
/** The line's decision (vision/train.py: verdicts). */
export function verdict(net: Cnn, p: number[]): Verdict {
  if (Math.max(...p) < net.sure_p) return "check";
  return p[net.classes.condition.indexOf("ok")] >= net.pass_p ? "pass" : "reject";
}

/** Tile k of an RGBA sheet as a 3 x N x N image. */
export function tile(rgba: Uint8ClampedArray, sheetW: number, cols: number, N: number, k: number) {
  const x0 = (k % cols) * N, y0 = Math.floor(k / cols) * N, img = new Float32Array(3 * N * N);
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    const a = ((y0 + i) * sheetW + x0 + j) * 4;
    for (let c = 0; c < 3; c++) img[c * N * N + i * N + j] = rgba[a + c] / 255;
  }
  return img;
}
