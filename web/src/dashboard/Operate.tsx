// The Operate pages built from the twin's export: Overview, Production, Quality & trace, Alarms -
// and the PLC Gantt chart they share.
import { useState } from "react";
import { motion } from "motion/react";
import { type CadDoc, type TraceRec } from "../shared/model";
import { JOB_COL, JOB_SAY, fmtT, makespan, unitsAt } from "../shared/hmi";
import { compAt } from "../shared/health";
















import { HBar } from "./Plot";
import { Kpi, Card, HBars } from "./ui";
type Page = string;

export function Gantt({ doc, t }: { doc: CadDoc; t: number }) {
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


export function Overview({ doc, t, age, pm, go }: { doc: CadDoc; t: number; age: number; pm: boolean; go: (p: Page) => void }) {
  const c = doc.control!, vc = doc.vc!, h = doc.health!, p = vc.performance;
  const prod = c.trace.filter((r) => r.kind === "production");
  const done = prod.filter((r) => (r.t.sorted ?? Infinity) <= t).length;
  const st = h.components.map((x) => compAt(x, age, pm));
  const fleet = st.reduce((a, x) => a + x.hi, 0) / st.length;
  const warned = st.filter((s) => s.status !== "ok").length;
  const worst = st.reduce((a, b) => (b.hi < a.hi ? b : a));
  const next = [...st].sort((a, b) => (a.rulShifts ?? 1e9) - (b.rulShifts ?? 1e9)).slice(0, 5);
  const now = unitsAt(c, t);
  const oee = [["Availability", p.availability], ["Performance", p.performance], ["Quality", p.quality]] as const;
  const loss = [...oee].sort((x, y) => x[1] - y[1])[0];
  const jobs = Array.from(new Set((c.policies[c.policy].bars ?? []).map((b) => b.job)));
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi"><span>order progress</span><b>{done}/{prod.length}</b>
          <div className="db-prog ov-prog"><i style={{ width: `${(done / prod.length) * 100}%` }} /></div><em>{fmtT(t)} of {fmtT(makespan(c))}</em></div>
        <Kpi label="throughput" value={`${((prod.length / p.makespan) * 3600).toFixed(1)}`} sub="cookies per hour" />
        <Kpi label="OEE" value={`${Math.round(p.oee * 100)} %`} sub={`biggest loss: ${loss[0].toLowerCase()}`} />
        <Kpi label="running units" value={`${now.filter((u) => u.state === "RUN").length}/${now.length}`} sub={`bottleneck: ${p.bottleneck}`} />
        <Kpi label="fleet health" value={`${Math.round(fleet)}`} sub={warned ? `${warned} part${warned > 1 ? "s" : ""} need service` : `worst: ${worst.c.name.replace(/ \(.*\)$/, "")}`}
          tone={st.some((s) => s.status === "fail") ? "fail" : warned ? "warn" : "ok"} />
      </div>
      <div className="db-grid">
        <Card title="Production timeline" wide extra={<button className="db-link" onClick={() => go("production")}>details →</button>}>
          <Gantt doc={doc} t={t} />
          <div className="db-legend">{jobs.map((j) => <span key={j} title={JOB_SAY[j]}><i style={{ background: JOB_COL[j] }} />{j.replace(/_/g, " ")}</span>)}</div>
        </Card>
        <Card title="Units now">
          <div className="ov-units">{now.map((u) => (
            <div key={u.unit} className={`ov-unit ${u.state.toLowerCase()}`} title={u.job ? JOB_SAY[u.job] : "ready"}>
              <span className={`hmi-led ${u.state.toLowerCase()}`} /><b>{u.unit}</b>
              <em style={u.job ? { color: JOB_COL[u.job] } : undefined}>{u.job ? u.job.replace(/_/g, " ") : "ready"}</em>
            </div>))}</div>
        </Card>
        <Card title="OEE breakdown">
          <div className="ov-oee">
            {oee.map(([k, v]) => <div key={k} className={k === loss[0] ? "loss" : ""}><span>{k}</span><i><b style={{ width: `${v * 100}%` }} /></i><em>{Math.round(v * 100)} %</em></div>)}
            <div className="tot"><span>OEE = A × P × Q</span><i><b style={{ width: `${p.oee * 100}%` }} /></i><em>{Math.round(p.oee * 100)} %</em></div>
          </div>
        </Card>
        <Card title="Next maintenance" extra={<button className="db-link" onClick={() => go("maintenance")}>planner →</button>}>
          <div className="hl-bars">{next.map((s) => (
            <button key={s.c.id} className="hl-bar" onClick={() => go("health")} title={s.c.name}>
              <span className="hl-name">{s.c.name.replace(/ \(.*\)$/, "")}</span>
              <span className="hl-track"><i style={{ width: `${Math.max(1, s.hi)}%`, background: s.status === "ok" ? "var(--ok)" : s.status === "warn" ? "var(--warn)" : "var(--bad)" }} /></span>
              <b>{Math.round(s.hi)}</b><em className={s.status}>{s.status === "fail" ? "failed" : `${(s.rulShifts ?? 0).toFixed(0)} sh`}</em>
            </button>))}</div>
        </Card>
        <section className="db-card hl-span2">
          <h3>Downtime by fault<button className="db-link" onClick={() => go("alarms")}>alarms →</button></h3>
          <HBars rows={[...vc.matrix].sort((a, b) => b.lost_s - a.lost_s).map((r) => [`${r.id} ${r.fault}`, r.lost_s, "#e0503a"])}
            max={Math.max(...vc.matrix.map((r) => r.lost_s))} unit="s" />
        </section>
        <Card title="Unit utilisation">
          <HBars rows={Object.entries(p.busy).sort((a, b) => b[1] - a[1]).map(([u, b]) => [u, (b / p.makespan) * 100])} max={100} unit="%" hl={p.bottleneck} />
        </Card>
      </div>
    </>
  );
}

