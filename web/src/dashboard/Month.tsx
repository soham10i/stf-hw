// One simulated month of production (stf-cad/hbw/month.py): production,
// sensor time series, component wear, maintenance, FSM and events. The page
// reads web/public/month/month.json; the CSVs beside it hold the same data.
import { Bars, HBar, Heat, Plot, Stacked, fmtNum, useWidth, type Band, type Series as PlotSeries } from "./Plot";
import { useMemo, useState } from "react";
import { useJson } from "../shared/data";

const BASE = import.meta.env.BASE_URL;

type Series = { t: number[]; obs: number[]; ewma: number[]; hi: number[]; rul: (number | null)[] };
type Ev = { t: number; kind: string; what: string; comp?: string; code?: string; lost_s?: number; down_h?: number;
            root_cause?: string; night?: boolean };
type Kpi = { orders: number; baked: number; good: number; scrap: number; returned: number; cookies_per_h: number;
             planned_h: number; run_h: number; unplanned_h: number; maint_h: number; availability: number;
             performance: number; quality: number; oee: number; faults: number; failures: number; maintenance: number;
             mtbf_h: number; mttr_min: number };
type Day = { day: number; date: string; orders: number; good: number; scrap: number; oee: number; A: number; P: number;
             Q: number; faults: number; maint: number; failures: number; run_h: number };
export type MonthDoc = {
  meta: { start: string; days: number; shifts: string[]; batch: string; order_s_commissioned: number; changeover_s: number;
          seed: number; machine: string; assumed: string };
  kpi: Kpi; kpi_cf: Kpi; daily: Day[]; daily_cf: Day[];
  pareto: { cause: string; hours: number }[]; pareto_cf: { cause: string; hours: number }[];
  saves: { comp: string; name: string; part: string; cause: string; warn_h: number; warn_what: string; pm_h: number;
           pm_min: number; hi_at_pm: number; fail_h: number; fail_what: string; fail_down_h: number; fail_scrap: number;
           lead_h: number }[];
  insights: { title: string; text: string }[];
  heat: number[][];
  components: { id: string; name: string; unit: string; metric: string; r_fail: number; soft: number; base: number;
                unit_of: string; w0: number; w_end: number; disturbances: { day: number; x: number; what: string }[];
                maintenance: number }[];
  sensors: Record<string, Series>;
  sensors_cf: Record<string, { t: number[]; hi: number[] }>;
  raw: { t: number[]; temp: number[]; a4: Record<string, number[]>; i_hbw: number[]; air_duty: number[] };
  orders: { t: number[]; dur: number[]; good: number[]; shift: number[] };
  fsm: Record<string, Record<string, number>>;
  events: Ev[]; events_cf: Ev[];
};

export function useMonth() {
  const { data: m, error: err } = useJson<MonthDoc>("month/month.json", "No month data. Run: STF_VARIANT=up7 python3 month.py");
  return { m, err };
}

// ------------------------------------------------------------ chart kit
// Colours that only read on a dark page map to theme tokens, so every chart
// works in the light theme too; the rest are mid-tone and read on both.
const THEMED: Record<string, string> = { "#e6f0ff": "var(--ink)", "#f2efe6": "var(--ink)", "#9fd0ff": "var(--sky)",
  "#7cc3f5": "var(--sky)", "#3a4a5c": "var(--grid-strong)", "#fff": "var(--text)" };
