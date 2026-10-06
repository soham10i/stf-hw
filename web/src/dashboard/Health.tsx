// The Health page: each wearing part's health index at the chosen machine age, how it got
// there, and the signal behind the selected part (Upgrade 6, health.py). The theory and a
// live run of the model are on the docs page (Degradation.tsx).
import { useMemo, useState } from "react";
import type { HealthDoc } from "../shared/model";
import { compAt, maxShifts, STATUS_TXT, type CompNow } from "../shared/health";

export const PART_COL = ["#4f8fd6", "#e0a02a", "#22b07d", "#c06bd6", "#e0503a", "#3fb8c9", "#8f9d3a", "#d66b9a", "#7a7fe0", "#b07a4a"];
const STAT_COL = { ok: "var(--ok)", warn: "var(--warn)", fail: "var(--bad)" };
const sh = (x: number) => (x >= 100 ? x.toFixed(0) : x.toFixed(1));

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className={`db-kpi ${tone ?? ""}`}><span>{label}</span><b>{value}</b>{sub && <em>{sub}</em>}</div>;
}

/** Health index of every part now, worst first. */
function HiBars({ st, sel, pick }: { st: CompNow[]; sel: string; pick: (id: string) => void }) {
  const rows = [...st].sort((a, b) => a.hi - b.hi);
  return (
    <div className="hl-bars">
      {rows.map((s) => (
        <button key={s.c.id} className={`hl-bar ${s.c.id === sel ? "on" : ""}`} onClick={() => pick(s.c.id)} title={s.c.metric}>
          <span className="hl-name">{s.c.name.replace(/ \(.*\)$/, "")}</span>
          <span className="hl-track"><i style={{ width: `${Math.max(1, s.hi)}%`, background: STAT_COL[s.status] }} /></span>
          <b>{Math.round(s.hi)}</b>
          <em className={s.status}>{s.status === "fail" ? "failed" : s.rulShifts === null ? "–" : `${sh(s.rulShifts)} sh`}</em>
        </button>
      ))}
    </div>
  );
}

/** Health index over machine age for every part; the selected one drawn bold. */
function HiOverAge({ h, age, ageMax, pm, sel, pick }: { h: HealthDoc; age: number; ageMax: number; pm: boolean; sel: string; pick: (id: string) => void }) {
  const W = 900, H = 210, L = 34, R = 12, T = 10, B = 24, N = 260;
  const X = (a: number) => L + (a / ageMax) * (W - L - R);
  const Y = (hi: number) => T + (1 - hi / 100) * (H - T - B);
  const paths = useMemo(() => h.components.map((c) => {
    let d = "";
    for (let i = 0; i <= N; i++) { const a = (i / N) * ageMax; d += `${i ? "L" : "M"}${X(a).toFixed(1)},${Y(compAt(c, a, pm).hi).toFixed(1)}`; }
    return d;
  }), [h, ageMax, pm]);   // eslint-disable-line react-hooks/exhaustive-deps
  const ticks = Array.from({ length: 6 }, (_, i) => (i / 5) * ageMax);
  return (
    <div className="mo-chart">
      <svg viewBox={`0 0 ${W} ${H}`}>
        <rect x={L} y={Y(100)} width={W - L - R} height={Y(50) - Y(100)} className="hl-zone ok" />
        <rect x={L} y={Y(50)} width={W - L - R} height={Y(0) - Y(50)} className="hl-zone warn" />
        {[0, 50, 100].map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="mo-grid" />
          <text x={L - 5} y={Y(v) + 3} textAnchor="end" className="mo-ax">{v}</text></g>)}
        {ticks.map((a) => <text key={a} x={X(a)} y={H - 7} textAnchor="middle" className="mo-ax">{a.toFixed(0)} sh</text>)}
        {h.components.map((c, i) => c.id !== sel && (
          <path key={c.id} d={paths[i]} fill="none" stroke={PART_COL[i]} strokeWidth={1} opacity={0.16} className="hl-line" onClick={() => pick(c.id)}><title>{c.name}</title></path>
        ))}
        {h.components.map((c, i) => c.id === sel && <path key={c.id} d={paths[i]} fill="none" stroke={PART_COL[i]} strokeWidth={2.6} />)}
        <line x1={X(age)} x2={X(age)} y1={T} y2={H - B} className="hl-now" />
        <text x={X(age) + 4} y={T + 9} className="mo-ax hl-now-t">now</text>
      </svg>
      <div className="mo-legend">{h.components.map((c, i) => (
        <span key={c.id} className={`hl-leg ${c.id === sel ? "on" : ""}`} onClick={() => pick(c.id)}><i style={{ background: PART_COL[i] }} />{c.name.replace(/ \(.*\)$/, "")}</span>
      ))}</div>
    </div>
  );
}

