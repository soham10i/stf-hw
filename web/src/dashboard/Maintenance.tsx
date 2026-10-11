// The Maintenance page: the service schedule the health model (U6) and the lifecycle plan
// (U7) create from the chosen machine age - when each part is next serviced and why, the
// workload per day, the work orders and the spare parts to stock.
import { useState } from "react";
import type { HealthDoc, LifecycleDoc } from "../shared/model";
import { compAt } from "../shared/health";
import { PART_COL } from "./Health";

const H = 90;                      // shifts ahead on the schedule (30 days of three shifts)
const KIND = {
  failed: { col: "var(--bad)", say: "failed: replace" },
  predictive: { col: "var(--warn)", say: "predictive: warned" },
  preventive: { col: "var(--accent)", say: "preventive interval" },
  visit: { col: "var(--faint)", say: "PM visit: switches, light barriers, chains" },
} as const;
type Kind = keyof typeof KIND;
const short = (s: string) => s.replace(/ \(.*\)$/, "");

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className={`db-kpi ${tone ?? ""}`}><span>{label}</span><b>{value}</b>{sub && <em>{sub}</em>}</div>;
}

type Row = { id: string; name: string; col: string; door: string; kind: Kind; due: number; every: number; events: number[]; fail: number | null };

function schedule(h: HealthDoc, lc: LifecycleDoc | undefined, age: number, pm: boolean): Row[] {
  const door = Object.fromEntries((lc?.access ?? []).map((a) => [a.part, a.door]));
  const rows: Row[] = h.components.map((c, i) => {
    const s = compAt(c, age, pm);
    const every = c.pm_shifts;
    const prev = (c.pm_interval - s.n) / c.per_shift;
    const kind: Kind = s.status === "fail" ? "failed" : s.status === "warn" ? "predictive" : "preventive";
    const due = kind === "preventive" ? Math.max(0, Math.min(prev, s.rulShifts ?? Infinity)) : 0;
    const events: number[] = [];
    if (pm) for (let t = due; t <= H; t += every) events.push(t);
    // PM off: nothing is serviced - the schedule shows where each part fails instead
    const fail = pm ? null : s.status === "fail" ? 0 : s.rulShifts !== null && s.rulShifts <= H ? s.rulShifts : null;
    return { id: c.id, name: short(c.name), col: PART_COL[i], door: door[c.part] ?? "–", kind, due, every, events, fail };
  });
  if (pm) rows.sort((a, b) => a.due - b.due);
  // the routine PM visit covers the detect-only modes (U7 plan: every 40 shifts)
  if (!pm) return rows.sort((a, b) => (a.fail ?? 1e9) - (b.fail ?? 1e9));
  const visit = lc?.plan.find((p) => p.trigger.startsWith("detect-only"))?.every_shifts ?? 40;
  const next = visit - (age % visit);
  const ev: number[] = [];
  for (let t = next; t <= H; t += visit) ev.push(t);
  rows.push({ id: "visit", name: "PM visit", col: "var(--faint)", door: "all", kind: "visit", due: next, every: visit, events: ev, fail: null });
  return rows;
}

