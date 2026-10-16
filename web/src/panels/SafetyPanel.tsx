import type { SafetyDoc } from "../shared/model";

// Upgrade 2's risk assessment and safety functions, straight from safety.py.
export function SafetyPanel({ sf, showZones, setShowZones }: {
  sf: SafetyDoc; showZones: boolean; setShowZones: (v: boolean) => void;
}) {
  const proofs: [string, string][] = [
    ["reach", "every hazard zone lies ≥ 20 mm inside the guard (the VGR arm sampled every 5° over its full range)"],
    ["fit", "no guard part touches any module"],
    ["logic", `${sf.logic_states.toLocaleString()} input states checked exhaustively: motion only with every E-stop released, every door closed and locked, and a reset; a fault in any single channel blocks enable; a door unlocks only at standstill`],
    ["air", `all ${sf.cylinders_vented.length} cylinders are fed only through the safe exhaust valve Y1`],
  ];
  return (
    <section className="panel upgrade safety">
      <div className="sf-head">
        <span>{sf.hazards.length} hazards · {sf.functions.length} safety functions, each at the PL it needs</span>
        <button className={`ui-btn ${showZones ? "on" : ""}`} onClick={() => setShowZones(!showZones)}>{showZones ? "Hide" : "Show"} zones in 3D</button>
      </div>
      <h3>Hazards <em className="sf-std">ISO 12100 · 13849-1</em></h3>
      <ul className="sf-rows">
        {sf.hazards.map((h) => (
          <li key={h.id} title={`${h.what}\nS${h.S} F${h.F} P${h.P}`}><b>{h.id}</b><span>{h.name}</span><i className={`plr plr-${h.PLr}`}>PL {h.PLr}</i></li>
        ))}
      </ul>
      <h3>Safety functions</h3>
      <ul className="sf-rows">
        {sf.functions.map((f) => (
          <li key={f.id} title={`${f.devices} · ${f.stop}`}><b>{f.id}</b><span>{f.name}</span><em>Cat {f.category}</em><i className={`plr plr-${f.PLr}`}>PL {f.PLr}</i></li>
        ))}
      </ul>
      <div className="sf-proven"><b>Proven</b>{proofs.map(([k]) => <span key={k}>✓ {k}</span>)}</div>
      <details className="hmi-fold">
        <summary>How each was proven{sf.notes.length > 0 ? " · why guard locking" : ""}</summary>
        <ul className="sf-how">{proofs.map(([k, v]) => <li key={k}><b>{k}</b> {v}</li>)}</ul>
        {sf.notes.map((n) => <p key={n} className="muted small">{n}</p>)}
      </details>
    </section>
  );
}
