// The Engineer pages built from the twin's export: Engineering and Data.

import { type CadDoc } from "../shared/model";


















import { Dumbbell, HBar } from "./Plot";
import { Card, HBars } from "./ui";

export function Engineering({ doc }: { doc: CadDoc }) {
  const vc = doc.vc!, lc = doc.lifecycle;
  return (
    <div className="db-grid">
      <Card title="Positioning accuracy">
        <Dumbbell xTitle="stopping error vs allowed (mm)" max={Math.max(...vc.accuracy.map((x) => Math.max(x.tol_mm, x.error_mm))) * 1.1} fmt={(v) => v.toFixed(1)}
          a={{ name: "error", color: "#4f8fd6" }} b={{ name: "allowed", color: "var(--ok)" }}
          rows={vc.accuracy.map((x) => ({ label: x.axis, a: x.error_mm, b: x.tol_mm, note: `${x.scan_ms} ms scan · ${x.why}` }))} />
      </Card>
      {lc && (
        <>
          <Card title="Tolerance chains: worst-case margin">
            <HBar xTitle="clearance left in the worst case (mm)" fmt={(v) => v.toFixed(2)}
              rows={lc.chains.map((ch) => ({ label: `${ch.id} ${ch.what.split(" (")[0]}`, v: Math.max(0, ch.worst), color: ch.ok ? "var(--ok)" : "var(--bad)",
                tip: `${ch.id} ${ch.what}: nominal ${ch.nominal} mm, worst ${ch.worst}, RSS ${ch.rss}${lc.chains_before?.find((x) => x.id === ch.id) ? ` · before the lifecycle changes: ${lc.chains_before.find((x) => x.id === ch.id)!.worst}` : ""}` }))} />
          </Card>
          <Card title="Structure: first natural frequency">
            <HBar xTitle="f₁ (Hz) · must stay above the drives' excitation" fmt={(v) => `${Math.round(v)}`} refs={[{ v: lc.rules.f_min_hz, label: "minimum", color: "var(--warn)" }]}
              rows={lc.structure.map((m) => ({ label: m.member, v: m.f1_hz, color: m.ok ? "#4f8fd6" : "var(--bad)", tip: `${m.member}: ${m.section}, deflection ${m.defl_mm} mm` }))} />
          </Card>
          <Card title="Service access">
            <HBars rows={lc.access.map((a) => [`${a.part} (${a.door})`, a.reach_mm, a.in_reach ? "#4f8fd6" : "#e0503a"])} max={lc.rules.reach_mm} unit="mm" />
          </Card>
        </>
      )}
    </div>
  );
}

export function Data({ doc, src }: { doc: CadDoc; src: string }) {
  const h = doc.health!, vc = doc.vc!;
  return (
    <div className="db-grid">
      <Card title="Topics (PLC → MQTT → historian → this page)" wide>
        <table className="db-table"><thead><tr><td>topic</td><td>rate</td><td>fields</td><td>from</td></tr></thead>
          <tbody>{h.topics.map((t) => <tr key={t.topic}><td className="mono">{t.topic}</td><td>{t.rate}</td><td>{t.fields}</td><td className="mono">{t.sources.join(" ")}</td></tr>)}</tbody></table>
        <p className="db-note">{h.new_hardware}. This page currently reads the twin's export ({src}); pointed at the broker, the same views read the live topics.</p>
      </Card>
      <Card title="Register map" wide>
        <table className="db-table"><thead><tr><td>tag</td><td>node</td><td>table</td><td className="num">address</td><td>meaning</td></tr></thead>
          <tbody>{vc.map.map((r) => <tr key={r.tag}><td className="mono">{r.tag}</td><td className="mono">{r.node}</td><td>{r.table}</td><td className="num">{r.addr}</td><td>{r.desc}</td></tr>)}</tbody></table>
      </Card>
    </div>
  );
}
