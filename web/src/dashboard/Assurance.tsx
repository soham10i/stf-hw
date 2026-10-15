// Upgrade 12 (stf-cad/hbw/hardening.py) and the validation of U1-U12
// (stf-cad/hbw/validate.py): what is hardwired now, and whether every proof still holds.
import { useJson } from "../shared/data";
import { Dumbbell, HBar } from "./Plot";

function useDoc<T>(path: string, hint: string) {
  const { data: d, error: err } = useJson<T>(path, hint);
  return { d, err };
}

type Hard = {
  interlocks: { id: string; module: string; outputs: string[]; permissive: string; contact: string; why: string;
                guarded_steps: number; blocked: number; blocked_u7: number; adopted: boolean; reason: string }[];
  relays: Record<string, { id: string; permissive: string; contact: string }[]>;
  attacks: { id: string; name: string; u11: string; u12: string; closed: boolean }[];
  ems: Record<"U9" | "U12", { dr_met: boolean; dr_import_wh: number; total_eur: number; ride_through: number; events: number; lowest_soc_in_dr: number | null }>;
  findings: { title: string; text: string }[];
  program_steps: number;
};

export function HardeningPage() {
  const { d, err } = useDoc<Hard>("hardening/hardening.json", "No data. Run: STF_VARIANT=up12 python3 hardening.py");
  if (err) return <div className="db-err">{err}</div>;
  if (!d) return <div className="db-err">loading…</div>;
  const ad = d.interlocks.filter((r) => r.adopted).length;
  const E = d.ems;
  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi ok"><span>hardwired interlocks</span><b>{ad} / {d.interlocks.length}</b><em>jog rules that were software only</em></div>
        <div className="db-kpi ok"><span>program steps replayed</span><b>{d.program_steps}</b><em>none blocked by an adopted interlock</em></div>
        <div className="db-kpi ok"><span>U11 findings closed</span><b>{d.attacks.filter((a) => a.closed).length + (E.U12.lowest_soc_in_dr === null || E.U12.lowest_soc_in_dr >= 0.3 - 1e-6 ? 1 : 0)} / 4</b><em>F1 · F2 · F3 · soft link</em></div>
        <div className={`db-kpi ${E.U12.dr_met ? "ok" : "warn"}`}><span>demand response</span><b>{E.U12.dr_met ? "met" : "not fully"}</b><em>with the reserve held</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card wide"><h3>What changed</h3>
          <div className="mo-insights">{d.findings.map((f) => <div key={f.title}><b>{f.title}</b><p>{f.text}</p></div>)}</div>
        </section>
        <section className="db-card wide"><h3>Every jog rule, and whether it can be hardwired</h3>
          <HBar xTitle="program steps the rule guards (hover for the reason)" fmt={(v) => `${Math.round(v)}`}
            rows={d.interlocks.map((r) => ({ label: `${r.id} · ${r.module} ${r.outputs.join("/")}`, v: r.guarded_steps, on: r.adopted,
              color: r.adopted ? "var(--ok)" : r.permissive === "POS" ? "#6c7884" : "var(--bad)",
              tip: `${r.id}: ${r.why}\n${r.adopted ? "hardwired" : r.permissive === "POS" ? "no sensor for it" : `would block ${r.blocked} steps`} - ${r.reason}` }))} />
          <div className="pl-legend static"><span><i style={{ background: "var(--ok)" }} />hardwired</span><span><i style={{ background: "#6c7884" }} />no switch to wire it to</span>
            <span><i style={{ background: "var(--bad)" }} />would block the program's own steps</span></div>
          <p className="hl-cap">Hardwired only if the switch exists and replaying the whole order never hits a blocked step. IL4 passed the U7 program but blocks U10's blended path.</p>
        </section>
        <section className="db-card wide"><h3>The U11 findings, re-run on the hardened machine</h3>
          <table className="db-table"><thead><tr><td>finding</td><td>Upgrade 11</td><td>Upgrade 12</td></tr></thead>
            <tbody>{d.attacks.map((a) => <tr key={a.id}><td><b>{a.id}</b> {a.name}</td><td className="db-muted">{a.u11}</td><td className="ok">{a.u12}</td></tr>)}
              <tr><td><b>F3</b> forged demand-response event</td><td className="db-muted">a DR window could drain the battery to its 10 % floor</td>
                <td className="ok">the window stops at the ride-through reserve; ride-through {E.U12.ride_through}/{E.U12.events}</td></tr></tbody></table>
        </section>
        <section className="db-card"><h3>Energy: what holding the reserve costs</h3>
          <h4 className="sec-h4">lowest battery charge in a DR window</h4>
          <HBar xTitle="" x1={100} fmt={(v) => `${Math.round(v)} %`} refs={[{ v: 30, label: "reserve", color: "var(--warn)" }]}
            rows={(["U9", "U12"] as const).map((k) => ({ label: k, v: Math.round((E[k].lowest_soc_in_dr ?? 0) * 100), color: k === "U12" ? "var(--ok)" : "var(--bad)" }))} />
          <h4 className="sec-h4">grid import in DR windows</h4>
          <HBar xTitle="" fmt={(v) => `${Math.round(v)} Wh`} rows={(["U9", "U12"] as const).map((k) => ({ label: k, v: E[k].dr_import_wh, color: k === "U12" ? "#4f8fd6" : "#6c7884" }))} />
          <p className="hl-cap">Bill €{E.U9.total_eur} → €{E.U12.total_eur} · DR met: {E.U9.dr_met ? "yes" : "no"} → {E.U12.dr_met ? "yes" : "no"}.</p>
        </section>
        <section className="db-card"><h3>New parts</h3>
          <table className="db-table"><tbody>{Object.entries(d.relays).flatMap(([m, rs]) => rs.map((r) => (
            <tr key={r.id}><td className="mono">{r.id}</td><td>{m} node rail</td><td className="db-muted">coil on {r.permissive}</td></tr>)))}
            <tr><td className="mono">K8</td><td>cabinet</td><td className="db-muted">standstill monitor: 0 V on the actuator bus</td></tr></tbody></table>
        </section>
      </div>
    </>
  );
}

