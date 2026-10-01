import type { SafetyDoc } from "../shared/model";

// Upgrade 2's risk assessment and safety functions, straight from safety.py.
export function SafetyPanel({ sf, showZones, setShowZones }: {
  sf: SafetyDoc; showZones: boolean; setShowZones: (v: boolean) => void;
}) {
  return (
    <section className="panel upgrade safety">
      <h2>Upgrade 2 · machine safety</h2>
      <label className="small" style={{ display: "flex", gap: 6, alignItems: "center", margin: "4px 0 8px" }}>
        <input type="checkbox" checked={showZones} onChange={(e) => setShowZones(e.target.checked)} />
        show hazard zones (swept envelopes, coloured by PLr)
      </label>
      <h3>Risk assessment (ISO 12100 / 13849-1)</h3>
      <table className="kv up-table">
        <thead><tr><td>hazard</td><td className="num">S F P</td><td className="num">PLr</td></tr></thead>
        <tbody>
          {sf.hazards.map((h) => (
            <tr key={h.id} title={h.what}>
              <td>{h.id} {h.name}<div className="muted small">{h.what}</div></td>
              <td className="num">{h.S} {h.F} {h.P}</td>
              <td className={`num plr plr-${h.PLr}`}>{h.PLr}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Safety functions</h3>
      <table className="kv up-table">
        <tbody>
          {sf.functions.map((f) => (
            <tr key={f.id}>
              <td>{f.id} {f.name}<div className="muted small">{f.devices} · {f.stop}</div></td>
              <td className="num">Cat {f.category}</td>
              <td className={`num plr plr-${f.PLr}`}>PL{f.PLr}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>Proofs that gate this export</h3>
      <ul className="up-proofs">
        <li>reach: every hazard zone lies ≥ 20 mm inside the guard (the VGR arm sampled every 5° over its full range)</li>
        <li>fit: no guard part touches any module</li>
        <li>logic: {sf.logic_states.toLocaleString()} input states checked exhaustively. Motion is enabled only with every E-stop released, every door closed and locked, and a reset. A fault in any single channel blocks enable, and a door unlocks only at standstill.</li>
        <li>air: all {sf.cylinders_vented.length} cylinders are fed only through the safe exhaust valve Y1</li>
      </ul>
      {sf.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
    </section>
  );
}
