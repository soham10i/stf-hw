// Upgrade 11: IEC 62443 zones and conduits, and attacks replayed on the twin (security.py).
import { useState } from "react";
import { useJson } from "../shared/data";
import { Empty, Head, Stat, Note } from "./kit";

export const ZONE_COL: Record<string, string> = { Z0: "#ef4444", Z1: "#3b82f6", Z2: "#8b5cf6", Z3: "#f59e0b", Z4: "#14b8a6", Z5: "#94a3b8" };
type Sec = {
  zones: { id: string; name: string; sl_t: number | null; assets: string[] }[];
  attacks: { id: string; name: string; what: string; without: string; detect_only: string; with: string }[];
  exposed: { module: string; signal: string }[]; allow_list: unknown[]; n_access: number;
};

export function NetSecurityPanel() {
  const { data: d, error: err } = useJson<Sec>("security/security.json");
  const [atk, setAtk] = useState("A1");
  const [mode, setMode] = useState<"without" | "detect_only" | "with">("with");
  if (err) return <Empty text="No security data: run security.py." />;
  if (!d) return <Empty text="loading…" />;
  const a = d.attacks.find((x) => x.id === atk)!;
  return (
    <div className="np">
      <Head title="OT security" sub="IEC 62443 zones on the machine" page="security" />
      <div className="np-zones">
        {d.zones.map((z) => (
          <div key={z.id} title={z.assets.join("\n")}><i style={{ background: ZONE_COL[z.id] }} /><b>{z.id}</b><span>{z.name}</span>
            <em>{z.sl_t ? `SL ${z.sl_t}` : z.id === "Z0" ? "no network" : "untrusted"}</em></div>
        ))}
      </div>
      <div className="np-stats">
        <Stat label="Allow-list" value={`${d.allow_list.length} rules`} sub={`${d.n_access} program accesses`} />
        <Stat label="Unused, writable" value={`${d.exposed.length}`} sub={d.exposed.map((e) => `${e.module}.${e.signal}`).join(" ")} tone="warn" />
      </div>
      <h4 className="np-h">Replay an attack</h4>
      <select className="ui-select np-sel" value={atk} onChange={(e) => setAtk(e.target.value)}>
        {d.attacks.map((x) => <option key={x.id} value={x.id}>{x.id} · {x.name}</option>)}
      </select>
      <div className="ui-seg np-seg">
        {(["without", "detect_only", "with"] as const).map((m) => (
          <button key={m} className={m === mode ? "on" : ""} onClick={() => setMode(m)}>{m === "without" ? "None" : m === "detect_only" ? "Detect" : "U11"}</button>))}
      </div>
      <div className={`np-out ${mode === "with" ? "ok" : mode === "without" ? "bad" : "warn"}`}>{a[mode]}</div>
      <Note title="What the boxes in 3D are">In 3D: blue boxes are cell control (Z1) - the four I/O nodes and the PLC; red boxes are the hardwired E-stops and
        reset (Z0), which have no network interface.</Note>
    </div>
  );
}
