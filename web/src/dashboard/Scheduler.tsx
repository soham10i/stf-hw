// Upgrade 16: a learned scheduler behind a safety shield (stf-cad/hbw/sched_rl.py). The PLC
// dispatches by a fixed priority list; the agent chooses which job to start, which slot to
// use and which cookie next - but only actions after which the PLC's proven policy could
// still take over and finish under every timing.
import { useJson } from "../shared/data";
import { JOB_COL, JOB_SAY } from "../shared/hmi";
import { Bars, Dumbbell, HBar, Plot, useWidth } from "./Plot";
import { roll } from "./Month";

type Bar = { job: string; bind: string[]; units: string[]; t0: number; t1: number };
type Ev = { runs: number; deadlocks: number; mean: number | null; min: number | null; max: number | null; nominal: number | null };
type Doc = {
  meta: { episodes: number; spread: number; eval_runs: number; q_entries: number; train_s: number; fallback: string;
          shield_states_explored: number; shield_checks: number; method: string; limits: string };
  curve: { episode: number; makespan: number | null; blocked: number }[];
  unshielded: { episodes: number; deadlocks: number };
  eval: Record<string, Ev>;
  paired: { runs: number; wins: number; ties: number; mean_diff_s: number; worst_diff_s: number; best_diff_s: number; diffs: number[] };
  crane_busy_s: { rollout: number; plc: number };
  crane_jobs: Record<"rollout" | "plc", [string, string[]][]>;
  gantt: Bar[]; gantt_plc: Bar[]; units: string[];
};
const NAME: Record<string, string> = { "learned (shielded)": "Q-learning, shielded", "rollout, no learning": "rollout scheduler, shielded",
  single: "PLC: single", reuse: "PLC: reuse (in use)", buffer: "PLC: buffer", prefetch: "PLC: prefetch" };

function Gantt({ rows }: { rows: { label: string; bars: Bar[] }[] }) {
  const [box, W] = useWidth<HTMLDivElement>();
  const units = ["crane", "belt", "arm", "door", "sauger", "turntable", "ovenbelt", "line"];
  const T = Math.max(...rows.flatMap((r) => r.bars.map((b) => b.t1)));
  const L = 74, R = 12, RH = 13, GAP = 24, B = 34;
  const X = (t: number) => L + (t / T) * (W - L - R);
  const h = rows.length * (units.length * RH + GAP) + B;
  return (
    <div className="pl"><div className="pl-box" ref={box}><svg viewBox={`0 0 ${W} ${h}`}>
      {rows.map((r, k) => {
        const y0 = k * (units.length * RH + GAP) + 16, end = Math.max(...r.bars.map((b) => b.t1));
        return <g key={r.label}>
          <text x={L} y={y0 - 5} className="pl-lab" style={{ fill: "var(--text)" }}>{r.label} · {end.toFixed(1)} s</text>
          {units.map((u, i) => <text key={u} x={L - 6} y={y0 + i * RH + 10} textAnchor="end" className="pl-tick">{u}</text>)}
          {r.bars.flatMap((b, j) => b.units.map((u) => units.indexOf(u) < 0 ? null :
            <rect key={`${j}${u}`} x={X(b.t0)} y={y0 + units.indexOf(u) * RH + 1} width={Math.max(0.8, X(b.t1) - X(b.t0) - 0.3)} height={RH - 2}
              fill={JOB_COL[b.job] ?? "#888"} opacity={u === b.units[0] ? 1 : 0.4}><title>{`${b.job} ${b.bind.join(" ")}\n${JOB_SAY[b.job] ?? ""}\n${b.t0}–${b.t1} s`}</title></rect>))}
          <line x1={X(end)} x2={X(end)} y1={y0 - 2} y2={y0 + units.length * RH} stroke="var(--text)" strokeDasharray="3 3" />
        </g>;
      })}
      {[0, 0.25, 0.5, 0.75, 1].map((f) => <text key={f} x={X(f * T)} y={h - 18} textAnchor="middle" className="pl-tick">{Math.round(f * T)}</text>)}
      <text x={(L + W - R) / 2} y={h - 4} textAnchor="middle" className="pl-title">seconds into the order (nominal job times)</text>
    </svg></div></div>
  );
}

