// Maintenance · Pre-failure window: the statistical predictive-maintenance pipeline
// (stf-cad/hbw/pdm, `make pdm`): normal-behaviour model, physics-informed Kalman filter,
// remaining life as a first-passage distribution, change detection - graded against the U6
// rules and the neural networks on the same unseen machines, and shown on the two failures of
// the production months.
import { Plot } from "./Plot";
import { useJson } from "../shared/data";

type Result = {
  name: string; failures: number; warned_1shift_pct: number; missed: number; late: number;
  lead_median_orders: number | null; false_per_1000: number; rul_mae_orders?: number; p10_p90_coverage?: number;
};
type Trace = { h: number[]; w: number[]; p_fail: number[]; p10: number[]; p50: number[]; p90: number[]; change_p: number[] };
type Show = {
  name: string; fail_h: number | null; window_h: number | null; rule_h: number | null; cusum_onset_h: number | null;
  p10_at_window: number | null; p50_at_window: number | null; p90_at_window: number | null; trace: Trace;
};
type Pdm = {
  results: Result[]; p_star: number; horizon_orders: number; lead_needed_orders: number;
  beta_per_degC: Record<string, number>; showcase: Record<string, Show>;
  detectors: { cusum_false_rate: number; t2_exceed_rate: number };
};

// (the loader drops design-step tags such as "U6" from strings: match on what stays)
const isOurs = (n: string) => n.startsWith("Statistical");
const isRule = (n: string) => /rules/i.test(n) && /EWMA/.test(n);
const short = (n: string) => isOurs(n) ? "Statistical pipeline" : isRule(n) ? "Rules (EWMA, limit, trend)" : `TCN · ${n.split(" (")[0]}`;
const day = (h: number) => `${Math.floor(h / 24) + 1}`;

export function PdmPage() {
  const { data: d, error } = useJson<Pdm>("pdm/pdm.json", "run `make pdm`");
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return <div className="db-err">loading the pipeline's results…</div>;
  const ours = d.results.find((r) => isOurs(r.name)), rule = d.results.find((r) => isRule(r.name));
  if (!ours || !rule) return <div className="db-err">The pipeline's results are incomplete: run `make pdm`.</div>;
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>warned a shift ahead</span><b>{ours.warned_1shift_pct} %</b><em>rules {rule.warned_1shift_pct} %</em></div>
        <div className="db-kpi"><span>median lead</span><b>{ours.lead_median_orders} orders</b><em>rules {rule.lead_median_orders}: life thrown away</em></div>
        <div className="db-kpi ok"><span>false alarms</span><b>{ours.false_per_1000}</b><em>per 1000 orders · rules {rule.false_per_1000}</em></div>
        <div className="db-kpi"><span>remaining-life error</span><b>{ours.rul_mae_orders} orders</b><em>median vs truth · P10–P90 holds {Math.round((ours.p10_p90_coverage ?? 0) * 100)} %</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide">
          <h3>Methods compared</h3>
          <table className="db-table">
            <thead><tr><td>method</td><td className="num">in time</td><td className="num">missed</td><td className="num">late</td>
              <td className="num">median lead</td><td className="num">false /1000</td><td className="num">RUL error</td></tr></thead>
            <tbody>{d.results.map((r) => (
              <tr key={r.name} className={r === ours ? "hl" : ""} title={r.name}>
                <td>{short(r.name)}</td><td className="num">{r.warned_1shift_pct} %</td><td className="num">{r.missed}</td><td className="num">{r.late}</td>
                <td className="num">{r.lead_median_orders ?? "–"}</td><td className="num">{r.false_per_1000}</td><td className="num">{r.rul_mae_orders ?? "–"}</td>
              </tr>))}</tbody>
          </table>
          <p className="hl-cap">16 machines no method saw, {ours.failures} failures. In time = the window opened at least {d.lead_needed_orders} orders (a shift) ahead. The window opens when P(failure within {d.horizon_orders} orders) ≥ {d.p_star}.</p>
        </section>
        <div className="vq-life-pair">{Object.entries(d.showcase).map(([k, s]) => <Failure key={k} s={s} />)}</div>
      </div>
    </>
  );
}

function Failure({ s }: { s: Show }) {
  const T = s.trace;
  const marks = [
    ...(s.cusum_onset_h != null ? [{ x: s.cusum_onset_h, color: "#b07ad6", label: "CUSUM alarm" }] : []),
    ...(s.rule_h != null ? [{ x: s.rule_h, color: "#e0a02a", label: "U6 rule" }] : []),
    ...(s.window_h != null ? [{ x: s.window_h, color: "#22c55e", label: "window opens" }] : []),
    ...(s.fail_h != null ? [{ x: s.fail_h, color: "#e0503a", label: "failure" }] : []),
  ];
  const x0 = Math.max(0, (s.fail_h ?? T.h[T.h.length - 1]) - 24 * 12), x1 = (s.fail_h ?? T.h[T.h.length - 1]) + 12;
  const i0 = T.h.findIndex((h) => h >= x0), cut = (a: number[]) => a.slice(Math.max(0, i0));
  const h = cut(T.h);
  return (
    <section className="db-card">
      <h3>{s.name.replace(/ \(.*\)$/, "")}</h3>
      <Plot h={190} xTitle="day" yTitle="P(failure ≤ 2 shifts)" xMin={x0} xMax={x1} yMin={0} yMax={1}
        xFmt={day} yFmt={(v) => `${Math.round(v * 100)} %`} tipTitle={(x) => `day ${day(x)}, ${String(Math.floor(x % 24)).padStart(2, "0")}:00`}
        series={[{ name: "P(failure within 2 shifts)", x: h, y: cut(T.p_fail), color: "#e0503a", kind: "area", width: 2, fmt: (v) => `${Math.round(v * 100)} %` }]}
        vmarks={marks} />
      <Plot h={170} xTitle="day" yTitle="remaining life (orders)" xMin={x0} xMax={x1} yMin={0} yMax={600}
        xFmt={day} yFmt={(v) => `${Math.round(v)}`}
        series={[{ name: "P90", x: h, y: cut(T.p90), color: "#8fb8ff", dash: true, width: 1.2, fmt: (v) => `${Math.round(v)}` },
                 { name: "median", x: h, y: cut(T.p50), color: "#5b8cff", width: 2.2, fmt: (v) => `${Math.round(v)}` },
                 { name: "P10", x: h, y: cut(T.p10), color: "#8fb8ff", dash: true, width: 1.2, fmt: (v) => `${Math.round(v)}` }]}
        vmarks={marks.filter((m) => m.label !== "CUSUM alarm")} />
      {s.window_h != null && s.fail_h != null && (
        <p className="hl-cap">Window opened {((s.fail_h - s.window_h)).toFixed(0)} h before the failure with {s.p50_at_window} orders left (80 %: {s.p10_at_window}–{s.p90_at_window}); the rule warned {s.rule_h != null ? `${(s.fail_h - s.rule_h).toFixed(0)} h` : "–"} before.</p>
      )}
    </section>
  );
}
