// The software-in-the-loop PLC as a live data source (Upgrade 14, OPC UA server).
//   node sil-stream.mjs <public/sil dir> <speed> <emit every ms of machine time>
// speed 1 = real time, 20 = twenty times faster, 0 = as fast as it can. One JSON line per
// emit: the I/O image in plc.json's order, every unit's state, job and alarm, and the job
// events since the last line. stdin: "restart" starts the order again from power-up.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";
import { Sil } from "../src/sil/sim";

const dir = process.argv[2], speed = Number(process.argv[3] ?? 1), emitMs = Number(process.argv[4] ?? 50);
const meta = JSON.parse(readFileSync(join(dir, "plc.json"), "utf8"));
const params = JSON.parse(readFileSync(join(dir, "plant.json"), "utf8"));
const wasm = new WebAssembly.Module(readFileSync(join(dir, "plc.wasm")));
let sim = new Sil(wasm, meta, structuredClone(params));
let sent = 0, run = 0;

// the server that reads this has gone: stop
process.stdout.on("error", () => process.exit(0));
createInterface({ input: process.stdin }).on("close", () => process.exit(0)).on("line", (l) => {
  if (l.trim() === "restart") { sim = new Sil(wasm, meta, structuredClone(params)); sent = 0; run++; }
});

function emit() {
  const ev = sim.events.slice(sent);
  sent = sim.events.length;
  const line = {
    run, t: Math.round(sim.t * 1000) / 1000, phase: sim.phase, jobs: sim.mw[1],
    ix: meta.io.ix.map((e: { bit: number }) => sim.ix[e.bit]), qx: meta.io.qx.map((e: { bit: number }) => sim.qx[e.bit]),
    iw: Array.from(sim.iw.subarray(0, meta.io.iw.length)), id: Array.from(sim.id.subarray(0, meta.io.id.length), (v) => Math.round(v * 100) / 100),
    units: meta.units.map((_: string, i: number) => [sim.mw[10 * (i + 1)], sim.mw[10 * (i + 1) + 1], sim.mw[10 * (i + 1) + 8]]),
    ev: ev.map((e) => [e.t, e.kind, e.unit, e.job]), flags: sim.plant.flags,
  };
  process.stdout.write(JSON.stringify(line) + "\n");
}

const scansPerEmit = Math.max(1, Math.round(emitMs / meta.scan_ms));
const tick = () => {
  for (let k = 0; k < scansPerEmit; k++) if (sim.phase !== 2) sim.tick();
  emit();
};
if (speed <= 0) {
  const loop = () => { for (let k = 0; k < 20; k++) tick(); setImmediate(loop); };
  loop();
} else {
  setInterval(tick, emitMs / speed);
}