export const tc = (c: string) => THEMED[c.toLowerCase()] ?? c;
type Line = { name: string; x: number[]; y: (number | null)[]; color: string; dash?: boolean; width?: number; kind?: PlotSeries["kind"]; fmt?: (v: number) => string };
/** Pearson correlation of two series (pairs with a null skipped). */
function corr(a: (number | null)[], b: (number | null)[]) {
  const p = a.map((v, i) => [v, b[i]]).filter((q): q is [number, number] => q[0] !== null && q[1] !== null);
  const ma = p.reduce((s, q) => s + q[0], 0) / p.length, mb = p.reduce((s, q) => s + q[1], 0) / p.length;
  let sab = 0, saa = 0, sbb = 0;
  for (const [x, y] of p) { sab += (x - ma) * (y - mb); saa += (x - ma) ** 2; sbb += (y - mb) ** 2; }
  return sab / Math.sqrt(saa * sbb || 1);
}
/** Rolling mean over n points (the trend under per-order noise). */
export function roll(y: (number | null)[], n: number) {
  const out: (number | null)[] = [];
  let sum = 0, cnt = 0;
  for (let i = 0; i < y.length; i++) {
    const v = y[i];
    if (v !== null) { sum += v; cnt++; }
    const o = i - n >= 0 ? y[i - n] : null;
    if (i - n >= 0 && o !== null) { sum -= o; cnt--; }
    out.push(cnt ? sum / cnt : null);
  }
  return out;
}
/** The month's time-series chart: x in hours, read as days of the month - or, with
    days=false, in the unit `xLabel` names. Drawn by Plot (axes, hover read-out, legend). */
export function Chart({ lines, h = 180, yLabel, xLabel, hlines = [], marks = [], xMax, yMin, yMax, days = true, bands, tipExtra, yFmt }: {
  lines: Line[]; h?: number; yLabel?: string; xLabel?: string; hlines?: { y: number; color: string; label: string }[];
  marks?: { x: number; color: string; label: string }[]; xMax?: number; yMin?: number; yMax?: number; days?: boolean;
  bands?: Band[]; tipExtra?: (x: number) => [string, string][]; yFmt?: (v: number) => string;
}) {
  const x1 = xMax ?? Math.max(...lines.flatMap((l) => l.x), 1);
  const dayTicks = days ? Array.from({ length: Math.floor(x1 / 24 / 5) + 1 }, (_, i) => i * 5 * 24) : undefined;
  // many marks of one kind (maintenance, failures) are labelled once
  const seen = new Set<string>();
  const vm = marks.map((m) => { const first = !seen.has(m.label); seen.add(m.label); return { x: m.x, color: tc(m.color), label: first ? m.label : "" }; });
  return (
    <Plot h={h + 40} xMin={0} xMax={x1} yMin={yMin} yMax={yMax} xTicks={dayTicks}
      xTitle={days ? "day of the month" : xLabel ?? ""} yTitle={yLabel ?? ""}
      xFmt={days ? (v) => `${Math.floor(v / 24) + 1}` : fmtNum}
      tipTitle={days ? (v) => `day ${Math.floor(v / 24) + 1}, ${String(Math.floor(v % 24)).padStart(2, "0")}:00` : undefined}
      series={lines.map((l) => ({ name: l.name, x: l.x, y: l.y, color: tc(l.color), dash: l.dash, width: (l.width ?? 1.3) * 1.2, kind: l.kind, fmt: l.fmt }))}
      hlines={hlines.filter((l) => l.label).map((l) => ({ ...l, color: tc(l.color) }))} vmarks={vm} bands={bands} tipExtra={tipExtra} yFmt={yFmt} />
  );
}

function Kp({ label, v, cf, fmt = (x: number) => `${x}`, better = "up" }: { label: string; v: number; cf?: number; fmt?: (x: number) => string; better?: "up" | "down" }) {
  const d = cf === undefined ? 0 : v - cf;
  const good = better === "up" ? d > 0 : d < 0;
  return (
    <div className="db-kpi"><span>{label}</span><b>{fmt(v)}</b>
      {cf !== undefined && d !== 0 && <em className={good ? "mo-good" : "mo-bad"}>{d > 0 ? "+" : ""}{fmt === pct ? `${(d * 100).toFixed(1)} pt` : fmt(Math.round(d * 1000) / 1000)} vs no PM</em>}</div>
  );
}
const pct = (x: number) => `${(x * 100).toFixed(1)} %`;