/** One row per part along the next H shifts: a diamond for each service. */
function Timeline({ rows, pm, sel, pick }: { rows: Row[]; pm: boolean; sel: string | null; pick: (id: string) => void }) {
  const W = 900, L = 190, R = 14, RH = 22, T = 18;
  const X = (t: number) => L + (t / H) * (W - L - R);
  const Hh = T + rows.length * RH + 6;
  return (
    <div className="mo-chart">
      <div className="mt-scroll"><svg viewBox={`0 0 ${W} ${Hh}`}>
        {Array.from({ length: H / 15 + 1 }, (_, i) => i * 15).map((t) => (
          <g key={t}><line x1={X(t)} x2={X(t)} y1={T - 4} y2={Hh - 6} className="mo-grid" />
            <text x={X(t)} y={10} textAnchor="middle" className="mo-ax">{t === 0 ? "now" : `day ${t / 3}`}</text></g>))}
        {rows.map((r, i) => {
          const y = T + i * RH + RH / 2;
          return (
            <g key={r.id} className={`mt-row ${sel === r.id ? "on" : ""}`} onClick={() => pick(r.id)}>
              <rect x={0} y={y - RH / 2} width={W} height={RH} className="mt-hit" />
              <circle cx={8} cy={y} r={4} fill={r.col} />
              <text x={18} y={y + 4} className="mt-name">{r.name}</text>
              <text x={L - 8} y={y + 4} textAnchor="end" className="mo-ax">{r.door === "–" ? "" : `door ${r.door}`}</text>
              <line x1={X(0)} x2={X(H)} y1={y} y2={y} className="mt-lane" />
              {r.fail !== null && <g><line x1={X(r.fail) - 4} x2={X(r.fail) + 4} y1={y - 4} y2={y + 4} className="mt-x" />
                <line x1={X(r.fail) - 4} x2={X(r.fail) + 4} y1={y + 4} y2={y - 4} className="mt-x" /></g>}
              {r.events.map((t, k) => (
                <path key={k} d={`M${X(t)},${y - 6}l6,6l-6,6l-6,-6z`} fill={k === 0 ? KIND[r.kind].col : r.kind === "visit" ? KIND.visit.col : KIND.preventive.col}
                  opacity={k === 0 ? 1 : 0.45}><title>{r.name}: {t < 0.05 ? "now" : `in ${t.toFixed(1)} shifts`}</title></path>
              ))}
            </g>
          );
        })}
      </svg></div>
      <div className="mo-legend">
        {(pm ? (Object.keys(KIND) as Kind[]) : []).map((k) => <span key={k}><i className="mt-dia" style={{ background: KIND[k].col }} />{KIND[k].say}</span>)}
        {!pm && <span><b className="mt-xl">×</b>breakdown: the part fails</span>}
      </div>
    </div>
  );
}

/** Services per day over the schedule. */
function Workload({ rows }: { rows: Row[] }) {
  const days = H / 3, W = 900, Hh = 110, L = 30, R = 14, T = 8, B = 20;
  const n = Array.from({ length: days }, () => 0);
  rows.filter((r) => r.kind !== "visit").forEach((r) => [...r.events, ...(r.fail !== null ? [r.fail] : [])].forEach((t) => { const d = Math.min(days - 1, Math.floor(t / 3)); n[d]++; }));
  const max = Math.max(2, ...n), bw = (W - L - R) / days;
  return (
    <div className="mo-chart">
      <svg viewBox={`0 0 ${W} ${Hh}`}>
        {[0, max].map((v) => <g key={v}><line x1={L} x2={W - R} y1={T + (1 - v / max) * (Hh - T - B)} y2={T + (1 - v / max) * (Hh - T - B)} className="mo-grid" />
          <text x={L - 5} y={T + (1 - v / max) * (Hh - T - B) + 3} textAnchor="end" className="mo-ax">{v}</text></g>)}
        {n.map((v, d) => v > 0 && <rect key={d} x={L + d * bw + 2} y={T + (1 - v / max) * (Hh - T - B)} width={bw - 4} height={(v / max) * (Hh - T - B)}
          rx={3} className={v >= 3 ? "mt-bar hi" : "mt-bar"}><title>day {d + 1}: {v} service{v > 1 ? "s" : ""}</title></rect>)}
        {[0, 5, 10, 15, 20, 25].map((d) => <text key={d} x={L + d * bw + bw / 2} y={Hh - 5} textAnchor="middle" className="mo-ax">day {d + 1}</text>)}
      </svg>
    </div>
  );
}

