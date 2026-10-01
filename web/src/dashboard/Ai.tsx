// Upgrade 8: the semi-supervised deep-learning predictor - how it was trained,
// how it scores against the U6 rules on machines it never saw, and the model
// itself running here in the browser on the month's data.
import { useEffect, useMemo, useState } from "react";
import { Chart } from "./Month";
import { type Weights, buildWindow, forward, predictAt } from "./ml";
import { useJson } from "../shared/data";

const BASE = import.meta.env.BASE_URL;

type Result = { name: string; failures: number; warned_1shift: number; warned_1shift_pct: number; missed: number; late: number;
                lead_median_orders: number | null; false: number; false_per_1000: number; rul_mae_orders?: number;
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
            sweep_validation: Record<string, { threshold: number; warned_1shift: number; failures: number; false_per_1000: number }[]> };
};
type MonthIn = { t: number[]; x: number[][]; torch_rul: number[][]; rule_warnings: { t: number; comp: string }[]; maintenance: { t: number; comp: string }[] };

function useAi() {
  const hint = "No model yet. Run: STF_VARIANT=up7 python3 -m ml.train";
  const W = useJson<Weights>("ml/weights.json", hint), R = useJson<Res>("ml/results.json", hint);
  const M = useJson<MonthIn>("ml/month_inputs.json", hint);
  const err = W.error ?? R.error ?? M.error;
  return { d: W.data && R.data && M.data ? { W: W.data, R: R.data, M: M.data } : null, err };
}

const NICE: Record<string, string> = { cup: "VGR cup seal", door: "oven door cyl.", lower: "Sauger cylinder", pusher: "Auswerfer cyl.",
  belt: "HBW belt", rfid: "RFID heads", spindle: "HBW spindle", gearbox: "VGR gearbox", air: "air supply", colour: "colour sensor" };

