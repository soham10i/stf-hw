// The live inspection feed: every cookie the line makes is photographed by the camera in the
// colour hood (vision/mount.py), classified by the CNN and scored by the autoencoder, and
// compared with what the simulation knows to be true - the check that the models still work.
//
// No real camera: the images are drawn by the renderer (render.ts) from the cookie's flavour
// and a condition the simulation injects at the chosen defect rate. The scenarios move the
// conditions out of the training ranges, as a real line drifts.

import { aeScore, type Ae } from "./ae";
import { forward, verdict, type Cnn, type Verdict } from "./cnn";
import { Rng, chw, render, type Ranges, type RenderParams } from "./render";

export const SCENARIOS = {
  hood: { label: "Inside the hood (as trained)", say: "The hood's controlled light: the conditions the models were trained in." },
  lamp: { label: "Ring light ageing", say: "The LEDs lose brightness with age: the light level falls below the training range." },
  warm: { label: "Warmer lamp", say: "A replacement ring light with a warmer colour than in training." },
  belt: { label: "Worn belt", say: "The belt's rubber wears lighter than anything in training." },
  unseen: { label: "Everything unseen", say: "All of the unseen conditions of the CNN's test at once (the SHIFT images)." },
} as const;
export type Scenario = keyof typeof SCENARIOS;

export type Frame = {
  n: number; t: number; source: "twin" | "line"; scenario: Scenario;
  flavour: string; truth: string; img: Float32Array;
  pred: { flavour: string; condition: string; pf: number; pc: number; verdict: Verdict };
  ae: { score: number; mean: number; err: Float32Array; anomaly: boolean };
};

function ranges(P: RenderParams, s: Scenario, age: number): Ranges {
  const w = P.ranges.wide;
  if (s === "unseen") return P.ranges.shift;
  if (s === "lamp") { const k = 1 - 0.55 * age; return { ...w, light: [w.light[0] * k, w.light[1] * k] }; }
  if (s === "warm") return { ...w, warm: true };
  if (s === "belt") return { ...w, belt: P.ranges.shift.belt };
  return w;
}

export class LiveLine {
  private rng: Rng;
  private n = 0;
  constructor(private P: RenderParams, private cnn: Cnn, private ae: Ae, seed = 15) { this.rng = new Rng(seed); }

  /** Photograph one cookie of `flavour`; `defect` = probability that the simulation spoils it. */
  capture(flavour: string, o: { scenario: Scenario; defect: number; age: number; source: "twin" | "line" }): Frame {
    const P = this.P, r = this.rng;
    const bad = P.conditions.filter((c) => c !== "ok");
    const truth = r.random() < o.defect ? bad[Math.floor(r.random() * bad.length)] : "ok";
    const img = render(P, flavour, truth, r, ranges(P, o.scenario, o.age));
    const x = chw(img, P.N);
    const c = forward(this.cnn, x);
    const fi = c.flavour.indexOf(Math.max(...c.flavour)), ci = c.condition.indexOf(Math.max(...c.condition));
    const a = aeScore(this.ae, x);
    return {
      n: ++this.n, t: Date.now(), source: o.source, scenario: o.scenario, flavour, truth, img,
      pred: { flavour: this.cnn.classes.flavour[fi], condition: this.cnn.classes.condition[ci], pf: c.flavour[fi], pc: c.condition[ci],
              verdict: verdict(this.cnn, c.condition) },
      ae: { score: a.score, mean: a.mean, err: a.err, anomaly: a.score > this.ae.threshold },
    };
  }
}

/** How the inspection went, over a list of frames. */
export function tally(frames: Frame[], conditions: string[]) {
  const cm = conditions.map(() => conditions.map(() => 0));
  let right = 0, flavRight = 0, escapes = 0, defects = 0, falseRejects = 0, good = 0, toPerson = 0, aeHits = 0, aeFalse = 0;
  for (const f of frames) {
    const t = conditions.indexOf(f.truth), p = conditions.indexOf(f.pred.condition);
    cm[t][p]++;
    right += +(t === p);
    flavRight += +(f.pred.flavour === f.flavour);
    toPerson += +(f.pred.verdict === "check");
    if (f.truth === "ok") { good++; falseRejects += +(f.pred.verdict === "reject"); aeFalse += +f.ae.anomaly; }
    else { defects++; escapes += +(f.pred.verdict === "pass"); aeHits += +f.ae.anomaly; }
  }
  const n = frames.length || 1;
  return {
    n: frames.length, cm, accuracy: right / n, flavourAcc: flavRight / n, toPerson: toPerson / n,
    escape: defects ? escapes / defects : 0, falseReject: good ? falseRejects / good : 0, defects, good,
    aeDetect: defects ? aeHits / defects : 0, aeFalse: good ? aeFalse / good : 0,
  };
}

/** The drift signal: the mean reconstruction error of recent GOOD-looking frames, against the
    autoencoder's good-cookie baseline. Above 2x: the line no longer looks like training. */
export function drift(frames: Frame[], ae: Ae, window = 20) {
  const recent = frames.filter((f) => !f.ae.anomaly).slice(-window);
  if (!recent.length) return 1;
  return recent.reduce((a, f) => a + f.ae.mean, 0) / recent.length / ae.ok_mean_error;
}

/** The twin and the dashboard share captures across tabs: the twin says which cookie it baked. */
export const CHANNEL = "stf-vision";
