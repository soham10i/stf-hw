import type { SafetyDoc } from "../shared/model";
import { Note, Proofs, Title } from "./kit";

// Upgrade 2's risk assessment and safety functions, straight from safety.py.
export function SafetyPanel({ sf, showZones, setShowZones }: {
  sf: SafetyDoc; showZones: boolean; setShowZones: (v: boolean) => void;
}) {
  return (
    <section className="panel upgrade safety">
      <Title up="Upgrade 2" lead={`${sf.hazards.length} hazards rated; ${sf.functions.length} safety functions meet the level each one needs.`}>
        Machine safety</Title>
      <label className="small" style={{ display: "flex", gap: 6, alignItems: "center", margin: "0 0 8px" }}>
        <input type="checkbox" checked={showZones} onChange={(e) => setShowZones(e.target.checked)} />
        show hazard zones in 3D (coloured by PLr)
      </label>
      <h3>Hazards (ISO 12100 / 13849-1)</h3>
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
      <Proofs items={[
        "reach: every hazard zone lies ≥ 20 mm inside the guard (the VGR arm sampled every 5° over its full range)",
        "fit: no guard part touches any module",
        `logic: ${sf.logic_states.toLocaleString()} input states checked exhaustively. Motion is enabled only with every E-stop released, every door closed and locked, and a reset. A fault in any single channel blocks enable, and a door unlocks only at standstill.`,
        `air: all ${sf.cylinders_vented.length} cylinders are fed only through the safe exhaust valve Y1`,
      ]} />
      {sf.notes.length > 0 && <Note title="Why guard locking, not a light curtain">{sf.notes.map((n) => <p key={n}>{n}</p>)}</Note>}
    </section>
  );
}
