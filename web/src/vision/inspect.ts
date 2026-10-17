// The inspection, in the twin: the models judge each photo the camera in the colour hood takes,
// and the verdict goes to the cell (store.decide), which acts on it - a cookie that does not pass
// is not ejected to its Lagerstelle but held at the end of the line. Vision that steers the
// machine: the camera sees, the CNN decides, the sorting line does what it decided.
//
// The same models and the same preparation as the dashboard's Vision QC (vision/twinCamera.ts):
// the cookie found against the empty hood, the rest set to the belt's colour, then the CNN's
// condition (pass only when "ok" is at least pass_p sure; an unsure cookie goes to a person) and
// the autoencoder's anomaly score.
import { aeScore, decodeAe, type Ae } from "./ae";
import { decode, forward, verdict, type Cnn } from "./cnn";
import { chw, type RenderParams } from "./render";
import { prepare } from "./twinCamera";
import { loadJson } from "../shared/data";
import type { Verdict } from "../scene/store/useCellStore";

type Models = { cnn: Cnn; ae: Ae; P: RenderParams };
let models: Promise<Models> | null = null;

/** The models, loaded once, on the first photo. */
function load(): Promise<Models> {
  models ??= Promise.all([loadJson("vision/weights.json"), loadJson("vision/autoencoder.json"), loadJson<RenderParams>("vision/render.json")])
    .then(([w, a, P]) => ({ cnn: decode(w as never), ae: decodeAe(a as never), P }));
  return models;
}

/** Judge camera shot `n`: its photo and the empty hood's reference image. */
export async function judge(n: number, jpeg: Blob, empty: Blob | null): Promise<Verdict> {
  const { cnn, ae, P } = await load();
  const { img } = await prepare({ jpeg, empty }, P.N, P.REF);
  const x = chw(img, P.N);
  const c = forward(cnn, x);
  const ci = c.condition.indexOf(Math.max(...c.condition)), fi = c.flavour.indexOf(Math.max(...c.flavour));
  const a = aeScore(ae, x);
  return {
    n, verdict: verdict(cnn, c.condition), condition: cnn.classes.condition[ci], p: c.condition[ci],
    flavour: cnn.classes.flavour[fi], ae: a.score / ae.threshold, anomaly: a.score > ae.threshold,
  };
}
