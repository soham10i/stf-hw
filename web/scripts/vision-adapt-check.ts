// Upgrade 15 step 3, in the browser: (1) the batch-norm forward pass (src/vision/adapt.ts)
// against PyTorch, for the source network and the AdaBN one; (2) the online estimator, fed
// the browser renderer's frames of the new line one at a time as the live feed does, must
// reach what Python's AdaBN reached; (3) it must not hurt the old line once it is back.
//   node .cache/vision-adapt-check.mjs public/vision [frames]
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { f32 } from "../src/vision/ae";
import { OnlineBn, decodeAdapt, forwardBn, verdictOf, type AdaptNet } from "../src/vision/adapt";
import { Rng, chw, render, type Ranges, type RenderParams } from "../src/vision/render";

const dir = process.argv[2], n = Number(process.argv[3] ?? 600);
const net: AdaptNet = decodeAdapt(JSON.parse(readFileSync(join(dir, "adapt.json"), "utf8")));
const P: RenderParams = JSON.parse(readFileSync(join(dir, "render.json"), "utf8"));
const src = net.bn.map((b) => ({ mean: b.mean, var: b.var }));
const fails: string[] = [];

// 1 parity with PyTorch
let err = 0;
net.parity.images.forEach((b64, i) => {
  for (const [stats, ref] of [[src, net.parity.source[i]], [net.adabn, net.parity.adabn[i]]] as const) {
    const o = forwardBn(net, f32(b64), stats);
    [o.flavourLogits, o.conditionLogits].forEach((z, h) => z.forEach((v, j) => { err = Math.max(err, Math.abs(v - ref[h][j])); }));
  }
});
if (err > 1e-3) fails.push(`PARITY: max |logit difference| ${err} > 1e-3`);

// a stream as the line delivers it: flavours in turn, 15 % defects
function frames(k: number, seed: number, R: Ranges) {
  const rng = new Rng(seed), out: { x: Float32Array; c: number }[] = [];
  for (let i = 0; i < k; i++) {
    const c = rng.random() < 0.15 ? 1 + Math.floor(rng.random() * (P.conditions.length - 1)) : 0;
    out.push({ x: chw(render(P, P.flavours[i % P.flavours.length], P.conditions[c], rng, R), P.N), c });
  }
  return out;
}
function score(fs: { x: Float32Array; c: number }[], stats: () => ReturnType<OnlineBn["stats"]>, add?: (o: ReturnType<typeof forwardBn>) => void) {
  let right = 0, fr = 0, good = 0, esc = 0, bad = 0;
  for (const f of fs) {
    const o = forwardBn(net, f.x, stats());
    const pc = o.condition.indexOf(Math.max(...o.condition)), v = verdictOf(net, o.condition);
    right += +(pc === f.c);
    if (f.c === 0) { good++; fr += +(v === "reject"); } else { bad++; esc += +(v === "pass"); }
    add?.(o);
  }
  return { right: right / fs.length, false_reject: fr / Math.max(1, good), escape: esc / Math.max(1, bad) };
}

// 2 the live estimator on the new line, then frozen and tested on fresh frames
const online = new OnlineBn(net);
const during = score(frames(n, 77, P.ranges.shift), () => online.stats(), (o) => online.add(o.moments));
const test = frames(n, 78, P.ranges.shift);
const res = { source: score(test, () => src), python_adabn: score(test, () => net.adabn), online: score(test, () => online.stats()), during };
if (Math.abs(res.online.right - res.python_adabn.right) > 0.04) fails.push(`ONLINE: ${res.online.right.toFixed(3)} vs Python AdaBN ${res.python_adabn.right.toFixed(3)}`);

// 3 the line goes back to the old conditions: the estimator follows it back
const back = new OnlineBn(net);
score(frames(n, 79, P.ranges.shift), () => back.stats(), (o) => back.add(o.moments));
const old = frames(n, 80, P.ranges.wide);
const oldRes = { source: score(old, () => src), after_return: score(old, () => back.stats(), (o) => back.add(o.moments)) };

const fmt = (r: { right: number; false_reject: number; escape: number }) => `right ${(100 * r.right).toFixed(1)}%  false rejects ${(100 * r.false_reject).toFixed(1)}%  escapes ${(100 * r.escape).toFixed(1)}%`;
console.log(`parity with PyTorch: max |Δlogit| ${err.toExponential(1)}`);
for (const [k, r] of Object.entries(res)) console.log(`new line, ${k.padEnd(13)} ${fmt(r)}`);
for (const [k, r] of Object.entries(oldRes)) console.log(`old line, ${k.padEnd(13)} ${fmt(r)}`);
console.log(fails.length ? fails.join("\n") : "ADAPT OK (parity with PyTorch; the online estimator reproduces Python's AdaBN)");
writeFileSync(join(dir, "adapt_check.json"), JSON.stringify({ parity: err, frames: n, new_line: res, old_line: oldRes, fails }, null, 1));
process.exit(fails.length ? 1 : 0);