// ---------------------------------------------------------------- views
function Summary({ m }: { m: MonthDoc }) {
  const k = m.kpi, c = m.kpi_cf;
  const minGood = Math.min(...m.daily.map((d) => d.good));
  const meanGood = m.daily.reduce((a, d) => a + d.good, 0) / m.daily.length;
  const hmax = Math.max(...m.heat.flat()), hmin = Math.min(...m.heat.flat());
  return (
    <>
      <div className="db-kpis">
        <Kp label="orders" v={k.orders} cf={c.orders} />
        <Kp label="good cookies" v={k.good} cf={c.good} />
        <Kp label="OEE" v={k.oee} cf={c.oee} fmt={pct} />
        <Kp label="availability" v={k.availability} fmt={pct} />
        <Kp label="performance" v={k.performance} cf={c.performance} fmt={pct} />
        <Kp label="quality" v={k.quality} fmt={pct} />
        <Kp label="unplanned stop" v={k.unplanned_h} cf={c.unplanned_h} fmt={(x) => `${x} h`} better="down" />
        <Kp label="failures" v={k.failures} cf={c.failures} better="down" />
        <Kp label="MTBF" v={k.mtbf_h} fmt={(x) => `${x} h`} />
        <Kp label="MTTR" v={k.mttr_min} cf={c.mttr_min} fmt={(x) => `${x} min`} better="down" />
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>Insights from the month's data</h3>
          <div className="mo-insights">{m.insights.map((i) => <div key={i.title}><b>{i.title}</b><p>{i.text}</p></div>)}</div>
        </section>
        <section className="db-card wide"><h3>Good cookies per day</h3>
          <Bars xTitle="day of the month" yTitle="good cookies" yMin={Math.floor(minGood * 0.9 / 10) * 10}
            hlines={[{ y: meanGood, color: "var(--accent)", label: "average" }]}
            bars={m.daily.map((d) => ({ key: `${d.day}`, label: `${d.day}`, v: d.good,
              color: d.failures ? "var(--bad)" : d.maint ? "var(--warn)" : "var(--ok)",
              tip: [["", `day ${d.day} · ${d.date}`], ["good cookies", `${d.good}`], ["vs average", `${d.good - meanGood >= 0 ? "+" : ""}${Math.round(d.good - meanGood)}`],
                    ["orders", `${d.orders}`], ["OEE", pct(d.oee)], ["faults", `${d.faults}`], ["maintenance", d.maint ? `${d.maint}` : "–"]] }))} />
          <div className="pl-legend static"><span><i style={{ background: "var(--ok)" }} />normal day</span><span><i style={{ background: "var(--warn)" }} />planned maintenance that night</span>
            <span><i style={{ background: "var(--bad)" }} />a failure</span></div>
        </section>
        <section className="db-card wide"><h3>OEE per day</h3>
          <Plot h={200} xTitle="day of the month" yTitle="OEE (%)" xMin={1} xMax={m.daily.length} yFmt={(v) => `${Math.round(v)}`}
            series={[{ name: "OEE", x: m.daily.map((d) => d.day), y: m.daily.map((d) => d.oee * 100), color: "var(--accent)", width: 2.4, fmt: (v) => `${v.toFixed(1)} %` }]}
            hlines={[{ y: k.oee * 100, color: "var(--muted)", label: "month" }]}
            tipTitle={(x) => `day ${Math.round(x)}`} legend={false} />
        </section>
        <section className="db-card"><h3>Where the time went</h3>
          <HBar xTitle="hours this month" fmt={(v) => v < 1 ? v.toFixed(2) : v.toFixed(1)}
            rows={m.pareto.map((p, i) => ({ label: p.cause, v: p.hours, color: i === 0 ? "var(--warn)" : "#4f8fd6", tip: `${p.cause}: ${p.hours} h (${Math.round((p.hours / k.planned_h) * 100)} % of planned time)` }))} />
          <p className="db-note">Planned {k.planned_h} h · producing {k.run_h} h.</p>
        </section>
        <section className="db-card wide"><h3>Orders started per hour (day × hour, 06:00–22:00)</h3>
          <Heat rh={14} rows={m.heat.map((row, d) => ({ id: `${d}`, label: `day ${d + 1}`, v: row.map((v) => ((v - hmin) / Math.max(1, hmax - hmin)) * 100) }))} x0={6} x1={22}
            xTitle="hour of the day" xTicks={[6, 8, 10, 12, 14, 16, 18, 20, 22]} xFmt={(v) => `${v}:00`}
            cell={(v) => `color-mix(in srgb, var(--accent) ${Math.round(8 + v * 0.9)}%, var(--surface-2))`}
            tip={(_, x, v) => `${Math.floor(x)}:00 — ${Math.round(hmin + (v / 100) * (hmax - hmin))} orders started`} />
          <div className="pl-scale">{hmin} orders <i className="acc" /> {hmax} orders an hour · dark = fewer: changeovers, faults, the shift change</div>
        </section>
      </div>
    </>
  );
}

