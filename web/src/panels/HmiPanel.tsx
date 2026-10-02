import { useEffect, useMemo, useState } from "react";
import type { ControlDoc } from "../shared/model";
import { JOB_COL, fmtT, makespan, unitsAt } from "../shared/hmi";

// Upgrade 4's operator screen, in the sidebar: the orchestrator's nominal run
// replayed (control.py), unit states, order progress, alarms, trace and jog.
export function HmiPanel({ c }: { c: ControlDoc }) {
  const T = makespan(c);
  const [t, setT] = useState(0);
  const [play, setPlay] = useState(false);
  const [alarm, setAlarm] = useState("");
  const [jogUnit, setJogUnit] = useState("crane");
  const [cookie, setCookie] = useState<string | null>(null);
  useEffect(() => {
    if (!play) return;
    const id = window.setInterval(() => setT((x) => (x + 2 >= T ? (setPlay(false), T) : x + 2)), 100);
    return () => window.clearInterval(id);
  }, [play, T]);
  const now = useMemo(() => unitsAt(c, t), [c, t]);
  const prod = c.trace.filter((r) => r.kind === "production");
  const ret = c.trace.filter((r) => r.kind === "return");
  const done = prod.filter((r) => (r.t.sorted ?? Infinity) <= t).length;
  const stored = ret.filter((r) => (r.t.stored ?? Infinity) <= t).length;
  const al = c.alarms.find((a) => a.code === alarm);
  const rec = c.trace.find((r) => r.id === cookie);
  const pol = c.policies;
  return (
    <section className="panel upgrade hmi">
      <h2>Upgrade 4 · HMI</h2>
      <div className="hmi-clock">
        <button onClick={() => { if (t >= T) setT(0); setPlay((p) => !p); }}>{play ? "❚❚" : "▶"}</button>
        <input type="range" min={0} max={T} step={0.5} value={t} onChange={(e) => { setPlay(false); setT(+e.target.value); }} />
        <b>{fmtT(t)}</b><span className="muted small">/ {fmtT(T)}</span>
      </div>
      <p className="muted small">The PLC's nominal run of the 12-cookie order (policy "{c.policy}"), 20× real time.</p>

      <h3>Units</h3>
      <table className="kv up-table hmi-units">
        <tbody>
          {now.map((u) => (
            <tr key={u.unit} title={u.label}>
              <td><span className={`hmi-led ${u.state.toLowerCase()}`} />{u.unit}</td>
              <td>{u.job ? <span style={{ color: JOB_COL[u.job] }}>{u.job}</span> : <span className="muted">ready</span>}
                <div className="muted small">{u.step ?? (u.state === "HELD" ? "held by its job" : "")}</div></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Order</h3>
      <div className="hmi-order">
        <div><b>{done}</b>/{prod.length} baked and sorted</div>
        <div><b>{stored}</b>/{ret.length} returned to the rack</div>
      </div>

      <h3>Alarms</h3>
      <select value={alarm} onChange={(e) => setAlarm(e.target.value)}>
        <option value="">no active alarm (nominal run) - preview one…</option>
        {c.alarms.map((a) => <option key={a.code} value={a.code}>{a.code} {a.text}</option>)}
      </select>
      {al && (
        <div className="hmi-alarm">
          <b>{al.code}</b> {al.text}
          <div><span>cause</span>{al.cause}</div>
          <div><span>reaction</span>{al.reaction}</div>
          <div><span>recovery</span>{al.recovery}</div>
          {al.limit && <div><span>watchdog</span>{al.limit} s · {al.steps.length} steps</div>}
        </div>
      )}

      <h3>Trace</h3>
      <table className="kv up-table">
        <thead><tr><td>id</td><td>flavour</td><td>mould</td><td className="num">state</td></tr></thead>
        <tbody>
          {c.trace.map((r) => {
            const st = r.kind === "return"
              ? ((r.t.stored ?? Infinity) <= t ? `in ${r.slot_to}` : "bay")
              : (r.t.sorted ?? Infinity) <= t ? `bin ${r.bin} ✓` : (r.t.bake_start ?? Infinity) <= t ? "oven+" :
                (r.t.retrieved ?? Infinity) <= t ? "belt" : `rack ${r.slot_from}`;
            return (
              <tr key={r.id} className={cookie === r.id ? "on" : ""} onClick={() => setCookie(cookie === r.id ? null : r.id)} style={{ cursor: "pointer" }}>
                <td>{r.id}</td><td>{r.flavour}</td><td>{r.mould}</td><td className="num">{st}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {rec && (
        <div className="hmi-alarm">
          <b>{rec.id}</b> {rec.flavour} · {rec.kind}
          {rec.reads.map(([rp, m, tt]) => <div key={rp + tt}><span>{rp}</span>{m} at {tt} s</div>)}
          {Object.entries(rec.t).map(([k, v]) => <div key={k}><span>{k}</span>{v} s</div>)}
          {rec.colour_mV !== undefined && <div><span>A4</span>{rec.colour_mV} mV → {rec.class} {rec.verified ? "= record ✓" : "≠ record"}</div>}
        </div>
      )}

      <h3>Manual jog</h3>
      <select value={jogUnit} onChange={(e) => setJogUnit(e.target.value)}>
        {Object.keys(c.units).map((u) => <option key={u} value={u}>{u}</option>)}
      </select>
      <table className="kv up-table">
        <tbody>
          {c.jog.filter((j) => j.unit === jogUnit).map((j) => (
            <tr key={j.axis}><td>{j.axis}<div className="muted small">{j.out}</div></td>
              <td>{j.when}<div className="muted small">{j.model}</div></td></tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Jog: mode MANUAL, guard closed, hold-to-run; each axis only while its model's interlock allows it.</p>

      <h3>Dispatch policy (measured)</h3>
      <table className="kv up-table">
        <tbody>
          {Object.entries(pol).map(([k, p]) => (
            <tr key={k} className={k === c.policy ? "on" : ""}>
              <td>{k}<div className="muted small">{p.say}</div></td>
              <td className={`num ${p.deadlock ? "up-cost" : ""}`}>{p.deadlock ? "deadlock" : `${p.makespan} s`}
                <div className="muted small">{p.states.toLocaleString()} states</div></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Every policy is explored over every completion order, i.e. every possible
        timing. The Gantt and the bake-time study are on blueprint sheet U4-02.</p>
    </section>
  );
}
