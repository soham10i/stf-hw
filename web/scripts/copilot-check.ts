// Upgrade 17: the copilot, tested on operator questions it was not tuned on one by one.
// Each question names what should answer it: a tool, a document (by a word of its section
// path), or "none" (nothing covers it - the copilot must say so, not guess).
//   node .cache/copilot-check.mjs public
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { DATA, answer, type Ctx, type DataKey } from "../src/copilot/copilot";

const dir = process.argv[2];
const cache = new Map<string, unknown>();
const ctx: Ctx = { age: 140, pm: true, get: async <T,>(k: DataKey) => {
  if (!cache.has(k)) cache.set(k, JSON.parse(readFileSync(join(dir, DATA[k]), "utf8")));
  return cache.get(k) as T;
} };

const Q: [string, string][] = [
  ["what should we service next", "service-next"],
  ["which part needs maintenance first?", "service-next"],
  ["is anything due for replacement at 300 shifts", "service-next"],
  ["when will the hbw belt fail", "part-life"],
  ["how long will the suction cup last", "part-life"],
  ["health of the spindle at 200 shifts", "part-life"],
  ["is the colour sensor worn", "part-life"],
  ["what does VGR-V01 mean", "alarm-code"],
  ["alarm HBW-C01", "alarm-code"],
  ["why did the line stop this month", "why-stop"],
  ["what caused the most downtime", "why-stop"],
  ["what is the oee", "oee"],
  ["how many cookies per hour", "oee"],
  ["which unit is the bottleneck", "oee"],
  ["how much co2 does a cookie cost", "carbon"],
  ["what is the carbon footprint per order", "carbon"],
  ["how much energy did the cell use", "energy"],
  ["what does the battery save on the power bill", "energy"],
  ["is the learned scheduler faster than the plc", "scheduler"],
  ["can the scheduler deadlock", "scheduler"],
  ["how accurate is the vision inspection", "vision"],
  ["do defects escape the camera", "vision"],
  ["how well does the neural network predict failures", "ai"],
  ["were the attacks blocked", "security"],
  ["what is the ride-through reserve", "doc:Upgrade 9"],
  ["how does the light curtain work", "doc:safety"],
  ["what is IEC 62443", "doc:security"],
  ["how do I deploy the app on render", "doc:DEPLOY"],
  ["what is the price of bitcoin", "none"],
  ["who won the football match yesterday", "none"],
];

// held out: written after the scoring above was tuned, and run once - reported, not tuned on
const HELD: [string, string][] = [
  ["anything I should fix before the next shift?", "service-next"],
  ["remaining life of the gearbox", "part-life"],
  ["will the oven door cylinder break soon", "part-life"],
  ["explain alarm OVN-D01", "alarm-code"],
  ["biggest reason for lost production", "why-stop"],
  ["are we losing efficiency anywhere", "oee"],
  ["what is our availability", "oee"],
  ["grams of carbon per cookie", "carbon"],
  ["how much solar did we use", "energy"],
  ["did the shielded agent ever deadlock", "scheduler"],
  ["how many good cookies does the camera reject", "vision"],
  ["is the AI better than the rules", "ai"],
  ["can someone write coils over the network", "security"],
  ["what is the emergency stop circuit", "doc:safety"],
  ["how is the turntable saw driven", "doc:"],
  ["what's the weather tomorrow", "none"],
];

let right = 0;
const rows: { q: string; want: string; got: string; ok: boolean }[] = [];
for (const [q, want] of Q) {
  const a = await answer(q, ctx);
  const got = a.tool === "documents" ? `doc:${a.sources[0]}` : a.tool;
  const ok = want.startsWith("doc:") ? a.tool === "documents" && a.sources.slice(0, 3).some((s) => s.toLowerCase().includes(want.slice(4).toLowerCase()))
    : got === want;
  right += +ok;
  rows.push({ q, want, got, ok });
  console.log(`${ok ? "ok  " : "MISS"} ${q.padEnd(52)} -> ${got.slice(0, 70)}${ok ? "" : `   (wanted ${want})`}`);
}
const acc = right / Q.length;
let held = 0;
const heldRows: typeof rows = [];
for (const [q, want] of HELD) {
  const a = await answer(q, ctx);
  const got = a.tool === "documents" ? `doc:${a.sources[0]}` : a.tool;
  const ok = want.startsWith("doc:") ? a.tool === "documents" && a.sources.slice(0, 3).some((s) => s.toLowerCase().includes(want.slice(4).toLowerCase()))
    : got === want;
  held += +ok;
  heldRows.push({ q, want, got, ok });
  console.log(`${ok ? "ok  " : "MISS"} [held out] ${q.padEnd(44)} -> ${got.slice(0, 70)}${ok ? "" : `   (wanted ${want})`}`);
}
console.log(`\ncopilot: ${right}/${Q.length} on the tuning questions, ${held}/${HELD.length} on held-out ones`);
writeFileSync(join(dir, "copilot", "check.json"), JSON.stringify({ right, total: Q.length, rows, held, held_total: HELD.length, held_rows: heldRows }, null, 1));
process.exit(acc >= 0.85 ? 0 : 1);
