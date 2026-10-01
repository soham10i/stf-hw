// Upgrade 13: the compiled PLC program (public/sil/plc.wasm, MatIEC -> C -> WebAssembly)
// and the plant, scanned together. One scan: the plant writes the inputs, the program
// runs once, the plant moves for one task interval with the outputs it set.
//
// The trace is read from the program's own monitor (%MW): for every lead unit, the
// job it runs, its binding and how many jobs it has started. That is what the proof
// (stf-cad/hbw/sil/run.py) compares, decision by decision, with control.py.

import { Plant, type IoMap, type PlantParams } from "./plant";

export type PlcMeta = {
  scan_ms: number; io: IoMap; image: Record<string, number>; jobs: string[];
  job_units: Record<string, string[]>; layout: Record<string, string[]>; units: string[];
  states: Record<string, Record<string, [number, number]>>; wasm_sha: string; st_lines: number; compiler: string;
};
export type JobEvent = { t: number; scan: number; kind: "start" | "end"; unit: string; job: string; b: number[] };

type Exports = {
  memory: WebAssembly.Memory; _initialize?: () => void; plc_init: () => void; plc_scan: () => void;
  plc_ix: () => number; plc_qx: () => number; plc_iw: () => number; plc_id: () => number; plc_mw: () => number;
};

export class Sil {
  readonly meta: PlcMeta;
  readonly plant: Plant;
  readonly dt: number;
  scan = 0;
  events: JobEvent[] = [];
  homedAt: number | null = null;
  doneAt: number | null = null;
  faults: { t: number; unit: string; state: number }[] = [];
  ix: Uint8Array; qx: Uint8Array; iw: Int16Array; id: Float32Array; mw: Int16Array;
  private ex: Exports;
  private last: { job: number; n: number; b: number[] }[];
  private faulted = new Set<string>();

  constructor(wasm: WebAssembly.Module, meta: PlcMeta, params: PlantParams) {
    this.meta = meta;
    this.dt = meta.scan_ms / 1000;
    this.ex = new WebAssembly.Instance(wasm, {}).exports as unknown as Exports;
    this.ex._initialize?.();
    this.ex.plc_init();
    const buf = this.ex.memory.buffer, im = meta.image;
    this.ix = new Uint8Array(buf, this.ex.plc_ix(), im.ix);
    this.qx = new Uint8Array(buf, this.ex.plc_qx(), im.qx);
    this.iw = new Int16Array(buf, this.ex.plc_iw(), im.iw);
    this.id = new Float32Array(buf, this.ex.plc_id(), im.id);
    this.mw = new Int16Array(buf, this.ex.plc_mw(), im.mw);
    this.plant = new Plant(params, meta.io);
    this.last = meta.units.map(() => ({ job: 0, n: 0, b: [0, 0, 0, 0, 0, 0] }));
  }

  get t() { return this.scan * this.dt; }
  get phase() { return this.mw[0]; }
  unitState(i: number) { return this.mw[10 * (i + 1)]; }

  /** One PLC scan and one plant step. */
  tick() {
    this.plant.writeInputs(this.ix, this.iw, this.id);
    this.ex.plc_scan();
    this.scan++;
    this.observe();
    this.plant.step(this.qx, this.dt);
  }

  /** Run until the order is complete, a unit faults, the plant flags a problem, or the time is up. */
  run(maxSeconds: number) {
    const n = Math.round(maxSeconds / this.dt);
    for (let k = 0; k < n; k++) {
      this.tick();
      if (this.doneAt !== null || this.faults.length || this.plant.flags.length) break;
    }
  }

  private observe() {
    const t = Math.round(this.t * 1000) / 1000;
    if (this.homedAt === null && this.mw[0] >= 1) this.homedAt = t;
    if (this.doneAt === null && this.mw[0] === 2) this.doneAt = t;
    this.meta.units.forEach((u, i) => {
      const base = 10 * (i + 1);
      const job = this.mw[base + 1], n = this.mw[100 + i + 1];
      const b = Array.from(this.mw.subarray(base + 2, base + 8));
      const L = this.last[i];
      if (L.job !== 0 && (job === 0 || n !== L.n)) {
        this.events.push({ t, scan: this.scan, kind: "end", unit: u, job: this.meta.jobs[L.job - 1], b: L.b });
      }
      if (job !== 0 && n !== L.n) {
        this.events.push({ t, scan: this.scan, kind: "start", unit: u, job: this.meta.jobs[job - 1], b });
      }
      this.last[i] = { job, n, b };
      if (this.mw[base] === 910 && !this.faulted.has(u)) {
        this.faulted.add(u);
        this.faults.push({ t, unit: u, state: this.mw[base + 8] });
      }
    });
  }
}
