// Headless run of the compiled PLC against the plant, for the proof (stf-cad/hbw/sil/run.py).
//   node sil-run.mjs <public/sil dir> <max seconds>   ->  the trace as JSON on stdout
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Sil } from "../src/sil/sim";

const dir = process.argv[2], max = Number(process.argv[3] ?? 3600);
const meta = JSON.parse(readFileSync(join(dir, "plc.json"), "utf8"));
const params = JSON.parse(readFileSync(join(dir, "plant.json"), "utf8"));
const sim = new Sil(new WebAssembly.Module(readFileSync(join(dir, "plc.wasm"))), meta, params);
const t0 = Date.now();
sim.run(max);
const p = sim.plant;
const states = Object.fromEntries(meta.units.map((u: string, i: number) => [u, sim.unitState(i)]));
process.stdout.write(JSON.stringify({
  scans: sim.scan, t: sim.t, wall_ms: Date.now() - t0, homed_at: sim.homedAt, done_at: sim.doneAt,
  events: sim.events, faults: sim.faults, flags: p.flags, states,
  plant_log: p.events,
  final: { slots: Object.fromEntries(Object.entries(p.slots).map(([s, m]) => [s, m ? [m.id, m.cookie] : null])),
           bays: p.bays, belt: p.belt.map((b) => [b.m.id, b.m.cookie, b.y]), fork: p.fork, cup: p.cup,
           tray: p.tray, nest: p.nest, line: p.line, baked: Object.fromEntries(p.baked) },
}));
