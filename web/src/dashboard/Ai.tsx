// Upgrade 8: the semi-supervised deep-learning predictor - how it was trained,
// how it scores against the U6 rules on machines it never saw, and the model
// itself running here in the browser on the month's data.
import { useEffect, useMemo, useState } from "react";
import { Chart } from "./Month";
import { Dumbbell, Plot, Scatter, Stacked } from "./Plot";
import { type Weights, buildWindow, forward, predictAt } from "./ml";
import { useJson } from "../shared/data";

const BASE = import.meta.env.BASE_URL;

type Result = { name: string; failures: number; warned_1shift: number; warned_1shift_pct: number; missed: number; late: number;
                lead_median_orders: number | null; false: number; false_per_1000: number; rul_mae_orders?: number; wasted_life_median_shifts?: number | null;
                macro_f1?: number; f1_healthy_degrading_critical?: number[] };
type Res = {
  method: string;
  model: { type: string; params: number; window_orders: number; rul_cap_orders: number; inputs: string[]; heads: string;
           onnx_bytes: number; onnx_max_abs_err: number; device: string };
  data: { machines: number; train: number; labelled: number; test: number; days_each: number; orders: number; failures: number;
          failures_labelled: number; failures_test: number; unlabelled_windows: number; labelled_windows: number };
  labels: { critical_orders: number; degrading_orders: number };
  alarm: { rul_below_orders: number; for_orders: number; lead_needed_orders: number };
  results: Result[]; per_component: Record<string, { failures: number; ml_ok: number; ml_lead_median: number | null; rule_ok: number; rule_lead_median: number | null }>;
  log: { stage: string; epoch: number; loss: number; consistency?: number }[]; train_s: number;
  showcase: { machine: number; stride: number; rows: { comp: string; true: (number | null)[]; pred: number[]; fails: number[]; alarms: number[]; rules: number[] }[] };
  limits: string;
  tuned?: { method: string; chosen: Record<string, number>; hybrid_note: string;
            table: (Result & { wasted_life_median_shifts: number | null })[];
            sweep_validation: Record<string, { threshold: number; warned_1shift: number; warned_1shift_pct: number; failures: number; false_per_1000: number; wasted_life_median_shifts: number }[]> };
};
type MonthIn = { t: number[]; x: number[][]; torch_rul: number[][]; rule_warnings: { t: number; comp: string }[]; maintenance: { t: number; comp: string }[] };

function useAi() {
  const hint = "No model yet. Run: STF_VARIANT=up7 python3 -m ml.train";
  const W = useJson<Weights>("ml/weights.json", hint), R = useJson<Res>("ml/results.json", hint);
  const M = useJson<MonthIn>("ml/month_inputs.json", hint);
  const err = W.error ?? R.error ?? M.error;
  // one object per loaded set: the month's computation below restarts whenever it changes
  const d = useMemo(() => (W.data && R.data && M.data ? { W: W.data, R: R.data, M: M.data } : null), [W.data, R.data, M.data]);
  return { d, err };
}

const NICE: Record<string, string> = { cup: "VGR cup seal", door: "oven door cyl.", lower: "Sauger cylinder", pusher: "Auswerfer cyl.",
  belt: "HBW belt", rfid: "RFID heads", spindle: "HBW spindle", gearbox: "VGR gearbox", air: "air supply", colour: "colour sensor" };