export function AiPage() {
  const { d, err } = useAi();
  const [comp, setComp] = useState(7);
  const [t, setT] = useState(0);
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
  const marks = [...M.rule_warnings.filter((w) => w.comp === k).map((w) => ({ x: w.t, color: "#e0a02a", label: "U6 warning" })),
                 ...M.maintenance.filter((w) => w.comp === k).map((w) => ({ x: w.t, color: "#22c55e", label: "renewed" }))];
  const stages = Array.from(new Set(R.log.map((l) => l.stage)));
  const SC: Record<string, string> = { pretrain: "#9fd0ff", "fine-tune": "#86efac", "mean teacher": "#22c55e", "supervised-only": "#e0a02a", oracle: "#b07ad6" };
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi"><span>model</span><b>{(R.model.params / 1000).toFixed(1)}k</b><em>parameters · causal TCN</em></div>
        <div className="db-kpi"><span>training data</span><b>{R.data.machines}</b><em>machines · {R.data.labelled} labelled · {R.data.failures} failures</em></div>
        <div className="db-kpi"><span>warned ≥ 1 shift</span><b>{semi.warned_1shift_pct} %</b><em>unseen machines (rules {rule.warned_1shift_pct} %)</em></div>
        <div className="db-kpi"><span>false alarms</span><b>{semi.false_per_1000}</b><em>per 1000 orders (rules {rule.false_per_1000})</em></div>
        <div className="db-kpi"><span>ONNX (RevPi)</span><b>{(R.model.onnx_bytes / 1024).toFixed(0)} kB</b><em>max error vs PyTorch {R.model.onnx_max_abs_err.toExponential(1)}</em></div>
        <div className={`db-kpi ${full && full.err < 0.05 ? "ok" : ""}`}><span>browser vs PyTorch</span>
          <b>{full ? full.err.toFixed(4) : "…"}</b><em>max |Δ| remaining life, orders ({full ? Math.round(full.done * 100) : 0} % checked)</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>Scored on {R.data.test} machines the model never saw ({semi.failures} failures)</h3>
          <table className="db-table">
            <thead><tr><td>method</td><td className="num">warned ≥ 1 shift</td><td className="num">missed</td><td className="num">late</td>
              <td className="num">median lead</td><td className="num">false / 1000</td><td className="num">life MAE</td><td className="num">class F1</td></tr></thead>
            <tbody>{R.results.map((r) => (
              <tr key={r.name} className={r.name.startsWith("semi") ? "on" : ""}><td>{r.name}</td>
                <td className="num">{r.warned_1shift}/{r.failures} ({r.warned_1shift_pct} %)</td><td className="num">{r.missed}</td><td className="num">{r.late}</td>
                <td className="num">{r.lead_median_orders ?? "–"} orders</td><td className="num">{r.false_per_1000}</td>
                <td className="num">{r.rul_mae_orders ?? "–"}</td><td className="num">{r.macro_f1 ?? "–"}</td></tr>
            ))}</tbody>
          </table>
          <p className="db-note">Alarm: predicted life under {R.alarm.rul_below_orders} orders for {R.alarm.for_orders} orders in a row; a warning
            counts if it comes ≥ {R.alarm.lead_needed_orders} orders (one shift) before the failure. {R.limits}.</p>
        </section>
        {R.tuned && (
          <section className="db-card wide"><h3>The decision, tuned properly: warned in time vs part life thrown away</h3>
            <table className="db-table">
              <thead><tr><td>policy</td><td className="num">warned ≥ 1 shift</td><td className="num">missed</td><td className="num">late</td>
                <td className="num">median lead</td><td className="num">life thrown away</td><td className="num">false / 1000</td></tr></thead>
              <tbody>{R.tuned.table.map((r) => (
                <tr key={r.name} className={r.name.startsWith("hybrid") ? "on" : ""}><td>{r.name}</td>
                  <td className="num">{r.warned_1shift}/{r.failures}</td><td className={`num ${r.missed ? "fail" : ""}`}>{r.missed}</td>
                  <td className={`num ${r.late ? "warn" : ""}`}>{r.late}</td><td className="num">{r.lead_median_orders} orders</td>
                  <td className="num">{r.wasted_life_median_shifts ?? "–"} shifts</td><td className="num">{r.false_per_1000}</td></tr>
              ))}</tbody>
            </table>
            <p className="db-note">{R.tuned.method}. Chosen: {Object.entries(R.tuned.chosen).map(([k, v]) => `${k} ${v} orders`).join(", ")}.
              The hybrid is {R.tuned.hybrid_note}.</p>
            <p className="db-note"><b>Verdict on this data:</b> the U6 rules know each part's true limit and warn every failure, but
              about 15 shifts early, so they renew parts with plenty of life left. The network alone times the work far better
              (about 3 shifts early) but misses a quarter of the failures on unseen machines: its threshold, tuned on 8 labelled
              machines, did not carry over. The hybrid misses none and saves about 3 shifts of life per renewal, but warns 5 failures
              late, which the rules never did. So the network goes in as an <b>advisory</b> remaining-life estimate beside the rules
              (shadow mode), until it has been trained on real run-to-failure data. Semi-supervised training still earns its place:
              the same 8 labelled machines give a better remaining-life estimate with the unlabelled ones than without.</p>
          </section>
        )}
        <section className="db-card"><h3>Per component (semi-supervised vs rules)</h3>
          <table className="db-table"><thead><tr><td>component</td><td className="num">failures</td><td className="num">ML ok</td><td className="num">rules ok</td></tr></thead>
            <tbody>{Object.entries(R.per_component).map(([c, v]) => (
              <tr key={c}><td>{NICE[c] ?? c}</td><td className="num">{v.failures}</td><td className="num">{v.ml_ok}</td><td className="num">{v.rule_ok}</td></tr>
            ))}</tbody></table>
        </section>
        <section className="db-card"><h3>How it was trained</h3>
          <p className="db-note" style={{ marginTop: 0 }}>{R.method}.</p>
          <table className="db-table"><tbody>
            <tr><td>network</td><td>{R.model.type}</td></tr>
            <tr><td>looks at</td><td>{R.model.window_orders} orders of {R.model.inputs.slice(0, 4).join(", ")} + which component</td></tr>
            <tr><td>predicts</td><td>{R.model.heads}</td></tr>
            <tr><td>unlabelled windows</td><td className="num">{R.data.unlabelled_windows.toLocaleString()}</td></tr>
            <tr><td>labelled windows</td><td className="num">{R.data.labelled_windows.toLocaleString()} ({R.data.failures_labelled} failures)</td></tr>
            <tr><td>trained in</td><td className="num">{R.train_s} s on {R.model.device}</td></tr>
          </tbody></table>
          <div className="mo-dl" style={{ marginTop: 8 }}><a href={`${BASE}ml/stf_pm_tcn.onnx`} download>stf_pm_tcn.onnx</a><a href={`${BASE}ml/weights.json`} download>weights.json</a><a href={`${BASE}ml/results.json`} download>results.json</a></div>
        </section>
        <section className="db-card"><h3>Training loss</h3>
          <Chart h={150} days={false} lines={stages.map((s) => {
            const L = R.log.filter((l) => l.stage === s);
            return { name: s, x: L.map((_, i) => i + 1), y: L.map((l) => l.loss), color: SC[s] ?? "#9fd0ff" };
          })} />
        </section>
        <section className="db-card wide"><h3>Running here, in the browser, on the month (Upgrade 7 with maintenance)</h3>
          <div className="db-chips">{W.components.map((c, i) => <button key={c} className={i === comp ? "on" : ""} onClick={() => setComp(i)}>{NICE[c] ?? c}</button>)}</div>
          {full && full.c === comp && (
            <Chart yMin={0} yMax={W.rul_cap} yLabel="predicted life (orders)" xMax={M.t[M.t.length - 1]}
              lines={[{ name: `${NICE[k] ?? k}: predicted remaining life (this browser)`, x: tArr, y: full.rul, color: "#22c55e", width: 1.6 }]}
              hlines={[{ y: W.alarm_rul, color: "#e0503a", label: "alarm threshold" }]} marks={marks} />
          )}
          <p className="db-note">The month's own work orders renew parts at the U6 warning, so no part reaches its failure here: the
            prediction dips, then resets at each renewal. Computed every 4th order in the page; every value is compared with
            PyTorch's (top right).</p>
        </section>
        <section className="db-card wide"><h3>At order
          <input type="range" min={0} max={M.x.length - 1} value={t} onChange={(e) => setT(+e.target.value)} style={{ width: 300 }} />
          {t} · day {(M.t[t] / 24 + 1).toFixed(1)}</h3>
          <div className="ai-live">{live && live.map((p, i) => (
            <div key={i} className={p.rul < W.alarm_rul ? "alarm" : p.p[2] > 0.5 ? "warn" : ""}>
              <b>{NICE[W.components[i]] ?? W.components[i]}</b>
              <span>{p.rul.toFixed(0)} orders</span>
              <div className="ai-prob">{p.p.map((v, j) => <i key={j} style={{ width: `${v * 100}%` }} className={["h", "d", "c"][j]} />)}</div>
            </div>
          ))}</div>
          <p className="db-note">Each tile: predicted remaining life and the class probabilities (green healthy, amber degrading, red critical)
            for the window ending at this order.</p>
        </section>
        <section className="db-card wide"><h3>An unseen test machine (#{R.showcase.machine}): truth vs prediction</h3>
          {R.showcase.rows.slice(0, 4).map((row) => {
            const xs = row.pred.map((_, i) => i * R.showcase.stride);
            return (
              <div key={row.comp}>
                <Chart h={120} days={false} yMin={0} yMax={W.rul_cap} xMax={xs[xs.length - 1]}
                  lines={[{ name: `${NICE[row.comp]}: true remaining life`, x: xs, y: row.true, color: "#9fd0ff", width: 1.2 },
                          { name: "predicted", x: xs, y: row.pred, color: "#22c55e", width: 1.4 }]}
                  marks={[...row.fails.map((f) => ({ x: f, color: "#e0503a", label: "failure" })),
                          ...(row.alarms.length ? [{ x: row.alarms[0], color: "#22c55e", label: "first ML alarm" }] : []),
                          ...row.rules.slice(0, 3).map((r) => ({ x: r, color: "#e0a02a", label: "U6 rule" }))]} />
              </div>
            );
          })}
        </section>
      </div>
    </>
  );
}
