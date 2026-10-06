// The browser renderer (src/vision/render.ts) against the Python one, where it matters: the
// trained CNN must score the browser's images as it scored Python's (results.json), in the
// training ranges and outside them.
//   node .cache/vision-live-check.mjs public/vision
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { decode, forward, verdict } from "../src/vision/cnn";
import { Rng, chw, render, type RenderParams } from "../src/vision/render";

const dir = process.argv[2];
const net = decode(JSON.parse(readFileSync(join(dir, "weights.json"), "utf8")));
const P: RenderParams = JSON.parse(readFileSync(join(dir, "render.json"), "utf8"));
const res = JSON.parse(readFileSync(join(dir, "results.json"), "utf8"));
const n = Number(process.argv[3] ?? 1500);
const out: Record<string, unknown> = {};
for (const [name, key, py] of [["in_domain", "wide", res.results.in_domain], ["shifted", "shift", res.results.shifted]] as const) {
  const rng = new Rng(1500 + n), ok = P.conditions.indexOf("ok");
  let cond = 0, flav = 0, esc = 0, fr = 0, nGood = 0, nBad = 0;
  for (let i = 0; i < n; i++) {
    const f = i % P.flavours.length, c = Math.floor(i / P.flavours.length) % P.conditions.length;
    const img = render(P, P.flavours[f], P.conditions[c], rng, P.ranges[key]);
    const o = forward(net, chw(img, P.N));
    const pc = o.condition.indexOf(Math.max(...o.condition)), pf = o.flavour.indexOf(Math.max(...o.flavour));
    cond += +(pc === c); flav += +(pf === f);
    const v = verdict(net, o.condition);
    if (c === ok) { nGood++; fr += +(v === "reject"); } else { nBad++; esc += +(v === "pass"); }
  }
  const r = { n, condition_acc: cond / n, flavour_acc: flav / n, escape_rate: esc / nBad, false_reject: fr / nGood };
  out[name] = { browser: r, python: { condition_acc: py.condition_acc, flavour_acc: py.flavour_acc, escape_rate: py.escape_rate, false_reject: py.false_reject } };
  console.log(name.padEnd(10), "browser renderer:", Object.entries(r).map(([k, v]) => `${k} ${typeof v === "number" && v < 1.5 ? (100 * v).toFixed(1) + "%" : v}`).join("  "));
  console.log("".padEnd(10), "python renderer: ", `condition_acc ${(100 * py.condition_acc).toFixed(1)}%  flavour_acc ${(100 * py.flavour_acc).toFixed(1)}%  escape_rate ${(100 * py.escape_rate).toFixed(1)}%  false_reject ${(100 * py.false_reject).toFixed(1)}%`);
}
writeFileSync(join(dir, "render_check.json"), JSON.stringify(out, null, 1));
