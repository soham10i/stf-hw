// Upgrade 19: the bake as a process (stf-cad/hbw/bake.py) - the oven heating and holding, one
// cookie baking through its thickness, four ways to end a bake compared on the same shifts, and
// what a real bake means for capacity and energy.
import { useState } from "react";
import { useJson } from "../shared/data";
import { HBar, Plot } from "./Plot";

type Pol = { policy: string; name: string; cookies: number; ok: number; underbaked: number; burnt: number; ok_pct: number;
  ok_pct_fridge: number; ok_pct_bench: number; bake_mean: number; bake_sd: number; bake_min: number; bake_max: number;
  wh_per_cookie: number; peak_air: number };
type Ck = { lot: number; fridge: boolean; thick_mm: number; t0: number; bake_s: number; b: number; water_pct: number; verdict: string; target: number };
type Doc = {
  params: { key: string; value: number | string | number[]; unit: string; source: string }[];
  derived: Record<string, number>;
  heatup: { t180: number; peak_air: number; peak_el: number; hold_w: number; preheat_kwh: number;
    trace: { t: number; air: number; tc: number; top: number; bot: number; wall: number; duty: number }[] };
  nominal: { t_done: number; t_b: number; plateau: number[];
    trace: { t: number; surface: number; core: number; bottom: number; water: number; b: number; air: number }[] };
  shift: { policy: string; power: number; power_learnt: number;
    trace: { t: number; air: number; tc: number; duty: number; surface: number | null; core: number | null; water: number | null; b: number | null; door: number }[] };
  cookies: Record<string, Ck[]>;
  policies: Pol[]; shifts: number; lot_size: number;
  throughput: { rows: { case: string; bake_s: number; order_s: number; baked: number; cookies_h: number }[];
    oven_handling_s: number; oven_cycle_s: number; oven_limit_h: number; rest_s_per_cookie: number; ovens_to_match: number };
  energy: { wh_per_cookie: number; hold_w: number; preheat_kwh: number; oven_month_kwh: number; cell_month_kwh: number | null;
    ledger_kwh: Record<string, number> };
  checks: { fails: string[]; mutations: { name: string; caught: boolean }[] };
  findings: string[];
  assumed: string;
};

const PCOL: Record<string, string> = { timer: "#8b95a3", soft: "#f2a33a", camera: "#4f8fd6", ir: "#22c55e" };
const LEDGER: Record<string, string> = { walls: "through the insulated walls", door: "through the shut door", vent: "out of the steam vent",
  mouth: "out of the open mouth", tray_hall: "tray and cookie outside", steam: "the water baked off (steam)" };
