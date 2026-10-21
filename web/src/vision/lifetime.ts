// How the two inspection models hold up over a year on the line, and where they are heading.
//
// The line ages under the camera: the ring light loses brightness, the belt's rubber wears
// lighter, the sensor gets noisier. Each week of operation is a test batch drawn by the
// renderer (render.ts) in that week's conditions - half good cookies, half damaged ones - and
// judged by the deployed models themselves: the CNN (supervised: is it ok, burnt, cracked...?)
// and the autoencoder (unsupervised: does it look like the good cookies it learnt?). What is
// measured is detection (damaged cookies caught) and false alarms (good cookies flagged).
//
// The forecast is fitted on the weeks measured so far only (a least-squares line on the logit
// of each rate, so it stays inside 0..1) and carried to the end of the year, with a
// band from the fit's residuals. Where a forecast crosses its limit is when to retrain.
import { aeScore, type Ae } from "./ae";
import { forward, verdict, type Cnn } from "./cnn";
import { Rng, chw, render, type Ranges, type RenderParams } from "./render";

export const WEEKS = 52;
/** detection more than 1 - TARGET under a model's commissioning level, or false alarms above
    FALSE_MAX, is not good enough: collect photos from the line and retrain */
export const TARGET = 0.9;
export const FALSE_MAX = 0.1;

export type Week = {
  w: number; n: number;
  cnn: { detect: number; falseAlarm: number };
  ae: { detect: number; falseAlarm: number; drift: number };
};

/** The camera's conditions after `a` of a year (0..1): light falling, belt lightening, noise rising. */
export function wear(P: RenderParams, a: number): Ranges {
  const w = P.ranges.wide, s = P.ranges.shift;
  const k = 1 - 0.5 * a;
  const mix = (x: number, y: number) => x + (y - x) * a;
  return {
    ...w,
    light: [w.light[0] * k, w.light[1] * k],
    belt: [mix(w.belt[0], s.belt[0]), mix(w.belt[1], s.belt[1])],
    noise: [mix(w.noise[0], s.noise[0]), mix(w.noise[1], s.noise[1])],
  };
}

/** One week's test batch, judged by both models. Deterministic: the same week, the same batch. */
export function measureWeek(P: RenderParams, cnn: Cnn, ae: Ae, w: number, n = 24): Week {
  const r = new Rng(9001 + w * 131);
  const R = wear(P, w / WEEKS);
  const bad = P.conditions.filter((c) => c !== "ok");
  let defects = 0, good = 0, cnnHit = 0, cnnFalse = 0, aeHit = 0, aeFalse = 0, okErr = 0;
  for (let i = 0; i < n; i++) {
    const flavour = P.flavours[i % P.flavours.length];
    const truth = i % 2 ? bad[Math.floor(r.random() * bad.length)] : "ok";
    const x = chw(render(P, flavour, truth, r, R), P.N);
    const v = verdict(cnn, forward(cnn, x).condition);
    const a = aeScore(ae, x), flagged = a.score > ae.threshold;
    // the CNN catches a damaged cookie when it does not pass it (rejected or sent to a person)
    if (truth === "ok") { good++; cnnFalse += +(v !== "pass"); aeFalse += +flagged; okErr += a.mean; }
    else { defects++; cnnHit += +(v !== "pass"); aeHit += +flagged; }
  }
  return {
    w, n,
    cnn: { detect: cnnHit / defects, falseAlarm: cnnFalse / good },
    ae: { detect: aeHit / defects, falseAlarm: aeFalse / good, drift: okErr / good / ae.ok_mean_error },
  };
}

const logit = (p: number) => Math.log(p / (1 - p));
const expit = (z: number) => 1 / (1 + Math.exp(-z));
/** how a measure is fitted: a rate on the logit scale (it stays inside 0..1), a ratio on the log scale */
const LINK = {
  rate: { f: (p: number) => logit(Math.min(0.98, Math.max(0.02, p))), inv: expit },
  ratio: { f: (r: number) => Math.log(Math.max(1e-3, r)), inv: Math.exp },
};

export type Forecast = { w: number[]; mid: number[]; lo: number[]; hi: number[]; crosses: number | null; atEnd: number };

/** Fit the measured weeks (a least-squares line on the link scale) and carry it from week `from`
    to `until`, with a 90 % prediction band. `crosses`: the first week the forecast passes `limit`
    (falling below it when `below`, rising above it otherwise). */
export function forecast(xs: number[], ys: number[], from: number,
  o: { link?: keyof typeof LINK; limit?: number; below?: boolean; until?: number } = {}): Forecast {
  const { f, inv } = LINK[o.link ?? "rate"], until = o.until ?? WEEKS, below = o.below ?? true;
  const z = ys.map(f), n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n, mz = z.reduce((a, b) => a + b, 0) / n;
  let sxx = 0, sxz = 0;
  xs.forEach((x, i) => { sxx += (x - mx) ** 2; sxz += (x - mx) * (z[i] - mz); });
  const b = sxx ? sxz / sxx : 0, a = mz - b * mx;
  const res = Math.sqrt(z.reduce((s, zi, i) => s + (zi - (a + b * xs[i])) ** 2, 0) / Math.max(1, n - 2));
  const w: number[] = [], mid: number[] = [], lo: number[] = [], hi: number[] = [];
  let crosses: number | null = null;
  for (let x = from; x <= until; x++) {
    // the band widens with distance from the data (the standard error of a prediction)
    const se = res * Math.sqrt(1 + 1 / n + (sxx ? (x - mx) ** 2 / sxx : 0));
    const m = a + b * x;
    w.push(x); mid.push(inv(m)); lo.push(inv(m - 1.64 * se)); hi.push(inv(m + 1.64 * se));
    if (crosses === null && o.limit != null && (below ? inv(m) < o.limit : inv(m) > o.limit)) crosses = x;
  }
  return { w, mid, lo, hi, crosses, atEnd: mid[mid.length - 1] };
}