function Saves({ m }: { m: MonthDoc }) {
  return (
    <div className="db-grid">
      {m.saves.map((s) => {
        const a = m.sensors[s.comp], cf = m.sensors_cf[s.comp];
        return (
          <section key={s.comp} className="db-card wide mo-save">
            <h3>Save: {s.name}</h3>
            <div className="mo-save-grid">
              <div>
                <p><b>Root cause:</b> {s.cause}.</p>
                <table className="db-table"><tbody>
                  <tr><td>condition monitoring warning</td><td className="num">day {(s.warn_h / 24 + 1).toFixed(1)}</td></tr>
                  <tr><td>renewed</td><td className="num">day {(s.pm_h / 24 + 1).toFixed(1)} · {s.pm_min} min at night · HI {s.hi_at_pm}</td></tr>
                  <tr><td>would have failed</td><td className="num mo-bad">day {(s.fail_h / 24 + 1).toFixed(1)}</td></tr>
                  <tr><td>warning lead</td><td className="num">{s.lead_h} h ({(s.lead_h / 8).toFixed(1)} shifts)</td></tr>
                  <tr><td>failure cost avoided</td><td className="num">{s.fail_down_h} h line stop · {s.fail_scrap} scrap</td></tr>
                </tbody></table>
                <p className="db-note"><b>The failure it prevented:</b> {s.fail_what}.</p>
              </div>
              <Chart yMin={0} yMax={100} yLabel="health index"
                lines={[{ name: "with predictive maintenance", x: a.t, y: a.hi, color: "#22c55e", width: 1.6 },
                        { name: "without (counterfactual)", x: cf.t, y: cf.hi, color: "#e0503a", dash: true }]}
                marks={[{ x: s.warn_h, color: "#e0a02a", label: "warning" }, { x: s.pm_h, color: "#22c55e", label: "renewed" },
                        { x: s.fail_h, color: "#e0503a", label: "failure (without)" }]} xMax={m.meta.days * 24} />
            </div>
          </section>
        );
      })}
      <section className="db-card wide"><h3>The counterfactual month</h3>
        <table className="db-table"><thead><tr><td /><td className="num">with the two work orders</td><td className="num">without</td><td className="num">difference</td></tr></thead>
          <tbody>
            {([["orders", "orders"], ["good cookies", "good"], ["scrap", "scrap"], ["unplanned stop (h)", "unplanned_h"], ["failures", "failures"], ["OEE", "oee"]] as const).map(([l, key]) => (
              <tr key={key}><td>{l}</td><td className="num">{key === "oee" ? pct(m.kpi[key]) : m.kpi[key]}</td><td className="num">{key === "oee" ? pct(m.kpi_cf[key]) : m.kpi_cf[key]}</td>
                <td className="num">{key === "oee" ? `${((m.kpi[key] - m.kpi_cf[key]) * 100).toFixed(1)} pt` : Math.round((m.kpi[key] - m.kpi_cf[key]) * 100) / 100}</td></tr>
            ))}
          </tbody></table>
        {m.events_cf.map((e) => <p key={e.t} className="db-note mo-bad">day {(e.t / 24 + 1).toFixed(1)}: {e.what}</p>)}
      </section>
    </div>
  );
}

