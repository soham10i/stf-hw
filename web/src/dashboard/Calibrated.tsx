// Maintenance · Pre-failure window · Calibrated remaining life: conformal prediction on top of the
// filter (stf-cad/hbw/pdm/conformal.py, `make conformal`). How often the remaining-life intervals
// and lower bounds actually hold on machines nothing was fitted or calibrated on - overall, in the
// last shift before a failure and for the worst part - and the alarm threshold chosen by
// conformal risk control, with its trade-off between late warnings and false alarms.
import { Plot } from "./Plot";
import { useJson } from "../shared/data";

type Cover = { n: number; coverage: number; lower_coverage: number; width_median: number; lower_median: number } | null;
type Method = {
  all: Cover; coverage_90ci: [number, number]; lower_coverage_90ci: [number, number];
  by_life: Record<string, Cover>; by_comp: Record<string, Cover>; worst_comp_coverage: number | null;
};
type Grid = { p_star: number; late_share: number; bound: number; false_per_1000: number; failures: number };
type Decision = { name: string; p_star: number; failures: number; late: number; late_share: number | null; false_per_1000: number };
type Conformal = {
  alpha: number; alpha_late: number; cal_machines: number[]; test_machines: number[]; cal_segments: number;
  intervals: Record<string, Method>; risk_control: { grid: Grid[]; feasible: boolean; p_star: number }; decisions: Decision[];
};

const LABEL: Record<string, string> = {
  filter: "Filter alone (P10–P90)", pooled: "Conformal, pooled", component: "Conformal, per part",
  component_life: "Conformal, per part × predicted life",
};
const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 1000) / 10} %`);

export function Calibrated() {
  const { data: d, error } = useJson<Conformal>("pdm/conformal.json", "run `make conformal`");
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return null;
  const want = 1 - d.alpha;
  const cls = (v: number | null | undefined) => (v == null ? "" : v >= want - 0.005 ? "ok" : v >= want - 0.1 ? "warn" : "fail");
  const g = d.risk_control.grid;
  const [pop, crc] = d.decisions;
  return (
    <>
      <section className="db-card wide">
        <h3>Calibrated remaining life · does the {Math.round(want * 100)} % interval hold?</h3>
        <table className="db-table">
          <thead><tr><td>method</td><td className="num">holds</td><td className="num">machine spread</td>
            <td className="num">last shift</td><td className="num">worst part</td><td className="num">lower bound, last shift</td>
            <td className="num">width, last shift</td></tr></thead>
          <tbody>{Object.entries(d.intervals).map(([k, m]) => {
            const last = m.by_life["0-45"];
            return (
              <tr key={k} className={k === "component_life" ? "hl" : ""}>
                <td>{LABEL[k] ?? k}</td>
                <td className={`num ${cls(m.all?.coverage)}`}>{pct(m.all?.coverage)}</td>
                <td className="num">{Math.round(m.coverage_90ci[0] * 100)}–{pct(m.coverage_90ci[1])}</td>
                <td className={`num ${cls(last?.coverage)}`}>{pct(last?.coverage)}</td>
                <td className={`num ${cls(m.worst_comp_coverage)}`}>{pct(m.worst_comp_coverage)}</td>
                <td className={`num ${cls(last?.lower_coverage)}`}>{pct(last?.lower_coverage)}</td>
                <td className="num">{last ? `${Math.round(last.width_median)} orders` : "–"}</td>
              </tr>);
          })}</tbody>
        </table>
        <p className="hl-cap">Calibrated on machines {d.cal_machines[0]}–{d.cal_machines[d.cal_machines.length - 1]} ({d.cal_segments} failures), graded on {d.test_machines[0]}–{d.test_machines[d.test_machines.length - 1]}; neither fitted the filter.</p>
        <p className="hl-cap">The promise is on average over machines, and per part where a part has enough failures to calibrate on.</p>
        <p className="hl-cap">"The last shift" is only known after a failure, so no interval can promise it: the decision below is guaranteed per failure.</p>
      </section>
      <section className="db-card wide">
        <h3>The alarm threshold by conformal risk control</h3>
        <Plot h={220} xTitle="threshold p* (window opens when P(failure ≤ 2 shifts) ≥ p*)" yTitle="share / rate"
          xMin={0} xMax={0.8} yMin={0} yMax={0.35} xFmt={(v) => v.toFixed(2)} yFmt={(v) => `${Math.round(v * 100)} %`}
          hlines={[{ y: d.alpha_late, color: "#e0a02a", label: "allowed late share" }]}
          vmarks={[{ x: pop.p_star, color: "#8fb8ff", label: "p* from the population" }, { x: crc.p_star, color: "#22c55e", label: "risk-controlled p*" }]}
          series={[
            { name: "late share (calibration)", x: g.map((r) => r.p_star), y: g.map((r) => r.late_share), color: "#e0503a", width: 2, fmt: pct },
            { name: "guarantee bound (n·R + 1)/(n + 1)", x: g.map((r) => r.p_star), y: g.map((r) => r.bound), color: "#e0503a", dash: true, width: 1.2, fmt: pct },
            { name: "false alarms per 1000 orders ÷ 10", x: g.map((r) => r.p_star), y: g.map((r) => r.false_per_1000 / 10), color: "#5b8cff", width: 2,
              fmt: (v) => `${(v * 10).toFixed(2)} /1000` },
          ]} />
        <table className="db-table">
          <thead><tr><td>threshold</td><td className="num">p*</td><td className="num">late (test)</td><td className="num">false /1000</td></tr></thead>
          <tbody>{d.decisions.map((r, i) => (
            <tr key={r.name} className={i === 1 ? "hl" : ""}><td>{i === 0 ? "From the population (best on the fit machines)" : `Risk-controlled (late ≤ ${Math.round(d.alpha_late * 100)} % in expectation)`}</td>
              <td className="num">{r.p_star}</td><td className="num">{r.late}/{r.failures} · {pct(r.late_share)}</td><td className="num">{r.false_per_1000}</td></tr>))}</tbody>
        </table>
        <p className="hl-cap">A failure is late when its window opened less than a shift ahead; the late share only grows with p*.</p>
        <p className="hl-cap">The largest p* whose bound stays under the allowed share keeps the guarantee on new machines, with the fewest false alarms.{d.risk_control.feasible ? "" : " No threshold met the bound here; the smallest was used."}</p>
      </section>
    </>
  );
}
