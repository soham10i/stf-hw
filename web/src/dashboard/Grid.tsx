// Upgrade 9: the cell as a microgrid (stf-cad/hbw/grid.py) - energy management,
// demand response, power quality and the health of the power assets.
import { useState } from "react";
import { Chart } from "./Month";
import { HBar, Plot } from "./Plot";
import { useJson } from "../shared/data";

const BASE = import.meta.env.BASE_URL;

type Kpi = { load_kwh: number; pv_kwh: number; import_kwh: number; export_kwh: number; energy_cost_eur: number; peak_w: number;
             demand_charge_eur: number; total_eur: number; co2_kg: number; self_sufficiency: number; self_consumption: number | null;
             dr_met: boolean; dr_import_wh: number };
type Outcome = { survives: boolean; why: string; lost_s?: number; need_wh?: number; have_wh?: number; producing?: boolean; oven?: string | null };
type SupplyOption = { name: string; inverter_w: number; battery_wh: number; pv_wp: number; carries_oven: boolean; inverter_ok: boolean; kpi: Kpi;
                      capex_total: number | null; payback_years?: number; ride_through: number; oven_kept_hot: number };
type GridDoc = {
  meta: { days: number; step_h: number; machine: string; assets: Record<string, number>; tariff: string; standards: string[];
          assumed: string; load_model: { standby_w: number; production_w: number; compressor_w: number; oven_shift_w?: number; oven_rated_w?: number } };
  scenarios: Record<string, Kpi>;
  series: { t_h: number[]; load: number[]; cell?: number[]; oven?: number[]; pv: number[]; grid: number[]; batt: number[]; soc: number[]; price: number[];
            co2: number[]; dr: number[]; irr: number[]; pv_expected: number[]; grid_only: number[] };
  weather: { day: number; kind: string }[];
  power_quality: { kind: string; day: number; h: number; depth?: number; dur_s: number; with_ups: Outcome; grid_only: Outcome }[];
  health: { cabinet: { t_cab: number[]; t_cab_cf: number[]; life_used_month: number; life_used_month_cf: number; life_years: number;
                       life_years_cf: number; events: { h: number; what: string }[] };
            pv: { performance_ratio: (number | null)[]; soiling: number[] };
            battery: { equivalent_full_cycles: number; soh_start: number; soh_end: number; years_to_80pct: number };
            contactors: { operations_month: number; electrical_life_ops: number; years_to_life: number } };
  pv_cleaning: { day: number; what: string }[];
  oven_supply?: { oven: { rated_w: number; shift_w: number; preheat_kwh: number; month_kwh: number; share_of_load: number; useful_share: number };
                  options: SupplyOption[]; cell_only: Kpi; outages: number };
  findings: { title: string; text: string }[];
  economics: { capex_eur: Record<string, number>; capex_total: number; saving_eur_month: number; payback_years: number;
               outage_cost_avoided_s: number; note: string };
};

type Sc = GridDoc["scenarios"][string];
const NAME: Record<string, string> = { grid: "grid only", pv: "PV only", "pv+battery": "PV + battery + EMS" };

