// Side panel: component health at a chosen machine age (Upgrade 6's model).
import { useState } from "react";
import type { CadDoc } from "../shared/model";
import { HealthGrid } from "../shared/HealthGrid";
import { maxShifts } from "../shared/health";

export function HealthPanel({ doc }: { doc: CadDoc }) {
  const h = doc.health!;
  const [age, setAge] = useState(0);
  const ageMax = maxShifts(h.components);
  return (
    <section className="panel">
      <h2>Component health</h2>
      <div className="hmi-clock">
        <span className="muted small">age</span>
        <input type="range" min={0} max={ageMax} step={1} value={age} onChange={(e) => setAge(+e.target.value)} />
        <b>{age.toFixed(0)}</b><span className="muted small">shifts</span>
      </div>
      <HealthGrid cs={h.components} shifts={age} compact />
      <table className="kv up-table" style={{ marginTop: 8 }}>
        <thead><tr><td>component</td><td className="num">warned</td></tr></thead>
        <tbody>
          {h.components.map((c) => (
            <tr key={c.id} title={c.metric}><td>{c.name}<div className="muted small">{c.warn_by}</div></td>
              <td className="num up-good">{c.lead_shifts} sh<div className="muted small">before failure</div></td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