function Components({ m }: { m: MonthDoc }) {
  const [id, setId] = useState(m.saves[0]?.comp ?? m.components[0].id);
  const c = m.components.find((x) => x.id === id)!;
  const s = m.sensors[id];
  const H = m.meta.days * 24;
  const ev = m.events.filter((e) => e.comp === id && (e.kind === "maintenance" || e.kind === "warning"));
  const marks = [
    ...ev.map((e) => ({ x: e.t, color: e.kind === "warning" ? "#e0a02a" : "#22c55e", label: e.kind === "warning" ? "warning" : "renewed" })),
    ...c.disturbances.map((d) => ({ x: d.day * 24, color: "#b07ad6", label: "disturbance" })),
  ];
  // the month's health of every component, one row each (sampled to 180 columns)
  const heat = useMemo(() => m.components.map((x) => {
    const q = m.sensors[x.id], n = 180;
    return { id: x.id, label: x.name.replace(/ \(.*\)$/, ""), v: Array.from({ length: n }, (_, k) => {
      const t = ((k + 0.5) / n) * H; let j = 0;
      while (j < q.t.length - 1 && q.t[j + 1] <= t) j++;
      return q.hi[j] ?? 100;
    }) };
  }), [m, H]);
  const obs = s.obs.map((v) => v / (c.unit_of === "s" ? c.base : 1));
  const at = (x: number) => { let j = 0; while (j < s.t.length - 1 && s.t[j + 1] <= x) j++; return j; };
  const top = Math.max(c.r_fail * 1.06, ...obs.filter((v) => v !== null) as number[]);
  return (
    <div className="db-grid">
      <section className="db-card wide"><h3>Health of every component over the month</h3>
        <Heat rows={heat} x0={0} x1={H} xTitle="day of the month" xFmt={(v) => `${Math.floor(v / 24) + 1}`} sel={id} pick={setId}
          xTicks={Array.from({ length: Math.floor(m.meta.days / 5) + 1 }, (_, i) => i * 5 * 24)}
          tip={(_, x, v) => `day ${Math.floor(x / 24) + 1}: health ${Math.round(v)}${v < 50 ? " — warned" : ""}`} />
        <div className="pl-scale">health 0 <i /> 100 · a sudden jump back to green is a renewal · click a row</div>
      </section>
      <section className="db-card hl-span2"><h3>{c.name}<span className="db-muted">{c.metric}</span></h3>
        <Chart h={250} yLabel="signal r = measured ÷ new" yMin={Math.min(0.9, ...(obs.filter((v) => v !== null) as number[]))} yMax={top} yFmt={(v) => v.toFixed(2)}
          lines={[{ name: "each order", x: s.t, y: obs, color: "#5b7ea3", kind: "dots", fmt: (v) => v.toFixed(3) },
                  { name: "smoothed (EWMA)", x: s.t, y: s.ewma, color: "#9fd0ff", width: 2, fmt: (v) => v.toFixed(3) }]}
          bands={[{ y0: 0, y1: c.soft, color: "var(--ok)" }, { y0: c.soft, y1: c.r_fail, color: "var(--warn)", label: "warned" }, { y0: c.r_fail, y1: top, color: "var(--bad)", label: "failed" }]}
          hlines={[{ y: c.soft, color: "#e0a02a", label: "soft limit" }, { y: c.r_fail, color: "#e0503a", label: "failure" }]}
          marks={marks} xMax={H}
          tipExtra={(x) => { const j = at(x); return [["health index", `${Math.round(s.hi[j])}`], ["trend: life left", s.rul[j] === null ? "–" : s.rul[j]! >= 999 ? "> 999 sh" : `${s.rul[j]} sh`]]; }} />
      </section>
      <section className="db-card"><h3>This month</h3>
        <div className="mo-wear"><span>worn at the start</span><i><b style={{ width: `${c.w0 * 100}%` }} /></i><em>{Math.round(c.w0 * 100)} %</em></div>
        <div className="mo-wear"><span>worn at the end</span><i><b style={{ width: `${c.w_end * 100}%` }} /></i><em>{Math.round(c.w_end * 100)} %</em></div>
        <ul className="mo-ev">
          {c.disturbances.map((d) => <li key={d.what} className="dist"><b>day {d.day}</b>{d.what} · wear × {d.x}</li>)}
          {ev.map((e) => <li key={e.t} className={e.kind}><b>day {(e.t / 24 + 1).toFixed(1)}</b>{e.what}</li>)}
          {!c.disturbances.length && !ev.length && <li>nothing happened: wear as expected</li>}
        </ul>
      </section>
    </div>
  );
}