export function Production({ doc, t }: { doc: CadDoc; t: number }) {
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
        {/* one lane per unit: its job as a bar in the job's colour, filled to now; what it does on hover */}
        <div className="pr-units">{now.map((u) => {
          const b = u.bar, frac = b ? Math.min(1, Math.max(0, (t - b.t0) / Math.max(0.1, b.t1 - b.t0))) : 0;
          const col = u.job ? JOB_COL[u.job] : undefined;
          return (
            <div key={u.unit} className={`pr-unit ${u.state.toLowerCase()}`} title={`${u.unit}: ${u.label}${u.job ? `\n${JOB_SAY[u.job]}` : ""}`}>
              <span className={`hmi-led ${u.state.toLowerCase()}`} />
              <b>{u.unit}</b>
              <span className="pr-track">{b && <i style={{ width: `${frac * 100}%`, background: col }} />}</span>
              <em>{b ? `${fmtT(Math.max(0, b.t1 - t))}` : ""}</em>
              <small>{u.job ? <><span style={{ color: col }}>{u.job.replace(/_/g, " ")}</span>{u.step ? ` · ${u.step}` : ""}</> : "ready"}</small>
            </div>
          );
        })}</div>
      </Card>
      <Card title="Order by flavour">
        {/* every cookie of the order, in its flavour: filled once sorted */}
        <div className="pr-flav">
          {flav.map((f) => {
            const all = prod.filter((r) => r.flavour === f);
            const done = all.filter((r) => (r.t.sorted ?? Infinity) <= t).length;
            const col = doc.pipeline.flavours[f]?.colour ?? "#999";
            return (
              <div key={f}>
                <span className="pr-flav-name">{f}</span>
                <span className="pr-dots">{all.map((r, i) => <i key={r.id} className={i < done ? "on" : ""} style={{ ["--c" as string]: col }} title={`${r.id}: ${i < done ? "sorted" : "on its way"}`} />)}</span>
                <b>{done}/{all.length}</b>
              </div>
            );
          })}
          {(() => {
            const back = ret.filter((r) => (r.t.stored ?? Infinity) <= t).length;
            return (
              <div className="pr-flav-ret">
                <span className="pr-flav-name">moulds back in the rack</span>
                <span className="pr-dots">{ret.map((r, i) => <i key={r.id} className={i < back ? "on" : ""} style={{ ["--c" as string]: "var(--muted)" }} />)}</span>
                <b>{back}/{ret.length}</b>
              </div>
            );
          })()}
        </div>
      </Card>
      <Card title="Dispatch policies (measured)">
        <HBar xTitle="order time (s) · hover for the rule" fmt={(v) => `${Math.round(v)}`}
          rows={Object.entries(c.policies).map(([k, p]) => ({ label: p.deadlock ? `${k} — DEADLOCK` : k, v: p.deadlock ? 0 : p.makespan ?? 0, on: k === c.policy,
            color: p.deadlock ? "var(--bad)" : k === c.policy ? "var(--ok)" : "#4f8fd6", tip: `${k}: ${p.say}` }))} />
        <p className="hl-cap">The PLC runs <b>{c.policy}</b>. Commissioned against the twin: {vc.performance.makespan} s (model {vc.performance.model} s).</p>
      </Card>
    </div>
  );
}

