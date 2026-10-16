// Upgrade 10: throughput (stf-cad/hbw/throughput.py) - where the order's time
// went, the four measures that took a third of it out, and the proofs that the
// faster program is still deadlock-free, collision-free and recoverable.
import { JOB_COL, JOB_SAY } from "../shared/hmi";
import { useJson } from "../shared/data";
import { Dumbbell, HBar, Plot } from "./Plot";

const COL: Record<string, string> = { ...JOB_COL, present: "#f0c05a", place_oven: "#c7851c", store_retrieve: "#1f78c8" };
const SAY: Record<string, string> = { ...JOB_SAY, belt_to_oven: "VGR: pick from the belt (the pick half only)",
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
          <Gantt bars={d.gantt.before} tMax={tMax} title="before: the original program" />
          <Gantt bars={d.gantt.after} tMax={tMax} title="after: the throughput program" />
          <div className="db-legend">{jobs.map((j) => <span key={j}><i style={{ background: COL[j] ?? "#888" }} />{j}</span>)}</div>
          <p className="db-note">Each row is a unit's state machine; each block one step, as the PLC saw it complete (plant physics, both
            Modbus hops, the scan). Hover a block for its job. Before, the arm row is long and the crane waits for the mould; after, the
            VGR hands the mould back at the pick and the oven opens while the arm is still on its way.</p>
        </section>
        <section className="db-card wide"><h3>Where the time went: the critical path, by job</h3>
          <Stack by={d.critical_path.before.by_job} scale={cpMax} label="before" />
          <Stack by={d.critical_path.after.by_job} scale={cpMax} label="after" />
          <div className="db-legend">{Array.from(new Set([...Object.keys(d.critical_path.before.by_job), ...Object.keys(d.critical_path.after.by_job)])).map((j) =>
            <span key={j} title={SAY[j]}><i style={{ background: COL[j] ?? "#888" }} />{j.replace(/_/g, " ")}</span>)}</div>
          <p className="db-note">Walked back from the last job: every job was started by the completion that freed it (the dispatcher only acts
            on completions). Before, the path circles the mould loop - crane, belt, the whole VGR tour to the oven, belt back, crane.</p>
        </section>
        <section className="db-card hl-span2"><h3>Ablation: the order time with each measure switched off</h3>
          <HBar xTitle="12-cookie order, commissioned (s)" fmt={(v) => `${Math.round(v)}`} x0={Math.floor(a.vc_s * 0.8 / 50) * 50}
            refs={[{ v: b.vc_s, label: "before", color: "var(--muted)" }, { v: a.vc_s, label: "Throughput program", color: "var(--ok)" }]}
            rows={[...d.ablation].sort((p, q) => q.vc_s - p.vc_s).map((x) => ({ label: x.name, v: x.vc_s, on: x.name === "Throughput program",
              color: x.name.startsWith("before") ? "#6c7884" : x.name === "Throughput program" ? "var(--ok)" : "#4f8fd6",
              tip: `${x.name}: ${x.vc_s} s commissioned (${x.model_s} s nominal) · cycle ${x.cycle_s} s · ${x.per_hour}/h · busiest ${bott(x)[0]}` }))} />
          <p className="hl-cap">Axis starts at {Math.floor(a.vc_s * 0.8 / 50) * 50} s so the differences show. Hover a bar for cycle time and the busiest unit.</p>
        </section>
        <section className="db-card"><h3>What each measure is worth</h3>
          <Dumbbell xTitle="seconds saved" max={Math.max(...d.measures.map((m) => Math.max(m.alone_s, m.marginal_s))) * 1.1} fmt={(v) => `${Math.round(v)} s`}
            a={{ name: "alone", color: "#9fd0ff" }} b={{ name: "in the full set", color: "var(--ok)" }}
            rows={d.measures.map((m) => ({ label: m.id, a: m.alone_s, b: m.marginal_s, note: m.say }))} />
          <ul className="tp-meas">{d.measures.map((m) => <li key={m.id}><b>{m.id}</b>{m.say}</li>)}</ul>
        </section>
        <section className="db-card"><h3>The VGR's tours</h3>
          <Dumbbell xTitle="tour time (s)" max={Math.max(...Object.values(d.tours.before)) * 1.1} fmt={(v) => `${v.toFixed(0)} s`}
            a={{ name: "after", color: "var(--ok)" }} b={{ name: "before", color: "#6c7884" }}
            rows={Object.keys(d.tours.before).map((k) => ({ label: k.replace(/_/g, " "), a: d.tours.after[k], b: d.tours.before[k] }))} />
          <p className="hl-cap">Crossings fly {d.meta.margin_mm} mm above the proven-clear height and swing while they climb, instead of rising to the 500 mm transit plane.</p>
        </section>
        <section className="db-card"><h3>With a real bake</h3>
          <Plot h={230} xTitle="bake time (s)" yTitle="order time (s)" yMin={0}
            series={[{ name: "before", x: d.study.map((r) => r.bake_s), y: d.study.map((r) => r.before), color: "#6c7884", width: 2.2 },
                     { name: "Throughput program", x: d.study.map((r) => r.bake_s), y: d.study.map((r) => r.after), color: "#22c55e", width: 2.4 }]}
            vmarks={[{ x: d.meta.bake_demo_s, color: "var(--muted)", label: "demo bake" }]}
            tipExtra={(x) => { const r = d.study.find((q) => q.bake_s === x); return r ? [["gain", `${Math.round(r.gain * 100)} %`]] : []; }} />
          <p className="hl-cap">The longer the bake, the more the oven limits the order and the less the faster loop matters.</p>
        </section>
        <section className="db-card"><h3>OEE, before and after</h3>
          <Dumbbell xTitle="share of the shift" a={{ name: "before", color: "#6c7884" }} b={{ name: "Throughput program", color: "var(--ok)" }}
            rows={(["availability", "performance", "quality", "oee"] as const).map((k) => ({ label: k === "oee" ? "OEE" : k, a: d.oee.before[k], b: d.oee.after[k] }))} />
          <p className="hl-cap">Bottleneck: {d.oee.before.bottleneck} → {d.oee.after.bottleneck}. Performance rises because idle waiting went, not because anything runs faster.</p>
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
