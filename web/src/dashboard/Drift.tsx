// Maintenance · Pre-failure window · When the plant drifts (stf-cad/hbw/pdm/drift.py, `make drift`).
// The test machines run again with one thing changed - a hotter hall, noisier sensors, faster wear,
// another wear law - and the calibrated pipeline is graded on them: which detector sees the shift,
// how far the guarantees fall, what online recalibration wins back, and the one shift no threshold
// can fix, fixed at its source in the model.
import { Plot } from "./Plot";
import { useJson } from "../shared/data";

type Cov = { all: number; last_shift: number; worst_part: number };
type Dec = { late: number; failures: number; late_share: number | null; false_per_1000: number };
type Shift = {
  failures: number; adapted_share: number;
  interval: Record<string, Cov>; lower_bound: Record<string, Cov>;
  decision: { static: Dec; online: Dec; hindsight: { best: { p_star: number } | null; lowest_late: { p_star: number; late_share: number } } };
  detect_inputs: { machines_alarmed: number; machines: number; median_delay_orders: number | null };
  detect_outcomes: { failures_to_alarm: number | null; failures: number; alarm_order: number | null; log_m: number[] };
};
type Model = { p_star_static: number; shifts: Record<string, Shift> };
type Drift = { say: Record<string, string>; alpha: number; alpha_late: number; delta: number; models: Record<string, Model> };

const SHORT: Record<string, string> = { nominal: "nominal", hot: "hall +6 °C", noisy: "sensor noise ×2", fast: "wear ×1.6", law: "wear law p ×0.7" };
const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 1000) / 10} %`);
const COLORS: Record<string, string> = { nominal: "#9aa4b2", hot: "#e0503a", noisy: "#e0a02a", fast: "#22c55e", law: "#8b74e6" };

export function DriftCards() {
  const { data: d, error } = useJson<Drift>("pdm/drift.json", "run `make drift`");
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return null;
  const std = d.models.standard, fix = d.models.temp_failure;
  const want = 1 - d.alpha;
  const cls = (v: number) => (v >= want - 0.005 ? "ok" : v >= want - 0.1 ? "warn" : "fail");
  const lateCls = (v: number | null) => (v == null ? "" : v <= d.alpha_late + 0.005 ? "ok" : v <= 2 * d.alpha_late ? "warn" : "fail");
  const names = Object.keys(std.shifts);
  const thr = Math.log(1 / d.delta);
  return (
    <>
      <section className="db-card wide">
        <h3>When the plant drifts · the same 16 machines, one thing changed</h3>
        <table className="db-table">
          <thead><tr><td>shift</td><td className="num">seen in the signals</td><td className="num">seen in the failures</td>
            <td className="num">holds, static</td><td className="num">holds, detect → adapt</td><td className="num">worst part, static → adapt</td>
            <td className="num">late, static p*</td><td className="num">late, best any p*</td></tr></thead>
          <tbody>{names.map((n) => {
            const s = std.shifts[n], di = s.detect_inputs, dout = s.detect_outcomes;
            const st = s.interval.static, ad = s.interval.detect_then_adapt;
            return (
              <tr key={n}>
                <td title={d.say[n]}>{SHORT[n] ?? n}</td>
                <td className="num">{di.machines_alarmed}/{di.machines}{di.median_delay_orders != null ? ` · ${di.median_delay_orders} orders` : ""}</td>
                <td className="num">{dout.failures_to_alarm != null ? `after ${dout.failures_to_alarm} failures` : "–"}</td>
                <td className={`num ${cls(st.all)}`}>{pct(st.all)}</td>
                <td className={`num ${cls(ad.all)}`}>{pct(ad.all)}</td>
                <td className="num">{pct(st.worst_part)} → {pct(ad.worst_part)}</td>
                <td className={`num ${lateCls(s.decision.static.late_share)}`}>{s.decision.static.late}/{s.decision.static.failures}</td>
                <td className={`num ${lateCls(s.decision.hindsight.lowest_late.late_share)}`}>{pct(s.decision.hindsight.lowest_late.late_share)}</td>
              </tr>);
          })}</tbody>
        </table>
        <p className="hl-cap">Signals: a conformal test martingale on the filter's innovations, no labels needed; it alarms at most {Math.round(d.delta * 100)} % of the time on an unchanged machine.</p>
        <p className="hl-cap">Failures: the same test on how optimistic each failure's lower bound was. Only failures show a shift the filter absorbs into its wear estimate.</p>
        <p className="hl-cap">Detect → adapt: the static calibration until a detector fires, then weighted conformal with adaptive conformal inference, per part.</p>
      </section>
      <section className="db-card">
        <h3>Seen in the failures · log of the test martingale</h3>
        <Plot h={220} xTitle="failures seen (fleet, in time order)" yTitle="log M" yMin={-4}
          hlines={[{ y: thr, color: "#e0a02a", label: `alarm (1/δ = ${Math.round(1 / d.delta)})` }]}
          series={names.map((n) => ({ name: SHORT[n] ?? n, x: std.shifts[n].detect_outcomes.log_m.map((_, i) => i + 1),
            y: std.shifts[n].detect_outcomes.log_m, color: COLORS[n] ?? "#5b8cff", width: n === "hot" ? 2.4 : 1.4, fmt: (v: number) => v.toFixed(1) }))} />
      </section>
      {fix && (
        <section className="db-card wide">
          <h3>Fixed at the source · failure on the raw signal</h3>
          <table className="db-table">
            <thead><tr><td>shift</td><td>model</td><td className="num">late, static p*</td><td className="num">best any p*</td><td className="num">holds</td><td className="num">last shift</td></tr></thead>
            <tbody>{names.flatMap((n) => [std, fix].map((m, j) => {
              const s = m.shifts[n];
              return (
                <tr key={`${n}${j}`} className={j ? "hl" : ""}>
                  <td>{j ? "" : SHORT[n] ?? n}</td><td>{j ? "raw-signal failure (default)" : "failure at w = 1 (first)"}</td>
                  <td className={`num ${lateCls(s.decision.static.late_share)}`}>{s.decision.static.late}/{s.decision.static.failures}</td>
                  <td className={`num ${lateCls(s.decision.hindsight.lowest_late.late_share)}`}>{pct(s.decision.hindsight.lowest_late.late_share)}</td>
                  <td className={`num ${cls(s.interval.static.all)}`}>{pct(s.interval.static.all)}</td>
                  <td className="num">{pct(s.interval.static.last_shift)}</td>
                </tr>);
            }))}</tbody>
          </table>
          <p className="hl-cap">The normal-behaviour model divides the hall temperature out of the signal; the part fails on the raw signal.</p>
          <p className="hl-cap">So in a warm hall it fails at less wear than the model's w = 1: the fix moves the failure point, not the threshold.</p>
        </section>
      )}
    </>
  );
}
