// Trustworthy maintenance T4: the TCN in this browser - the TypeScript forward pass (dashboard/ml.ts)
// against the WebGPU kernel (edge/tcnGpu.ts), on the dashboard's own month (ml/month_inputs.json).
// Latency for one window and for one order (every part), throughput for the whole month, and the
// largest difference between the two answers. Run by the dashboard's Edge card and, for the
// published numbers, by scripts/edge-bench.mjs in headless Chrome.
import { buildWindow, forward, type Weights } from "../dashboard/ml";
import { flatten, gpuTcn } from "./tcnGpu";

export type Lat = { p50_us: number; p99_us: number };
export type BenchResult = {
  adapter: string | null; userAgent: string; windows: number; orders: number;
  ts: { window: Lat; order: Lat; windows_per_s: number };
  gpu: null | { tile: number; window: Lat; order: Lat; windows_per_s: number; month_ms: number; max_abs_rul_diff: number; max_abs_p_diff: number }[];
  gpu_error?: string;
};

const pct = (a: number[], q: number) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(q * s.length))]; };
const lat = (a: number[]): Lat => ({ p50_us: +(pct(a, 0.5) * 1e3).toFixed(1), p99_us: +(pct(a, 0.99) * 1e3).toFixed(1) });

async function times(fn: () => unknown | Promise<unknown>, n: number, warm = 20) {
  for (let i = 0; i < warm; i++) await fn();
  const out: number[] = [];
  for (let i = 0; i < n; i++) { const a = performance.now(); await fn(); out.push(performance.now() - a); }
  return out;
}

export async function bench(W: Weights, X: number[][], opts: { n?: number; tiles?: number[]; onStep?: (s: string) => void } = {}): Promise<BenchResult> {
  const n = opts.n ?? 300, say = opts.onStep ?? (() => {});
  const C = W.components.length, NIN = W.inputs.length, T = W.window, size = NIN * T;
  const orders = X.length, N = orders * C;
  // every window of the month, flat, order-major: the C parts of order t are rows t*C .. t*C+C-1
  say("building the month's windows");
  const flat = new Float32Array(N * size);
  const wins: Float32Array[][] = [];
  for (let t = 0; t < orders; t++)
    for (let c = 0; c < C; c++) {
      const w = buildWindow(W, X, c, t);
      flatten(w, flat, (t * C + c) * size);
      if (t === Math.floor(orders / 2)) wins.push(w);
    }
  const mid = Math.floor(orders / 2);
  say("TypeScript forward pass");
  const tsWin = await times(() => forward(W, wins[0]), n);
  const tsOrd = await times(() => wins.map((w) => forward(W, w)), Math.max(30, n / 5));
  const sample = Math.min(N, 3000);
  const ref = new Float32Array(N * 4);
  const a = performance.now();
  for (let i = 0; i < N; i++) {
    const t = Math.floor(i / C), c = i % C;
    if (i >= sample && i % Math.ceil(N / sample) !== 0) continue;          // a spread sample for parity
    const r = forward(W, buildWindow(W, X, c, t));
    ref[i * 4] = r.rul; ref.set(r.p, i * 4 + 1);
  }
  const tsSecs = (performance.now() - a) / 1e3;
  const counted = Array.from({ length: N }, (_, i) => i < sample || i % Math.ceil(N / sample) === 0).filter(Boolean).length;
  const out: BenchResult = {
    adapter: null, userAgent: navigator.userAgent, windows: N, orders,
    ts: { window: lat(tsWin), order: lat(tsOrd), windows_per_s: Math.round(counted / tsSecs) },
    gpu: null,
  };
  for (const tile of opts.tiles ?? [1, 4]) {
    let g;
    try { g = await gpuTcn(W, tile); } catch (e) { out.gpu_error = String(e); break; }
    if (!g) { out.gpu_error = "WebGPU is not available in this browser"; break; }
    out.adapter = g.adapter;
    say(`WebGPU kernel, tile ${tile}`);
    const one = flat.subarray(mid * C * size, mid * C * size + size);
    const ord = flat.subarray(mid * C * size, (mid + 1) * C * size);
    const gWin = await times(() => g.run(one, 1), n);
    const gOrd = await times(() => g.run(ord, C), n);
    await g.run(flat, N);                                                   // warm the large buffers
    const b = performance.now();
    const y = await g.run(flat, N);
    const monthMs = performance.now() - b;
    let dr = 0, dp = 0;
    for (let i = 0; i < N; i++) {
      if (!(i < sample || i % Math.ceil(N / sample) === 0)) continue;
      dr = Math.max(dr, Math.abs(y[i * 4] - ref[i * 4]));
      for (let k = 1; k < 4; k++) dp = Math.max(dp, Math.abs(y[i * 4 + k] - ref[i * 4 + k]));
    }
    (out.gpu ??= []).push({ tile, window: lat(gWin), order: lat(gOrd), windows_per_s: Math.round(N / (monthMs / 1e3)),
      month_ms: +monthMs.toFixed(1), max_abs_rul_diff: +dr.toExponential(2), max_abs_p_diff: +dp.toExponential(2) });
    g.destroy();
  }
  return out;
}