const c1 = (v: number) => `${v.toFixed(1)} °C`;
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export function ProcessPage() {
  const { data: d, error } = useJson<Doc>("bake/process.json", "No data. Run: make bake");
  const [span, setSpan] = useState(2);          // hours of the shift on the chart
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return <div className="db-err">loading…</div>;
  const P = Object.fromEntries(d.params.map((p) => [p.key, p.value]));
  const best = d.policies[d.policies.length - 1], timer = d.policies[0];
  const [demo, real] = d.throughput.rows;
  const n = d.nominal, h = d.heatup;
  const band = P.b_band as number[];
  const sh = d.shift.trace.filter((x) => x.t <= span * 3600);
  const ledger = Object.entries(d.energy.ledger_kwh).filter(([k]) => k in LEDGER);
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>right first time</span><b>{best.ok_pct} %</b><em>{best.name} · a fixed timer {timer.ok_pct} %</em></div>
        <div className="db-kpi warn"><span>cookies an hour</span><b>{real.cookies_h}</b><em>with a real {Math.round(real.bake_s / 60)} min bake · {demo.cookies_h} with the 2 s lamp</em></div>
        <div className="db-kpi"><span>heat per cookie</span><b>{best.wh_per_cookie.toFixed(0)} Wh</b><em>holding 180 °C takes {d.energy.hold_w} W</em></div>
        <div className="db-kpi"><span>ovens the cell could feed</span><b>{d.throughput.ovens_to_match}</b><em>one oven: {d.throughput.oven_limit_h} cookies an hour at most</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>What the model found</h3>
          <ul className="ai-verdict">{d.findings.map((f, i) => <li key={i}>{f}</li>)}</ul>
        </section>

        <section className="db-card wide"><h3>One cookie in the oven</h3>
          <Plot h={250} xTitle="time in the oven" yTitle="temperature (°C)" xMin={0} xMax={n.trace[n.trace.length - 1].t} xFmt={mmss} yMin={0}
            series={[
              { name: "oven air", x: n.trace.map((p) => p.t), y: n.trace.map((p) => p.air), color: "#8b95a3", dash: true, width: 1.4, fmt: c1 },
              { name: "top surface", x: n.trace.map((p) => p.t), y: n.trace.map((p) => p.surface), color: "#e0503a", width: 2.2, fmt: c1 },
              { name: "bottom (on the tray)", x: n.trace.map((p) => p.t), y: n.trace.map((p) => p.bottom), color: "#f2a33a", width: 1.8, fmt: c1 },
              { name: "centre", x: n.trace.map((p) => p.t), y: n.trace.map((p) => p.core), color: "#4f8fd6", width: 2.4, fmt: c1 }]}
            hlines={[{ y: 100, color: "var(--muted)", label: "water boils" }]}
            vmarks={[{ x: n.t_done, color: "var(--ok)", label: "done" }, { x: n.t_b, color: "#b07ad6", label: "colour 0.5" }]}
            tipTitle={(x) => mmss(x)} />
          <Plot h={190} xTitle="time in the oven" yTitle="water (% wet) · browning ×10" xMin={0} xMax={n.trace[n.trace.length - 1].t} xFmt={mmss} yMin={0}
            series={[
              { name: "water", x: n.trace.map((p) => p.t), y: n.trace.map((p) => p.water), color: "#4fb3d6", width: 2.2, fmt: (v) => `${v.toFixed(1)} %` },
              { name: "browning index ×10", x: n.trace.map((p) => p.t), y: n.trace.map((p) => p.b * 10), color: "#b07ad6", width: 2.2, fmt: (v) => (v / 10).toFixed(2) }]}
            bands={[{ y0: band[0] * 10, y1: band[1] * 10, color: "rgba(176,122,214,.12)", label: "right colour" }]}
            hlines={[{ y: 6, color: "#4fb3d6", label: "done: ≤ 6 % water" }]}
            vmarks={[{ x: n.t_done, color: "var(--ok)", label: "done" }, { x: n.t_b, color: "#b07ad6", label: "colour 0.5" }]}
            tipTitle={(x) => mmss(x)} />
          <p className="hl-cap">A nominal 8 mm cookie in a settled 180 °C oven. The centre stays near 100 °C ({n.plateau[0].toFixed(0)}–{n.plateau[1].toFixed(0)} °C) while its water boils off, then climbs. The surface browns only once it is dry. Done at {mmss(n.t_done)}, the colour target at {mmss(n.t_b)}; the right colour lasts under two minutes.</p>
        </section>

        <section className="db-card"><h3>The oven heating up</h3>
          <Plot h={230} xTitle="time from switch-on" yTitle="°C" xMin={0} xMax={900} xFmt={mmss} yMin={0}
            series={[
              { name: "grill element", x: h.trace.map((p) => p.t), y: h.trace.map((p) => p.top), color: "#e0503a", width: 1.8, fmt: (v) => `${v.toFixed(0)} °C` },
              { name: "chamber air", x: h.trace.map((p) => p.t), y: h.trace.map((p) => p.air), color: "#f2a33a", width: 2.2, fmt: c1 },
              { name: "thermocouple", x: h.trace.map((p) => p.t), y: h.trace.map((p) => p.tc), color: "#4f8fd6", dash: true, width: 1.6, fmt: c1 },
              { name: "liner and walls", x: h.trace.map((p) => p.t), y: h.trace.map((p) => p.wall), color: "#8b95a3", width: 1.6, fmt: c1 }]}
            hlines={[{ y: 180, color: "var(--ok)", label: "180 °C" }]}
            tipTitle={(x) => mmss(x)}
            tipExtra={(x) => { const p = h.trace[Math.min(h.trace.length - 1, Math.max(0, Math.round(x / 10) - 1))]; return p ? [["heater duty", `${Math.round(p.duty * 100)} %`]] : []; }} />
          <p className="hl-cap">180 °C in {mmss(h.t180)} on 1 300 W, the elements peaking at {h.peak_el.toFixed(0)} °C (their sheath is good to 800 °C). Holding it takes {Math.round(h.hold_w)} W; the preheat costs {Math.round(h.preheat_kwh * 1000)} Wh.</p>
        </section>

        <section className="db-card"><h3>Four ways to end a bake</h3>
          <HBar xTitle="cookies right first time" fmt={(v) => `${v.toFixed(1)} %`} x0={50} x1={100}
            rows={d.policies.map((p) => ({ label: p.name, v: p.ok_pct, color: PCOL[p.policy],
              tip: `${p.name}: ${p.ok} right, ${p.underbaked} underbaked, ${p.burnt} burnt of ${p.cookies} · fridge dough ${p.ok_pct_fridge} % right · bake ${Math.round(p.bake_mean)} ± ${Math.round(p.bake_sd)} s` }))} />
          <div className="cx-table" style={{ marginTop: 10 }}><table>
            <thead><tr><th>policy</th><th>underbaked</th><th>burnt</th><th>fridge dough right</th><th>bake</th></tr></thead>
            <tbody>{d.policies.map((p) => (
              <tr key={p.policy}><td><i className="pr-dot" style={{ background: PCOL[p.policy] }} />{p.name}</td><td>{p.underbaked}</td><td>{p.burnt}</td>
                <td>{p.ok_pct_fridge} %</td><td>{Math.round(p.bake_mean)} ± {Math.round(p.bake_sd)} s</td></tr>))}</tbody>
          </table></div>
          <p className="hl-cap">{d.shifts} shifts each, {d.policies[0].cookies} cookies, the same dough, hall and oven for every policy. The timer cannot see a cold oven or cold dough; the soft sensor follows the oven; the camera corrects the colour cookie by cookie; the dough sensors read each piece before it goes in.</p>
        </section>

        <section className="db-card wide"><h3>Each cookie of one shift</h3>
          <Plot h={240} xTitle="cookie in the shift" yTitle="browning index" xMin={0} xMax={d.cookies.timer.length} yMin={0.1} yMax={0.9}
            series={d.policies.map((p) => ({ name: p.name, x: d.cookies[p.policy].map((_, i) => i + 1), y: d.cookies[p.policy].map((c) => c.b),
              color: PCOL[p.policy], kind: "dots" as const, width: 2, fmt: (v: number) => v.toFixed(2) }))}
            bands={[{ y0: band[0], y1: band[1], color: "rgba(34,197,94,.10)", label: "right colour" }]}
            vmarks={d.cookies.timer.map((c, i) => [c, i] as const).filter(([c, i]) => i > 0 && c.lot !== d.cookies.timer[i - 1].lot)
              .map(([c, i]) => ({ x: i + 0.5, color: "var(--muted)", label: c.fridge ? "lot from the fridge" : "new lot" }))}
            tipTitle={(x) => { const c = d.cookies.timer[Math.round(x) - 1]; return c ? `cookie ${Math.round(x)} · ${c.thick_mm} mm · dough at ${c.t0} °C${c.fridge ? " (fridge)" : ""}` : ""; }}
            tipExtra={(x) => d.policies.map((p) => { const c = d.cookies[p.policy][Math.round(x) - 1]; return [p.name, c ? `${c.verdict}, ${Math.round(c.bake_s)} s` : ""] as [string, string]; })} />
          <p className="hl-cap">Lots of {d.lot_size}. A lot from the fridge comes out pale on a timer; the policies that look at the oven, the colour and the dough keep inside the band. Hover for each cookie's dough and verdict.</p>
        </section>

        <section className="db-card wide"><h3>The oven through a shift</h3>
          <div className="db-chips" style={{ marginBottom: 8 }}>
            {[1, 2, 4, 9].map((x) => <button key={x} className={span === x ? "on" : ""} onClick={() => setSpan(x)}>{x === 9 ? "whole shift" : `${x} h`}</button>)}
          </div>
          <Plot h={250} xTitle="time in the shift" yTitle="°C" xMin={0} xMax={sh[sh.length - 1]?.t ?? 3600} xFmt={(v) => `${(v / 3600).toFixed(1)} h`} yMin={0}
            series={[
              { name: "chamber air", x: sh.map((p) => p.t), y: sh.map((p) => p.air), color: "#f2a33a", width: 1.6, fmt: c1 },
              { name: "cookie centre", x: sh.map((p) => p.t), y: sh.map((p) => p.core), color: "#4f8fd6", width: 1.8, fmt: c1 },
              { name: "cookie surface", x: sh.map((p) => p.t), y: sh.map((p) => p.surface), color: "#e0503a", width: 1.4, fmt: c1 }]}
            hlines={[{ y: 180, color: "var(--ok)", label: "180 °C" }]}
            tipTitle={(x) => `${(x / 3600).toFixed(2)} h`}
            tipExtra={(x) => { const p = sh.find((q) => q.t >= x); return p ? [["door", p.door ? "open" : "shut"], ["heater duty", `${Math.round(p.duty * 100)} %`]] : []; }} />
          <p className="hl-cap">The {best.name} policy. Every door opening drops the air, and the oven recovers before the next bake ends. The PLC's own model of the oven learnt the elements' output as {Math.round(d.shift.power_learnt * 100)} % (they were at {Math.round(d.shift.power * 100)} %) from the thermocouple alone.</p>
        </section>

        <section className="db-card"><h3>What a real bake does to capacity</h3>
          <div className="cx-table"><table>
            <thead><tr><th>bake</th><th>12-cookie order</th><th>cookies an hour</th></tr></thead>
            <tbody>{d.throughput.rows.map((r) => <tr key={r.case}><td>{r.case}</td><td>{(r.order_s / 60).toFixed(1)} min</td><td>{r.cookies_h}</td></tr>)}</tbody>
          </table></div>
          <p className="hl-cap">The oven holds one cookie for {Math.round(d.throughput.oven_cycle_s)} s: the bake plus {Math.round(d.throughput.oven_handling_s)} s of door, slider and handover. The rest of the cell needs {d.throughput.rest_s_per_cookie} s a cookie, so it could feed {d.throughput.ovens_to_match} such ovens. A real line bakes many at once in a tunnel oven: the STF-2 redesign.</p>
        </section>

        <section className="db-card"><h3>Where the heat goes</h3>
          <HBar xTitle="kWh in one shift" fmt={(v) => v.toFixed(3)}
            rows={ledger.sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: LEDGER[k], v, color: k === "steam" ? "#4fb3d6" : k === "mouth" ? "#f2a33a" : "#8b95a3",
              tip: `${LEDGER[k]}: ${v.toFixed(3)} kWh` }))} />
          <p className="hl-cap">About {d.energy.oven_month_kwh} kWh a month on two shifts{d.energy.cell_month_kwh ? `, ${(d.energy.oven_month_kwh / d.energy.cell_month_kwh).toFixed(1)} times the rest of the cell's ${d.energy.cell_month_kwh} kWh` : ""}. The cell's microgrid was sized for the 5 W lamp, and its 600 W inverter cannot run these elements.</p>
        </section>

        <section className="db-card wide"><h3>Checks</h3>
          <p className={d.checks.fails.length ? "cx-note bad" : "hl-cap"}>{d.checks.fails.length ? d.checks.fails.join("; ") : "Every check passes: the energy ledger closes on every shift, the heat-up matches the oven's design, the numerics converge and are stable, the physics goes the right way, and each policy is at least as good as the one before."}</p>
          <ul className="ai-verdict">{d.checks.mutations.map((m) => <li key={m.name}><b>{m.caught ? "Caught" : "MISSED"}</b>: {m.name}</li>)}</ul>
          <details className="pr-params"><summary>The {d.params.length} parameters, and where each comes from</summary>
            <div className="cx-table"><table>
              <thead><tr><th>name</th><th>value</th><th>unit</th><th>source</th></tr></thead>
              <tbody>{d.params.map((p) => <tr key={p.key}><td><code>{p.key}</code></td><td>{Array.isArray(p.value) ? p.value.join(", ") : typeof p.value === "number" ? +p.value.toPrecision(4) : p.value}</td><td>{p.unit}</td><td>{p.source}</td></tr>)}</tbody>
            </table></div>
          </details>
          <p className="hl-cap">Assumed: {d.assumed}. The full model and its equations: Docs, “The bake as a process”.</p>
        </section>
      </div>
    </>
  );
}
