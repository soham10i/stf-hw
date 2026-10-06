// The STF operations dashboard: a page of its own, separate from the 3D twin.
// It reads the newest upgrade export (up7, else up6) - the PLC's run (U4), the
// commissioning results (U5), the condition-monitoring model (U6) and the
// lifecycle checks (U7). Nothing here is typed in.
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useCadDoc, type CadDoc, type HealthComp } from "../shared/model";
import { JOB_COL, JOB_SAY, fmtT, makespan, unitsAt } from "../shared/hmi";
import { STATUS_TXT, compAt, maxShifts } from "../shared/health";
import { HealthGrid } from "../shared/HealthGrid";
import { Curve } from "../shared/Curve";
import { MonthPage } from "./Month";
import { AiPage } from "./Ai";
import { GridPage } from "./Grid";
import { ThroughputPage } from "./Throughput";
import { SecurityPage } from "./Security";
import { HardeningPage, ValidationPage } from "./Assurance";
import { VisionPage } from "./Vision";
import { Icon, ThemeToggle } from "../shared/icons";
import { useTheme } from "../shared/theme";
import { GUIDE, TERMS, cardHelp } from "./guide";

const BASE = import.meta.env.BASE_URL;
const PAGES = [
  ["overview", "Overview", "home", "Operate"], ["production", "Production", "factory", "Operate"],
  ["quality", "Quality & trace", "check", "Operate"], ["vision", "Vision QC", "eye", "Operate"], ["alarms", "Alarms", "bell", "Operate"],
  ["health", "Health", "heart", "Maintain"], ["maintenance", "Maintenance", "wrench", "Maintain"],
  ["ai", "AI maintenance", "brain", "Maintain"],
  ["month", "Month", "calendar", "Analyse"], ["throughput", "Throughput", "gauge", "Analyse"],
  ["energy", "Energy & grid", "bolt", "Analyse"], ["security", "OT security", "shield", "Analyse"],
  ["hardening", "Defence in depth", "layers", "Analyse"],
  ["engineering", "Engineering", "cog", "Engineer"], ["validation", "Validation", "check", "Engineer"], ["data", "Data", "database", "Engineer"],
] as const;
const CLOCK_PAGES = ["overview", "production", "quality"];
const AGE_PAGES = ["overview", "health", "maintenance"];
type Page = (typeof PAGES)[number][0];

function useDoc() {
  const { doc, err } = useCadDoc();
  return { doc: doc && doc.control && doc.vc && doc.health ? doc : null, src: "up12", err };
}

// --------------------------------------------------------------- shared
function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className={`db-kpi ${tone ?? ""}`}><span>{label}</span><b>{value}</b>{sub && <em>{sub}</em>}</div>;
}
const PageCtx = createContext("overview");
function Card({ title, children, wide, extra }: { title: string; children: React.ReactNode; wide?: boolean; extra?: React.ReactNode }) {
  const help = cardHelp(useContext(PageCtx), title);
  return (
    <section className={`db-card ${wide ? "wide" : ""}`}>
      <h3>{title}{help && <i className="db-help" title={help} aria-label={help}>i</i>}{extra}</h3>
      {children}
    </section>
  );
}

