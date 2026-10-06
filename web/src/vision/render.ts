// The inspection camera's image of a cookie, drawn in the browser: a line-for-line port of
// stf-cad/hbw/vision/render.py, with its numbers from public/vision/render.json. The live
// feed (vision/live.ts) photographs each cookie the line makes with it. The port is checked
// where it matters: the trained CNN must score these images as it scored Python's
// (web/scripts/vision-live-check.ts).

export type Ranges = {
  light: number[]; tint: number; noise: [number, number]; blur: [number, number]; motion: [number, number];
  belt: [number, number]; jitter: number; warm: boolean;
};
export type RenderParams = {
  N: number; MM: number; REF: number; belt: string; wp_d: number; dough: number[];
  colour: Record<string, number[]>; flavours: string[]; conditions: string[];
  ranges: Record<"narrow" | "wide" | "shift", Ranges>;
};

/** A seeded generator: uniform and standard normal draws (mulberry32 + Box-Muller). */
export class Rng {
  private s: number;
  private spare: number | null = null;
  constructor(seed: number) { this.s = seed >>> 0; }
  random() {
    let t = (this.s += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  u(a: number, b: number) { return a + (b - a) * this.random(); }
  normal() {
    if (this.spare !== null) { const v = this.spare; this.spare = null; return v; }
    let a = 0, b = 0;
    while (a === 0) a = this.random();
    b = this.random();
    const r = Math.sqrt(-2 * Math.log(a));
    this.spare = r * Math.sin(2 * Math.PI * b);
    return r * Math.cos(2 * Math.PI * b);
  }
}

const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);

/** Separable Gaussian blur, sigma in px; img is N x N x 3 (row-major, channel last). */
function blur(img: Float32Array, N: number, s: number) {
  if (s <= 0.05) return img;
  const r = Math.max(1, Math.floor(3 * s));
  const k: number[] = [];
  for (let i = -r; i <= r; i++) k.push(Math.exp(-0.5 * (i / s) ** 2));
  const sum = k.reduce((a, b) => a + b, 0);
  for (let i = 0; i < k.length; i++) k[i] /= sum;
  const tmp = new Float32Array(img.length), out = new Float32Array(img.length);
  const at = (a: Float32Array, y: number, x: number, c: number) =>
    a[(Math.min(N - 1, Math.max(0, y)) * N + Math.min(N - 1, Math.max(0, x))) * 3 + c];
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) for (let c = 0; c < 3; c++) {
    let a = 0;
    for (let i = -r; i <= r; i++) a += k[i + r] * at(img, y + i, x, c);
    tmp[(y * N + x) * 3 + c] = a;
  }
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) for (let c = 0; c < 3; c++) {
    let a = 0;
    for (let i = -r; i <= r; i++) a += k[i + r] * at(tmp, y, x + i, c);
    out[(y * N + x) * 3 + c] = a;
  }
  return out;
}

/** The belt moves along x during the exposure. */
function motion(img: Float32Array, N: number, px: number) {
  const n = Math.round(px);
  if (n < 1) return img;
  const out = new Float32Array(img.length);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) for (let c = 0; c < 3; c++) {
    let a = 0;
    for (let i = -n; i <= n; i++) a += img[(y * N + Math.min(N - 1, Math.max(0, x + i))) * 3 + c];
    out[(y * N + x) * 3 + c] = a / (2 * n + 1);
  }
  return out;
}

