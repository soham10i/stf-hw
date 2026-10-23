// The electrical card: what a part clicked in the 3D twin is, electrically - its ratings, its pins
// and what each is wired to, and the voltage on each pin now.
//
// "Now" is the Test bench's physics when it runs the part's module: a motor's speed, current and
// voltage come from its motor model, and its direction switches the relay outputs in the circuit
// (so its leads read +24 V and GND); a switch's or a light barrier's state presses its contact.
// Otherwise the circuit is shown at rest, and the card says so.
import { useEffect, useMemo } from "react";

import { FactoryCircuit } from "../circuit/factoryCircuit";
import { useBench, type BenchView } from "../scene/bench/benchStore";
import { electricalDoc, loadElectrical, pickPart, usePicked } from "../scene/electricPick";
import { Icon } from "../shared/icons";

/** bench axis -> the motor it is, and its two outputs: [negative direction, positive direction] */
const AXIS_MOTOR: Record<string, Record<string, { inst: string; out: [string, string] }>> = {
  warehouse: {
    travel: { inst: "hbw.M2", out: ["hbw.Q3", "hbw.Q4"] }, // Q3 towards the rack (-), Q4 towards the belt (+)
    lift: { inst: "hbw.M3", out: ["hbw.Q5", "hbw.Q6"] }, // Q5 down, Q6 up
    fork: { inst: "hbw.M4", out: ["hbw.Q8", "hbw.Q7"] }, // Q7 forward (+), Q8 back
    belt: { inst: "hbw.M1", out: ["hbw.Q2", "hbw.Q1"] }, // Q1 forward (out, +), Q2 back
  },
  arm: {
    plunge: { inst: "vgr.M1", out: ["vgr.Q2", "vgr.Q1"] }, // Q1 up (+), Q2 down
    reach: { inst: "vgr.M2", out: ["vgr.Q3", "vgr.Q4"] }, // Q3 backward (-), Q4 forward (+)
    swivel: { inst: "vgr.M3", out: ["vgr.Q5", "vgr.Q6"] }, // Q5 clockwise (-), Q6 counter-clockwise (+)
  },
};
const SWITCH_PREFIX: Record<string, string> = { warehouse: "hbw", arm: "vgr", sorting: "sorting" };
const BENCH_OF: Record<string, string> = { hbw: "warehouse", vgr: "arm", sorting: "sorting" };

export function ElectricCard() {
  const inst = usePicked();
  const bench = useBench();
  useEffect(() => { void loadElectrical(); }, []);
  const file = electricalDoc();
  const circuit = useMemo(() => (file ? new FactoryCircuit(file, "upgraded") : null), [file]);
  if (!inst || !file || !circuit) return null;
  const doc = circuit.doc;
  const placed = doc.project.placed_parts.find((p) => p.instance_id === inst);
  if (!placed) return null;
  const sheet = file.parts[placed.part_id];
  const where = doc.placement[inst];
  const module = inst.split(".")[0];
  const live = (bench.status === "running" || bench.status === "paused") && BENCH_OF[module] === bench.module;
  const motor = live ? applyBench(circuit, bench) : null;
  const reading = motor?.[inst];

  const pins = sheet.pins.length > 30 ? [] : sheet.pins;
  return (
    <aside className="el-card" aria-label={`${sheet.name}: electrical sheet`}>
      <header>
        <div>
          <b>{sheet.name}</b>
          <span>{inst}{sheet.ft ? ` · ft ${sheet.ft}` : ""}</span>
        </div>
        <button className="ui-btn icon" aria-label="Close" onClick={() => pickPart(null)}><Icon name="close" size={14} /></button>
      </header>
      <p className={`el-card-live ${live ? "on" : ""}`}>
        {live ? "Live: the Test bench's physics" : "At rest - start the Test bench on this module for live values"}
      </p>
      {reading && (
        <dl className="el-card-read">
          <dt>speed</dt><dd>{reading.rpm.toFixed(0)} rpm</dd>
          <dt>current</dt><dd>{(reading.current * 1000).toFixed(0)} mA</dd>
          <dt>voltage</dt><dd>{reading.volts.toFixed(0)} V</dd>
        </dl>
      )}
      {pins.length > 0 && (
        <table className="tbl el-card-pins">
          <thead><tr><th>pin</th><th>function</th><th className="num">now</th></tr></thead>
          <tbody>
            {pins.map((p) => {
              let v: number | null | undefined;
              try { v = circuit.volts({ part_instance: inst, pin_label: p.label }); } catch { v = undefined; }
              const over = v != null && (v > p.voltage_limits[1] || v < p.voltage_limits[0]);
              return (
                <tr key={p.label}>
                  <td><b>{p.label}</b></td>
                  <td title={`rated ${p.voltage_limits[0]}…${p.voltage_limits[1]} V${p.max_mA ? `, ${p.max_mA} mA` : ""}`}>{p.function}</td>
                  <td className={`num ${over ? "warn" : ""}`}>{v === undefined ? "–" : v === null ? "float" : `${v} V`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {pins.length === 0 && <p className="clock">{sheet.pins.length} pins - see the Electrics view.</p>}
      <p className="clock">
        {sheet.ratings.slice(0, 3).map((r) => `${r.label}: ${r.value}`).join(" · ")}
      </p>
      {where && <p className="clock">CAD part <code>{where.cad}</code>{where.frame !== "world" ? ` · on the ${where.frame} axis` : ""}</p>}
      <a className="el-card-more" href={`?view=electrics&part=${encodeURIComponent(inst)}`}>Full sheet and wiring →</a>
    </aside>
  );
}

/** Puts the bench's state into the circuit: each motor's direction as its relay outputs, each
    switch and light barrier as its contact. Returns the motors' readings by instance. */
function applyBench(c: FactoryCircuit, b: BenchView) {
  const out: Record<string, { rpm: number; current: number; volts: number }> = {};
  const axes = AXIS_MOTOR[b.module] ?? {};
  for (const [id, m] of Object.entries(axes)) {
    const r = b.axes?.[id];
    if (!r) continue;
    const dir = r.current > 0.001 ? 1 : r.current < -0.001 ? -1 : 0;
    c.setOutput(m.out[0], dir < 0);
    c.setOutput(m.out[1], dir > 0);
    out[m.inst] = { rpm: r.rpm, current: Math.abs(r.current), volts: dir === 0 ? 0 : 24 };
  }
  const prefix = SWITCH_PREFIX[b.module];
  const states = b.module === "sorting" ? b.barriers : b.switches;
  for (const [tag, on] of Object.entries(states ?? {})) {
    const inst = `${prefix}.${tag}`;
    try { c.press(inst, on); } catch { /* a light barrier: no contact, its pin is driven */ }
  }
  return out;
}