function Raw({ m }: { m: MonthDoc }) {
  const r = m.raw, H = m.meta.days * 24, N = 40;
  const vac = m.events.filter((e) => e.code === "VGR-V01");
  const perDay = Array.from({ length: m.meta.days }, (_, d) => vac.filter((e) => Math.floor(e.t / 24) === d).length);
  const cupPm = m.events.find((e) => e.comp === "cup" && e.kind === "maintenance");
  const FL: [keyof typeof r.a4, string][] = [["vanilla", "#f2efe6"], ["strawberry", "#f4a6bf"], ["chocolate", "#b0773f"]];
  return (
    <div className="db-grid">
      <section className="db-card wide"><h3>Colour sensor A4: each cookie's reading, and its band</h3>
        <Chart h={240} yLabel="reading (mV)" yFmt={(v) => `${Math.round(v)}`}
          lines={[...FL.map(([f, col]) => ({ name: f, x: r.t, y: r.a4[f], color: col, kind: "dots" as const, fmt: (v: number) => `${Math.round(v)} mV` })),
                  ...FL.map(([f, col]) => ({ name: `${f}, ${N}-order mean`, x: r.t, y: roll(r.a4[f], N), color: col, width: 2, fmt: (v: number) => `${Math.round(v)} mV` }))]}
          hlines={[{ y: 1305, color: "#e0a02a", label: "band edge rot | weiss" }, { y: 645, color: "#e0a02a", label: "band edge blau | rot" }]}
          marks={m.events.filter((e) => e.comp === "colour" && e.kind === "maintenance").map((e) => ({ x: e.t, color: "#22c55e", label: "recalibrated" }))} xMax={H} />
        <p className="hl-cap">The LED ages and readings drift down toward the next band; a reading across a band edge would sort a cookie into the wrong bin.</p>
      </section>
      <section className="db-card hl-span2"><h3>HBW actuator current, from the remote I/O breaker</h3>
        <Chart h={210} yLabel="current (A)" yFmt={(v) => v.toFixed(2)}
          lines={[{ name: "each order", x: r.t, y: r.i_hbw, color: "#4f8fd6", kind: "dots", fmt: (v) => `${v.toFixed(3)} A` },
                  { name: `${N}-order mean`, x: r.t, y: roll(r.i_hbw, N), color: "#9fd0ff", width: 2.2, fmt: (v) => `${v.toFixed(3)} A` }]}
          hlines={[{ y: 0.8 * 1.5, color: "#e0503a", label: "breaker trips (1.5 ×)" }]}
          marks={m.events.filter((e) => e.comp === "spindle" && e.kind !== "fault").map((e) => ({ x: e.t, color: e.kind === "warning" ? "#e0a02a" : "#22c55e", label: e.kind }))} xMax={H} />
      </section>
      <section className="db-card"><h3>VGR vacuum losses per day</h3>
        <Bars h={210} xTitle="day of the month" yTitle="losses (VGR-V01)" yMin={0} yFmt={(v) => `${v}`} xLabelEvery={5}
          bars={perDay.map((n, d) => ({ key: `${d}`, label: `${d + 1}`, v: n, color: cupPm && d >= Math.floor(cupPm.t / 24) ? "var(--ok)" : "var(--bad)",
            tip: [["", `day ${d + 1}`], ["vacuum losses", `${n}`]] }))} />
        <p className="hl-cap">{cupPm ? `Red before the cup seal's renewal (day ${(cupPm.t / 24 + 1).toFixed(1)}), green after: ` : ""}an earlier sign than the build-up time.</p>
      </section>
      <section className="db-card wide"><h3>Air: compressor duty against hall temperature</h3>
        <Chart h={200} yLabel="compressor duty" yFmt={(v) => v.toFixed(2)}
          lines={[{ name: "each order", x: r.t, y: r.air_duty, color: "#7cc3f5", kind: "dots", fmt: (v) => v.toFixed(3) },
                  { name: `${N}-order mean`, x: r.t, y: roll(r.air_duty, N), color: "#9fd0ff", width: 2.2, fmt: (v) => v.toFixed(3) }]}
          marks={m.events.filter((e) => e.comp === "air" && e.kind === "maintenance").map((e) => ({ x: e.t, color: "#22c55e", label: "leak fixed" }))} xMax={H} />
        <Chart h={140} yLabel="hall (°C)" yFmt={(v) => v.toFixed(1)} lines={[{ name: "hall temperature", x: r.t, y: r.temp, color: "#e0a02a", fmt: (v) => `${v.toFixed(1)} °C` }]} xMax={H} />
        <p className="hl-cap">Correlation of duty with temperature: r = {corr(r.air_duty, r.temp).toFixed(2)}{Math.abs(corr(r.air_duty, r.temp)) < 0.2 ? " — the duty follows the leak, not the weather." : "."}</p>
      </section>
    </div>
  );
}

