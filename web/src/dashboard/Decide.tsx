// Maintenance · Pre-failure window · The decision with a shield (stf-cad/hbw/pdm/decide.py,
// `make decide`): renew tonight in the free night gap, or stop the cell now - with the calibrated
// lower bound on remaining life deciding whether waiting is safe. Graded by renewal-reward on every
// failure stretch of the test machines, nominal and drifted.
import { Plot } from "./Plot";
import { useJson } from "../shared/data";

type Pol = {
  failures_per_1000: number; down_h_per_1000: number; renewals_per_1000: number; life_used_median: number | null;
  stops_now: number; renewed_tonight: number; failed_in_service: number; waits: number; waits_failed: number;
};
type Decide = { alpha: number; p_star: number; say: Record<string, string>; shifts: Record<string, Record<string, Pol>>; sweep: Record<string, Record<string, Pol>> };

const SAY: Record<string, string> = {
  "run to failure": "Run to failure", "U6 rules": "U6 rules → tonight", "window -> tonight": "Window → tonight",
  "window + shield": "Window + shield, 90 %", "window + cost-aware shield": "Window + cost-aware shield", "shield alone": "Shield alone",
};

export function DecideCards() {
  const { data: d, error } = useJson<Decide>("pdm/decide.json", "run `make decide`");
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return null;
  const nom = d.shifts.nominal;
  const sweep = Object.entries(d.sweep.nominal).map(([a, r]) => ({ a: +a, r }));
  const base = nom["window -> tonight"];
  return (
    <>
      <section className="db-card wide">
        <h3>The decision · renew tonight or stop now</h3>
        <table className="db-table">
          <thead><tr><td>policy</td><td className="num">failures</td><td className="num">hours lost</td>
            <td className="num">renewals</td><td className="num">life used</td><td className="num">stop·tonight·fail</td><td className="num">waits failed</td></tr></thead>
          <tbody>{Object.entries(nom).map(([k, r]) => (
            <tr key={k} className={k === "window + cost-aware shield" ? "hl" : ""}>
              <td>{SAY[k] ?? k}</td>
              <td className={`num ${r.failures_per_1000 === 0 ? "ok" : r.failures_per_1000 < 0.1 ? "warn" : "fail"}`}>{r.failures_per_1000.toFixed(3)}</td>
              <td className="num">{r.down_h_per_1000.toFixed(3)}</td>
              <td className="num">{r.renewals_per_1000.toFixed(2)}</td>
              <td className="num">{r.life_used_median != null ? `${Math.round(r.life_used_median * 100)} %` : "–"}</td>
              <td className="num">{r.stops_now} · {r.renewed_tonight} · {r.failed_in_service}</td>
              <td className="num">{r.waits ? `${r.waits_failed}/${r.waits}` : "–"}</td>
            </tr>))}</tbody>
        </table>
        <p className="hl-cap">Failures, hours lost and renewals per 1000 orders.</p>
        <p className="hl-cap">The shield lets the part wait for the free night gap only while its calibrated lower bound outlasts the gap; otherwise the cell stops now.</p>
        <p className="hl-cap">Renewal-reward over every failure stretch of the 16 test machines; service minutes and failure downtime are the plant model's assumptions.</p>
      </section>
      <section className="db-card">
        <h3>What zero in-service failures costs</h3>
        <Plot h={220} xTitle="shield level α (waits allowed to fail)" yTitle="hours lost per 1000 orders" xMin={0} xMax={0.5} yMin={0}
          xFmt={(v) => v.toFixed(2)} yFmt={(v) => v.toFixed(2)}
          hlines={[{ y: base.down_h_per_1000, color: "#e0a02a", label: `window → tonight (${base.failed_in_service} failures)` }]}
          series={[{ name: "window + shield", x: sweep.map((s) => s.a), y: sweep.map((s) => s.r.down_h_per_1000), color: "#5b8cff", width: 2, kind: "line",
            fmt: (v) => `${v.toFixed(3)} h` }]} />
        <p className="hl-cap">Every shield level kept in-service failures at zero on these machines; a looser α stops the cell less often.</p>
      </section>
      <section className="db-card wide">
        <h3>Under drift · window + cost-aware shield</h3>
        <table className="db-table">
          <thead><tr><td>shift</td><td className="num">failures /1000</td><td className="num">hours lost /1000</td><td className="num">waits that failed</td></tr></thead>
          <tbody>{Object.entries(d.shifts).map(([n, s]) => {
            const r = s["window + cost-aware shield"];
            return (
              <tr key={n}><td>{n === "nominal" ? "nominal" : d.say[n] ?? n}</td><td className={`num ${r.failures_per_1000 === 0 ? "ok" : "warn"}`}>{r.failures_per_1000.toFixed(3)}</td>
                <td className="num">{r.down_h_per_1000.toFixed(3)}</td><td className="num">{r.waits_failed}/{r.waits}</td></tr>);
          })}</tbody>
        </table>
      </section>
    </>
  );
}