export function SchedulerPage() {
  const { data: d, error } = useJson<Doc>("sched/rl.json", "No data. Run: make sched");
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return <div className="db-err">loading…</div>;
  const E = d.eval, ro = E["rollout, no learning"], plc = E[d.meta.fallback], P = d.paired;
  const order = ["rollout, no learning", "learned (shielded)", "reuse", "buffer", "single", "prefetch"].filter((k) => E[k]);
  const ok = d.curve.filter((c) => c.makespan !== null);
  const stores = (k: "rollout" | "plc") => d.crane_jobs[k].filter(([j]) => j === "store" || j === "store_retrieve").map(([, b]) => b[2]).join(" ");
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>order time, nominal</span><b>{ro.nominal} s</b><em>rollout scheduler · PLC {plc.nominal} s (−{((1 - (ro.nominal ?? 0) / (plc.nominal ?? 1)) * 100).toFixed(1)} %)</em></div>
        <div className="db-kpi ok"><span>faster on the same timings</span><b>{P.wins}/{P.runs}</b><em>runs · mean {P.mean_diff_s} s per order</em></div>
        <div className="db-kpi ok"><span>deadlocks, shielded</span><b>0</b><em>in {d.meta.episodes} training orders + every test</em></div>
        <div className="db-kpi fail"><span>deadlocks, no shield</span><b>{d.unshielded.deadlocks}/{d.unshielded.episodes}</b><em>the same agent while it learns</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>The same order, two schedulers</h3>
          <Gantt rows={[{ label: `PLC (${d.meta.fallback})`, bars: d.gantt_plc }, { label: "rollout scheduler", bars: d.gantt }]} />
          <p className="hl-cap">Hover a block for the job and the slot. The gain is the crane: {d.crane_busy_s.plc} s busy under the PLC, {d.crane_busy_s.rollout} s under the scheduler — it stores moulds nearer the belt.</p>
        </section>
        <section className="db-card hl-span2"><h3>Order time on random job times (±{Math.round(d.meta.spread * 100)} %)</h3>
          <Dumbbell xTitle="12-cookie order (s): fastest to slowest of the runs" max={Math.max(...order.map((k) => E[k].max ?? 0)) * 1.02} min={Math.floor(Math.min(...order.map((k) => E[k].min ?? 0)) * 0.97 / 10) * 10} fmt={(v) => `${Math.round(v)}`}
            a={{ name: "fastest", color: "var(--ok)" }} b={{ name: "slowest", color: "var(--bad)" }}
            rows={order.map((k) => ({ label: NAME[k] ?? k, a: E[k].min ?? 0, b: E[k].max ?? 0, note: `mean ${E[k].mean} s, nominal ${E[k].nominal} s, deadlocks ${E[k].deadlocks}/${E[k].runs}` }))} />
          <HBar xTitle="mean order time (s)" x0={Math.floor(Math.min(...order.map((k) => E[k].mean ?? 0)) * 0.95 / 10) * 10} fmt={(v) => v.toFixed(1)}
            rows={order.map((k) => ({ label: NAME[k] ?? k, v: E[k].mean ?? 0, on: k.startsWith("rollout"), color: k.startsWith("rollout") ? "var(--ok)" : k.startsWith("learned") ? "#4f8fd6" : "#6c7884" }))} />
        </section>
        <section className="db-card"><h3>Run by run against the PLC</h3>
          <Bars h={210} xTitle="test run (identical job times for both)" yTitle="seconds saved (− = slower)" yFmt={(v) => v.toFixed(0)} base={0}
            bars={P.diffs.map((x, i) => ({ key: `${i}`, label: `${i + 1}`, v: -x, color: x < 0 ? "var(--ok)" : "var(--bad)",
              tip: [["", `run ${i + 1}`], [x < 0 ? "saved" : "slower by", `${Math.abs(x).toFixed(1)} s`]] }))}
            hlines={[{ y: -P.mean_diff_s, color: "var(--muted)", label: "mean" }]} xLabelEvery={5} />
          <p className="hl-cap">{P.wins} of {P.runs} runs faster; best {(-P.best_diff_s).toFixed(1)} s, worst {P.worst_diff_s > 0 ? `${P.worst_diff_s.toFixed(1)} s slower` : `${(-P.worst_diff_s).toFixed(1)} s faster`}.</p>
        </section>
        <section className="db-card hl-span2"><h3>Learning, and what the shield blocked</h3>
          <Plot h={220} xTitle="training order" yTitle="order time (s)" yFmt={(v) => `${Math.round(v)}`}
            series={[{ name: "each order (exploring)", x: ok.map((c) => c.episode), y: ok.map((c) => c.makespan), color: "#9aa7b4", kind: "dots", fmt: (v) => `${v.toFixed(1)} s` },
                     { name: "50-order mean", x: ok.map((c) => c.episode), y: roll(ok.map((c) => c.makespan), 50), color: "#4f8fd6", width: 2.4, fmt: (v) => `${v.toFixed(1)} s` }]}
            hlines={[{ y: plc.nominal ?? 0, color: "var(--muted)", label: "PLC, nominal" }]}
            tipExtra={(x) => { const c = d.curve[Math.round(x) - 1]; return c ? [["actions blocked by the shield", `${c.blocked}`]] : []; }} />
          <p className="hl-cap">Q-learning on top of the rollout prior does not beat it ({E["learned (shielded)"].mean} s vs {ro.mean} s mean): job times vary and the state does not see time. The shield explored {d.meta.shield_states_explored.toLocaleString()} states.</p>
        </section>
        <section className="db-card"><h3>Where the moulds go</h3>
          <div className="hl-facts col">
            <div><b className="wrap mono">{stores("plc")}</b><span>PLC: the first free slot</span></div>
            <div><b className="wrap mono">{stores("rollout")}</b><span>scheduler: the slot that finishes the order soonest</span></div>
          </div>
          <p className="hl-cap">{d.meta.method}. {d.meta.limits}.</p>
        </section>
      </div>
    </>
  );
}
