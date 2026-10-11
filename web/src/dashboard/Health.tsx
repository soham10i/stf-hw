// The Health page: each wearing part's health index at the chosen machine age, how it got
// there, and the signal behind the selected part (Upgrade 6, health.py). The theory and a
// live run of the model are on the docs page (Degradation.tsx).
import { useMemo, useState } from "react";
import type { HealthDoc } from "../shared/model";
import { compAt, maxShifts, STATUS_TXT, type CompNow } from "../shared/health";
import { Heat, niceTicks, Plot, useWidth } from "./Plot";

export const PART_COL = ["#4f8fd6", "#e0a02a", "#22b07d", "#c06bd6", "#e0503a", "#3fb8c9", "#8f9d3a", "#d66b9a", "#7a7fe0", "#b07a4a"];
const STAT_COL = { ok: "var(--ok)", warn: "var(--warn)", fail: "var(--bad)" };
const short = (s: string) => s.replace(/ \(.*\)$/, "");
const sh = (x: number) => (x >= 100 ? x.toFixed(0) : x.toFixed(1));

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className={`db-kpi ${tone ?? ""}`}><span>{label}</span><b>{value}</b>{sub && <em>{sub}</em>}</div>;
}

/** Each part's remaining life from now: healthy until its warning (green), warned until it
    fails (amber). Sorted by what needs attention first. */
function Runway({ st, sel, pick, horizon }: { st: CompNow[]; sel: string; pick: (id: string) => void; horizon: number }) {
  const rows = st.map((s) => {
    const warnIn = s.status === "ok" && s.c.warn !== null ? (s.c.warn - s.n) / s.c.per_shift : 0;
    return { s, warnIn, failIn: s.status === "fail" ? 0 : s.rulShifts ?? Infinity };
  }).sort((a, b) => a.warnIn - b.warnIn || a.failIn - b.failIn);
  const [box, W] = useWidth<HTMLDivElement>();
  const L = W < 560 ? 160 : 200, R = W < 560 ? 12 : 170, T = 4, RH = 26, B = 40, h = T + rows.length * RH + B;
  const X = (x: number) => L + (Math.min(x, horizon) / horizon) * (W - L - R);
  return (
    <div className="pl"><div className="pl-box" ref={box}><svg viewBox={`0 0 ${W} ${h}`}>
      {niceTicks(0, horizon, W < 560 ? 3 : 6).map((v) => <g key={v}><line x1={X(v)} x2={X(v)} y1={T} y2={T + rows.length * RH} className="pl-grid" />
        <text x={X(v)} y={T + rows.length * RH + 15} textAnchor="middle" className="pl-tick">{v}</text></g>)}
      <text x={(L + W - R) / 2} y={h - 6} textAnchor="middle" className="pl-title">shifts from now (8 h each)</text>
      {rows.map(({ s, warnIn, failIn }, i) => {
        const y = T + i * RH, on = s.c.id === sel, over = failIn > horizon;
        return (
          <g key={s.c.id} onClick={() => pick(s.c.id)} style={{ cursor: "pointer" }}>
            <rect x={0} y={y} width={W} height={RH} className={`rw-hit ${on ? "on" : ""}`} />
            <text x={10} y={y + RH / 2 + 4} className={`pl-row ${on ? "on" : ""}`}>{short(s.c.name)}</text>
            {W >= 560 && <text x={L - 10} y={y + RH / 2 + 4} textAnchor="end" className="rw-hi" style={{ fill: STAT_COL[s.status] }}>HI {Math.round(s.hi)}</text>}
            {s.status === "fail" ? <text x={L + 6} y={y + RH / 2 + 4} className="pl-lab" style={{ fill: "var(--bad)" }}>FAILED: replace now</text> : <>
              {warnIn > 0 && <rect x={X(0)} y={y + 6} width={Math.max(1, X(warnIn) - X(0))} height={RH - 12} rx={3} className="rw-ok" />}
              {warnIn < horizon && <rect x={X(warnIn)} y={y + 6} width={Math.max(2, X(failIn) - X(warnIn))} height={RH - 12} rx={3} className="rw-warn" />}
              {!over && <path d={`M${X(failIn)},${y + 4}l0,${RH - 8}`} className="rw-fail" />}
              {over && <text x={X(horizon) + 3} y={y + RH / 2 + 4} className="rw-arrow">›</text>}
            </>}
            {R > 100 && <text x={W - R + 14} y={y + RH / 2 + 4} className="rw-say">
              {s.status === "fail" ? "" : s.status === "warn" ? `warned · fails in ${sh(failIn)}` : `warns ${sh(warnIn)} · fails ${sh(failIn)}`}
            </text>}
            <title>{`${s.c.name}: ${s.status === "fail" ? "failed" : s.status === "warn" ? `warned, fails in ${sh(failIn)} shifts` : `warns in ${sh(warnIn)} shifts, fails in ${sh(failIn)}`}`}</title>
          </g>
        );
      })}
    </svg></div>
    <div className="pl-legend static"><span><i className="rw-ok" />healthy until its warning</span><span><i className="rw-warn" />warned: the window to service it</span>
      <span><i className="rw-fail" />failure</span><span>› beyond the chart</span></div>
    </div>
  );
}

