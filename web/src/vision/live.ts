// The live inspection feed: every cookie the 3D twin bakes is photographed by the camera in the
// colour hood (vision/mount.py), classified by the CNN and scored by the autoencoder, and
// compared with what the simulation knows to be true - the check that the models still work.
// The twin bakes every cookie right unless a fault is injected (the Orders panel, QC testing),
// and that injected fault is the photo's truth.

import { aeScore, type Ae } from "./ae";
import { forward, verdict, type Cnn, type Verdict } from "./cnn";
import { chw, type RenderParams } from "./render";

export type Frame = {
  n: number; t: number;
  flavour: string; truth: string; img: Float32Array;
  /** the twin camera's photo itself (an object URL), where the image is one */
  photo?: string;
  pred: { flavour: string; condition: string; pf: number; pc: number; verdict: Verdict };
  ae: { score: number; mean: number; err: Float32Array; anomaly: boolean };
};

export class LiveLine {
  private n = 0;
  constructor(private P: RenderParams, private cnn: Cnn, private ae: Ae) {}

  /** Judge a photo the twin's camera took (N x N x 3, 0..1): a cookie of `flavour`, in the
      condition the simulation gave it (`truth`: ok, or the fault injected from the Orders panel). */
  inspect(img: Float32Array, flavour: string, passP?: number, truth = "ok"): Frame {
    return this.judge(img, flavour, truth, passP);
  }

  private judge(img: Float32Array, flavour: string, truth: string, passP?: number): Frame {
    const x = chw(img, this.P.N);
    const c = forward(this.cnn, x);
    const fi = c.flavour.indexOf(Math.max(...c.flavour)), ci = c.condition.indexOf(Math.max(...c.condition));
    const a = aeScore(this.ae, x);
    return {
      n: ++this.n, t: Date.now(), flavour, truth, img,
      pred: { flavour: this.cnn.classes.flavour[fi], condition: this.cnn.classes.condition[ci], pf: c.flavour[fi], pc: c.condition[ci],
              verdict: verdict(passP ? { ...this.cnn, pass_p: passP } : this.cnn, c.condition) },
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