const FLAV_DOT: Record<string, string> = { vanilla: "#f2efe6", strawberry: "#f4a6bf", chocolate: "#b0773f" };
const CLASS_DOT: Record<string, string> = { weiss: "#f2efe6", rot: "#c8233c", blau: "#3b2112" };

// one journey step: done (green), now (lit), or still ahead (faint)
type Step = { label: string; done: boolean; now: boolean };
function journey(r: TraceRec, t: number): { steps: Step[]; label: string; tone: "ok" | "live" | "wait" } {
  if (r.kind === "return") {
    const home = (r.t.stored ?? Infinity) <= t;
    return {
      steps: [{ label: "bay", done: true, now: !home }, { label: r.slot_to ?? "rack", done: home, now: home }],
      label: home ? `in ${r.slot_to}` : "bay", tone: home ? "ok" : "wait",
    };
  }
  const sorted = (r.t.sorted ?? Infinity) <= t;
  const oven = !sorted && (r.t.bake_start ?? Infinity) <= t;
  const belt = !sorted && !oven && (r.t.retrieved ?? Infinity) <= t;
  return {
    steps: [
      { label: r.slot_from ?? "rack", done: belt || oven || sorted, now: !belt && !oven && !sorted },
      { label: "belt", done: oven || sorted, now: belt },
      { label: "oven", done: sorted, now: oven },
      { label: r.bin ?? "bin", done: sorted, now: sorted },
    ],
    label: sorted ? `bin ${r.bin}` : oven ? "in process" : belt ? "on the belt" : `rack ${r.slot_from}`,
    tone: sorted ? "ok" : oven ? "live" : "wait",
  };
}

