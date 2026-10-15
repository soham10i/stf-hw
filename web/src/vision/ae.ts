// The autoencoder that knows only good cookies (stf-cad/hbw/vision/autoencoder.py), in the
// browser: the same forward pass, weights from public/vision/autoencoder.json. It returns the
// anomaly score (the worst patch of the error map), the mean error (the drift signal) and the
// error map itself, for the live feed's heat map.

type Layer = { shape: number[]; w: Float32Array; b: Float32Array };
export type Ae = {
  size: number; ref: number; patch: number; threshold: number; ok_mean_error: number; drift_alarm: number;
  layers: Record<"e1" | "e2" | "e3" | "e4" | "d1" | "d2" | "d3" | "d4", Layer>;
  parity: { images: string[]; scores: number[]; means: number[] };
  meta: { results: { in_domain: { auroc: number; detected: number; false_alarm: number }; shifted: { auroc: number; false_alarm: number } };
          drift_ratio: number; score: string };
};
type Raw = Omit<Ae, "layers"> & { layers: Record<string, { shape: number[]; w: string; b: string }> };

export function f32(b64: string) {
  const s = atob(b64), u = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
  return new Float32Array(u.buffer);
}

export function decodeAe(raw: Raw): Ae {
  const layers = Object.fromEntries(Object.entries(raw.layers).map(([k, l]) => [k, { shape: l.shape, w: f32(l.w), b: f32(l.b) }]));
  return { ...raw, layers } as Ae;
}

/** 3x3 convolution, padding 1; ReLU unless `linear`. x: C x H x W. */
function conv(x: Float32Array, C: number, H: number, W: number, l: Layer, linear = false) {
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
  if (!linear) for (let k = 0; k < y.length; k++) if (y[k] < 0) y[k] = 0;
  return y;
}

function pool(x: Float32Array, C: number, H: number, W: number) {
  const h = H / 2, w = W / 2, y = new Float32Array(C * h * w);
  for (let c = 0; c < C; c++) for (let i = 0; i < h; i++) for (let j = 0; j < w; j++) {
    const a = c * H * W + 2 * i * W + 2 * j;
    y[c * h * w + i * w + j] = Math.max(x[a], x[a + 1], x[a + W], x[a + W + 1]);
  }
  return y;
}

function up(x: Float32Array, C: number, H: number, W: number) {
  const y = new Float32Array(C * H * W * 4), W2 = 2 * W;
  for (let c = 0; c < C; c++) for (let i = 0; i < 2 * H; i++) for (let j = 0; j < W2; j++)
    y[c * 4 * H * W + i * W2 + j] = x[c * H * W + (i >> 1) * W + (j >> 1)];
  return y;
}

/** image: 3 x N x N, 0..1 -> anomaly score, mean error and the N x N error map. */
export function aeScore(net: Ae, image: Float32Array) {
  const N = net.size, L = net.layers, NN = N * N;
  const g = [0, 1, 2].map((c) => {
    let a = 0;
    for (let i = 0; i < net.ref; i++) for (let j = 0; j < net.ref; j++) a += image[c * NN + i * N + j];
    return a / (net.ref * net.ref);
  });
  const x = image.map((v, k) => v * (0.5 / (g[Math.floor(k / NN)] + 1e-3)) - 0.5);
  let h = pool(conv(x, 3, N, N, L.e1), 16, N, N);
  h = pool(conv(h, 16, N / 2, N / 2, L.e2), 32, N / 2, N / 2);
  h = pool(conv(h, 32, N / 4, N / 4, L.e3), 32, N / 4, N / 4);
  const s = N / 8;
  h = conv(h, 32, s, s, L.e4);
  h = conv(up(h, 8, s, s), 8, 2 * s, 2 * s, L.d1);
  h = conv(up(h, 32, 2 * s, 2 * s), 32, 4 * s, 4 * s, L.d2);
  h = conv(up(h, 16, 4 * s, 4 * s), 16, N, N, L.d3);
  const y = conv(h, 16, N, N, L.d4, true);
  const err = new Float32Array(NN);
  for (let k = 0; k < NN; k++) {
    let e = 0;
    for (let c = 0; c < 3; c++) e += (y[c * NN + k] - x[c * NN + k]) ** 2;
    err[k] = e / 3;
  }
  const mean = err.reduce((a, b) => a + b, 0) / NN;
  // the worst P x P patch (stride 2, as avg_pool2d(P, stride=2))
  const P = net.patch;
  let worst = 0;
  for (let i = 0; i + P <= N; i += 2) for (let j = 0; j + P <= N; j += 2) {
    let a = 0;
    for (let di = 0; di < P; di++) for (let dj = 0; dj < P; dj++) a += err[(i + di) * N + j + dj];
    worst = Math.max(worst, a / (P * P));
  }
  return { score: worst, mean, err };
}