/** The selected part's smoothed signal over its life: healthy, warned and failed zones. */
function Signal({ s, col }: { s: CompNow; col: string }) {
  const c = s.c, W = 600, H = 230, L = 40, R = 12, T = 12, B = 24;
  const nmax = c.curve[c.curve.length - 1][0] || 1, top = c.r_fail * 1.06;
  const X = (n: number) => L + (n / nmax) * (W - L - R);
  const Y = (r: number) => T + (1 - (r - 1) / (top - 1)) * (H - T - B);
  const past = c.curve.filter((p) => p[0] <= s.n), last = past[past.length - 1];
  const future = c.curve.filter((p) => p[0] >= (last?.[0] ?? 0));
  const d = (pts: typeof c.curve) => pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(Math.min(p[1], top)).toFixed(1)}`).join("");
  return (
    <div className="mo-chart">
      <svg viewBox={`0 0 ${W} ${H}`}>
        <rect x={L} y={Y(c.soft)} width={W - L - R} height={Y(1) - Y(c.soft)} className="hl-zone ok" />
        <rect x={L} y={Y(c.r_fail)} width={W - L - R} height={Y(c.soft) - Y(c.r_fail)} className="hl-zone warn" />
        <rect x={L} y={Y(top)} width={W - L - R} height={Y(c.r_fail) - Y(top)} className="hl-zone fail" />
        <text x={W - R - 4} y={Y(c.soft) - 4} textAnchor="end" className="mo-ax">soft limit {c.soft}</text>
        <text x={W - R - 4} y={Y(c.r_fail) - 4} textAnchor="end" className="mo-ax">fails {c.r_fail}</text>
        <text x={L - 5} y={Y(1) + 3} textAnchor="end" className="mo-ax">1.0</text>
        <text x={L - 5} y={Y(c.r_fail) + 3} textAnchor="end" className="mo-ax">{c.r_fail.toFixed(1)}</text>
        {c.warn !== null && <g><line x1={X(c.warn)} x2={X(c.warn)} y1={T} y2={H - B} className="hl-mark warn" />
          <text x={X(c.warn) - 4} y={H - B - 6} textAnchor="end" className="mo-ax hl-warn-t">warned</text></g>}
        <path d={d(future)} fill="none" stroke={col} strokeWidth={1.6} strokeDasharray="4 4" opacity={0.45} />
        <path d={d(past)} fill="none" stroke={col} strokeWidth={2.4} />
        {last && <circle cx={X(last[0])} cy={Y(Math.min(last[1], top))} r={5} fill={col} className="hl-dot" />}
        <text x={L} y={H - 7} className="mo-ax">0</text>
        <text x={W - R} y={H - 7} textAnchor="end" className="mo-ax">{nmax.toLocaleString()} uses</text>
      </svg>
    </div>
  );
}

export function HealthPage({ h, age, pm, go }: { h: HealthDoc; age: number; pm: boolean; go: (p: string) => void }) {
  const [sel, setSel] = useState(h.components[0].id);
  const ageMax = useMemo(() => maxShifts(h.components), [h]);
  const st = h.components.map((c) => compAt(c, age, pm));
  const i = h.components.findIndex((c) => c.id === sel), s = st[i];
  const n = { ok: st.filter((x) => x.status === "ok").length, warn: st.filter((x) => x.status === "warn").length, fail: st.filter((x) => x.status === "fail").length };
  const fleet = st.reduce((a, x) => a + x.hi, 0) / st.length;
  const alive = st.filter((x) => x.status !== "fail" && x.rulShifts !== null).sort((a, b) => a.rulShifts! - b.rulShifts!);
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

      <section className="db-card">
        <h3>Health index now</h3>
        <HiBars st={st} sel={sel} pick={setSel} />
        <p className="hl-cap">Worst first · shifts until failure on the right · click a part</p>
      </section>

      <section className="db-card hl-span2">
        <h3>Health over machine age</h3>
        <HiOverAge h={h} age={age} ageMax={ageMax} pm={pm} sel={sel} pick={setSel} />
        <p className="hl-cap">{pm ? "PM on: each part is renewed when it warns, so health saw-tooths and never reaches 0." : "PM off: parts run to failure."}</p>
      </section>

      <section className="db-card hl-span2">
        <h3>{s.c.name}<span className={`hl-pill ${s.status}`}>{STATUS_TXT[s.status]}</span>
          <button className="db-link" onClick={() => go("docs-degradation")}>how it's computed →</button></h3>
        <Signal s={s} col={PART_COL[i]} />
        <div className="hl-facts">
          <div><b>{s.c.lead_shifts ?? "–"} sh</b><span>warning before failure</span></div>
          <div><b>{s.c.false_warnings} / {(s.c.healthy_cycles / 1000).toFixed(0)}k</b><span>false warnings, healthy run</span></div>
          <div><b>{Math.round(s.n).toLocaleString()}</b><span>uses this life{s.serviced ? ` · renewed ×${s.serviced}` : ""}</span></div>
          <div><b className="mono">{s.c.source.join(" ")}</b><span>{s.c.metric}</span></div>
        </div>
      </section>

      <section className="db-card">
        <h3>Not predictable</h3>
        <ul className="hl-list">{h.detect_only.map((d) => (
          <li key={d.mode} title={d.why}><b>{d.mode}</b><span>{d.cover}</span></li>
        ))}</ul>
        <p className="hl-cap">No gradual precursor: caught when it happens (watchdog) or by a routine check.</p>
      </section>
    </div>
  );
}
