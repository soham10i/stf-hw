// Upgrade 18: the carbon footprint of a cookie (stf-cad/hbw/carbon.py) - grams of CO2e per
// good cookie from the simulated month on the microgrid, where they come from, and what each
// lever saves when the same month is re-run through the same energy manager.
import { useJson } from "../shared/data";
import { clean } from "../shared/names";
import { Bars, HBar, Plot } from "./Plot";

type Lever = { co2_kg: number | null; g_per_cookie: number; load_kwh?: number; import_kwh?: number; cost_eur?: number; wh_per_cookie?: number; estimate?: boolean; note?: string };
type Doc = {
  meta: { days: number; good_cookies: number; orders: number; cookies_per_order: number; sleep_after_h: number; sleep_w: number; awake_w: number;
          inverter_w: number; u10_gain: number; scope: string; assumed: string; oven_share?: number };
  real_bake?: { g_per_cookie: number; cookies_h: number; demo_cookies_h: number; note: string };
  levers: Record<string, Lever>;
  breakdown_g_per_cookie: Record<string, number>;
  standing_share: number;
  hours: { h: number; intensity: number; import_w: number; grid_only_w: number; pv_w: number; load_w: number }[];
  daily: { day: number; g_per_cookie: number | null; weather: string }[];
};
const WCOL: Record<string, string> = { clear: "#f2c230", partly: "#c9b458", overcast: "#8b95a3", rain: "#4f8fd6" };

