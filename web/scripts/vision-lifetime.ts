// A year on the line for the two inspection models (src/vision/lifetime.ts): each week's test
// batch in that week's camera conditions, judged by the deployed CNN and autoencoder. The page
// (Vision QC) shows the first half as measured and forecasts the rest from it.
//   node .cache/vision-lifetime.mjs public/vision [cookies per week]
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { decodeAe } from "../src/vision/ae";
import { decode } from "../src/vision/cnn";
import { WEEKS, measureWeek } from "../src/vision/lifetime";
import type { RenderParams } from "../src/vision/render";

const dir = process.argv[2];
const n = Number(process.argv[3] ?? 40);
const j = (f: string) => JSON.parse(readFileSync(join(dir, f), "utf8"));
const P: RenderParams = j("render.json");
const cnn = decode(j("weights.json")), ae = decodeAe(j("autoencoder.json"));
const r3 = (x: number) => Math.round(x * 1000) / 1000;
const weeks = [];
for (let w = 0; w <= WEEKS; w++) {
  const m = measureWeek(P, cnn, ae, w, n);
  weeks.push({ w, n, cnn: { detect: r3(m.cnn.detect), falseAlarm: r3(m.cnn.falseAlarm) },
               ae: { detect: r3(m.ae.detect), falseAlarm: r3(m.ae.falseAlarm), drift: r3(m.ae.drift) } });
  process.stdout.write(`week ${w}: CNN ${m.cnn.detect.toFixed(2)}/${m.cnn.falseAlarm.toFixed(2)}  AE ${m.ae.detect.toFixed(2)}/${m.ae.falseAlarm.toFixed(2)} drift ${m.ae.drift.toFixed(2)}\n`);
}
writeFileSync(join(dir, "lifetime.json"), JSON.stringify({
  note: "Measured by web/scripts/vision-lifetime.ts with the deployed models; conditions from src/vision/lifetime.ts wear()",
  per_week: n, weeks,
}) + "\n");