/** One camera image (N x N x 3, 0..1, channel last) of a cookie of a flavour in a condition. */
export function render(P: RenderParams, flavour: string, condition: string, rng: Rng, R: Ranges): Float32Array {
  const N = P.N, PX = N / P.MM, u = (a: number, b: number) => rng.u(a, b);
  const img = new Float32Array(N * N * 3);
  // the belt: dark rubber, a fine texture and the lateral ribs
  const beltL = u(R.belt[0], R.belt[1]), belt = hex(P.belt).map((v) => v * beltL);
  const ribOff = u(0, 8);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const t = rng.normal() * 0.015, rib = Math.sin(((x + ribOff) * 2 * Math.PI) / 8) > 0.6 ? 0.02 : 0;
    for (let c = 0; c < 3; c++) img[(y * N + x) * 3 + c] = belt[c] + t + rib;
  }
  // the cookie: a shallow dome, its colour from the bake
  const cx = N / 2 + u(-R.jitter, R.jitter), cy = N / 2 + u(-R.jitter, R.jitter);
  const rad = (P.wp_d / 2) * PX * u(0.92, 1.08), rot = u(0, 2 * Math.PI);
  const bake = condition === "underbaked" ? u(0.15, 0.55) : condition === "burnt" ? 1.0 : u(0.9, 1.0);
  let base = P.dough.map((d, c) => d + (P.colour[flavour][c] - d) * bake);
  if (condition === "burnt") { const k = u(0.35, 0.55); base = base.map((v) => v * k); }
  const rimAt = condition === "burnt" ? u(0.6, 0.75) : 0;
  let crack: null | { ax: number; ay: number; f: number; ph: number; w: number; len: number; k: number } = null;
  if (condition === "cracked") {
    crack = { ax: Math.cos(rot), ay: Math.sin(rot), f: u(0.4, 0.8), ph: u(0, 6), w: u(0.8, 1.6),
              len: rad * u(0.6, 0.95), k: u(0.25, 0.45) };
  }
  let bite: null | { bx: number; by: number; r: number } = null;
  if (condition === "chipped") bite = { bx: cx + Math.cos(rot) * rad, by: cy + Math.sin(rot) * rad, r: rad * u(0.3, 0.5) };
  const inside = new Uint8Array(N * N), col = new Float32Array(N * N * 3);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const dx = x - cx, dy = y - cy, d = Math.sqrt(dx * dx + dy * dy) / rad, i = y * N + x;
    let ins = d <= 1;
    const shade = 1 - 0.35 * d * d, crumb = 1 + rng.normal() * 0.04;
    for (let c = 0; c < 3; c++) col[i * 3 + c] = base[c] * shade * crumb;
    if (condition === "burnt") { const rim = Math.min(1, Math.max(0, (d - rimAt) / 0.3)); for (let c = 0; c < 3; c++) col[i * 3 + c] *= 1 - 0.7 * rim; }
    if (condition === "underbaked") { const g = 0.12 * Math.min(1, Math.max(0, 1 - d / 0.5)); for (let c = 0; c < 3; c++) col[i * 3 + c] += g; }
    if (crack) {
      const along = dx * crack.ax + dy * crack.ay, across = -dx * crack.ay + dy * crack.ax;
      const wig = 1.6 * Math.sin(along * crack.f + crack.ph);
      if (Math.abs(across - wig) < crack.w && Math.abs(along) < crack.len) for (let c = 0; c < 3; c++) col[i * 3 + c] *= crack.k;
    }
    if (bite && Math.hypot(x - bite.bx, y - bite.by) < bite.r) ins = false;
    inside[i] = ins ? 1 : 0;
  }
  // the grey reference target, then a soft shadow on the belt, then the cookie
  for (let y = 0; y < P.REF; y++) for (let x = 0; x < P.REF; x++) for (let c = 0; c < 3; c++) img[(y * N + x) * 3 + c] = 0.5;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const i = y * N + x;
    const sh = Math.hypot(x - cx - 2, y - cy - 2) / rad <= 1.05;
    if (sh && !inside[i]) for (let c = 0; c < 3; c++) img[i * 3 + c] *= 0.7;
    if (inside[i]) for (let c = 0; c < 3; c++) img[i * 3 + c] = col[i * 3 + c];
  }
  // the light: level and colour; a highlight on the dome
  const L = R.light.length === 2 ? u(R.light[0], R.light[1]) : (rng.random() < 0.5 ? u(R.light[0], R.light[1]) : u(R.light[2], R.light[3]));
  let tint = [0, 1, 2].map(() => 1 + u(-R.tint, R.tint));
  if (R.warm) tint = [tint[0] * 1.08, tint[1], tint[2] * 0.9];
  const hx = cx - rad * 0.35, hy = cy - rad * 0.35;
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    const i = y * N + x;
    for (let c = 0; c < 3; c++) img[i * 3 + c] *= L * tint[c];
    if (inside[i]) {
      const h = 0.08 * Math.exp(-((x - hx) ** 2 + (y - hy) ** 2) / (rad * 0.3) ** 2);
      for (let c = 0; c < 3; c++) img[i * 3 + c] += h;
    }
  }
  // the optics and the sensor
  let out = motion(blur(img, N, u(R.blur[0], R.blur[1])), N, u(R.motion[0], R.motion[1]));
  const nz = u(R.noise[0], R.noise[1]);
  out = out.map((v) => Math.min(1, Math.max(0, v + rng.normal() * nz)));
  return out;
}

/** N x N x 3 (channel last) -> 3 x N x N (channel first), the CNN's input. */
export function chw(img: Float32Array, N: number) {
  const o = new Float32Array(3 * N * N);
  for (let i = 0; i < N * N; i++) for (let c = 0; c < 3; c++) o[c * N * N + i] = img[i * 3 + c];
  return o;
}

/** N x N x 3 -> RGBA for a canvas. */
export function rgba(img: Float32Array, N: number) {
  const o = new Uint8ClampedArray(N * N * 4);
  for (let i = 0; i < N * N; i++) { for (let c = 0; c < 3; c++) o[i * 4 + c] = img[i * 3 + c] * 255 + 0.5; o[i * 4 + 3] = 255; }
  return o;
}