export function CarbonPage() {
  const { data: d, error } = useJson<Doc>("carbon/carbon.json", "No data. Run: make carbon");
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return <div className="db-err">loading…</div>;
  const L = d.levers, keys = Object.keys(L), built = L["as built: PV + battery"], grid = L["grid only"];
  const best = keys[keys.length - 1];
  const B = Object.entries(d.breakdown_g_per_cookie);
  const motors = B.filter(([k]) => k.startsWith("motor")).reduce((a, [, v]) => a + v, 0);
  const groups: [string, number, string][] = [
    ...B.filter(([k]) => !k.startsWith("motor")).map(([k, v]) => [k, v, k.startsWith("oven") ? "#e0a02a" : k.includes("standing") ? "#e0503a" : "#4f8fd6"] as [string, number, string]),
    ["motors (all units)", motors, "#22c55e"]];
  groups.sort((a, b) => b[1] - a[1]);
  const ca = L["+ carbon-aware battery"], sl = L["+ sleep when idle"];
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>per good cookie</span><b>{built.g_per_cookie.toFixed(2)} g</b><em>CO₂e, as built · grid only {grid.g_per_cookie.toFixed(2)} g</em></div>
        <div className="db-kpi"><span>per order</span><b>{(built.g_per_cookie * d.meta.cookies_per_order).toFixed(1)} g</b><em>{d.meta.cookies_per_order} good cookies</em></div>
        {d.meta.oven_share !== undefined && <div className="db-kpi warn"><span>the oven</span><b>{Math.round(d.meta.oven_share * 100)} %</b><em>of the footprint: held at 180 °C through the shifts</em></div>}
        <div className="db-kpi warn"><span>standing load</span><b>{Math.round(d.standing_share * 100)} %</b><em>of the footprint: the cell idling, not making</em></div>
        <div className="db-kpi ok"><span>with every lever</span><b>{L[best].g_per_cookie.toFixed(2)} g</b><em>−{Math.round((1 - L[best].g_per_cookie / built.g_per_cookie) * 100)} % vs as built</em></div>
        {d.real_bake && <div className="db-kpi warn" title={d.real_bake.note}><span>with a real bake (estimate)</span><b>{d.real_bake.g_per_cookie.toFixed(1)} g</b><em>{d.real_bake.cookies_h} cookies an hour instead of {d.real_bake.demo_cookies_h}</em></div>}
      </div>
      <div className="db-grid">
        <section className="db-card hl-span2"><h3>Where a cookie's carbon comes from</h3>
          <HBar xTitle="g CO₂e per good cookie (as built)" fmt={(v) => v.toFixed(3)}
            rows={groups.map(([k, v, c]) => ({ label: k, v, color: c, tip: `${k}: ${v.toFixed(4)} g (${Math.round((v / built.g_per_cookie) * 100)} %)` }))} />
          <p className="hl-cap">Red: drawn whether or not a cookie is made; amber: the oven, held hot whether or not it bakes. The motors that actually move cookies are a small part; hover for each unit.</p>
        </section>
        <section className="db-card"><h3>What each lever does</h3>
          <HBar xTitle="g CO₂e per good cookie" fmt={(v) => v.toFixed(3)}
            rows={keys.map((k, i) => ({ label: clean(k), v: L[k].g_per_cookie, on: k.startsWith("as built"),
              color: k === "grid only" ? "#6c7884" : L[k].estimate ? "#b07ad6" : i === 1 ? "#4f8fd6" : "#22c55e",
              tip: L[k].note ?? `${k}: ${L[k].import_kwh} kWh imported, €${L[k].cost_eur} this month` }))} />
          <ul className="ai-verdict">
            <li><b>Sleep when idle</b> ({d.meta.awake_w} → {d.meta.sleep_w} W after {d.meta.sleep_after_h * 60} min idle): −{Math.round((1 - sl.g_per_cookie / built.g_per_cookie) * 100)} %, and cheaper.</li>
            <li><b>Carbon-aware battery</b>: {ca.g_per_cookie < sl.g_per_cookie * 0.995
              ? `−${Math.round((1 - ca.g_per_cookie / sl.g_per_cookie) * 100)} % more: planned against the grid's intensity, the battery shifts the held oven's draw out of the dirtiest hours`
              : "no gain here — the price already peaks when the grid is dirtiest, so the cost plan is the carbon plan"}. {(ca.cost_eur ?? 0) >= (sl.cost_eur ?? 0) ? ` It costs €${((ca.cost_eur ?? 0) - (sl.cost_eur ?? 0)).toFixed(2)} a month more.` : ` It saves €${((sl.cost_eur ?? 0) - (ca.cost_eur ?? 0)).toFixed(2)} a month too.`}</li>
          </ul>
        </section>
        <section className="db-card wide"><h3>The day, hour by hour (month average)</h3>
          <Plot h={250} xTitle="hour of the day" yTitle="power (W)" xMin={0} xMax={23} yMin={0} yFmt={(v) => `${Math.round(v)}`}
            series={[{ name: d.meta.oven_share !== undefined ? "site load (cell + oven)" : "cell load", x: d.hours.map((h) => h.h), y: d.hours.map((h) => h.load_w), color: "#9fd0ff", width: 2, fmt: (v) => `${v.toFixed(0)} W` },
                     { name: "PV", x: d.hours.map((h) => h.h), y: d.hours.map((h) => h.pv_w), color: "#f2c230", kind: "area", width: 1.6, fmt: (v) => `${v.toFixed(0)} W` },
                     { name: "grid import, as built", x: d.hours.map((h) => h.h), y: d.hours.map((h) => h.import_w), color: "#4f8fd6", width: 2.4, fmt: (v) => `${v.toFixed(0)} W` },
                     { name: "grid import, grid only", x: d.hours.map((h) => h.h), y: d.hours.map((h) => h.grid_only_w), color: "#6c7884", dash: true, width: 1.6, fmt: (v) => `${v.toFixed(0)} W` }]}
            tipTitle={(x) => `${Math.round(x)}:00–${Math.round(x) + 1}:00`}
            tipExtra={(x) => { const h = d.hours[Math.round(x)]; return h ? [["grid intensity", `${h.intensity} g/kWh`]] : []; }} />
          <Plot h={150} xTitle="hour of the day" yTitle="g CO₂e / kWh" xMin={0} xMax={23} yFmt={(v) => `${Math.round(v)}`} legend={false}
            series={[{ name: "grid carbon intensity", x: d.hours.map((h) => h.h), y: d.hours.map((h) => h.intensity), color: "#e0503a", kind: "step", width: 2.2, fmt: (v) => `${v.toFixed(0)} g/kWh` }]} />
          <p className="hl-cap">The battery covers part of the dirty evening peak with midday sun; at night the cell still draws its standing load from the grid.</p>
        </section>
        <section className="db-card wide"><h3>Per day</h3>
          <Bars xTitle="day of the month" yTitle="g CO₂e per cookie" yMin={0} yFmt={(v) => v.toFixed(2)} xLabelEvery={5}
            hlines={[{ y: built.g_per_cookie, color: "var(--muted)", label: "month" }]}
            bars={d.daily.filter((x) => x.g_per_cookie !== null).map((x) => ({ key: `${x.day}`, label: `${x.day}`, v: x.g_per_cookie!, color: WCOL[x.weather] ?? "#4f8fd6",
              tip: [["", `day ${x.day}`], ["weather", x.weather], ["g per cookie", x.g_per_cookie!.toFixed(3)]] }))} />
          <div className="pl-legend static">{Object.entries(WCOL).map(([k, c]) => <span key={k}><i style={{ background: c }} />{k}</span>)}</div>
          <p className="hl-cap">{d.meta.scope}. Assumed: {d.meta.assumed}.</p>
        </section>
      </div>
    </>
  );
}