export function Quality({ doc, t }: { doc: CadDoc; t: number }) {
  const c = doc.control!;
  const [q, setQ] = useState("");
  const rows = c.trace.filter((r) => !q || [r.id, r.mould, r.flavour, r.slot_from, r.slot_to, r.bin].some((v) => v && String(v).toLowerCase().includes(q.toLowerCase())));
  const made = c.trace.filter((r) => r.kind === "production");
  const ok = made.filter((r) => r.verified).length;
  const rps = Object.keys(c.read_points);
  // the bake column is one shared time axis across the visible rows: bar position = when, bar
  // length = how long; the header says the axis' range
  const bakes = rows.filter((r) => r.t.bake_start !== undefined && r.t.bake_end !== undefined);
  const bt0 = bakes.length ? Math.min(...bakes.map((r) => r.t.bake_start)) : 0;
  const bt1 = bakes.length ? Math.max(...bakes.map((r) => r.t.bake_end)) : 0;
  const span = bt1 - bt0 || 1;
  return (
    <div className="db-grid">
      <div className="db-kpis wide">
        <Kpi label="made" value={`${made.length}`} />
        <Kpi label="A4-verified" value={`${ok}/${made.length}`} tone={ok === made.length ? "ok" : "fail"} />
        <Kpi label="read points" value={rps.join(" · ")} sub="RFID under the HBW belt" />
      </div>
      <Card title="Records" wide extra={<span className="rc-filter"><span className="rc-count">{rows.length} of {c.trace.length}</span>
        <input className="db-search" placeholder="search cookie, mould, flavour, slot, bin…" value={q} onChange={(e) => setQ(e.target.value)} /></span>}>
        <table className="db-table db-rec">
          <thead><tr><td>cookie</td><td>mould</td><td>route</td>
            <td>reads<span className="rc-th-sub"> · {rps.join(" · ")}</span></td>
            <td>bake{bakes.length > 0 && <span className="rc-th-sub"> · {bt0}–{bt1} s</span>}</td>
            <td className="num">A4<span className="rc-th-sub"> · mV</span></td><td>state</td></tr></thead>
          <tbody>{rows.map((r) => {
            const j = journey(r, t);
            return (
              <tr key={r.id}>
                <td className="rc-cookie"><b>{r.id}</b><i className="rc-sw" style={{ background: FLAV_DOT[r.flavour] ?? "var(--faint)" }} />{r.flavour}</td>
                <td className="mono">{r.mould}</td>
                <td className="rc-route">{r.slot_from ?? "bay"} <i>→</i> {r.bin ?? r.slot_to}</td>
                <td className="rc-reads">{rps.map((rp) => {
                  // read_points say RF1/RF2, the trace's reads say RP1/RP2: match on the digits
                  const hit = r.reads.find((x) => x[0].replace(/\D/g, "") === rp.replace(/\D/g, ""));
                  return (
                    <span key={rp} className={`rc-rp${hit ? "" : " off"}`} title={hit ? `${rp} — ${c.read_points[rp]}: mould ${hit[1]} at ${hit[2]} s` : `${rp} — ${c.read_points[rp]}: not read yet`}>
                      <b>{rp}</b>{hit ? <span className="mono">{hit[2]}s</span> : <span>–</span>}
                    </span>
                  );
                })}</td>
                <td className="rc-bake">{r.t.bake_start !== undefined ? (
                  <span className="rc-track" title={`bake ${r.t.bake_start}–${r.t.bake_end} s`}>
                    <span className="rc-bar" style={{ left: `${((r.t.bake_start - bt0) / span) * 100}%`,
                      width: `${Math.max(4, ((r.t.bake_end - r.t.bake_start) / span) * 100)}%` }} />
                  </span>
                ) : <span className="rc-dash">–</span>}{r.t.bake_end !== undefined && <span className="rc-bake-s mono">{+((r.t.bake_end - r.t.bake_start).toFixed(1))} s</span>}</td>
                <td className="num rc-a4">{r.colour_mV !== undefined ? (<>
                  <i className="rc-sw" style={{ background: CLASS_DOT[r.class ?? ""] ?? "var(--faint)" }} title={r.class} />
                  <span className="mono">{r.colour_mV}</span> mV
                  <span className={`rc-badge ${r.verified ? "ok" : "bad"}`} title={r.verified ? "colour matches the order" : "colour does not match the order"}>{r.verified ? "✓" : "✗"}</span>
                </>) : <span className="rc-dash">–</span>}</td>
                <td className="rc-state">
                  <span className="rc-journey" title={`${j.label} · t = ${t} s`}>
                    {j.steps.map((s, i) => (
                      <span key={i} style={{ display: "inline-flex", alignItems: "center" }}>
                        {i > 0 && <i className={`rc-link${s.done ? " on" : ""}`} />}
                        <i className={`rc-dot${s.done ? " done" : ""}${s.now ? " now" : ""}`} />
                      </span>
                    ))}
                  </span>
                  <span className={`rc-now ${j.tone}`}>{j.label}</span>
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && <tr><td colSpan={7} className="db-muted">No cookies match “{q}”.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

export function Alarms({ doc }: { doc: CadDoc }) {
  const c = doc.control!, vc = doc.vc!;
  const [f, setF] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const al = c.alarms.filter((a) => !f || (a.code + a.text + a.unit).toLowerCase().includes(f.toLowerCase()));
  const mttr = vc.matrix.reduce((s, r) => s + r.lost_s, 0) / vc.matrix.length;
  return (
    <div className="db-grid">
      <div className="db-kpis wide">
        <Kpi label="alarms defined" value={`${c.alarms.length}`} />
        <Kpi label="fault matrix" value={`${vc.matrix.filter((r) => r.pass).length}/${vc.matrix.length}`} sub="pass" tone="ok" />
        <Kpi label="MTTR" value={`${mttr.toFixed(0)} s`} sub="mean time lost per fault" />
        <Kpi label="fastest detection" value={`${Math.min(...vc.matrix.map((r) => r.latency_s ?? 99))} s`} />
      </div>
      <Card title="Detection time per fault">
        <HBar xTitle="seconds until the alarm" fmt={(v) => v < 1 ? v.toFixed(2) : v.toFixed(1)}
          rows={[...vc.matrix].sort((x, y) => (x.latency_s ?? 0) - (y.latency_s ?? 0)).map((r) => ({ label: `${r.id} ${r.fault}`, v: r.latency_s ?? 0, color: "#4f8fd6", tip: `${r.id} ${r.fault}: ${r.what}` }))} />
      </Card>
      <Card title="Time lost per fault">
        <HBar xTitle="seconds of production lost, once" fmt={(v) => `${Math.round(v)}`} refs={[{ v: mttr, label: "mean", color: "var(--muted)" }]}
          rows={[...vc.matrix].sort((x, y) => y.lost_s - x.lost_s).map((r) => ({ label: `${r.id} ${r.fault}`, v: r.lost_s, color: "#e0503a", tip: `${r.id}: ${r.reaction} → ${r.recovery}` }))} />
      </Card>
      <Card title="Fault matrix (commissioned)" wide>
        <table className="db-table">
          <thead><tr><td>fault</td><td>alarm</td><td className="num">detected</td><td>reaction</td><td>recovery</td><td className="num">lost</td></tr></thead>
          <tbody>{vc.matrix.map((r) => <tr key={r.id}><td>{r.id} {r.fault}<div className="db-muted">{r.what}</div></td><td className="mono">{r.observed.join(" ")}</td>
            <td className="num">{r.latency_s} s</td><td>{r.reaction}</td><td>{r.recovery}</td><td className="num">{r.lost_s} s</td></tr>)}</tbody>
        </table>
      </Card>
      <Card title="Alarm list" wide extra={<input className="db-search" placeholder="filter by code, text or unit…" value={f} onChange={(e) => setF(e.target.value)} />}>
        {/* one line per alarm; the cause and the recovery open where they are needed, in the row */}
        <div className="al-list">
          {al.map((a) => (
            <div key={a.code} className={`al-item ${open === a.code ? "open" : ""}`}>
              <button className="al-row" onClick={() => setOpen(open === a.code ? null : a.code)}
                aria-expanded={open === a.code} title={open === a.code ? "Close the details" : "Cause and recovery"}>
                <span className="al-code">{a.code}</span>
                <span className="al-text">{a.text}</span>
                <span className="ui-chip">{a.unit}</span>
                <i className="al-chev" aria-hidden="true">›</i>
              </button>
              {open === a.code && (
                <motion.div className="al-detail" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.18, ease: "easeOut" }}>
                  <div><b>Cause</b><p>{a.cause}</p></div>
                  <div><b>Recovery</b><p>{a.recovery}</p></div>
                </motion.div>
              )}
            </div>
          ))}
          {al.length === 0 && <p className="db-muted">No alarms match the filter.</p>}
        </div>
      </Card>
    </div>
  );
}