export function GridPage() {
  const { data: g, error: err } = useJson<GridDoc>("grid/grid.json", "No grid data. Run: STF_VARIANT=up7 python3 grid.py");
  const [day, setDay] = useState(8);
  if (err) return <div className="db-err">{err}</div>;
  if (!g) return <div className="db-err">loading the microgrid…</div>;
  const S = g.series, per = 24 / g.meta.step_h;
  const sl = (a: number[]) => a.slice((day - 1) * per, day * per);
  const hx = sl(S.t_h).map((t) => t - (day - 1) * 24);
  const sc = g.scenarios, best = sc["pv+battery"], base = sc.grid;
  const pq = g.power_quality;
  const ups = pq.filter((p) => p.with_ups.survives).length, raw = pq.filter((p) => p.grid_only.survives).length;
  const dailyE = Array.from({ length: g.meta.days }, (_, d) => {
    const a = (arr: number[]) => arr.slice(d * per, (d + 1) * per).reduce((s, v) => s + Math.max(0, v), 0) * g.meta.step_h / 1000;
    return { load: a(S.load), pv: a(S.pv), imp: a(S.grid) };
  });
  const cab = g.health.cabinet;
  const ov = g.oven_supply;
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi"><span>energy this month</span><b>{best.load_kwh} kWh</b><em>{ov ? `oven ${ov.oven.month_kwh} kWh · cell ${ov.cell_only.load_kwh} kWh` : `${g.meta.load_model.standby_w} W standing + production`}</em></div>
        <div className="db-kpi ok"><span>self-sufficiency</span><b>{Math.round(best.self_sufficiency * 100)} %</b><em>PV {best.pv_kwh} kWh</em></div>
        <div className="db-kpi"><span>cost</span><b>€{best.total_eur}</b><em>grid only €{base.total_eur}</em></div>
        <div className="db-kpi"><span>peak import</span><b>{best.peak_w} W</b><em>cap {g.meta.assets.peak_cap_w} W (grid only {base.peak_w} W)</em></div>
        <div className="db-kpi"><span>CO₂</span><b>{best.co2_kg} kg</b><em>grid only {base.co2_kg} kg</em></div>
        <div className={`db-kpi ${ups === pq.length ? "ok" : "warn"}`}><span>mains events ridden through</span><b>{ups}/{pq.length}</b><em>without the inverter {raw}/{pq.length}</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>What the month says</h3>
          <div className="mo-insights">{g.findings.map((f) => <div key={f.title}><b>{f.title}</b><p>{f.text}</p></div>)}</div>
        </section>
        <section className="db-card wide"><h3>Power flows on day
          <input type="range" min={1} max={g.meta.days} value={day} onChange={(e) => setDay(+e.target.value)} style={{ width: 240 }} /> {day}
          <span className="db-muted">({g.weather[day - 1].kind}{sl(S.dr).some(Boolean) ? " · demand-response event" : ""})</span></h3>
          <Chart days={false} xLabel="hour of the day" yLabel="power (W)" xMax={24}
            lines={[{ name: S.oven ? "site load (cell + oven)" : "cell load", x: hx, y: sl(S.load), color: "#e6f0ff", width: 1.6 },
                    ...(S.oven ? [{ name: "oven", x: hx, y: sl(S.oven), color: "#e0703a" }] : []), { name: "PV", x: hx, y: sl(S.pv), color: "#f2c230" },
                    { name: "grid (+ import, − export)", x: hx, y: sl(S.grid), color: "#4f8fd6", width: 1.6 },
                    { name: "battery (+ charge)", x: hx, y: sl(S.batt), color: "#22c55e" },
                    { name: "grid only (no PV, no battery)", x: hx, y: sl(S.grid_only), color: "#e0503a", dash: true }]}
            hlines={[{ y: g.meta.assets.peak_cap_w, color: "#e0a02a", label: "peak cap" }, { y: 0, color: "#3a4a5c", label: "" }]}
            marks={hx.filter((_, i) => sl(S.dr)[i] && !sl(S.dr)[i - 1]).map((x) => ({ x, color: "#b07ad6", label: "DR event" }))} />
          <Chart h={110} days={false} xLabel="hour of the day" yMin={0} yMax={1} yLabel="battery SoC" xMax={24}
            lines={[{ name: "state of charge", x: hx, y: sl(S.soc), color: "#22c55e", width: 1.6 }]}
            hlines={[{ y: g.meta.assets.reserve, color: "#e0503a", label: "ride-through reserve" }]} />
          <Chart h={100} days={false} xLabel="hour of the day" yLabel="€/kWh" xMax={24} lines={[{ name: "price", x: hx, y: sl(S.price), color: "#e0a02a" }]} />
          <p className="db-note">The energy manager plans each day at midnight with a dynamic programme over the battery's charge (20 Wh steps)
            against the forecast; in real time it trims charging to hold the peak cap and covers any forecast miss inside a
            demand-response window. It never discharges into the {Math.round(g.meta.assets.reserve * 100)} % reserve kept for outages.</p>
        </section>
        <section className="db-card wide"><h3>Three ways to power the site, this month</h3>
          <div className="gr-four">{([["cost (€)", (v: Sc) => v.total_eur, (x: number) => `€${x.toFixed(2)}`],
                                      ["CO₂ (kg)", (v: Sc) => v.co2_kg, (x: number) => `${x.toFixed(1)}`],
                                      ["peak import (W)", (v: Sc) => v.peak_w, (x: number) => `${Math.round(x)}`],
                                      ["self-sufficiency (%)", (v: Sc) => v.self_sufficiency * 100, (x: number) => `${Math.round(x)}`]] as const).map(([t, get, fmt]) => (
            <div key={t}><h4>{t}</h4>
              <HBar xTitle="" fmt={fmt} rows={Object.entries(sc).map(([k, v]) => ({ label: NAME[k] ?? k, v: get(v), on: k === "pv+battery",
                color: k === "pv+battery" ? "var(--ok)" : k === "pv" ? "#f2c230" : "#6c7884" }))}
                refs={t.startsWith("peak") ? [{ v: g.meta.assets.peak_cap_w, label: "cap", color: "var(--warn)" }] : []} /></div>))}
          </div>
          <p className="hl-cap">Demand-response events met: {Object.entries(sc).map(([k, v]) => `${NAME[k] ?? k} ${v.dr_met ? "yes" : "no"}`).join(" · ")}. {g.meta.tariff}.</p>
        </section>
        <section className="db-card wide"><h3>Energy per day</h3>
          <Plot h={220} xTitle="day of the month" yTitle="energy (kWh)" xMin={1} xMax={g.meta.days} yMin={0} yFmt={(v) => v.toFixed(1)}
            series={[{ name: "PV generated", x: dailyE.map((_, d) => d + 1), y: dailyE.map((e) => e.pv), color: "#f2c230", kind: "area", width: 1.8, fmt: (v) => `${v.toFixed(2)} kWh` },
                     { name: S.oven ? "site load" : "cell load", x: dailyE.map((_, d) => d + 1), y: dailyE.map((e) => e.load), color: "#9fd0ff", width: 2, fmt: (v) => `${v.toFixed(2)} kWh` },
                     { name: "grid import", x: dailyE.map((_, d) => d + 1), y: dailyE.map((e) => e.imp), color: "#4f8fd6", dash: true, width: 1.6, fmt: (v) => `${v.toFixed(2)} kWh` }]}
            tipTitle={(x) => `day ${Math.round(x)} · ${g.weather[Math.round(x) - 1]?.kind ?? ""}`} />
          <p className="hl-cap">{g.weather.filter((w) => w.kind === "rain" || w.kind === "overcast").length} dull days: import rises where PV falls.</p>
        </section>
        <section className="db-card wide"><h3>Power quality: every mains event, with and without the inverter <span className="db-muted">hover a result for why</span></h3>
          <table className="db-table"><thead><tr><td>when</td><td>event</td><td>with the inverter (UPS mode)</td><td>grid only</td></tr></thead>
            <tbody>{pq.map((p, i) => (
              <tr key={i}><td className="mono">day {p.day} {String(Math.floor(p.h)).padStart(2, "0")}:{String(Math.round((p.h % 1) * 60)).padStart(2, "0")}</td>
                <td>{p.kind === "outage" ? `outage, ${Math.round(p.dur_s / 60)} min` : `sag to ${Math.round((p.depth ?? 0) * 100)} %, ${p.dur_s * 1000} ms`}</td>
                <td><span className={`gr-pill ${p.with_ups.survives ? "ok" : "fail"}`} title={p.with_ups.why}>{p.with_ups.survives ? "✓ rides through" : "✗ stops"}</span>
                  {p.with_ups.oven && <span className="gr-pill fail" title={p.with_ups.oven}>oven goes cold</span>}</td>
                <td><span className={`gr-pill ${p.grid_only.survives ? "ok" : "fail"}`} title={p.grid_only.why}>{p.grid_only.survives ? "✓ rides through" : `✗ stops${p.grid_only.lost_s ? ` · −${p.grid_only.lost_s} s` : ""}`}</span></td></tr>
            ))}</tbody></table>
        </section>
        <section className="db-card wide"><h3>Power-asset health: the PSU's capacitors and the cabinet air filter</h3>
          <Chart yLabel="°C cabinet" lines={[{ name: "with the filter work orders", x: cab.t_cab.map((_, i) => i * 2), y: cab.t_cab, color: "#22c55e", width: 1.4 },
                                               { name: "without (counterfactual)", x: cab.t_cab_cf.map((_, i) => i * 2), y: cab.t_cab_cf, color: "#e0503a", dash: true }]}
            marks={cab.events.filter((e) => e.what.startsWith("planned")).map((e) => ({ x: e.h, color: "#22c55e", label: "filter changed" }))} xMax={g.meta.days * 24} />
          <p className="db-note">The PSU's electrolytic capacitors lose half their life for every 10 K (Arrhenius). Dust from the building work
            clogs the cabinet's air filter; a cabinet sensor sees the temperature rise, and the filter is changed in the night gap.
            Capacitor life at this month's rate: <b>{cab.life_years} years</b> with the work orders, <b>{cab.life_years_cf} years</b> without.</p>
        </section>
        <section className="db-card"><h3>PV soiling</h3>
          <Chart h={130} days={false} xLabel="day of the month" yMin={0.8} yMax={1.02} yLabel="performance ratio" xMax={g.meta.days}
            lines={[{ name: "PV performance ratio (vs the irradiance sensor)", x: g.health.pv.performance_ratio.map((_, i) => i + 1), y: g.health.pv.performance_ratio, color: "#f2c230", width: 1.6 }]}
            marks={g.pv_cleaning.filter((c) => c.what.startsWith("planned")).map((c) => ({ x: c.day, color: "#22c55e", label: "cleaned" }))} />
          {g.pv_cleaning.map((c) => <p key={c.what} className="db-note">day {c.day}: {c.what}</p>)}
        </section>
        <section className="db-card"><h3>Battery and contactors</h3>
          <table className="db-table"><tbody>
            <tr><td>battery state of health</td><td className="num">{(g.health.battery.soh_start * 100).toFixed(1)} → {(g.health.battery.soh_end * 100).toFixed(2)} %</td></tr>
            <tr><td>equivalent full cycles this month</td><td className="num">{g.health.battery.equivalent_full_cycles}</td></tr>
            <tr><td>years to 80 % at this rate</td><td className="num">{g.health.battery.years_to_80pct}</td></tr>
            <tr><td>K1/K2 operations this month</td><td className="num">{g.health.contactors.operations_month}</td></tr>
            <tr><td>years to their electrical life</td><td className="num">{g.health.contactors.years_to_life}</td></tr>
          </tbody></table>
        </section>
        <section className="db-card"><h3>Economics, honestly</h3>
          <HBar xTitle="capital cost (€)" fmt={(v) => `€${Math.round(v)}`} rows={Object.entries(g.economics.capex_eur).sort((x, y) => y[1] - x[1]).map(([k, v]) => ({ label: k, v, color: "#4f8fd6" }))} />
          <div className="hl-facts col">
            <div><b>€{g.economics.capex_total} total · {g.economics.payback_years} years payback</b><span>on €{g.economics.saving_eur_month} a month of energy and demand savings</span></div>
            <div><b>{Math.round(g.economics.outage_cost_avoided_s / 60)} min of production</b><span>lost to mains events without it</span></div>
          </div>
          <p className="db-note">{g.economics.note}.</p>
        </section>
        {ov && <section className="db-card wide"><h3>The oven's supply: its own circuit, or a microgrid that carries it</h3>
          <table className="db-table"><thead><tr><td></td>{ov.options.map((o) => <td key={o.name}>{o.name}</td>)}</tr></thead>
            <tbody>
              <tr><td>inverter · battery · PV</td>{ov.options.map((o) => <td key={o.name} className="num">{o.inverter_w} W · {o.battery_wh / 1000} kWh · {o.pv_wp} Wp</td>)}</tr>
              <tr><td>the oven on the UPS</td>{ov.options.map((o) => <td key={o.name} className="num">{o.carries_oven ? "yes" : `no: ${ov.oven.rated_w} W > ${o.inverter_w} W`}</td>)}</tr>
              <tr><td>outages the oven stays hot</td>{ov.options.map((o) => <td key={o.name} className="num">{o.oven_kept_hot}/{ov.outages}</td>)}</tr>
              <tr><td>self-sufficiency</td>{ov.options.map((o) => <td key={o.name} className="num">{Math.round(o.kpi.self_sufficiency * 100)} %</td>)}</tr>
              <tr><td>demand response met</td>{ov.options.map((o) => <td key={o.name} className="num">{o.kpi.dr_met ? "yes" : `no (${o.kpi.dr_import_wh} Wh over)`}</td>)}</tr>
              <tr><td>bill this month</td>{ov.options.map((o) => <td key={o.name} className="num">€{o.kpi.total_eur}</td>)}</tr>
              <tr><td>CO₂ this month</td>{ov.options.map((o) => <td key={o.name} className="num">{o.kpi.co2_kg} kg</td>)}</tr>
              <tr><td>capital · payback</td>{ov.options.map((o) => <td key={o.name} className="num">{o.capex_total ? `€${o.capex_total} · ${o.payback_years} years` : `€${g.economics.capex_total} · ${g.economics.payback_years} years`}</td>)}</tr>
            </tbody></table>
          <p className="db-note">The oven ({ov.oven.rated_w} W of elements) is preheated once a day ({Math.round(ov.oven.preheat_kwh * 1000)} Wh) and held
            at 180 °C through both shifts on {ov.oven.shift_w} W on average: {ov.oven.month_kwh} kWh a month, {Math.round(ov.oven.share_of_load * 100)} % of the site's energy.
            Only {Math.round(ov.oven.useful_share * 100)} % of its heat goes into the cookies. The cell alone uses {ov.cell_only.load_kwh} kWh.</p>
        </section>}
        <section className="db-card wide"><h3>Standards the design follows</h3>
          <ul className="gr-std">{g.meta.standards.map((s) => <li key={s}>{s}</li>)}</ul>
          <div className="mo-dl"><a href={`${BASE}grid/grid_15min.csv`} download>grid_15min.csv</a><a href={`${BASE}grid/grid.json`} download>grid.json</a></div>
          <p className="db-note">Simulated, not measured. Assumed: {g.meta.assumed}.</p>
        </section>
      </div>
    </>
  );
}
