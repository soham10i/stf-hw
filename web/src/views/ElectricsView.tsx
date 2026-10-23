// Electrics: every electrical part of the factory, pin by pin, from public/electrical.json
// (stf-cad/hbw/electrical.py - the board's pinouts, the RevPi occupancy plans and the datasheets).
//
// Pick a module and a part: its ratings and pinout, each value with its source; what each pin is
// wired to; and the voltage on it now, from the live netlist (circuit/factoryCircuit.ts). Switch
// a module's PLC outputs or press its switches and every node is re-checked for shorts and
// overvoltage. Motors show their characteristic curves from the motor model the physics runs.
import { useMemo, useState } from "react";

import { useJson } from "../shared/data";
import { FactoryCircuit, type ElectricalDoc, type PartSheet, type Variant } from "../circuit/factoryCircuit";
import { Schematic } from "./Schematic";
import { FT_ENCODER_MOTOR, loadedTo, S_MOTOR_24V, type MotorSpec } from "../workers/motors";

const MODULES: [string, string][] = [["cabinet", "Cabinet"], ["hbw", "Warehouse"], ["vgr", "Robot arm"], ["oven", "Oven"], ["sorting", "Sorting line"], ["air", "Air station"]];
const SRC: Record<string, string> = {
  datasheet: "datasheet", booklet: "booklet", plan: "plan", board: "board doc", derived: "derived", design: "design", assumed: "measure",
};
const VARIANTS: [Variant, string, string][] = [
  ["upgraded", "Upgraded", "the factory the 3D twin shows: remote I/O nodes, safety contactors, central air"],
  ["original", "Original", "as fischertechnik documents it: a RevPi DIO per module (the occupancy plans)"],
];

export function useElectrical(): { doc: ElectricalDoc | null; err: string | null } {
  const { data, error } = useJson<ElectricalDoc>("electrical.json", "electrical.json missing - run electrical.py in stf-cad/hbw");
  return { doc: data, err: error };
}

