import { useState } from "react";
import type { VcDoc } from "../shared/model";

// Upgrade 5's commissioning report in the sidebar (vc.py): the healthy run
// against the model, the fault matrix, positioning accuracy and OEE.
export function VcPanel({ vc }: { vc: VcDoc }) {
  const [open, setOpen] = useState<string | null>(null);
  const p = vc.performance;
  const dev = (p.makespan - p.model) / p.model;
  const pct = (x: number) => `${Math.round(x * 1000) / 10} %`;
  return (
    <section className="panel upgrade vc">
      <h2>Upgrade 5 · virtual commissioning</h2>
      <p className="muted small">Upgrade 4's program against the twin: a {vc.scan_ms.crane} ms task ({vc.scan_ms.arm} ms for
        the VGR), Modbus TCP at {vc.bus_ms} ms, the same register map as the real nodes.</p>

      <h3>Healthy run</h3>
      <table className="kv up-table"><tbody>
        <tr><td>order time, commissioned</td><td className="num">{p.makespan} s</td></tr>
        <tr><td>order time, model (U4)</td><td className="num">{p.model} s</td></tr>
        <tr><td>difference</td><td className={`num ${Math.abs(dev) <= vc.tol_makespan ? "up-good" : "up-cost"}`}>
          {dev > 0 ? "+" : ""}{pct(dev)} (≤ {pct(vc.tol_makespan)})</td></tr>
        <tr><td>closest step to its watchdog</td><td className="num">{pct(vc.healthy.worst_watchdog ?? 0)} of the limit</td></tr>
      </tbody></table>

      <h3>Fault matrix</h3>
      <table className="kv up-table vc-matrix">
        <tbody>
          {vc.matrix.map((r) => (
            <tr key={r.id} onClick={() => setOpen(open === r.id ? null : r.id)} style={{ cursor: "pointer" }}
              className={open === r.id ? "on" : ""}>
              <td><b>{r.id}</b> {r.fault}
                {open === r.id && <div className="muted small">
                  {r.what}<br />→ {r.observed.join(", ")} after {r.latency_s} s (bound {r.bound_s} s)<br />
                  {r.reaction}<br />{r.recovery}{r.notes.length > 0 && <><br /><b>{r.notes.join("; ")}</b></>}
                </div>}
              </td>
              <td className="num">{r.expected}<div className="muted small">+{r.lost_s} s</div></td>
              <td className={`num ${r.pass ? "up-good" : "up-cost"}`}>{r.pass ? "pass" : "FAIL"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">Before Upgrade 5's sensors: {vc.before.map((b) => `${b.id} found only by ${b.detected}, ${b.after_s} s later`).join("; ")}.</p>

      <h3>Positioning accuracy</h3>
      <table className="kv up-table"><tbody>
        <tr><td>axis</td><td className="num">task</td><td className="num">stop error</td><td className="num">allowed</td></tr>
        {vc.accuracy.map((a) => (
          <tr key={a.axis} title={a.why}><td>{a.axis}</td><td className="num">{a.scan_ms} ms</td>
            <td className={`num ${a.ok ? "up-good" : "up-cost"}`}>± {a.error_mm} mm</td><td className="num">± {a.tol_mm} mm</td></tr>
        ))}
      </tbody></table>

      <h3>OEE (one shift with every fault once)</h3>
      <div className="vc-oee">
        <div><span>availability</span>{pct(p.availability)}</div>
        <div><span>performance</span>{pct(p.performance)}</div>
        <div><span>quality</span>{pct(p.quality)}</div>
        <div className="big"><span>OEE</span>{pct(p.oee)}</div>
      </div>
      <p className="muted small">Bottleneck: the {p.bottleneck} ({p.busy[p.bottleneck]} s busy of {p.makespan} s), not the
        oven as the plan expected. With the buffer: {p.buffer_makespan} s.</p>
    </section>
  );
}