type Val = {
  date: string; minutes: number; fails: string[];
  exports: Record<string, { variant: string; ok: boolean; fingerprint: string; baseline: string; match: boolean; s: number }>;
  jobs: {
    security: { rules: number; accesses: number; contained: number; attacks: number; fails: string[] };
    throughput: { before: number; after: number; states: number; fails: string[] };
    mc: Record<"before" | "after", { runs: number; min: number; median: number; max: number; false_trips: number; worst_watchdog_use: number }> & { fails: string[] };
    mutants: { rows: { id: string; proof: string; defect: string; caught: boolean; how: string }[]; fails: string[] };
    ml: { checked_windows: number; pytorch_vs_stored: number; onnx_vs_pytorch: number; json_vs_pytorch: number; fails: string[] };
    data: { month_json: string; grid_json: string; pytest: string; web_build: string; fails: string[] };
  };
};

export function ValidationPage() {
  const { d, err } = useDoc<Val>("validation/validation.json", "No validation run yet. Run: python3 validate.py");
  if (err) return <div className="db-err">{err}</div>;
  if (!d) return <div className="db-err">loading…</div>;
  const J = d.jobs, ex = Object.values(d.exports);
  const caught = J.mutants.rows.filter((r) => r.caught).length;
  return (
    <>
      <div className="db-kpis">
        <div className={`db-kpi ${d.fails.length ? "fail" : "ok"}`}><span>result</span><b>{d.fails.length ? `${d.fails.length} fail` : "all pass"}</b><em>{d.date} · {d.minutes} min</em></div>
        <div className="db-kpi ok"><span>variants re-proven</span><b>{ex.filter((e) => e.ok && e.match).length} / {ex.length}</b><em>fingerprint = baseline</em></div>
        <div className="db-kpi ok"><span>mutants caught</span><b>{caught} / {J.mutants.rows.length}</b><em>planted defects</em></div>
        <div className="db-kpi ok"><span>false trips at ±20 %</span><b>{J.mc.before.false_trips + J.mc.after.false_trips}</b><em>{J.mc.before.runs + J.mc.after.runs} randomised runs</em></div>
        <div className="db-kpi ok"><span>network parity</span><b>{Math.max(J.ml.onnx_vs_pytorch, J.ml.json_vs_pytorch).toFixed(4)}</b><em>orders, worst of 3 deployments</em></div>
      </div>
      <div className="db-grid">
        <section className="db-card hl-span2"><h3>Regression: every variant re-exported and re-proven</h3>
          <HBar xTitle="export and proof time (min) · hover for the fingerprint" fmt={(v) => `${Math.round(v)}`}
            rows={ex.sort((a, b) => a.variant.localeCompare(b.variant, undefined, { numeric: true })).map((e) => ({ label: e.variant, v: e.s / 60,
              color: e.ok && e.match ? "var(--ok)" : "var(--bad)", tip: `${e.variant}: gates ${e.ok ? "pass" : "FAIL"} · fingerprint ${e.fingerprint}${e.match ? " = baseline" : ` ≠ baseline ${e.baseline}`} · ${Math.round(e.s / 60)} min` }))} />
          <p className="hl-cap">Green = every gate passed and the fingerprint equals the recorded baseline.</p>
        </section>
        <section className="db-card"><h3>Robustness: ±20 % on every plant step</h3>
          <Dumbbell xTitle="order time over 25 random plants (s)" max={Math.max(J.mc.before.max, J.mc.after.max) * 1.08} fmt={(v) => `${Math.round(v)}`}
            a={{ name: "fastest", color: "var(--ok)" }} b={{ name: "slowest", color: "var(--bad)" }}
            rows={(["before", "after"] as const).map((k) => ({ label: k === "before" ? "U7 program" : "U10 program", a: J.mc[k].min, b: J.mc[k].max, note: `median ${J.mc[k].median} s` }))} />
          <p className="hl-cap">U10's slowest run beats U7's fastest. No watchdog tripped falsely (worst step used {Math.round(Math.max(J.mc.before.worst_watchdog_use, J.mc.after.worst_watchdog_use) * 100)} % of its limit).</p>
        </section>
        <section className="db-card"><h3>Data products</h3>
          <table className="db-table"><tbody>
            <tr><td>network: ONNX vs PyTorch</td><td className="num">{J.ml.onnx_vs_pytorch.toFixed(6)}</td></tr>
            <tr><td>network: browser weights vs PyTorch</td><td className="num">{J.ml.json_vs_pytorch.toFixed(6)}</td></tr>
            <tr><td>month.json</td><td className="num">{J.data.month_json}</td></tr>
            <tr><td>grid re-run</td><td className="num">{J.data.grid_json}</td></tr>
            <tr><td>pytest</td><td className="num">{J.data.pytest}</td></tr>
            <tr><td>web build</td><td className="num">{J.data.web_build}</td></tr></tbody></table>
        </section>
        <section className="db-card wide"><h3>Mutation tests: a defect planted in each proof</h3>
          <table className="db-table"><thead><tr><td>#</td><td>proof</td><td>planted defect</td><td>caught by</td></tr></thead>
            <tbody>{J.mutants.rows.map((r) => <tr key={r.id}><td className="mono">{r.id}</td><td>{r.proof}</td><td>{r.defect}</td>
              <td className={r.caught ? "ok" : "fail"} title={r.how}>{r.caught ? r.how.slice(0, 70) : "SURVIVED"}</td></tr>)}</tbody></table>
          <p className="db-note">A proof that cannot fail proves nothing. Writing M1 exposed a gap: the explorer checked that cookies were conserved, but not
            that the VGR's cup holds only one. With that invariant switched off, M1 survives (checked) - a dispatcher bug handing the arm a second
            job would have passed. The invariant is now in control.py, and M1 is caught.</p>
        </section>
        {d.fails.length > 0 && <section className="db-card wide"><h3>Failing checks</h3><ul>{d.fails.map((f) => <li key={f}>{f}</li>)}</ul></section>}
      </div>
    </>
  );
}