function Fsm({ m }: { m: MonthDoc }) {
  const S = ["RUN", "HELD", "READY", "FAULT", "ESTOP", "MAINT"];
  const COL: Record<string, string> = { RUN: "#22c55e", HELD: "#e0a02a", READY: "#3a4a5c", FAULT: "#e0503a", ESTOP: "#b91c1c", MAINT: "#4f8fd6" };
  return (
    <div className="db-grid">
      <section className="db-card wide"><h3>Hours per state, per unit (state machines)</h3>
        <Stacked unit=" h" parts={S.map((x) => ({ name: x, color: COL[x] }))}
          rows={Object.entries(m.fsm).sort((p, q) => (q[1].RUN ?? 0) - (p[1].RUN ?? 0)).map(([u, d]) => ({ label: `${u} · ${Math.round(d.RUN ?? 0)} h run`, v: S.map((x) => Math.round(d[x] ?? 0)) }))} />
        <p className="db-note">RUN: the unit's own step. HELD: its job waits on another unit, or it holds while another unit is faulted.
          READY: idle, including changeovers. FAULT/ESTOP: from the month's faults. MAINT: line-stopping maintenance (none this month).</p>
      </section>
    </div>
  );
}

const EV_COL: Record<string, string> = { failure: "#e0503a", fault: "#e07a5a", warning: "#e0a02a", maintenance: "#22c55e", disturbance: "#b07ad6" };
/** Every event of the month on one time axis, one row per kind. */
function EventStrip({ m, kinds }: { m: MonthDoc; kinds: string[] }) {
  const [box, W] = useWidth<HTMLDivElement>();
  const [hov, setHov] = useState<number | null>(null);
  const H = m.meta.days * 24, L = 110, R = 14, RH = 22, T = 4, B = 36, h = T + kinds.length * RH + B;
  const X = (t: number) => L + (t / H) * (W - L - R);
  const e = hov === null ? null : m.events[hov];
  return (
    <div className="pl"><div className="pl-box" ref={box} onMouseLeave={() => setHov(null)}><svg viewBox={`0 0 ${W} ${h}`}>
      {Array.from({ length: Math.floor(m.meta.days / 5) + 1 }, (_, i) => i * 5 * 24).map((t) => <g key={t}>
        <line x1={X(t)} x2={X(t)} y1={T} y2={T + kinds.length * RH} className="pl-grid" />
        <text x={X(t)} y={T + kinds.length * RH + 14} textAnchor="middle" className="pl-tick">{t / 24 + 1}</text></g>)}
      <text x={(L + W - R) / 2} y={h - 5} textAnchor="middle" className="pl-title">day of the month · hover an event</text>
      {kinds.map((k, i) => <text key={k} x={L - 10} y={T + i * RH + RH / 2 + 4} textAnchor="end" className="pl-row">{k}</text>)}
      {m.events.map((ev, j) => {
        const i = kinds.indexOf(ev.kind);
        return i < 0 ? null : <circle key={j} cx={X(ev.t)} cy={T + i * RH + RH / 2} r={hov === j ? 7 : 4.5} fill={EV_COL[ev.kind] ?? "#9fd0ff"} opacity={0.85}
          onMouseEnter={() => setHov(j)} className="pl-dot" />;
      })}
    </svg>
    {e && <div className="pl-tip" style={{ left: `${(X(e.t) / W) * 100}%`, transform: `translateX(${X(e.t) / W > 0.6 ? "calc(-100% - 12px)" : "12px"})` }}>
      <b>day {(e.t / 24 + 1).toFixed(1)} · {e.kind}</b><div>{e.what}</div>{(e.lost_s || e.down_h) ? <div><i />lost<em>{e.lost_s ? `${e.lost_s} s` : `${e.down_h} h`}</em></div> : null}</div>}
    </div></div>
  );
}