export function ElectricsView({ doc: file }: { doc: ElectricalDoc }) {
  const [variant, setVariant] = useState<Variant>("upgraded");
  const circuit = useMemo(() => new FactoryCircuit(file, variant), [file, variant]);
  const doc = { ...circuit.doc, parts: file.parts };
  // ?part=hbw.M2 (from the 3D twin's card) opens that part
  const asked = new URLSearchParams(location.search).get("part");
  const [mid, setMid] = useState(() => (asked && circuit.doc.modules[asked]) || "hbw");
  const [sel, setSel] = useState<string>(() => asked ?? "hbw.M2");
  const [tick, setTick] = useState(0); // re-render after a switch: the circuit is mutable
  const [outs, setOuts] = useState<Record<string, boolean>>({});
  const [pressed, setPressed] = useState<Record<string, boolean>>({});
  const [safe, setSafe] = useState(true);
  const [tab, setTab] = useState<"parts" | "schematic">("parts");
  const chooseVariant = (v: Variant) => { setVariant(v); setOuts({}); setPressed({}); setSafe(true); };
  const toggleSafety = () => {
    circuit.setContact("safety.K1", !safe);
    circuit.setContact("safety.K2", !safe);
    setSafe(!safe);
    setTick((t) => t + 1);
  };

  const insts = doc.project.placed_parts.filter((p) => doc.modules[p.instance_id] === mid);
  const inst = doc.project.placed_parts.find((p) => p.instance_id === sel) ?? insts[0];
  const sheet = doc.parts[inst.part_id];
  const faults = useMemo(() => circuit.faults(), [circuit, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  // what each pin of the selected part is wired to, and its voltage now
  const wiring = useMemo(() => {
    const out = new Map<string, { to: string[]; net: string; volts: number | null }>();
    for (const p of sheet.pins) {
      const net = doc.project.wire_nets.find((n) => n.connections.some((c) => c.part_instance === inst.instance_id && c.pin_label === p.label));
      if (!net) continue;
      const to = net.connections.filter((c) => !(c.part_instance === inst.instance_id && c.pin_label === p.label)).map((c) => `${c.part_instance}.${c.pin_label}`);
      out.set(p.label, { to, net: net.net_id, volts: circuit.volts({ part_instance: inst.instance_id, pin_label: p.label }) });
    }
    return out;
  }, [doc, circuit, inst, sheet, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const outputs = (doc.io[mid] ?? []).filter((r) => r.channel.startsWith("OUT") || r.kind === "OUT");
  const where = doc.placement[inst.instance_id];
  const pos = inst.world_position_mm;
  const switches = insts.filter((p) => p.part_id === "mini_switch");
  const toggleOut = (sig: string) => {
    const k = `${mid}.${sig}`;
    const on = !outs[k];
    circuit.setOutput(k, on);
    setOuts({ ...outs, [k]: on });
    setTick((t) => t + 1);
  };
  const toggleSwitch = (id: string) => {
    const on = !pressed[id];
    circuit.press(id, on);
    setPressed({ ...pressed, [id]: on });
    setTick((t) => t + 1);
  };

  const counts = { parts: doc.project.placed_parts.length, pins: doc.project.placed_parts.reduce((n, p) => n + doc.parts[p.part_id].pins.length, 0), nets: doc.project.wire_nets.length, contacts: doc.contacts.length };
  const warn = doc.checks.filter((c) => c.severity === "warn").length;
  const fail = doc.checks.filter((c) => c.severity === "fail").length;

  return (
    <div className="body">
      <div className="viewport ctl-main el-main">
        <div className="ctl-modules" role="radiogroup" aria-label="Variant">
          {VARIANTS.map(([v, name, about]) => (
            <button key={v} role="radio" aria-checked={variant === v} className={variant === v ? "on" : ""} title={about} onClick={() => chooseVariant(v)}>{name}</button>
          ))}
          <span className="clock el-variant">{VARIANTS.find((x) => x[0] === variant)![2]}</span>
        </div>
        <div className="ctl-modules">
          {MODULES.filter(([id]) => doc.project.placed_parts.some((p) => doc.modules[p.instance_id] === id)).map(([id, name]) => (
            <button key={id} className={id === mid ? "on" : ""} onClick={() => { setMid(id); setSel(doc.project.placed_parts.find((p) => doc.modules[p.instance_id] === id)!.instance_id); }}>
              {name} <span>{doc.project.placed_parts.filter((p) => doc.modules[p.instance_id] === id).length}</span>
            </button>
          ))}
        </div>
        <h2 className="ctl-title">
          Electrics, pin by pin <span className="clock">{counts.parts} parts · {counts.pins} pins · {counts.nets} nets · {counts.contacts} contacts</span>
          {" "}<span className={`tag ${faults.length ? "warn" : "run"}`}>{faults.length ? `${faults.length} fault${faults.length > 1 ? "s" : ""}` : "no faults"}</span>
        </h2>

        <div className="ui-seg el-tabs" role="tablist" aria-label="Show">
          <button role="tab" aria-selected={tab === "parts"} className={tab === "parts" ? "on" : ""} onClick={() => setTab("parts")}>Parts</button>
          <button role="tab" aria-selected={tab === "schematic"} className={tab === "schematic" ? "on" : ""} onClick={() => setTab("schematic")}>Wiring diagram</button>
        </div>

        <div className={`el-cols ${tab === "schematic" ? "el-cols-sch" : ""}`}>
          {tab === "schematic" && (
            <section className="panel el-sch-panel">
              <Schematic circuit={circuit} module={mid} tick={tick} onPick={(i) => { setSel(i); setTab("parts"); }} />
            </section>
          )}
          {tab === "parts" && <>
          <nav className="el-list" aria-label="Parts">
            {insts.map((p) => (
              <button key={p.instance_id} className={p.instance_id === inst.instance_id ? "on" : ""} onClick={() => setSel(p.instance_id)}>
                <b>{p.instance_id.split(".").slice(1).join(".") || p.instance_id}</b>
                <span>{doc.parts[p.part_id].name}</span>
              </button>
            ))}
          </nav>

          <div className="el-sheet">
            <section className="panel">
              <h2>{sheet.name} <span className="tag idle">{sheet.ft ? `${sheet.ft}` : sheet.kind}</span></h2>
              <p className="clock">
                {inst.instance_id} · {sheet.dimensions_mm.x} × {sheet.dimensions_mm.y} × {sheet.dimensions_mm.z} mm{" "}
                <span className="src">{SRC[sheet.dimensions_source] ?? sheet.dimensions_source}</span> · {sheet.mass_g} g · source: {sheet.document}
              </p>
              <p className="clock">
                {where
                  ? <>In 3D at ({pos.map((v) => v.toFixed(1)).join(", ")}) mm, from the CAD part <code>{where.cad}</code>{where.frame !== "world" ? <>, riding the {where.frame} axis</> : null}</>
                  : <>Not in the CAD export: the 3D twin shows the upgraded factory.</>}
              </p>
              <table className="tbl"><tbody>
                {sheet.ratings.map((r) => (
                  <tr key={r.label}><th>{r.label}</th><td>{r.value}</td><td><span className="src">{SRC[r.source] ?? r.source}</span></td></tr>
                ))}
              </tbody></table>
            </section>

            <section className="panel">
              <h2>Pinout <span className="tag idle">{sheet.pins.length > 30 ? `${wiring.size} of ${sheet.pins.length} pins wired` : `${sheet.pins.length} pins`}</span></h2>
              <div className="el-scroll">
                <table className="tbl el-pins">
                  <thead><tr><th>pin</th><th>function</th><th className="num">rated V</th><th className="num">max mA</th><th className="num">now</th><th>wired to</th></tr></thead>
                  <tbody>
                    {(sheet.pins.length > 30 ? sheet.pins.filter((p) => wiring.has(p.label)) : sheet.pins).map((p) => {
                      const w = wiring.get(p.label);
                      const over = w?.volts != null && (w.volts > p.voltage_limits[1] || w.volts < p.voltage_limits[0]);
                      return (
                        <tr key={p.label} className={w ? "" : "el-unwired"}>
                          <td>{p.colour && <i className="el-wire" style={{ background: WIRE[p.colour] ?? p.colour }} title={p.colour} />}<b>{p.label}</b></td>
                          <td>{p.function}</td>
                          <td className="num" title={SRC[p.voltage_source]}>{p.voltage_limits[0]}…{p.voltage_limits[1]}</td>
                          <td className="num" title={p.current_source ? SRC[p.current_source] : ""}>{p.max_mA ?? "–"}</td>
                          <td className={`num ${over ? "warn" : ""}`}>{w ? (w.volts === null ? "float" : `${w.volts} V`) : "–"}</td>
                          <td className="el-to">{w ? w.to.slice(0, 4).join(", ") + (w.to.length > 4 ? ` +${w.to.length - 4}` : "") : "not wired"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="clock">Rated V: the pin's limits (hover for the source). "float": on no supply right now - an open input reads 0.</p>
            </section>

            {(sheet.part_id === "encoder_motor" || sheet.part_id === "s_motor") && <MotorCurves sheet={sheet} />}
          </div>
          </>}

          <div className="el-side">
            <section className="panel">
              <h2>Drive the {MODULES.find((m) => m[0] === mid)?.[1].toLowerCase()}</h2>
              {outputs.length ? (
                <div className="el-btns">
                  {outputs.map((r) => (
                    <button key={r.signal} className={`tick-toggle ${outs[`${mid}.${r.signal}`] ? "on" : ""}`} onClick={() => toggleOut(r.signal)}
                      title={r.revpi_terminal != null ? `${r.channel} on DIO terminal ${r.revpi_terminal}, board terminal ${r.terminal}` : `node channel ${r.channel}, board terminal ${r.terminal}`}>
                      {r.signal}
                    </button>
                  ))}
                </div>
              ) : <p className="clock">No PLC outputs here.</p>}
              {switches.length > 0 && (
                <>
                  <p className="clock">Press a switch:</p>
                  <div className="el-btns">
                    {switches.map((p) => (
                      <button key={p.instance_id} className={`tick-toggle ${pressed[p.instance_id] ? "on" : ""}`} onClick={() => toggleSwitch(p.instance_id)}>
                        {p.instance_id.split(".")[1]}
                      </button>
                    ))}
                  </div>
                </>
              )}
              <p className="clock">An output coils its relay: the motor lead goes from GND to +24 V. Both of a pair on: both leads on +24 V - a stop, not a short.</p>
              {variant === "upgraded" && (
                <button className={`tick-toggle ${safe ? "on" : ""}`} onClick={toggleSafety} title="K0 holds K1 and K2 while the guards are shut and reset is done">
                  {safe ? "Guards shut: K1/K2 hold the actuator 24 V" : "Guard open: K1/K2 dropped - motors and valves dead"}
                </button>
              )}
            </section>

            <section className="panel">
              <h2>Circuit check <span className={`tag ${faults.length ? "warn" : "run"}`}>{faults.length ? "FAULT" : "OK"}</span></h2>
              {faults.length ? faults.map((f, i) => <p key={i} className="np-err">{f.status}: {f.message}</p>)
                : <p className="clock">Every node checked: no supply wired to ground, no pin past its rated voltage.</p>}
            </section>

            <section className="panel">
              <h2>Rating checks <span className={`tag ${fail ? "warn" : warn ? "idle" : "run"}`}>{fail ? `${fail} fail` : warn ? `${warn} warn` : "pass"}</span></h2>
              <ul className="el-checks">
                {doc.checks.map((c) => (
                  <li key={c.check} className={c.severity}><b>{c.severity === "ok" ? "✓" : c.severity === "warn" ? "!" : "✗"}</b> <span>{c.check}</span><em>{c.detail}</em></li>
                ))}
              </ul>
            </section>

            {doc.findings.length > 0 && (
              <section className="panel">
                <h2>Findings</h2>
                <ul className="el-checks">{doc.findings.map((f) => <li key={f} className="warn"><b>!</b> <span>{f}</span></li>)}</ul>
              </section>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const WIRE: Record<string, string> = { red: "#d23a32", green: "#2f9e57", black: "#1b1c1e", yellow: "#e2c21b" };

/** The motor's straight speed-torque line at 24 V, its current, its output power, and where its
    load puts it - the same model (workers/motors.ts) the physics runs. */
function MotorCurves({ sheet }: { sheet: PartSheet }) {
  const enc = sheet.part_id === "encoder_motor";
  const spec: MotorSpec = enc ? FT_ENCODER_MOTOR : loadedTo(S_MOTOR_24V, (50 / (Math.PI * 20)) * 60);
  const Ts = spec.stallTorqueNm;
  const w0 = spec.noLoadRpm;
  const op = { T: spec.frictionNm, rpm: w0 * (1 - spec.frictionNm / Ts) };
  const I = (T: number) => spec.noLoadCurrentA + (spec.stallCurrentA - spec.noLoadCurrentA) * (T / Ts);
  const Pw = (T: number) => T * ((w0 * (1 - T / Ts)) * 2 * Math.PI) / 60;
  const W = 300, H = 170, L = 40, R = 40, Tp = 12, Bt = 28;
  const x = (T: number) => L + (T / Ts) * (W - L - R);
  const y = (f: number) => H - Bt - f * (H - Bt - Tp);
  const pts = (fn: (T: number) => number, max: number) => Array.from({ length: 41 }, (_, i) => (i / 40) * Ts).map((T) => `${x(T)},${y(fn(T) / max)}`).join(" ");
  const pMax = Pw(Ts / 2);
  return (
    <section className="panel">
      <h2>Characteristic at 24 V <span className="tag idle">the physics' model</span></h2>
      <svg viewBox={`0 0 ${W} ${H}`} className="el-curve" role="img" aria-label="Speed, current and power against torque">
        <line x1={L} y1={H - Bt} x2={W - R} y2={H - Bt} className="ax" />
        <line x1={L} y1={Tp} x2={L} y2={H - Bt} className="ax" />
        <polyline points={pts((T) => w0 * (1 - T / Ts), w0)} className="c-speed" />
        <polyline points={pts(I, spec.stallCurrentA)} className="c-current" />
        <polyline points={pts(Pw, pMax)} className="c-power" />
        <circle cx={x(op.T)} cy={y(op.rpm / w0)} r={4} className="c-op" />
        <text x={x(op.T) + 6} y={y(op.rpm / w0) - 6} className="lbl">{op.rpm.toFixed(0)} rpm · {(I(op.T) * 1000).toFixed(0)} mA</text>
        <text x={L} y={H - 8} className="lbl">0</text>
        <text x={W - R} y={H - 8} className="lbl" textAnchor="end">{(Ts * 1000).toFixed(0)} mN·m (stall)</text>
        <text x={L - 4} y={Tp + 4} className="lbl" textAnchor="end">{w0.toFixed(0)}</text>
        <text x={W - R + 4} y={Tp + 4} className="lbl">{(spec.stallCurrentA * 1000).toFixed(0)} mA</text>
      </svg>
      <p className="el-legend"><i className="c-speed" /> speed (rpm) <i className="c-current" /> current <i className="c-power" /> power (peak {pMax.toFixed(2)} W) <i className="c-op" /> its load</p>
      <p className="clock">
        {enc ? "Datasheet line (440 rpm, 1800 g·cm, 0.60 A); the load point is the lab's 214 rpm on the spindles."
          : "Booklet ratings through the 64.8:1 gearbox at an assumed 50 % efficiency; the load point is the belt at the project's assumed 50 mm/s."}
      </p>
    </section>
  );
}