/** The selected part's signal over its life, with its limits, warning and the machine's "now". */
function Signal({ s, col }: { s: CompNow; col: string }) {
  const c = s.c, ps = c.per_shift;
  const xs = c.curve.map((p) => p[0] / ps);
  const last = c.curve.filter((p) => p[0] <= s.n).length - 1;
  const at = (x: number) => { let k = 0; while (k < c.curve.length - 1 && c.curve[k + 1][0] / ps <= x) k++; return c.curve[k]; };
  return (
    <Plot h={270} xTitle="part age (shifts since new or renewed)" yTitle="signal r = measured ÷ healthy"
      xFmt={(v) => `${Math.round(v)}`} yFmt={(v) => v.toFixed(2)} yMin={0.9} yMax={c.r_fail * 1.08}
      series={[
        { name: "smoothed signal (EWMA)", x: xs, y: c.curve.map((p, i) => (i <= last ? p[1] : null)), color: col, width: 2.6 },
        { name: "expected from here", x: xs, y: c.curve.map((p, i) => (i >= last ? p[1] : null)), color: col, dash: true, width: 1.6 },
      ]}
      bands={[{ y0: 0.9, y1: c.soft, color: "var(--ok)", label: "healthy" }, { y0: c.soft, y1: c.r_fail, color: "var(--warn)", label: "warned" },
              { y0: c.r_fail, y1: c.r_fail * 1.08, color: "var(--bad)", label: "failed" }]}
      hlines={[{ y: c.soft, color: "var(--warn)", label: "soft limit" }, { y: c.r_fail, color: "var(--bad)", label: "failure limit" }]}
      vmarks={[...(c.warn !== null ? [{ x: c.warn / ps, color: "var(--warn)", label: `warning · ${c.lead_shifts} sh before failure` }] : []),
               ...(c.fail !== null ? [{ x: c.fail / ps, color: "var(--bad)", label: "failure" }] : [])]}
      now={{ x: s.n / ps, label: "now" }}
      tipTitle={(x) => `${x.toFixed(1)} shifts old`}
      tipExtra={(x) => {
        const p = at(x);
        return [["health index", `${Math.round(p[2])}`],
                ["to failure", c.fail === null ? "–" : `${sh(Math.max(0, c.fail / ps - x))} sh`],
                ["trend estimate", p[3] === null ? "–" : `${sh(p[3] / ps)} sh`]];
      }}
    />
  );
}

