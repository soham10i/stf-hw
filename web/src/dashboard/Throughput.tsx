// Upgrade 10: throughput (stf-cad/hbw/throughput.py) - where the order's time
// went, the four measures that took a third of it out, and the proofs that the
// faster program is still deadlock-free, collision-free and recoverable.
import { JOB_COL, JOB_SAY } from "../shared/hmi";
import { useJson } from "../shared/data";

const COL: Record<string, string> = { ...JOB_COL, present: "#f0c05a", place_oven: "#c7851c", store_retrieve: "#1f78c8" };
const SAY: Record<string, string> = { ...JOB_SAY, belt_to_oven: "VGR: pick from the belt (U10: the pick half only)",
  present: "oven: door open, Ofenschieber out", place_oven: "VGR: lay the cookie on the tray, home",
  store_retrieve: "crane: store the mould coming in + retrieve the next (one trip)" };
const UNITS = ["crane", "belt", "arm", "door", "sauger", "turntable", "ovenbelt", "line"];

type Bar = { job: string; bind: string[]; units: string[]; t0: number; t1: number; steps: [string, number, number][] };
type Abl = { name: string; on: string[]; model_s: number; vc_s: number; busy: Record<string, number>; cycle_s: number; per_hour: number };
type Oee = { availability: number; performance: number; quality: number; oee: number; bottleneck: string; makespan: number; shift_s: number };
type Doc = {
  meta: { cookies: number; orders_note: string; bake_demo_s: number; margin_mm: number; t_zero_s: number; t_min_s: number; assumed: string };
  measures: { id: string; say: string; alone_s: number; marginal_s: number }[];
  ablation: Abl[];
  critical_path: Record<"before" | "after", { chain: { job: string; t0: number; t1: number }[]; by_job: Record<string, number> }>;
  tours: Record<"before" | "after", Record<string, number>>;
  study: { bake_s: number; before: number; after: number; gain: number }[];
  proofs: { explored_states: Record<string, number>; recovery_poses: number; vc_vs_model: number;
            fault_matrix: { id: string; fault: string; expected: string; observed: string[]; latency_s: number; lost_s: number; pass: boolean }[] };
  oee: Record<"before" | "after", Oee>;
  gantt: Record<"before" | "after", Bar[]>;
  main_st: string;
  findings: { title: string; text: string }[];
};

function Gantt({ bars, tMax, title }: { bars: Bar[]; tMax: number; title: string }) {
  const W = 1000, L = 74, R = 8, rowH = 16, T = 16;
  const X = (t: number) => L + (t / tMax) * (W - L - R);
  const H = T + UNITS.length * rowH + 16;
  const end = Math.max(...bars.map((b) => b.t1));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="db-gantt">
      <text x={L} y={11} className="db-gt">{title}</text>
      {UNITS.map((u, i) => <text key={u} x={L - 6} y={T + i * rowH + 11} textAnchor="end" className="db-gt">{u}</text>)}
      {bars.flatMap((b, bi) => b.steps.map((s, si) => {
        const r = UNITS.indexOf(s[0]);
        if (r < 0 || s[2] <= s[1]) return null;
        return <rect key={`${bi}-${si}`} x={X(s[1])} y={T + r * rowH + 2} width={Math.max(0.6, X(s[2]) - X(s[1]))} height={rowH - 4}
          fill={COL[b.job] ?? "#888"}><title>{`${b.job} ${b.bind.join(" ")}\n${SAY[b.job] ?? ""}\n${s[1].toFixed(1)}–${s[2].toFixed(1)} s`}</title></rect>;
      }))}
      <line x1={X(end)} x2={X(end)} y1={T - 4} y2={T + UNITS.length * rowH} style={{ stroke: "var(--text)" }} strokeDasharray="3 3" />
      <text x={X(end) + 4} y={T + UNITS.length * rowH + 12} className="db-gt">{end.toFixed(0)} s</text>
      {[0, 100, 200, 300, 400, 500, 600].filter((x) => x <= tMax).map((x) => (
        <text key={x} x={X(x)} y={H - 2} textAnchor="middle" className="db-gt">{x}</text>))}
    </svg>
  );
}

function Stack({ by, scale, label }: { by: Record<string, number>; scale: number; label: string }) {
  const tot = Object.values(by).reduce((a, b) => a + b, 0);
  return (
    <div className="mo-stack"><span>{label}</span>
      <div>{Object.entries(by).map(([j, v]) => (
        <i key={j} title={`${j}: ${v} s`} style={{ width: `${(v / scale) * 100}%`, background: COL[j] ?? "#888" }} />))}</div>
      <b>{tot.toFixed(0)} s</b></div>
  );
}

