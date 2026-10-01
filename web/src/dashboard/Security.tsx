// Upgrade 11: OT security to IEC 62443 (stf-cad/hbw/security.py) - zones and
// conduits, the Modbus allow-list generated from the PLC program, and six
// attacks replayed against the twin with and without the countermeasures.
import { useState } from "react";
import { useJson } from "../shared/data";

const BASE = import.meta.env.BASE_URL;

type Zone = { id: string; name: string; sl_t: number | null; assets: string[]; note: string; untrusted?: boolean };
type Conduit = { id: string; a: string; b: string; flow: string; proto: string; auth: string; dpi: string };
type Rule = { node: string; module: string; fc: number; fn: string; start: number; count: number };
type Attack = { id: string; name: string; zone: string; what: string; without: string; detect_only: string; with: string;
                residual: string; blocked: boolean;
                coverage?: { steps: number; detected: number; fast_factor: number; zero_legs: number; by_class: { class: string; steps: number; detected: number; blind: string[] }[] } };
type SlRow = { component: string; fr: string; sl_c: number; sl_t: number; gap: boolean; countermeasure: string };
type Doc = {
  meta: { plc_ip: string; node_ips: Record<string, string>; standards: string[]; assumed: string };
  zones: Zone[]; conduits: Conduit[]; denied_pairs: [string, string][]; paths_in: { path: string[]; via: string[] }[];
  allow_list: Rule[]; n_access: number; sunspec: { point: string; offset: number; ems_write: boolean }[]; exposed: { module: string; signal: string; addr: number; what: string; retired: boolean }[];
  hmi_tags: [string, string, string][];
  safety: { functions: { id: string; name: string; devices: string; PLr: string }[]; soft_links: { what: string; by: string; why: string; still: string }[] };
  sl: SlRow[]; attacks: Attack[]; findings: { title: string; text: string }[];
  manifest: { files: Record<string, string>; root: string };
  alarms: { code: string; text: string; reaction: string }[];
  proofs: Record<string, string>;
};

// zone diagram positions (a Purdue-style stack: outside at the top, safety at the bottom)
const POS: Record<string, [number, number]> = { Z5: [380, 30], Z4: [380, 120], Z2: [240, 215], Z3: [560, 215], Z1: [240, 310], Z0: [560, 330] };

function ZoneMap({ d, sel, setSel }: { d: Doc; sel: string | null; setSel: (s: string | null) => void }) {
  const W = 760, H = 380, bw = 200, bh = 54;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="db-gantt">
      {d.conduits.map((c) => {
        const [x1, y1] = POS[c.a], [x2, y2] = POS[c.b];
        if (c.a === c.b) return <text key={c.id} x={x1 - bw / 2 + 4} y={y1 + bh / 2 + 14} className="db-gt">{c.id}: PLC ↔ nodes (Modbus, DPI)</text>;
        const on = sel === c.id;
        return <g key={c.id} onMouseEnter={() => setSel(c.id)} onMouseLeave={() => setSel(null)} style={{ cursor: "default" }}>
          <line x1={x1} y1={y1} x2={x2} y2={y2} style={{ stroke: on ? "var(--warn)" : "var(--accent)" }} strokeWidth={on ? 3 : 1.8} />
          <text x={(x1 + x2) / 2 + 6} y={(y1 + y2) / 2 - 4} className="db-gt">{c.id}</text>
          <title>{`${c.id} ${c.flow}\n${c.proto}\n${c.auth}`}</title></g>;
      })}
      <line x1={POS.Z1[0] + bw / 2} y1={POS.Z1[1]} x2={POS.Z0[0] - bw / 2} y2={POS.Z0[1]} style={{ stroke: "var(--bad)" }} strokeDasharray="4 4" />
      <text x={(POS.Z1[0] + POS.Z0[0]) / 2 - 30} y={(POS.Z1[1] + POS.Z0[1]) / 2 + 16} className="db-gt" style={{ fill: "var(--bad)" }}>hardwired only</text>
      {d.zones.map((z) => {
        const [x, y] = POS[z.id];
        return <g key={z.id}>
          <rect x={x - bw / 2} y={y - bh / 2} width={bw} height={bh} rx={10} className={`sec-node ${z.id === "Z0" ? "safe" : z.untrusted ? "out" : ""}`} />
          <text x={x} y={y - 4} textAnchor="middle" className="sec-lbl">{z.id} {z.name}</text>
          <text x={x} y={y + 12} textAnchor="middle" className="db-gt">{z.sl_t ? `SL-T ${z.sl_t}` : z.untrusted ? "untrusted" : "no network"}</text>
          <title>{z.assets.join("\n")}</title></g>;
      })}
    </svg>
  );
}