export function HealthPage({ h, age, pm, go }: { h: HealthDoc; age: number; pm: boolean; go: (p: string) => void }) {
  const [sel, setSel] = useState(h.components[0].id);
  const [horizon, setHorizon] = useState(90);
  const ageMax = useMemo(() => maxShifts(h.components), [h]);
  const st = h.components.map((c) => compAt(c, age, pm));
  const i = h.components.findIndex((c) => c.id === sel), s = st[i];
  const n = { ok: st.filter((x) => x.status === "ok").length, warn: st.filter((x) => x.status === "warn").length, fail: st.filter((x) => x.status === "fail").length };
  const fleet = st.reduce((a, x) => a + x.hi, 0) / st.length;
  const alive = st.filter((x) => x.status !== "fail" && x.rulShifts !== null).sort((a, b) => a.rulShifts! - b.rulShifts!);
  const heat = useMemo(() => h.components.map((c) => ({ id: c.id, label: short(c.name),
    v: Array.from({ length: 150 }, (_, k) => compAt(c, ((k + 0.5) / 150) * ageMax, pm).hi) })), [h, ageMax, pm]);
  const nextWarn = st.filter((x) => x.status === "ok" && x.c.warn !== null)
    .map((x) => ({ x, in: (x.c.warn! - x.n) / x.c.per_shift })).sort((a, b) => a.in - b.in)[0];
  return (
    <div className="db-grid">
      <div className="db-kpis wide">
        <Kpi label="fleet health" value={`${Math.round(fleet)}`} sub="mean health index, 100 = new" tone={n.fail ? "fail" : n.warn ? "warn" : "ok"} />
        <Kpi label="parts" value={`${n.ok} / ${n.warn} / ${n.fail}`} sub="healthy / service due / failed" tone={n.fail ? "fail" : n.warn ? "warn" : "ok"} />
        <Kpi label="next warning" value={nextWarn ? `${sh(nextWarn.in)} sh` : "–"} sub={nextWarn?.x.c.name ?? "all parts warned"} />
        <Kpi label="first failure" value={alive[0] ? `${sh(alive[0].rulShifts!)} sh` : "–"} sub={alive[0] ? alive[0].c.name : "none"} tone={alive[0] && alive[0].rulShifts! < 3 ? "warn" : undefined} />
      </div>

      <section className="db-card hl-span2">
        <h3>Remaining life runway
          <div className="ui-seg db-mini-seg">{[30, 90, 450].map((v) => <button key={v} className={horizon === v ? "on" : ""} onClick={() => setHorizon(v)}>{v === 450 ? "all" : `${v} sh`}</button>)}</div></h3>
        <Runway st={st} sel={sel} pick={setSel} horizon={horizon} />
      </section>

      <section className="db-card">
        <h3>Not predictable</h3>
        <ul className="hl-list">{h.detect_only.map((d) => (
          <li key={d.mode} title={d.why}><b>{d.mode}</b><span>{d.cover}</span></li>
        ))}</ul>
        <p className="hl-cap">No gradual precursor: caught when it happens (watchdog) or by a routine check.</p>
      </section>

      <section className="db-card wide">
        <h3>Health map · every part over the machine's life</h3>
        <Heat rows={heat} x0={0} x1={ageMax} xTitle="machine age (shifts)" now={age} sel={sel} pick={setSel}
          tip={(_, x, v) => `${Math.round(x)} shifts: health ${Math.round(v)}${v <= 0 ? " — failed" : v < 50 ? " — warned" : ""}`} />
        <div className="pl-scale">health 0 <i /> 100 · {pm ? "PM on: each part is renewed when it warns (the stripes)" : "PM off: parts run to failure (red)"} · white line = now</div>
      </section>

      <section className="db-card hl-span2">
        <h3>{s.c.name}<span className={`hl-pill ${s.status}`}>{STATUS_TXT[s.status]}</span>
          <button className="db-link" onClick={() => go("docs-degradation")}>how it's computed →</button></h3>
        <Signal s={s} col={PART_COL[i]} />
      </section>

      <section className="db-card">
        <h3>About this part</h3>
        <div className="hl-facts col">
          <div><b>{s.c.lead_shifts ?? "–"} shifts</b><span>warning comes before failure</span></div>
          <div><b>{s.c.false_warnings} in {(s.c.healthy_cycles / 1000).toFixed(0)}k uses</b><span>false warnings on a healthy part</span></div>
          <div><b>{Math.round(s.n).toLocaleString()} uses</b><span>this life{s.serviced ? ` · renewed ×${s.serviced}` : ""}</span></div>
          <div><b className="wrap">{s.c.metric}</b><span className="mono">{s.c.source.join(" ")}</span></div>
        </div>
      </section>
    </div>
  );
}
