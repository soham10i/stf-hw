// One simulated month of production (stf-cad/hbw/month.py): production,
// sensor time series, component wear, maintenance, FSM and events. The page
// reads web/public/month/month.json; the CSVs beside it hold the same data.
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
type Line = { name: string; x: number[]; y: (number | null)[]; color: string; dash?: boolean; width?: number };
export function Chart({ lines, h = 180, yLabel, hlines = [], marks = [], xMax, yMin, yMax, days = true }: {
  lines: Line[]; h?: number; yLabel?: string; hlines?: { y: number; color: string; label: string }[];
  marks?: { x: number; color: string; label: string }[]; xMax?: number; yMin?: number; yMax?: number; days?: boolean;
}) {
  const W = 900, L = 48, R = 10, T = 10, B = 22;
  const xs = lines.flatMap((l) => l.x);
  const ys = lines.flatMap((l) => l.y.filter((v): v is number => v !== null)).concat(hlines.map((l) => l.y));
  const x1 = xMax ?? Math.max(...xs, 1);
  const y0 = yMin ?? Math.min(...ys), y1 = yMax ?? Math.max(...ys);
  const pad = (y1 - y0) * 0.06 || 1;
  const Y0 = y0 - (yMin === undefined ? pad : 0), Y1 = y1 + (yMax === undefined ? pad : 0);
  const X = (x: number) => L + (x / x1) * (W - L - R);
  const Yp = (y: number) => T + (1 - (y - Y0) / (Y1 - Y0)) * (h - T - B);
  const path = (l: Line) => {
    const step = Math.max(1, Math.floor(l.x.length / 900));
    let d = "", pen = false;
    for (let i = 0; i < l.x.length; i += step) {
      const y = l.y[i];
      if (y === null || y === undefined) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${X(l.x[i]).toFixed(1)},${Yp(y).toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const ticks = days ? Array.from({ length: Math.floor(x1 / 24 / 5) + 1 }, (_, i) => i * 5 * 24) : [0, x1 / 2, x1];
  return (
    <div className="mo-chart">
      <svg viewBox={`0 0 ${W} ${h}`}>
        {[0, 0.5, 1].map((f) => {
          const y = Y0 + f * (Y1 - Y0);
          return <g key={f}><line x1={L} x2={W - R} y1={Yp(y)} y2={Yp(y)} className="mo-grid" />
            <text x={L - 4} y={Yp(y) + 3} textAnchor="end" className="mo-ax">{Math.abs(y) >= 100 ? y.toFixed(0) : y.toFixed(2)}</text></g>;
        })}
        {ticks.map((x) => <text key={x} x={X(x)} y={h - 6} textAnchor="middle" className="mo-ax">{days ? `day ${Math.round(x / 24) + 1}` : x.toFixed(0)}</text>)}
        {hlines.map((l) => <g key={l.label}><line x1={L} x2={W - R} y1={Yp(l.y)} y2={Yp(l.y)} style={{ stroke: tc(l.color) }} strokeDasharray="5 4" />
          <text x={W - R - 2} y={Yp(l.y) - 3} textAnchor="end" className="mo-ax" style={{ fill: tc(l.color) }}>{l.label}</text></g>)}
        {marks.map((mk, i) => <g key={i}><line x1={X(mk.x)} x2={X(mk.x)} y1={T} y2={h - B} style={{ stroke: tc(mk.color) }} strokeWidth={1.2} opacity={0.8} />
          <text x={X(mk.x) + 3} y={T + 10 + (i % 3) * 11} className="mo-ax" style={{ fill: tc(mk.color) }}>{mk.label}</text></g>)}
        {lines.map((l) => <path key={l.name} d={path(l)} fill="none" style={{ stroke: tc(l.color) }} strokeWidth={(l.width ?? 1.3) * 1.15} strokeLinejoin="round" strokeDasharray={l.dash ? "4 3" : undefined} />)}
        {yLabel && <text x={4} y={T + 2} className="mo-ax">{yLabel}</text>}
      </svg>
      <div className="mo-legend">{lines.map((l) => <span key={l.name}><i style={{ background: tc(l.color) }} />{l.name}</span>)}</div>
    </div>
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
  const maxGood = Math.max(...m.daily.map((d) => d.good));
  const hmax = Math.max(...m.heat.flat());
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
        <section className="db-card wide"><h3>Good cookies per day, and OEE</h3>
          <div className="mo-days">
            {m.daily.map((d) => (
              <div key={d.day} title={`${d.date}: ${d.good} good, ${d.orders} orders, OEE ${pct(d.oee)}, ${d.faults} faults, ${d.maint} maintenance`}>
                <i style={{ height: `${(d.good / maxGood) * 100}%` }} className={d.failures ? "fail" : d.maint ? "maint" : ""} />
                <em style={{ bottom: `${d.oee * 100}%` }} />
                <span>{d.day}</span>
              </div>
            ))}
          </div>
          <p className="db-note">Bars: good cookies (amber = a day with planned maintenance, all of it in the night gap). Dots: OEE.
            {" "}{m.meta.batch}; {m.meta.shifts.join(" and ")}, {m.meta.days} days.</p>
        </section>
        <section className="db-card"><h3>Where the time went</h3>
          <div className="db-bars">{m.pareto.map((p) => <div key={p.cause}><span>{p.cause}</span><i style={{ width: `${(p.hours / m.pareto[0].hours) * 100}%` }} /><b>{p.hours} h</b></div>)}</div>
          <p className="db-note">Planned {k.planned_h} h · producing {k.run_h} h.</p>
        </section>
        <section className="db-card wide"><h3>Orders started per hour (day × hour, 06:00–22:00)</h3>
          <div className="mo-heat">
            {m.heat.map((row, d) => (
              <div key={d}><span>{d + 1}</span>{row.map((v, h) => <i key={h} style={{ opacity: 0.15 + 0.85 * (v / hmax) }} title={`day ${d + 1}, ${h + 6}:00 - ${v} orders`} />)}</div>
            ))}
            <div className="mo-heat-x"><span />{Array.from({ length: 16 }, (_, h) => <em key={h}>{h + 6}</em>)}</div>
          </div>
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
                  <tr><td>U6 warning</td><td className="num">day {(s.warn_h / 24 + 1).toFixed(1)}</td></tr>
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
  const ev = m.events.filter((e) => e.comp === id && (e.kind === "maintenance" || e.kind === "warning"));
  const marks = [
    ...ev.map((e) => ({ x: e.t, color: e.kind === "warning" ? "#e0a02a" : "#22c55e", label: e.kind === "warning" ? "warning" : "renewed" })),
    ...c.disturbances.map((d) => ({ x: d.day * 24, color: "#b07ad6", label: "disturbance" })),
  ];
  return (
    <div className="db-grid">
      <section className="db-card wide"><h3>Component</h3>
        <div className="db-chips">{m.components.map((x) => <button key={x.id} className={x.id === id ? "on" : ""} onClick={() => setId(x.id)}>{x.name} {x.maintenance ? `(${x.maintenance}×)` : ""}</button>)}</div>
      </section>
      <section className="db-card wide"><h3>{c.name}: {c.metric}</h3>
        <Chart yLabel="r = observed / new" lines={[{ name: "per order", x: s.t, y: s.ewma.map((_, i) => s.obs[i] / (c.unit_of === "s" ? c.base : 1)), color: "#5b7ea3", width: 0.8 },
          { name: "EWMA (U6)", x: s.t, y: s.ewma, color: "#9fd0ff", width: 1.8 }]}
          hlines={[{ y: c.soft, color: "#e0a02a", label: "soft limit" }, { y: c.r_fail, color: "#e0503a", label: "failure" }]}
          marks={marks} xMax={m.meta.days * 24} />
        <Chart h={130} yMin={0} yMax={100} yLabel="health index" lines={[{ name: "HI", x: s.t, y: s.hi, color: "#22c55e", width: 1.6 }]} marks={marks} xMax={m.meta.days * 24} />
        <table className="db-table"><tbody>
          <tr><td>worn at the start of the month</td><td className="num">{Math.round(c.w0 * 100)} % of its life</td></tr>
          <tr><td>at the end</td><td className="num">{Math.round(c.w_end * 100)} %</td></tr>
          {c.disturbances.map((d) => <tr key={d.what}><td>from day {d.day}: {d.what}</td><td className="num">wear × {d.x}</td></tr>)}
          {ev.map((e) => <tr key={e.t} className={e.kind === "warning" ? "warn" : ""}><td>{e.what}</td><td className="num">day {(e.t / 24 + 1).toFixed(1)}</td></tr>)}
        </tbody></table>
      </section>
    </div>
  );
}

function Raw({ m }: { m: MonthDoc }) {
  const r = m.raw;
  const vac = m.events.filter((e) => e.code === "VGR-V01");
  const perDay = Array.from({ length: m.meta.days }, (_, d) => vac.filter((e) => Math.floor(e.t / 24) === d).length);
  return (
    <div className="db-grid">
      <section className="db-card wide"><h3>Colour sensor A4, per order (mV)</h3>
        <Chart yLabel="mV" lines={[{ name: "vanilla", x: r.t, y: r.a4.vanilla, color: "#f2efe6" }, { name: "strawberry", x: r.t, y: r.a4.strawberry, color: "#f4a6bf" },
          { name: "chocolate", x: r.t, y: r.a4.chocolate, color: "#b0773f" }]}
          hlines={[{ y: 1305, color: "#e0a02a", label: "band edge rot | weiss" }, { y: 645, color: "#e0a02a", label: "band edge blau | rot" }]}
          marks={m.events.filter((e) => e.comp === "colour" && e.kind === "maintenance").map((e) => ({ x: e.t, color: "#22c55e", label: "recalibrated" }))} xMax={m.meta.days * 24} />
      </section>
      <section className="db-card wide"><h3>HBW actuator current (A), from the U3 breaker</h3>
        <Chart yLabel="A" lines={[{ name: "HBW feed", x: r.t, y: r.i_hbw, color: "#4f8fd6" }]}
          hlines={[{ y: 0.8 * 1.5, color: "#e0503a", label: "breaker trips (1.5 x)" }]}
          marks={m.events.filter((e) => e.comp === "spindle" && e.kind !== "fault").map((e) => ({ x: e.t, color: e.kind === "warning" ? "#e0a02a" : "#22c55e", label: e.kind }))} xMax={m.meta.days * 24} />
      </section>
      <section className="db-card wide"><h3>Air: compressor duty, and hall temperature</h3>
        <Chart yLabel="duty" lines={[{ name: "compressor duty", x: r.t, y: r.air_duty, color: "#7cc3f5" }]} xMax={m.meta.days * 24}
          marks={m.events.filter((e) => e.comp === "air" && e.kind === "maintenance").map((e) => ({ x: e.t, color: "#22c55e", label: "leak fixed" }))} />
        <Chart h={110} yLabel="°C" lines={[{ name: "hall temperature", x: r.t, y: r.temp, color: "#e0a02a" }]} xMax={m.meta.days * 24} />
      </section>
      <section className="db-card wide"><h3>VGR vacuum losses per day (VGR-V01)</h3>
        <div className="mo-days">{perDay.map((n, d) => <div key={d} title={`day ${d + 1}: ${n}`}><i className="fail" style={{ height: `${(n / Math.max(1, ...perDay)) * 100}%` }} /><span>{d + 1}</span></div>)}</div>
        <p className="db-note">They climb with the nicked cup lip and stop after its renewal: an earlier signal than the build-up time (see the insights).</p>
      </section>
    </div>
  );
}

function Fsm({ m }: { m: MonthDoc }) {
  const S = ["RUN", "HELD", "READY", "FAULT", "ESTOP", "MAINT"];
  const COL: Record<string, string> = { RUN: "#22c55e", HELD: "#e0a02a", READY: "#3a4a5c", FAULT: "#e0503a", ESTOP: "#b91c1c", MAINT: "#4f8fd6" };
  return (
    <div className="db-grid">
      <section className="db-card wide"><h3>Hours per state, per unit (U4 state machines)</h3>
        {Object.entries(m.fsm).map(([u, d]) => {
          const tot = S.reduce((a, s) => a + (d[s] ?? 0), 0);
          return (
            <div key={u} className="mo-stack"><span>{u}</span>
              <div>{S.map((s) => (d[s] ?? 0) > 0 && <i key={s} style={{ width: `${((d[s] ?? 0) / tot) * 100}%`, background: COL[s] }} title={`${s} ${d[s]} h`} />)}</div>
              <b>{(d.RUN ?? 0).toFixed(0)} h run</b>
            </div>
          );
        })}
        <div className="mo-legend">{S.map((s) => <span key={s}><i style={{ background: COL[s] }} />{s}</span>)}</div>
        <p className="db-note">RUN: the unit's own step. HELD: its job waits on another unit, or it holds while another unit is faulted.
          READY: idle, including changeovers. FAULT/ESTOP: from the month's faults. MAINT: line-stopping maintenance (none this month).</p>
      </section>
    </div>
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
