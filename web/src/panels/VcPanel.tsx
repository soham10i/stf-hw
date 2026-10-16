import { useState } from "react";
import type { VcDoc } from "../shared/model";
import { Note, Verified } from "./kit";

// Upgrade 5's commissioning report in the sidebar (vc.py): the healthy run
// against the model, the fault matrix, positioning accuracy and OEE.
export function VcPanel({ vc }: { vc: VcDoc }) {
  const [open, setOpen] = useState<string | null>(null);
  const p = vc.performance;
  const dev = (p.makespan - p.model) / p.model;
  const pct = (x: number) => `${Math.round(x * 1000) / 10} %`;
  const timeOk = Math.abs(dev) <= vc.tol_makespan;
  const passed = vc.matrix.filter((r) => r.pass).length;
  const accOk = vc.accuracy.every((a) => a.ok);
  return (
    <section className="panel upgrade vc">
      <Verified ok={timeOk && passed === vc.matrix.length && accOk} items={[
        [`order ${p.makespan} s vs model ${p.model} s (${dev > 0 ? "+" : ""}${pct(dev)})`,
          `allowed ±${pct(vc.tol_makespan)}; closest step to its watchdog: ${pct(vc.healthy.worst_watchdog ?? 0)} of the limit`],
        [`${passed}/${vc.matrix.length} faults handled`],
        [accOk ? "accuracy in tolerance" : "accuracy out of tolerance"],
      ]} />

      <div className="vc-oee">
        <div className="big"><span>OEE</span>{pct(p.oee)}</div>
        <div title="availability"><span>avail.</span>{pct(p.availability)}</div>
        <div title="performance"><span>perf.</span>{pct(p.performance)}</div>
        <div><span>quality</span>{pct(p.quality)}</div>
      </div>
      <p className="muted small">One shift with every fault once. Bottleneck: the {p.bottleneck} ({p.busy[p.bottleneck]} s busy of {p.makespan} s);
        with the buffer {p.buffer_makespan} s.</p>

      <h3>Faults <em className="sf-std">click one</em></h3>
      <ul className="sf-rows vc-faults">
        {vc.matrix.map((r) => (
          <li key={r.id} className={open === r.id ? "on" : ""} onClick={() => setOpen(open === r.id ? null : r.id)}>
            <div className="vc-row">
              <b>{r.id}</b><span>{r.fault}</span><em>{r.expected} +{r.lost_s} s</em>
              <i className={r.pass ? "plr-a" : "plr-e"}>{r.pass ? "pass" : "FAIL"}</i>
            </div>
            {open === r.id && <p className="muted small">
              {r.what}<br />→ {r.observed.join(", ")} after {r.latency_s} s (bound {r.bound_s} s)<br />
              {r.reaction}<br />{r.recovery}{r.notes.length > 0 && <><br /><b>{r.notes.join("; ")}</b></>}
            </p>}
          </li>
        ))}
      </ul>

      <h3>Accuracy <em className="sf-std">stop error / allowed</em></h3>
      <ul className="sf-rows">
        {vc.accuracy.map((a) => (
          <li key={a.axis} title={`${a.why}\n${a.scan_ms} ms task`}><span>{a.axis}</span>
            <em>± {a.error_mm} / {a.tol_mm} mm</em><i className={a.ok ? "plr-a" : "plr-e"}>{a.ok ? "✓" : "✗"}</i></li>
        ))}
      </ul>

      <Note title="Test setup">Upgrade 4's program against the twin: a {vc.scan_ms.crane} ms task ({vc.scan_ms.arm} ms for
        the VGR), Modbus TCP at {vc.bus_ms} ms, the same register map as the real nodes.</Note>
      <Note title="Without Upgrade 5's sensors">{vc.before.map((b) => `${b.id} found only by ${b.detected}, ${b.after_s} s later`).join("; ")}.</Note>
    </section>
  );
}
