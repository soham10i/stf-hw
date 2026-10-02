// Upgrade 12: defence in depth - hardwired interlocks and the re-run attacks (hardening.py).
import { useState } from "react";
import { useJson } from "../shared/data";
import { Empty, Head, Stat } from "./kit";

type Hard = {
  interlocks: { id: string; module: string; outputs: string[]; permissive: string; contact: string; why: string;
                guarded_steps: number; blocked: number; blocked_u7: number; adopted: boolean; reason: string }[];
  attacks: { id: string; name: string; u11: string; u12: string; closed: boolean }[];
  ems: Record<"U9" | "U12", { dr_met: boolean; dr_import_wh: number; total_eur: number; ride_through: number; events: number }> &
       { forged: { reserve_wh: number } };
};

export function HardeningPanel() {
  const { data: d, error: err } = useJson<Hard>("hardening/hardening.json");
  const [sel, setSel] = useState<string | null>(null);
  if (err) return <Empty text="No hardening data: run hardening.py." />;
  if (!d) return <Empty text="loading…" />;
  const ad = d.interlocks.filter((r) => r.adopted);
  const e = d.ems;
  return (
    <div className="np">
      <Head title="Defence in depth" sub="hardwired where the program can't be trusted" page="hardening" />
      <div className="np-stats">
        <Stat label="Hardwired interlocks" value={`${ad.length}/${d.interlocks.length}`} sub="never block the program" tone="ok" />
        <Stat label="Findings closed" value={`${d.attacks.filter((a) => a.closed).length + 1}/4`} sub="F1 F2 F3 + soft link" tone="ok" />
      </div>
      <h4 className="np-h">Jog rules</h4>
      <div className="np-il">
        {d.interlocks.map((r) => (
          <button key={r.id} className={`${r.adopted ? "on" : ""} ${sel === r.id ? "sel" : ""}`} onClick={() => setSel(sel === r.id ? null : r.id)}>
            <b>{r.id}</b><span>{r.why.split(":")[0]}</span><em>{r.adopted ? "hardwired" : "software"}</em>
            {sel === r.id && <p>{r.reason}</p>}
          </button>
        ))}
      </div>
      <h4 className="np-h">Re-run on the hardened machine</h4>
      {d.attacks.map((a) => (
        <div key={a.id} className="np-out ok"><b>{a.id} · {a.name}</b><br />{a.u12}</div>
      ))}
      <div className="np-out ok"><b>F3 · a forged demand-response event</b><br />The energy manager now stops at the ride-through reserve:
        {" "}{e.forged.reserve_wh} Wh stay for outages. Demand response {e.U12.dr_met ? "still met" : "no longer fully met"}; bill €{e.U12.total_eur} (was €{e.U9.total_eur}).</div>
      <p className="np-foot">In 3D the interlock relays sit at the end of each I/O node's rail (teal). They protect the machine and are not safety functions.</p>
    </div>
  );
}