export function ThroughputPage() {
  const { data: d, error: err } = useJson<Doc>("throughput/throughput.json", "No throughput data. Run: STF_VARIANT=up10 python3 throughput.py");
  if (err) return <div className="db-err">{err}</div>;
  if (!d) return <div className="db-err">loading the throughput study…</div>;
  const b = d.ablation[0], a = d.ablation[d.ablation.length - 1];
  const tMax = Math.max(b.vc_s, a.vc_s);
  const maxVc = Math.max(...d.ablation.map((x) => x.vc_s));
  const jobs = Array.from(new Set([...d.gantt.before, ...d.gantt.after].map((x) => x.job)));
  const cpMax = Math.max(...(["before", "after"] as const).map((k) => Object.values(d.critical_path[k].by_job).reduce((s, v) => s + v, 0)));
  const bott = (x: Abl) => Object.entries(x.busy).sort((p, q) => q[1] - p[1])[0];
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>12-cookie order (commissioned)</span><b>{a.vc_s} s</b><em>before {b.vc_s} s (−{Math.round(100 * (1 - a.vc_s / b.vc_s))} %)</em></div>
        <div className="db-kpi"><span>cookies an hour</span><b>{a.per_hour}</b><em>before {b.per_hour}</em></div>
        <div className="db-kpi"><span>steady-state cycle</span><b>{a.cycle_s} s</b><em>before {b.cycle_s} s</em></div>
        <div className="db-kpi"><span>OEE (shift with every fault once)</span><b>{Math.round(d.oee.after.oee * 100)} %</b><em>before {Math.round(d.oee.before.oee * 100)} %</em></div>
        <div className="db-kpi warn"><span>busiest unit</span><b>{bott(a)[0]}</b><em>{bott(a)[1]} s busy; before: {bott(b)[0]} {bott(b)[1]} s</em></div>
        <div className="db-kpi ok"><span>proofs</span><b>{d.proofs.fault_matrix.filter((r) => r.pass).length}/{d.proofs.fault_matrix.length}</b><em>faults recovered; no deadlock in {d.proofs.explored_states.reuse} states</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>What the study says</h3>
          <div className="mo-insights">{d.findings.map((f) => <div key={f.title}><b>{f.title}</b><p>{f.text}</p></div>)}</div>
        </section>
        <section className="db-card wide"><h3>The same order, before and after, on one time scale (virtual commissioning)</h3>
          <Gantt bars={d.gantt.before} tMax={tMax} title="before: the Upgrade 7 program" />
          <Gantt bars={d.gantt.after} tMax={tMax} title="after: Upgrade 10" />
          <div className="db-legend">{jobs.map((j) => <span key={j}><i style={{ background: COL[j] ?? "#888" }} />{j}</span>)}</div>
          <p className="db-note">Each row is a unit's state machine; each block one step, as the PLC saw it complete (plant physics, both
            Modbus hops, the scan). Hover a block for its job. Before, the arm row is long and the crane waits for the mould; after, the
            VGR hands the mould back at the pick and the oven opens while the arm is still on its way.</p>
        </section>
        <section className="db-card wide"><h3>Where the time went: the critical path, by job</h3>
          <Stack by={d.critical_path.before.by_job} scale={cpMax} label="before" />
          <Stack by={d.critical_path.after.by_job} scale={cpMax} label="after" />
          <p className="db-note">Walked back from the last job: every job was started by the completion that freed it (the dispatcher only acts
            on completions). Before, the path circles the mould loop - crane, belt, the whole VGR tour to the oven, belt back, crane.</p>
        </section>
        <section className="db-card wide"><h3>Ablation: each measure switched off alone, same process, same plant model</h3>
          <table className="db-table"><thead><tr><td>program</td><td className="num">nominal</td><td className="num">commissioned</td><td /><td className="num">cycle</td>
            <td className="num">per hour</td><td className="num">busiest</td></tr></thead>
            <tbody>{d.ablation.map((x) => (
              <tr key={x.name} className={x.name === "Upgrade 10" ? "on" : ""}><td>{x.name}</td><td className="num">{x.model_s} s</td>
                <td className="num">{x.vc_s} s</td>
                <td style={{ width: "30%" }}><div className="db-prog"><i style={{ width: `${(x.vc_s / maxVc) * 100}%`, background: x.name.startsWith("before") ? "#6c7884" : "#4f8fd6" }} /></div></td>
                <td className="num">{x.cycle_s} s</td><td className="num">{x.per_hour}</td><td className="num">{bott(x)[0]}</td></tr>))}</tbody></table>
          <table className="db-table" style={{ marginTop: 10 }}><thead><tr><td>measure</td><td className="num">saves alone</td><td className="num">worth in the full set</td></tr></thead>
            <tbody>{d.measures.map((m) => <tr key={m.id}><td><b>{m.id}</b> - {m.say}</td><td className="num">{m.alone_s} s</td><td className="num">{m.marginal_s} s</td></tr>)}</tbody></table>
          <p className="db-note">"Worth in the full set" is the time added back when only that measure is removed. The two columns differ because
            the measures interact: a shorter VGR tour matters most once the tour is off the mould loop.</p>
        </section>
        <section className="db-card"><h3>The VGR's tours</h3>
          <table className="db-table"><thead><tr><td>tour</td><td className="num">before</td><td className="num">after</td></tr></thead>
            <tbody>{Object.keys(d.tours.before).map((k) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{d.tours.before[k]} s</td>
              <td className="num">{d.tours.after[k]} s</td></tr>)}</tbody></table>
          <p className="db-note">Crossings fly {d.meta.margin_mm} mm above the lowest height the SAT sweep proves clear, and swing while they climb,
            instead of rising to the 500 mm transit plane. A waypoint with nothing to move costs a {d.meta.t_zero_s * 1000} ms position check, not the
            {" "}{d.meta.t_min_s} s minimum move.</p>
        </section>
        <section className="db-card"><h3>With a real bake</h3>
          <table className="db-table"><thead><tr><td>bake</td><td className="num">before</td><td className="num">after</td><td className="num">gain</td></tr></thead>
            <tbody>{d.study.map((r) => <tr key={r.bake_s}><td>{r.bake_s} s{r.bake_s === d.meta.bake_demo_s ? " (demo)" : ""}</td><td className="num">{r.before} s</td>
              <td className="num">{r.after} s</td><td className="num">{Math.round(r.gain * 100)} %</td></tr>)}</tbody></table>
          <p className="db-note">Nominal schedule. The longer the bake, the more the oven limits the order, and the less the loop matters.</p>
        </section>
        <section className="db-card"><h3>OEE, same shift definition</h3>
          <table className="db-table"><thead><tr><td /><td className="num">before</td><td className="num">after</td></tr></thead>
            <tbody>{(["availability", "performance", "quality", "oee"] as const).map((k) => (
              <tr key={k}><td>{k}</td><td className="num">{Math.round(d.oee.before[k] * 100)} %</td><td className="num">{Math.round(d.oee.after[k] * 100)} %</td></tr>))}
              <tr><td>bottleneck</td><td className="num">{d.oee.before.bottleneck}</td><td className="num">{d.oee.after.bottleneck}</td></tr></tbody></table>
          <p className="db-note">A shift = the order with every fault of the matrix once. Performance = the busiest unit's time / the order time:
            it rises because the idle waiting went, not because anything runs faster.</p>
        </section>
        <section className="db-card wide"><h3>Proofs the faster program still passes</h3>
          <table className="db-table"><thead><tr><td>fault</td><td>expected</td><td>observed</td><td className="num">detected after</td><td className="num">time lost</td><td /></tr></thead>
            <tbody>{d.proofs.fault_matrix.map((r) => (
              <tr key={r.id}><td>{r.id} {r.fault}</td><td className="mono">{r.expected}</td><td className="mono">{r.observed.join(", ")}</td>
                <td className="num">{r.latency_s} s</td><td className="num">+{r.lost_s} s</td><td className={r.pass ? "ok" : "fail"}>{r.pass ? "pass" : "FAIL"}</td></tr>))}</tbody></table>
          <p className="db-note">Explored exhaustively, every completion order: {Object.entries(d.proofs.explored_states).map(([p, n]) => `${p} ${n} states`).join(", ")}
            {" "}(prefetch still deadlocks, as it must). Every blended tour swept at 1°/2 mm; the plunge-up recovery holds from {d.proofs.recovery_poses} poses.
            Commissioned vs nominal: {(d.proofs.vc_vs_model * 100).toFixed(1)} %.</p>
          <details><summary className="db-muted">the orchestrator's priority table (MAIN.st, generated)</summary><pre className="tp-st">{d.main_st}</pre></details>
          <p className="db-note">Simulated, not measured. Assumed: {d.meta.assumed}. {d.meta.orders_note}.</p>
        </section>
      </div>
    </>
  );
}