export function SecurityPage() {
  const { data: d, error: err } = useJson<Doc>("security/security.json", "No security data. Run: STF_VARIANT=up11 python3 security.py");
  const [sel, setSel] = useState<string | null>(null);
  const [atk, setAtk] = useState("A1");
  const [mode, setMode] = useState<"without" | "detect_only" | "with">("with");
  if (err) return <div className="db-err">{err}</div>;
  if (!d) return <div className="db-err">loading the security model…</div>;
  const a = d.attacks.find((x) => x.id === atk)!;
  const gaps = d.sl.filter((r) => r.gap).length;
  const sp = d.attacks.find((x) => x.coverage)?.coverage;
  const byNode = Object.entries(d.meta.node_ips).map(([m, ip]) => ({ m, ip, rules: d.allow_list.filter((r) => r.node === ip) }));
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>attacks contained</span><b>{d.attacks.filter((x) => x.blocked).length}/{d.attacks.length}</b><em>replayed on the twin</em></div>
        <div className="db-kpi"><span>Modbus allow-list</span><b>{d.allow_list.length} rules</b><em>cover the program's {d.n_access} accesses exactly</em></div>
        <div className="db-kpi warn"><span>writable, never used</span><b>{d.exposed.length}</b><em>coils blocked (F1)</em></div>
        <div className="db-kpi"><span>zone pairs denied</span><b>{d.denied_pairs.length}</b><em>{d.conduits.length} conduits allowed</em></div>
        <div className="db-kpi"><span>spoof plausibility</span><b>{sp ? `${sp.detected}/${sp.steps}` : "–"}</b><em>moving steps: an instant lie caught</em></div>
        <div className="db-kpi ok"><span>SL-C gaps</span><b>{gaps}</b><em>each with a countermeasure</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>What the analysis says</h3>
          <div className="mo-insights">{d.findings.map((f) => <div key={f.title}><b>{f.title}</b><p>{f.text}</p></div>)}</div>
        </section>
        <section className="db-card wide"><h3>Zones and conduits (IEC 62443-3-2)</h3>
          <div className="sec-zone">
            <ZoneMap d={d} sel={sel} setSel={setSel} />
            <table className="db-table"><thead><tr><td>conduit</td><td>flow</td><td>protocol</td></tr></thead>
              <tbody>{d.conduits.map((c) => (
                <tr key={c.id} className={sel === c.id ? "on" : ""} onMouseEnter={() => setSel(c.id)} onMouseLeave={() => setSel(null)}
                  title={`${c.auth}${c.dpi !== "-" ? `\nDPI: ${c.dpi}` : ""}`}>
                  <td className="mono">{c.id} <span className="db-muted">{c.a}↔{c.b}</span></td><td>{c.flow}</td>
                  <td><span className="ui-chip">{c.proto}</span></td></tr>))}</tbody></table>
          </div>
          <p className="db-note">Every other zone pair is denied ({d.denied_pairs.map((p) => p.join("→")).join(", ")}). Paths from the internet into the
            cell: {d.paths_in.map((p) => p.path.join(" → ") + ` (via ${p.via.join(", ")})`).join("; ")}, each through an authenticated hop.</p>
        </section>
        <section className="db-card wide"><h3>Attacks, replayed on the twin</h3>
          <div className="mo-sub">
            {d.attacks.map((x) => <button key={x.id} className={x.id === atk ? "on" : ""} onClick={() => setAtk(x.id)}>{x.id} {x.name}</button>)}
          </div>
          <p><b>{a.what}</b> <span className="db-muted">- attacker in {a.zone}</span></p>
          <div className="mo-sub">
            {(["without", "detect_only", "with"] as const).map((m) => (
              <button key={m} className={m === mode ? "on" : ""} onClick={() => setMode(m)}>
                {m === "without" ? "no security" : m === "detect_only" ? "detection only" : "Upgrade 11"}</button>))}
          </div>
          <div className={`sec-out ${mode === "with" ? "ok" : mode === "without" ? "bad" : "warn"}`}>{a[mode]}</div>
          <p className="db-note"><b>Residual:</b> {a.residual}</p>
          {a.coverage && <table className="db-table" style={{ marginTop: 8 }}><thead><tr><td>steps</td><td className="num">supervised</td><td className="num">an instant lie caught</td><td>too short to tell</td></tr></thead>
            <tbody>{a.coverage.by_class.map((c) => <tr key={c.class}><td>{c.class}</td><td className="num">{c.steps}</td><td className="num">{c.detected}</td>
              <td className="db-muted">{c.blind.join(", ") || "-"}</td></tr>)}</tbody></table>}
          {a.coverage && <p className="db-note">A lie counts as caught when it arrives sooner than {Math.round(a.coverage.fast_factor * 100)} % of the
            plant model's time for that step. {a.coverage.zero_legs} legs that move nothing are left out.</p>}
        </section>
        <section className="db-card wide"><h3>Conduit C1: the Modbus allow-list, generated from the PLC program</h3>
          <table className="db-table"><thead><tr><td>node</td><td>function</td><td className="num">address</td><td className="num">count</td></tr></thead>
            <tbody>{byNode.flatMap(({ m, ip, rules }) => rules.map((r, i) => (
              <tr key={`${ip}-${i}`}><td className="mono">{i === 0 ? `${m} ${ip}` : ""}</td><td className="mono">FC{r.fc} {r.fn.replace("_", " ")}</td>
                <td className="num">{r.start}</td><td className="num">{r.count}</td></tr>)))}</tbody></table>
          <p className="db-note">Source: the PLC ({d.meta.plc_ip}) only. Writes are exactly the coils the state machines drive; the PLC reads the same
            coils back every scan (SEC-01). Not writable although wired: {d.exposed.map((e) => `${e.module}.${e.signal}${e.retired ? " (retired)" : ""}`).join(", ")}.
            {" "}<a href={`${BASE}security/cell_firewall.nft`} download>cell_firewall.nft</a></p>
        </section>
        <section className="db-card"><h3>Conduit C3: what the energy manager may write (SunSpec 124)</h3>
          <table className="db-table"><thead><tr><td>point</td><td className="num">offset</td><td>EMS</td></tr></thead>
            <tbody>{d.sunspec.map((p) => <tr key={p.point}><td className="mono">{p.point}</td><td className="num">{p.offset}</td>
              <td className={p.ems_write ? "ok" : ""}>{p.ems_write ? "write" : "read only"}</td></tr>)}</tbody></table>
          <p className="db-note">The reserve (MinRsvPct) and grid charging are set on the inverter and cannot be written over the network; the revert
            timer makes a silent EMS fall back to the inverter's own mode.</p>
        </section>
        <section className="db-card"><h3>Security levels: capability vs target 2</h3>
          <table className="db-table"><thead><tr><td>component</td><td>requirement</td><td className="num">SL-C</td><td>countermeasure</td></tr></thead>
            <tbody>{d.sl.filter((r) => r.gap).map((r, i) => (
              <tr key={i}><td>{r.component}</td><td>{r.fr}</td><td className="num warn">{r.sl_c}</td><td className="db-muted">{r.countermeasure}</td></tr>))}</tbody></table>
          <p className="db-note">Only the gaps are listed; the PLC meets SL 2 on every requirement. Component capabilities are assumed by product class.</p>
        </section>
        <section className="db-card"><h3>Safety stays off the network</h3>
          <table className="db-table"><tbody>{d.safety.functions.map((f) => <tr key={f.id}><td className="mono">{f.id}</td><td>{f.name}</td><td className="db-muted">{f.devices}</td><td className="num">PL{f.PLr}</td></tr>)}</tbody></table>
          {d.safety.soft_links.map((s) => <p key={s.what} className="db-note"><b>Soft link: {s.what}.</b> {s.why}. {s.still}.</p>)}
        </section>
        <section className="db-card"><h3>HMI: what an operator may write</h3>
          <table className="db-table"><tbody>{d.hmi_tags.map(([t, role, why]) => <tr key={t}><td className="mono">{t}</td><td>{role}</td><td className="db-muted">{why}</td></tr>)}</tbody></table>
          <h3 style={{ marginTop: 12 }}>New alarms</h3>
          <table className="db-table"><tbody>{d.alarms.map((x) => <tr key={x.code}><td className="mono">{x.code}</td><td>{x.text}</td></tr>)}</tbody></table>
        </section>
        <section className="db-card wide"><h3>Signed program manifest</h3>
          <table className="db-table"><tbody>{Object.entries(d.manifest.files).map(([f, h]) => <tr key={f}><td className="mono">{f}</td><td className="mono db-muted">{h.slice(0, 32)}…</td></tr>)}
            <tr><td><b>root</b></td><td className="mono">{d.manifest.root}</td></tr></tbody></table>
          <p className="db-note">The PLC refuses to leave INIT unless the running program hashes to the signed root (SEC-03).</p>
          <ul className="gr-std">{d.meta.standards.map((s) => <li key={s}>{s}</li>)}</ul>
          <p className="db-note">A design and a model-based assessment, not a penetration test. Assumed: {d.meta.assumed}.</p>
        </section>
      </div>
    </>
  );
}