export function AiPage() {
  const { d, err } = useAi();
  const [comp, setComp] = useState(7);
  const [t, setT] = useState(0);
  const [show, setShow] = useState(0);
  const [full, setFull] = useState<{ c: number; rul: number[]; err: number; done: number } | null>(null);
  const live = useMemo(() => (d ? predictAt(d.W, d.M.x, t) : null), [d, t]);
  // the whole month for one component, every 4th order, computed here in small chunks
  useEffect(() => {
    if (!d) return;
    let stop = false;
    const n = d.M.x.length, step = 4, out: number[] = [];
    let i = 0, maxErr = 0;
    const run = () => {
      const t0 = performance.now();
      while (i < n && performance.now() - t0 < 25) {
        const r = forward(d.W, buildWindow(d.W, d.M.x, comp, i)).rul;
        out.push(r);
        maxErr = Math.max(maxErr, Math.abs(r - d.M.torch_rul[i][comp]));
        i += step;
      }
      if (stop) return;
      setFull({ c: comp, rul: [...out], err: maxErr, done: i / n });
      if (i < n) setTimeout(run, 0);        // not rAF: it pauses in a hidden tab
    };
    setFull(null);
    const id = setTimeout(run, 0);
    return () => { stop = true; clearTimeout(id); };
  }, [d, comp]);
  if (err) return <div className="db-err">{err}</div>;
  if (!d) return <div className="db-err">loading the model…</div>;
  const { W, R, M } = d;
  const semi = R.tuned?.table.find((r) => r.name.startsWith("semi")) ?? R.results.find((r) => r.name.startsWith("semi"))!;
  const rule = R.tuned?.table[0] ?? R.results[0];
  const k = W.components[comp];
  const tArr = M.t.filter((_, i) => i % 4 === 0).slice(0, full?.rul.length ?? 0);
  const marks = [...M.rule_warnings.filter((w) => w.comp === k).map((w) => ({ x: w.t, color: "#e0a02a", label: "rule warning" })),
                 ...M.maintenance.filter((w) => w.comp === k).map((w) => ({ x: w.t, color: "#22c55e", label: "renewed" }))];
  const stages = Array.from(new Set(R.log.map((l) => l.stage)));
  const SC: Record<string, string> = { pretrain: "#9fd0ff", "fine-tune": "#86efac", "mean teacher": "#22c55e", "supervised-only": "#e0a02a", oracle: "#b07ad6" };
  const tuned = R.tuned?.table ?? R.results;
  const short = (n: string) => n.startsWith("Condition monitoring") ? "threshold rules" : n.startsWith("hybrid") ? "hybrid" : n.startsWith("semi") ? "network (semi-supervised)"
    : n.startsWith("supervised") ? "network (supervised only)" : n.startsWith("oracle") ? "network (all labelled)" : n;
  const PC: Record<string, string> = { "threshold rules": "#e0a02a", hybrid: "#22c55e", "network (semi-supervised)": "#4f8fd6", "network (supervised only)": "#9fd0ff", "network (all labelled)": "#b07ad6" };
  const hybrid = R.tuned?.table.find((r) => r.name.startsWith("hybrid"));
  const row = R.showcase.rows[Math.min(show, R.showcase.rows.length - 1)];
  const sx = row.pred.map((_, i) => i * R.showcase.stride);
  const mae = row.pred.reduce((a, p, i) => a + (row.true[i] === null ? 0 : Math.abs(p - (row.true[i] as number))), 0) / Math.max(1, row.true.filter((v) => v !== null).length);
  const sweep = R.tuned?.sweep_validation;
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>warned in time · rules</span><b>{rule.warned_1shift}/{rule.failures}</b><em>but ~{rule.wasted_life_median_shifts ?? "15"} shifts of life thrown away</em></div>
        <div className="db-kpi warn"><span>warned in time · network</span><b>{semi.warned_1shift}/{semi.failures}</b><em>unseen machines · {semi.missed} missed</em></div>
        {hybrid && <div className="db-kpi"><span>hybrid (rules flag, network dates)</span><b>{hybrid.missed} missed</b><em>{hybrid.late} late · saves {(rule.wasted_life_median_shifts! - hybrid.wasted_life_median_shifts!).toFixed(1)} shifts of life</em></div>}
        <div className={`db-kpi ${full && full.err < 0.05 ? "ok" : ""}`}><span>browser = PyTorch</span><b>{full ? full.err.toFixed(4) : "…"}</b><em>max difference, orders ({full ? Math.round(full.done * 100) : 0} % checked)</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card hl-span2"><h3>What happened to each of the {rule.failures} failures</h3>
          <Stacked parts={[{ name: "warned ≥ 1 shift ahead", color: "var(--ok)" }, { name: "warned late", color: "var(--warn)" }, { name: "missed", color: "var(--bad)" }]}
            rows={tuned.map((r) => ({ label: short(r.name), v: [r.warned_1shift, r.late, r.missed], on: r.name.startsWith("hybrid") }))} />
          <p className="hl-cap">{R.data.test} machines the model never saw · a warning counts if it comes ≥ {R.alarm.lead_needed_orders} orders (one shift) before the failure.</p>
        </section>
        <section className="db-card"><h3>Verdict</h3>
          <ul className="ai-verdict">
            <li><b>Rules</b> catch every failure, but renew parts ~15 shifts early.</li>
            <li><b>Network</b> times the work well (~3 shifts early) but misses a quarter on unseen machines.</li>
            <li><b>Use</b> the network as an advisory date beside the rules (shadow mode) until it has real run-to-failure data.</li>
          </ul>
        </section>
        {R.tuned && (
          <section className="db-card hl-span2"><h3>The trade-off: catching failures vs throwing life away</h3>
            <Scatter better="top-left" xTitle="part life thrown away per renewal (shifts, median)" yTitle="failures warned in time (%)" yMin={0} yMax={105}
              yFmt={(v) => `${Math.round(v)}`} xFmt={(v) => `${v}`}
              pts={R.tuned.table.map((r) => ({ label: short(r.name), x: r.wasted_life_median_shifts ?? 0, y: (100 * r.warned_1shift) / r.failures, color: PC[short(r.name)] ?? "#9fd0ff",
                tip: [["warned in time", `${r.warned_1shift}/${r.failures}`], ["late", `${r.late}`], ["missed", `${r.missed}`], ["life thrown away", `${r.wasted_life_median_shifts} shifts`], ["false alarms", `${r.false_per_1000} / 1000 orders`]] }))} />
          </section>
        )}
        {sweep && (
          <section className="db-card"><h3>Choosing the network's alarm threshold</h3>
            <Plot h={230} xTitle="alarm when predicted life < (orders)" yTitle="warned in time (%)" yMin={0} yMax={105} yFmt={(v) => `${Math.round(v)}`}
              series={Object.entries(sweep).map(([k, v]) => ({ name: k === "semi" ? "semi-supervised" : "supervised only", x: v.map((p) => p.threshold), y: v.map((p) => p.warned_1shift_pct),
                color: k === "semi" ? "#4f8fd6" : "#9fd0ff", width: 2.4, fmt: (y: number) => `${y.toFixed(0)} %` }))}
              vmarks={[{ x: R.tuned!.chosen.semi, color: "var(--ok)", label: "chosen" }]}
              tipExtra={(x) => { const p = sweep.semi?.find((q) => q.threshold === x); return p ? [["life thrown away", `${p.wasted_life_median_shifts} sh`], ["false / 1000", `${p.false_per_1000}`]] : []; }} />
            <p className="hl-cap">Tuned on the {R.data.labelled} labelled machines: higher = earlier, safer, more life wasted.</p>
          </section>
        )}
        <section className="db-card hl-span2"><h3>Per part: failures warned in time</h3>
          <Dumbbell xTitle="failures warned ≥ 1 shift ahead" a={{ name: "network", color: "#4f8fd6" }} b={{ name: "threshold rules", color: "#e0a02a" }}
            rows={Object.entries(R.per_component).sort((x, y) => x[1].ml_ok / x[1].failures - y[1].ml_ok / y[1].failures)
              .map(([c, v]) => ({ label: NICE[c] ?? c, a: v.ml_ok / v.failures, b: v.rule_ok / v.failures, note: `${v.failures} failures` }))} />
          <p className="hl-cap">The network is weakest on rare failures (cup seal, pusher, RFID: too few examples to learn from).</p>
        </section>
        <section className="db-card"><h3>Training loss</h3>
          <Chart h={170} days={false} xLabel="epoch" yLabel="loss" lines={stages.map((st) => {
            const L = R.log.filter((l) => l.stage === st);
            return { name: st, x: L.map((_, i) => i + 1), y: L.map((l) => l.loss), color: SC[st] ?? "#9fd0ff" };
          })} />
          <details className="ai-how"><summary>Model and data</summary>
            <table className="db-table"><tbody>
              <tr><td>network</td><td>{R.model.type} · {(R.model.params / 1000).toFixed(1)}k parameters</td></tr>
              <tr><td>input</td><td>last {R.model.window_orders} orders of {R.model.inputs.slice(0, 4).join(", ")}</td></tr>
              <tr><td>data</td><td>{R.data.machines} machines, {R.data.labelled} labelled, {R.data.failures} failures</td></tr>
              <tr><td>on the RevPi</td><td>ONNX {(R.model.onnx_bytes / 1024).toFixed(0)} kB, error {R.model.onnx_max_abs_err.toExponential(1)}</td></tr>
            </tbody></table>
            <div className="mo-dl"><a href={`${BASE}ml/stf_pm_tcn.onnx`} download>stf_pm_tcn.onnx</a><a href={`${BASE}ml/weights.json`} download>weights.json</a><a href={`${BASE}ml/results.json`} download>results.json</a></div>
          </details>
        </section>
        <section className="db-card wide"><h3>An unseen machine (#{R.showcase.machine}): predicted vs true remaining life</h3>
          <div className="db-chips">{R.showcase.rows.map((r, i) => <button key={r.comp} className={i === show ? "on" : ""} onClick={() => setShow(i)}>{NICE[r.comp] ?? r.comp}</button>)}</div>
          <Plot h={250} xTitle="orders on this machine" yTitle="remaining life (orders)" yMin={0} yMax={W.rul_cap}
            series={[{ name: "true remaining life", x: sx, y: row.true, color: "var(--text)", dash: true, width: 1.6 },
                     { name: "network's prediction", x: sx, y: row.pred, color: "#4f8fd6", width: 2.2 }]}
            hlines={[{ y: W.alarm_rul, color: "var(--bad)", label: "alarm threshold" }]}
            vmarks={[...row.fails.map((f) => ({ x: f, color: "var(--bad)", label: "failure" })),
                     ...(row.alarms.length ? [{ x: row.alarms[0], color: "#4f8fd6", label: "first network alarm" }] : []),
                     ...row.rules.slice(0, 2).map((r) => ({ x: r, color: "var(--warn)", label: "rule warning" }))]}
            tipExtra={(x) => { const i = Math.round(x / R.showcase.stride); const tr = row.true[i]; return tr === null || tr === undefined ? [] : [["error", `${(row.pred[i] - tr).toFixed(0)} orders`]]; }} />
          <p className="hl-cap">Mean error on this part: {mae.toFixed(0)} orders. The prediction is capped at {W.rul_cap} orders: far from failure it only says "plenty".</p>
        </section>
        <section className="db-card hl-span2"><h3>Running here, on the simulated month</h3>
          <div className="db-chips">{W.components.map((c, i) => <button key={c} className={i === comp ? "on" : ""} onClick={() => setComp(i)}>{NICE[c] ?? c}</button>)}</div>
          {full && full.c === comp ? (
            <Chart yMin={0} yMax={W.rul_cap} yLabel="predicted life (orders)" xMax={M.t[M.t.length - 1]}
              lines={[{ name: "predicted remaining life (this browser)", x: tArr, y: full.rul, color: "#22c55e", width: 1.6 }]}
              hlines={[{ y: W.alarm_rul, color: "#e0503a", label: "alarm threshold" }]} marks={marks} />
          ) : <p className="db-muted">computing in the page…</p>}
          <p className="hl-cap">Parts are renewed at the rule warning, so the prediction dips, then resets.</p>
        </section>
        <section className="db-card"><h3>At order <input type="range" min={0} max={M.x.length - 1} value={t} onChange={(e) => setT(+e.target.value)} className="ai-slider" />
          <span className="mono">day {(M.t[t] / 24 + 1).toFixed(1)}</span></h3>
          <div className="hl-bars">{live && live.map((p, i) => ({ p, i })).sort((x, y) => x.p.rul - y.p.rul).map(({ p, i }) => (
            <div key={i} className="hl-bar" title={`healthy ${Math.round(p.p[0] * 100)} % · degrading ${Math.round(p.p[1] * 100)} % · critical ${Math.round(p.p[2] * 100)} %`}>
              <span className="hl-name">{NICE[W.components[i]] ?? W.components[i]}</span>
              <span className="hl-track"><i style={{ width: `${(p.rul / W.rul_cap) * 100}%`, background: p.rul < W.alarm_rul ? "var(--bad)" : p.p[2] > 0.5 ? "var(--warn)" : "var(--ok)" }} /></span>
              <b>{p.rul.toFixed(0)}</b><em>orders</em>
            </div>))}</div>
          <p className="hl-cap">Predicted remaining life per part, shortest first; red = below the alarm threshold.</p>
        </section>
      </div>
    </>
  );
}