/** The page's guide: what it is for, how to read it, its sections and the terms it uses. */
function GuideBox({ page, onClose }: { page: string; onClose: () => void }) {
  const g = GUIDE[page];
  if (!g) return null;
  const terms = g.terms.filter((k) => TERMS[k]).map((k) => [k, TERMS[k]] as const);
  return (
    <aside className="db-guide" aria-label="Guide to this page">
      <div className="db-guide-h"><b>Guide · {g.title}</b><button className="ui-btn ghost" onClick={onClose}>Hide</button></div>
      <p className="db-guide-what">{g.what}</p>
      <div className="db-guide-cols">
        <div><h4>How to read it</h4><ol>{g.read.map((r) => <li key={r}>{r}</li>)}</ol></div>
        <div><h4>On this page</h4><dl>{g.sections.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></div>
      </div>
      {terms.length > 0 && (
        <details className="db-guide-terms"><summary>Terms used here · {terms.length}</summary>
          <dl>{terms.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl></details>
      )}
      <p className="db-guide-src">Data: {g.source}</p>
    </aside>
  );
}
function HBars({ rows, max, unit, hl }: { rows: [string, number, string?][]; max: number; unit: string; hl?: string }) {
  return (
    <div className="db-bars">
      {rows.map(([k, v, col]) => (
        <div key={k} className={k === hl ? "hl" : ""}><span>{k}</span>
          <i style={{ width: `${Math.max(0.5, (v / (max || 1)) * 100)}%`, background: col }} /><b>{Math.round(v * 10) / 10} {unit}</b></div>
      ))}
    </div>
  );
}

function Gantt({ doc, t }: { doc: CadDoc; t: number }) {
  const c = doc.control!;
  const bars = c.policies[c.policy].bars ?? [];
  const T = makespan(c);
  const units = Object.keys(c.units);
  const W = 1000, L = 80, RH = 20;
  const X = (s: number) => L + (s / T) * (W - L - 8);
  return (
    <svg viewBox={`0 0 ${W} ${units.length * RH + 22}`} className="db-gantt">
      {units.map((u, i) => <text key={u} x={4} y={i * RH + 14} className="db-gt">{u}</text>)}
      {bars.map((b, k) => b.units.map((u) => (
        <rect key={`${k}${u}`} x={X(b.t0)} y={units.indexOf(u) * RH + 3} width={Math.max(0.8, X(b.t1) - X(b.t0) - 0.3)} height={RH - 6}
          style={{ fill: JOB_COL[b.job], opacity: u === b.units[0] ? 1 : 0.35 }}><title>{b.job} {b.bind.join(" ")} {b.t0}–{b.t1} s</title></rect>
      )))}
      <line x1={X(t)} x2={X(t)} y1={0} y2={units.length * RH} className="db-now" />
      {[0, 0.25, 0.5, 0.75, 1].map((f) => <text key={f} x={X(f * T)} y={units.length * RH + 16} className="db-gt" textAnchor="middle">{fmtT(f * T)}</text>)}
    </svg>
  );
}

// ---------------------------------------------------------------- pages
function Overview({ doc, t, age, pm, go }: { doc: CadDoc; t: number; age: number; pm: boolean; go: (p: Page) => void }) {
  const c = doc.control!, vc = doc.vc!, h = doc.health!, p = vc.performance;
  const prod = c.trace.filter((r) => r.kind === "production");
  const done = prod.filter((r) => (r.t.sorted ?? Infinity) <= t).length;
  const st = h.components.map((x) => compAt(x, age, pm));
  const n = { ok: st.filter((s) => s.status === "ok").length, warn: st.filter((s) => s.status === "warn").length, fail: st.filter((s) => s.status === "fail").length };
  const worst = st.reduce((a, b) => (b.hi < a.hi ? b : a));
  const next = [...st].sort((a, b) => (a.rulShifts ?? 1e9) - (b.rulShifts ?? 1e9)).slice(0, 5);
  const now = unitsAt(c, t);
  return (
    <>
      <div className="db-kpis">
        <Kpi label="order progress" value={`${done}/${prod.length}`} sub={`${fmtT(t)} of ${fmtT(makespan(c))}`} />
        <Kpi label="throughput" value={`${((prod.length / p.makespan) * 3600).toFixed(1)}`} sub="cookies per hour" />
        <Kpi label="OEE" value={`${Math.round(p.oee * 100)} %`} sub={`A ${Math.round(p.availability * 100)} · P ${Math.round(p.performance * 100)} · Q ${Math.round(p.quality * 100)}`} />
        <Kpi label="running units" value={`${now.filter((u) => u.state === "RUN").length}/${now.length}`} sub={`bottleneck: ${p.bottleneck}`} />
        <Kpi label="component health" value={`${n.ok} ok`} sub={`${n.warn} service due · ${n.fail} failed`} tone={n.fail ? "fail" : n.warn ? "warn" : "ok"} />
        <Kpi label="worst component" value={`${Math.round(worst.hi)}`} sub={worst.c.name} tone={worst.status} />
      </div>
      <div className="db-grid">
        <Card title="Production timeline" wide extra={<button className="db-link" onClick={() => go("production")}>details →</button>}>
          <Gantt doc={doc} t={t} />
        </Card>
        <Card title="Units now">
          <table className="db-table"><tbody>
            {now.map((u) => <tr key={u.unit}><td><span className={`hmi-led ${u.state.toLowerCase()}`} />{u.unit}</td>
              <td>{u.job ? <span style={{ color: JOB_COL[u.job] }}>{u.job}</span> : <span className="db-muted">ready</span>}</td></tr>)}
          </tbody></table>
        </Card>
        <Card title="Next maintenance" extra={<button className="db-link" onClick={() => go("maintenance")}>planner →</button>}>
          <table className="db-table"><tbody>
            {next.map((s) => <tr key={s.c.id} className={s.status}><td>{s.c.name}</td>
              <td className="num">{s.status === "fail" ? "failed" : `${(s.rulShifts ?? 0).toFixed(1)} sh left`}</td></tr>)}
          </tbody></table>
        </Card>
        <Card title="Downtime by cause (U5 fault matrix)" extra={<button className="db-link" onClick={() => go("alarms")}>alarms →</button>}>
          <HBars rows={[...vc.matrix].sort((a, b) => b.lost_s - a.lost_s).map((r) => [`${r.id} ${r.fault}`, r.lost_s, "#e0503a"])}
            max={Math.max(...vc.matrix.map((r) => r.lost_s))} unit="s" />
        </Card>
        <Card title="Unit utilisation">
          <HBars rows={Object.entries(p.busy).map(([u, b]) => [u, (b / p.makespan) * 100])} max={100} unit="%" hl={p.bottleneck} />
        </Card>
      </div>
    </>
  );
}

function Production({ doc, t }: { doc: CadDoc; t: number }) {
  const c = doc.control!, vc = doc.vc!;
  const now = unitsAt(c, t);
  const prod = c.trace.filter((r) => r.kind === "production");
  const flav = ["chocolate", "vanilla", "strawberry"];
  const ret = c.trace.filter((r) => r.kind === "return");
  return (
    <div className="db-grid">
      <Card title="Gantt: the 12-cookie order, PLC policy" wide><Gantt doc={doc} t={t} />
        <div className="db-legend">{Object.entries(JOB_COL).map(([j, col]) => <span key={j}><i style={{ background: col }} />{JOB_SAY[j]}</span>)}</div>
      </Card>
      <Card title="Units and their current step">
        <table className="db-table"><tbody>
          {now.map((u) => <tr key={u.unit}><td><span className={`hmi-led ${u.state.toLowerCase()}`} />{u.unit}<div className="db-muted">{u.label}</div></td>
            <td>{u.job ? <><span style={{ color: JOB_COL[u.job] }}>{u.job}</span><div className="db-muted">{u.step}</div></> : <span className="db-muted">ready</span>}</td></tr>)}
        </tbody></table>
      </Card>
      <Card title="Order by flavour">
        <table className="db-table"><tbody>
          {flav.map((f) => {
            const all = prod.filter((r) => r.flavour === f);
            const d = all.filter((r) => (r.t.sorted ?? Infinity) <= t).length;
            return <tr key={f}><td>{f}</td><td><div className="db-prog"><i style={{ width: `${(d / all.length) * 100}%` }} /></div></td><td className="num">{d}/{all.length}</td></tr>;
          })}
          <tr><td>returned to rack</td><td /><td className="num">{ret.filter((r) => (r.t.stored ?? Infinity) <= t).length}/{ret.length}</td></tr>
        </tbody></table>
      </Card>
      <Card title="Dispatch policies (measured)">
        <table className="db-table"><tbody>
          {Object.entries(c.policies).map(([k, p]) => <tr key={k} className={k === c.policy ? "on" : ""}><td>{k}<div className="db-muted">{p.say}</div></td>
            <td className="num">{p.deadlock ? <span className="db-bad">deadlock</span> : `${p.makespan} s`}</td></tr>)}
        </tbody></table>
        <p className="db-note">Commissioned against the twin: {vc.performance.makespan} s (model {vc.performance.model} s).</p>
      </Card>
    </div>
  );
}

function Health({ doc, age, pm }: { doc: CadDoc; age: number; pm: boolean }) {
  const h = doc.health!;
  const [sel, setSel] = useState<HealthComp>(h.components[0]);
  const s = compAt(sel, age, pm);
  return (
    <div className="db-grid">
      <Card title="Component health" wide><HealthGrid cs={h.components} shifts={age} maintained={pm} />
        <div className="db-chips">{h.components.map((c) => <button key={c.id} className={c.id === sel.id ? "on" : ""} onClick={() => setSel(c)}>{c.name}</button>)}</div>
      </Card>
      <Card title={sel.name}>
        <Curve c={sel} />
        <table className="db-table"><tbody>
          <tr><td>signal</td><td>{sel.metric}</td></tr>
          <tr><td>sources</td><td className="mono">{sel.source.join(" ")}</td></tr>
          <tr><td>state</td><td className={s.status}>{STATUS_TXT[s.status]} · HI {Math.round(s.hi)}</td></tr>
          <tr><td>fails at</td><td>r = {sel.r_fail} (warn at {sel.soft})</td></tr>
          <tr><td>warned</td><td>{sel.lead_shifts} shifts before failure ({sel.warn_by})</td></tr>
          <tr><td>false warnings</td><td>{sel.false_warnings} in {sel.healthy_cycles.toLocaleString()} healthy cycles</td></tr>
        </tbody></table>
      </Card>
      <Card title="Detect-only failure modes">
        <table className="db-table"><tbody>{h.detect_only.map((d) => <tr key={d.mode}><td>{d.mode}<div className="db-muted">{d.why}</div></td><td>{d.cover}</td></tr>)}</tbody></table>
      </Card>
    </div>
  );
}

function Maintenance({ doc, age, pm }: { doc: CadDoc; age: number; pm: boolean }) {
  const h = doc.health!, lc = doc.lifecycle;
  const rows = h.components.map((x) => {
    const s = compAt(x, age, pm);
    const due = (x.pm_interval - s.n) / x.per_shift;
    return { x, s, due: s.status !== "ok" ? 0 : Math.max(0, Math.min(due, s.rulShifts ?? Infinity)),
             why: s.status === "fail" ? "FAILED - replace" : s.status === "warn" ? `predictive: ${x.warn_by}` : due <= 0 ? "preventive interval reached" : "preventive interval" };
  }).sort((a, b) => a.due - b.due);
  const door = Object.fromEntries((lc?.access ?? []).map((a) => [a.part, a.door]));
  return (
    <div className="db-grid">
      <Card title="Work orders" wide>
        <table className="db-table">
          <thead><tr><td>component</td><td>why</td><td>door</td><td>services so far</td><td className="num">due</td></tr></thead>
          <tbody>{rows.map(({ x, s, due, why }) => (
            <tr key={x.id} className={s.status}><td>{x.name}</td><td>{why}</td><td>{door[x.part] ?? "–"}</td><td>{s.serviced}</td>
              <td className="num">{s.status === "ok" ? `in ${due.toFixed(1)} shifts` : "now"}</td></tr>
          ))}</tbody>
        </table>
      </Card>
      {lc && (
        <Card title="Spare parts (U7)" wide>
          <table className="db-table">
            <thead><tr><td>item</td><td>in the cell</td><td>per year</td><td>stock</td></tr></thead>
            <tbody>{lc.spares.map((s) => <tr key={s.item} className={s.wear ? "on" : ""}><td>{s.item}<div className="db-muted">{s.what}</div></td>
              <td className="num">{s.qty}</td><td className="num">{s.per_year ?? "–"}</td><td className="num">{s.stock}</td></tr>)}</tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function Quality({ doc, t }: { doc: CadDoc; t: number }) {
  const c = doc.control!;
  const [q, setQ] = useState("");
  const rows = c.trace.filter((r) => !q || [r.id, r.mould, r.flavour, r.slot_from, r.slot_to, r.bin].some((v) => v && String(v).toLowerCase().includes(q.toLowerCase())));
  const made = c.trace.filter((r) => r.kind === "production");
  const ok = made.filter((r) => r.verified).length;
  return (
    <div className="db-grid">
      <div className="db-kpis wide">
        <Kpi label="made" value={`${made.length}`} />
        <Kpi label="A4-verified" value={`${ok}/${made.length}`} tone={ok === made.length ? "ok" : "fail"} />
        <Kpi label="read points" value={Object.keys(c.read_points).join(" · ")} sub="RFID under the HBW belt" />
      </div>
      <Card title="Records" wide extra={<input className="db-search" placeholder="search cookie, mould, flavour, slot, bin…" value={q} onChange={(e) => setQ(e.target.value)} />}>
        <table className="db-table">
          <thead><tr><td>id</td><td>flavour</td><td>mould</td><td>from → to</td><td>reads</td><td>bake</td><td>A4</td><td className="num">state now</td></tr></thead>
          <tbody>{rows.map((r) => {
            const now = r.kind === "return" ? ((r.t.stored ?? Infinity) <= t ? `in ${r.slot_to}` : "bay") :
              (r.t.sorted ?? Infinity) <= t ? `bin ${r.bin}` : (r.t.bake_start ?? Infinity) <= t ? "in process" : (r.t.retrieved ?? Infinity) <= t ? "on the belt" : `rack ${r.slot_from}`;
            return (
              <tr key={r.id}><td>{r.id}</td><td>{r.flavour}</td><td className="mono">{r.mould}</td><td>{r.slot_from ?? "bay"} → {r.bin ?? r.slot_to}</td>
                <td className="mono">{r.reads.map(([rp, , tt]) => `${rp}@${tt}`).join(" ")}</td>
                <td className="mono">{r.t.bake_start !== undefined ? `${r.t.bake_start}–${r.t.bake_end}` : "–"}</td>
                <td>{r.colour_mV !== undefined ? `${r.colour_mV} mV ${r.verified ? "✓" : "✗"}` : "–"}</td><td className="num">{now}</td></tr>
            );
          })}</tbody>
        </table>
      </Card>
    </div>
  );
}

function Alarms({ doc }: { doc: CadDoc }) {
  const c = doc.control!, vc = doc.vc!;
  const [f, setF] = useState("");
  const al = c.alarms.filter((a) => !f || (a.code + a.text + a.unit).toLowerCase().includes(f.toLowerCase()));
  const mttr = vc.matrix.reduce((s, r) => s + r.lost_s, 0) / vc.matrix.length;
  return (
    <div className="db-grid">
      <div className="db-kpis wide">
        <Kpi label="alarms defined" value={`${c.alarms.length}`} />
        <Kpi label="fault matrix" value={`${vc.matrix.filter((r) => r.pass).length}/${vc.matrix.length}`} sub="pass (U5)" tone="ok" />
        <Kpi label="MTTR" value={`${mttr.toFixed(0)} s`} sub="mean time lost per fault" />
        <Kpi label="fastest detection" value={`${Math.min(...vc.matrix.map((r) => r.latency_s ?? 99))} s`} />
      </div>
      <Card title="Fault matrix (commissioned)" wide>
        <table className="db-table">
          <thead><tr><td>fault</td><td>alarm</td><td className="num">detected</td><td>reaction</td><td>recovery</td><td className="num">lost</td></tr></thead>
          <tbody>{vc.matrix.map((r) => <tr key={r.id}><td>{r.id} {r.fault}<div className="db-muted">{r.what}</div></td><td className="mono">{r.observed.join(" ")}</td>
            <td className="num">{r.latency_s} s</td><td>{r.reaction}</td><td>{r.recovery}</td><td className="num">{r.lost_s} s</td></tr>)}</tbody>
        </table>
      </Card>
      <Card title="Alarm list" wide extra={<input className="db-search" placeholder="filter…" value={f} onChange={(e) => setF(e.target.value)} />}>
        <table className="db-table">
          <thead><tr><td>code</td><td>alarm</td><td>cause</td><td>recovery</td></tr></thead>
          <tbody>{al.map((a) => <tr key={a.code}><td className="mono">{a.code}</td><td>{a.text}</td><td>{a.cause}</td><td>{a.recovery}</td></tr>)}</tbody>
        </table>
      </Card>
    </div>
  );
}

function Engineering({ doc }: { doc: CadDoc }) {
  const vc = doc.vc!, lc = doc.lifecycle;
  return (
    <div className="db-grid">
      <Card title="Positioning accuracy (U5)">
        <table className="db-table"><thead><tr><td>axis</td><td>task</td><td className="num">error</td><td className="num">allowed</td></tr></thead>
          <tbody>{vc.accuracy.map((a) => <tr key={a.axis}><td>{a.axis}</td><td>{a.scan_ms} ms</td><td className="num">± {a.error_mm} mm</td><td className="num">± {a.tol_mm} mm</td></tr>)}</tbody></table>
      </Card>
      {lc && (
        <>
          <Card title="Tolerance chains, worst case (U7)">
            <table className="db-table"><thead><tr><td>chain</td><td className="num">nominal</td><td className="num">worst</td><td className="num">before U7</td></tr></thead>
              <tbody>{lc.chains.map((ch) => {
                const b = lc.chains_before?.find((x) => x.id === ch.id);
                return <tr key={ch.id}><td>{ch.id} {ch.what}</td><td className="num">{ch.nominal}</td><td className={`num ${ch.ok ? "ok" : "fail"}`}>{ch.worst}</td>
                  <td className={`num ${b && b.worst < 0 ? "fail" : ""}`}>{b?.worst ?? "–"}</td></tr>;
              })}</tbody></table>
          </Card>
          <Card title="Structure dynamics (U7)">
            <table className="db-table"><thead><tr><td>member</td><td className="num">δ</td><td className="num">f₁</td></tr></thead>
              <tbody>{lc.structure.map((s) => <tr key={s.member}><td>{s.member}<div className="db-muted">{s.section}</div></td>
                <td className="num">{s.defl_mm} mm</td><td className="num">{s.f1_hz} Hz</td></tr>)}</tbody></table>
          </Card>
          <Card title="Service access (U7)">
            <HBars rows={lc.access.map((a) => [`${a.part} (${a.door})`, a.reach_mm, a.in_reach ? "#4f8fd6" : "#e0503a"])} max={lc.rules.reach_mm} unit="mm" />
          </Card>
        </>
      )}
    </div>
  );
}

function Data({ doc, src }: { doc: CadDoc; src: string }) {
  const h = doc.health!, vc = doc.vc!;
  return (
    <div className="db-grid">
      <Card title="Topics (PLC → MQTT → historian → this page)" wide>
        <table className="db-table"><thead><tr><td>topic</td><td>rate</td><td>fields</td><td>from</td></tr></thead>
          <tbody>{h.topics.map((t) => <tr key={t.topic}><td className="mono">{t.topic}</td><td>{t.rate}</td><td>{t.fields}</td><td className="mono">{t.sources.join(" ")}</td></tr>)}</tbody></table>
        <p className="db-note">{h.new_hardware}. This page currently reads the twin's export ({src}); pointed at the broker, the same views read the live topics.</p>
      </Card>
      <Card title="Register map (U5)" wide>
        <table className="db-table"><thead><tr><td>tag</td><td>node</td><td>table</td><td className="num">address</td><td>meaning</td></tr></thead>
          <tbody>{vc.map.map((r) => <tr key={r.tag}><td className="mono">{r.tag}</td><td className="mono">{r.node}</td><td>{r.table}</td><td className="num">{r.addr}</td><td>{r.desc}</td></tr>)}</tbody></table>
      </Card>
    </div>
  );
}

// ----------------------------------------------------------------- shell
export function Dashboard() {
  const { doc, src, err } = useDoc();
  const [page, setPage] = useState<Page>(() => (new URLSearchParams(location.search).get("p") as Page) || "overview");
  const [t, setT] = useState(0);
  const [play, setPlay] = useState(true);
  const [age, setAge] = useState(0);
  const [pm, setPm] = useState(true);
  const [theme, toggleTheme] = useTheme();
  // the guide is open on the first visit and remembered after that
  const [guide, setGuide] = useState(() => { try { return localStorage.getItem("stf.db.guide") !== "0"; } catch { return true; } });
  const showGuide = (v: boolean) => { setGuide(v); try { localStorage.setItem("stf.db.guide", v ? "1" : "0"); } catch { /* private mode */ } };
  const [navOpen, setNavOpen] = useState(() => window.innerWidth > 900);
  const T = doc?.control ? makespan(doc.control) : 1;
  useEffect(() => {
    if (!play || !doc) return;
    const id = window.setInterval(() => setT((x) => (x + 2 >= T ? 0 : x + 2)), 100);
    return () => window.clearInterval(id);
  }, [play, T, doc]);
  useEffect(() => { history.replaceState(null, "", `?p=${page}`); }, [page]);
  // the pages that build their own sections (Month, AI, Energy, Throughput, Security, Assurance)
  // get the same i-hint on each section title as Card gives, as their data loads
  useEffect(() => {
    const root = document.querySelector(".db-main");
    if (!root) return;
    const hint = () => {
      root.querySelectorAll<HTMLElement>(".db-card > h3").forEach((h) => {
        if (h.querySelector(".db-help")) return;
        const help = cardHelp(page, h.textContent ?? "");
        if (!help) return;
        const i = document.createElement("i");
        i.className = "db-help"; i.title = help; i.setAttribute("aria-label", help); i.textContent = "i";
        h.appendChild(i);
      });
    };
    hint();
    const mo = new MutationObserver(hint);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [page, doc]);
  const ageMax = useMemo(() => (doc?.health ? maxShifts(doc.health.components) : 1), [doc]);
  if (err) return <div className="db-err">{err}</div>;
  if (!doc) return <div className="db-err">loading the twin's export…</div>;
  const cur = PAGES.find((p) => p[0] === page)!;
  const groups = Array.from(new Set(PAGES.map((p) => p[3])));
  // long notes and findings open on click instead of filling the page
  const expand = (e: React.MouseEvent) => {
    const el = (e.target as HTMLElement).closest(".db-note, .mo-insights > div");
    if (el) el.classList.toggle("open");
  };
  return (
    <div className={`db ${navOpen ? "" : "nav-min"}`}>
      <nav className="db-nav">
        <div className="db-brand">
          <span className="brand-mark">STF</span><div><b>Operations</b><span>{src} · live twin data</span></div>
        </div>
        {groups.map((g) => (
          <div key={g} className="db-group">
            <div className="db-group-h">{g}</div>
            {PAGES.filter((p) => p[3] === g).map(([id, label, icon]) => (
              <button key={id} className={id === page ? "on" : ""} onClick={() => setPage(id)} title={label}>
                <Icon name={icon} size={17} /><span>{label}</span>
              </button>
            ))}
          </div>
        ))}
        <div className="db-nav-foot">
          <a className="db-twin" href={BASE} title="Open the 3D twin"><Icon name="cube" size={17} /><span>3D twin</span><Icon name="external" size={13} /></a>
          <div className="db-src" title={doc.fingerprint}>{doc.fingerprint}</div>
        </div>
      </nav>
      <main className="db-main" onClick={expand}>
        <div className="db-top">
          <button className="ui-btn icon ghost" onClick={() => setNavOpen(!navOpen)} aria-label="Toggle navigation"><Icon name="menu" size={18} /></button>
          <div className="db-title"><span>{cur[3]}</span><h1>{cur[1]}</h1></div>
          {CLOCK_PAGES.includes(page) && (
            <div className="db-ctl">
              <button className="ui-btn icon" onClick={() => setPlay(!play)} aria-label={play ? "Pause" : "Play"}><Icon name={play ? "pause" : "play"} size={14} /></button>
              <input type="range" min={0} max={T} step={0.5} value={t} onChange={(e) => { setPlay(false); setT(+e.target.value); }} aria-label="Order time" />
              <span className="mono">{fmtT(t)}</span>
            </div>
          )}
          {AGE_PAGES.includes(page) && (
            <div className="db-ctl">
              <span>Machine age</span>
              <input type="range" min={0} max={ageMax} step={1} value={age} onChange={(e) => setAge(+e.target.value)} aria-label="Machine age" />
              <span className="mono">{age} sh</span>
              <div className="ui-seg"><button className={pm ? "on" : ""} onClick={() => setPm(true)}>PM on</button><button className={!pm ? "on" : ""} onClick={() => setPm(false)}>off</button></div>
            </div>
          )}
          <button className={`ui-btn db-guide-btn ${guide ? "on" : ""}`} onClick={() => showGuide(!guide)} aria-pressed={guide}
            title="What this page shows and how to read it"><Icon name="info" size={15} /> Guide</button>
          <ThemeToggle theme={theme} toggle={toggleTheme} />
        </div>
        {guide && <GuideBox page={page} onClose={() => showGuide(false)} />}
        <PageCtx.Provider value={page}>
        <div className="db-page" key={page}>
          {page === "month" && <MonthPage />}
          {page === "vision" && <VisionPage />}
          {page === "ai" && <AiPage />}
          {page === "energy" && <GridPage />}
          {page === "throughput" && <ThroughputPage />}
          {page === "security" && <SecurityPage />}
          {page === "hardening" && <HardeningPage />}
          {page === "validation" && <ValidationPage />}
          {page === "overview" && <Overview doc={doc} t={t} age={age} pm={pm} go={setPage} />}
          {page === "production" && <Production doc={doc} t={t} />}
          {page === "health" && <Health doc={doc} age={age} pm={pm} />}
          {page === "maintenance" && <Maintenance doc={doc} age={age} pm={pm} />}
          {page === "quality" && <Quality doc={doc} t={t} />}
          {page === "alarms" && <Alarms doc={doc} />}
          {page === "engineering" && <Engineering doc={doc} />}
          {page === "data" && <Data doc={doc} src={src} />}
        </div>
        </PageCtx.Provider>
        <p className="db-foot">Simulated from the twin's models; values marked assumed are listed on the blueprint sheets. Click any note to expand it.</p>
      </main>
    </div>
  );
}