function Spares({ lc }: { lc: LifecycleDoc }) {
  const wear = lc.spares.filter((s) => s.wear), other = lc.spares.filter((s) => !s.wear);
  const max = Math.max(...wear.map((s) => s.per_year ?? 0));
  return (
    <div className="mt-spares">
      <div>
        <h4>Wear parts · used per year vs in stock</h4>
        {wear.sort((a, b) => (b.per_year ?? 0) - (a.per_year ?? 0)).map((s) => (
          <div key={s.item} className="mt-sp" title={s.what}>
            <span>{short(s.item.replace(/^wear: /, ""))}</span>
            <span className="hl-track"><i style={{ width: `${((s.per_year ?? 0) / max) * 100}%` }} /></span>
            <b>{s.per_year?.toFixed(1)}/yr</b><em>stock {s.stock}</em>
          </div>
        ))}
      </div>
      <div>
        <h4>Breakdown spares · stock / in the cell</h4>
        <div className="mt-chips">{other.map((s) => <span key={s.item} title={s.what}><b>{s.stock}</b>{s.item}<em>of {s.qty}</em></span>)}</div>
      </div>
    </div>
  );
}

export function MaintenancePage({ h, lc, age, pm }: { h: HealthDoc; lc?: LifecycleDoc; age: number; pm: boolean }) {
  const [sel, setSel] = useState<string | null>(null);
  const rows = schedule(h, lc, age, pm);
  const parts = rows.filter((r) => r.kind !== "visit");
  const now = parts.filter((r) => r.due < 0.05);
  const soon = parts.filter((r) => r.due >= 0.05 && r.due <= 9);
  const next = parts.find((r) => r.due >= 0.05);
  const nextFail = parts.filter((r) => r.fail !== null && r.fail > 0).sort((a, b) => a.fail! - b.fail!)[0];
  const renewed = h.components.reduce((a, c) => a + compAt(c, age, pm).serviced, 0);
  const s = rows.find((r) => r.id === sel) ?? null;
  return (
    <div className="db-grid">
      <div className="db-kpis wide">
        <Kpi label="due now" value={`${now.length}`} sub={now.map((r) => r.name).join(", ") || "nothing"} tone={now.some((r) => r.kind === "failed") ? "fail" : now.length ? "warn" : "ok"} />
        <Kpi label="due in 3 days" value={`${soon.length}`} sub={soon.map((r) => r.name).join(", ") || "nothing"} />
        {pm ? <Kpi label="next service" value={next ? `${next.due.toFixed(1)} sh` : "–"} sub={next?.name} />
          : <Kpi label="next breakdown" value={nextFail ? `${nextFail.fail!.toFixed(1)} sh` : "–"} sub={nextFail?.name ?? "none in 30 days"} tone={nextFail ? "warn" : undefined} />}
        <Kpi label="renewed so far" value={`${renewed}`} sub={pm ? "parts, at this age" : "PM off: none"} />
      </div>

      <section className="db-card wide">
        <h3>{pm ? "Service schedule · next 30 days" : "Without PM · where parts fail in the next 30 days"}</h3>
        <Timeline rows={rows} pm={pm} sel={sel} pick={(id) => setSel(id === sel ? null : id)} />
        {s && <p className="mt-sel"><i style={{ background: s.col }} /><b>{s.name}</b> · {KIND[s.kind].say} · first {s.due < 0.05 ? "now" : `in ${s.due.toFixed(1)} shifts`}, then every {s.every.toFixed(0)} shifts{s.door !== "–" ? ` · through door ${s.door}` : ""}</p>}
      </section>

      <section className="db-card hl-span2">
        <h3>{pm ? "Workload · services per day" : "Breakdowns per day"}</h3>
        <Workload rows={rows} />
        <p className="hl-cap">{pm ? "Days with three or more services are highlighted: candidates to spread out." : "Every bar is an unplanned stop. Switch PM on to turn them into planned services."}</p>
      </section>

      <section className="db-card">
        <h3>Work orders</h3>
        <ul className="mt-wo">{parts.slice(0, 6).map((r) => (
          <li key={r.id}><i style={{ background: KIND[r.kind].col }} /><span>{r.name}<em>{KIND[r.kind].say}</em></span>
            <b className={r.due < 0.05 ? r.kind === "failed" ? "fail" : "warn" : ""}>{r.due < 0.05 ? "now" : `${r.due.toFixed(1)} sh`}</b></li>
        ))}</ul>
      </section>

      {lc && <section className="db-card wide"><h3>Spare parts (U7)</h3><Spares lc={lc} /></section>}
    </div>
  );
}