function Events({ m }: { m: MonthDoc }) {
  const [k, setK] = useState("all");
  const kinds = ["all", ...Array.from(new Set(m.events.map((e) => e.kind)))];
  const ev = m.events.filter((e) => k === "all" || e.kind === k);
  const at = (h: number) => {
    const d = new Date(new Date(m.meta.start).getTime() + h * 3600e3);
    return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  };
  return (
    <div className="db-grid">
      <section className="db-card wide"><h3>Downloads (CSV)</h3>
        <div className="mo-dl">{["orders", "sensors", "raw", "events", "daily", "fsm"].map((f) => <a key={f} href={`${BASE}month/${f}.csv`} download>{f}.csv</a>)}
          <a href={`${BASE}month/month.json`} download>month.json</a></div>
      </section>
      <section className="db-card wide"><h3>Event log</h3>
        <EventStrip m={m} kinds={kinds.slice(1)} />
        <div className="db-chips">{kinds.map((x) => <button key={x} className={x === k ? "on" : ""} onClick={() => setK(x)}>{x} ({x === "all" ? m.events.length : m.events.filter((e) => e.kind === x).length})</button>)}</div>
        <table className="db-table"><tbody>
          {ev.map((e, i) => <tr key={i} className={e.kind === "failure" ? "fail" : e.kind === "warning" ? "warn" : ""}>
            <td className="mono">{at(e.t)}</td><td>{e.kind}</td><td>{e.what}</td>
            <td className="num">{e.lost_s ? `${e.lost_s} s` : e.down_h ? `${e.down_h} h` : ""}</td></tr>)}
        </tbody></table>
      </section>
    </div>
  );
}

const VIEWS = [["summary", "Summary"], ["saves", "The two saves"], ["components", "Component wear"], ["raw", "Sensor data"],
               ["fsm", "State machines"], ["events", "Events & data"]] as const;

export function MonthPage() {
  const { m, err } = useMonth();
  const [v, setV] = useState<(typeof VIEWS)[number][0]>("summary");
  const title = useMemo(() => m && `${new Date(m.meta.start).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })} + ${m.meta.days} days · ${m.meta.machine}`, [m]);
  if (err) return <div className="db-err">{err}</div>;
  if (!m) return <div className="db-err">loading the month…</div>;
  return (
    <>
      <div className="mo-sub">
        {VIEWS.map(([id, label]) => <button key={id} className={id === v ? "on" : ""} onClick={() => setV(id)}>{label}</button>)}
        <span className="db-muted">{title} · seed {m.meta.seed}</span>
      </div>
      {v === "summary" && <Summary m={m} />}
      {v === "saves" && <Saves m={m} />}
      {v === "components" && <Components m={m} />}
      {v === "raw" && <Raw m={m} />}
      {v === "fsm" && <Fsm m={m} />}
      {v === "events" && <Events m={m} />}
      <p className="db-foot">Simulated from the models (month.py), not measured. Assumed: {m.meta.assumed}.</p>
    </>
  );
}
