// Upgrade 14, step 2: the cell's OPC UA address space (OPC 40001-1 Machinery on DI and IA),
// as stf-cad/hbw/opcua/check.py exported it from the running server, with the proof results.
// The real server needs Python and a socket, so on the static site the values come from the
// same compiled PLC program scanning the plant in this browser - the stream the server serves.
import { useEffect, useMemo, useState } from "react";
import { useJson } from "../shared/data";
import { Icon } from "../shared/icons";
import { useSil } from "./PlcPanel";
import { Empty, Stat } from "./kit";

const BASE = import.meta.env.BASE_URL;
const PHASES = ["homing", "running", "complete"];

type N = {
  name: string; id: string; cls: string; type?: string; desc?: string; value?: string;
  signal?: string; unit?: string; field?: string; children?: N[];
};
type Result = {
  nodes: number; signals: number; namespace: string; endpoint: string; companions: string[]; seconds: number;
  security: Record<string, string | [string, string][]>;
  live?: { phases: string[]; order_s: number; jobs: number; wall_s: number; crane_jobs: string[] };
  mutants: { id: string; what: string; caught: boolean; by: string | null }[];
  fails: string[]; tree: N;
};
type Values = Record<string, string>;

/** The values the server would publish now, keyed by node id (server.py Feed.apply, in TypeScript). */
function useValues(tree: N | undefined, on: boolean) {
  const { sim, names, err, restart } = useSil();
  const [vals, setVals] = useState<Values>({});
  const ids = useMemo(() => {
    const sig: [string, string][] = [], unit: [string, string, string][] = [], prod: [string, string][] = [];
    let state = "";
    const walk = (n: N, parent: string) => {
      if (n.signal) sig.push([n.id, n.signal]);
      if (n.unit && n.field) unit.push([n.id, n.unit, n.field]);
      if (parent === "Production" && n.cls === "Variable") prod.push([n.id, n.name]);
      if (n.name === "CurrentState" && parent === "MachineryItemState") state = n.id;
      n.children?.forEach((c) => walk(c, n.name));
    };
    if (tree) walk(tree, "");
    return { sig, unit, prod, state };
  }, [tree]);

  useEffect(() => {
    if (!sim || !on) return;
    const m = sim.meta;
    const where: Record<string, () => number> = {};
    m.io.ix.forEach((e) => { where[e.name] = () => sim.ix[e.bit!]; });
    m.io.qx.forEach((e) => { where[e.name] = () => sim.qx[e.bit!]; });
    m.io.iw.forEach((e, i) => { where[e.name] = () => sim.iw[i]; });
    m.io.id.forEach((e, i) => { where[e.name] = () => sim.id[i]; });
    const boolean = new Set([...m.io.ix, ...m.io.qx].map((e) => e.name));
    let last = performance.now(), acc = 0, raf = 0, shown = 0;
    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (sim.phase !== 2 && !sim.faults.length) {
        acc += dt * 8;
        const n = Math.min(4000, Math.floor(acc / sim.dt));
        acc -= n * sim.dt;
        for (let k = 0; k < n; k++) sim.tick();
      }
      if (now - shown > 200) {
        shown = now;
        const v: Values = {};
        for (const [id, s] of ids.sig) {
          const x = where[s]?.();
          if (x !== undefined) v[id] = boolean.has(s) ? (x ? "true" : "false") : String(Math.round(x * 100) / 100);
        }
        let fault = false;
        const unitVals = Object.fromEntries(m.units.map((u, i) => {
          const sn = sim.mw[10 * (i + 1)], job = sim.mw[10 * (i + 1) + 1];
          fault ||= sn === 910;
          return [u, {
            State: String(sn), StateText: sn === 100 ? "ready" : names[u]?.[sn] ?? "", Job: job ? m.jobs[job - 1] : "",
            Busy: String(sn >= 1000), Fault: String(sn === 910), Alarm: String(sim.mw[10 * (i + 1) + 8]),
          } as Record<string, string>];
        }));
        for (const [id, u, f] of ids.unit) v[id] = unitVals[u]?.[f] ?? "";
        const prod: Record<string, string> = {
          Phase: PHASES[sim.phase] ?? "?", JobsCompleted: String(sim.mw[1]), MachineTime: sim.t.toFixed(1),
          OrderTime: sim.homedAt === null ? "0" : (sim.t - sim.homedAt).toFixed(1), Run: "0",
        };
        for (const [id, f] of ids.prod) if (f in prod) v[id] = prod[f];
        if (ids.state) v[ids.state] = fault || sim.plant.flags.length ? "OutOfService" : sim.phase === 1 ? "Executing" : "NotExecuting";
        setVals(v);
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [sim, on, ids, names]);
  return { vals, err, ready: !!sim, phase: sim?.phase ?? 0, restart };
}

const matches = (n: N, q: string): boolean =>
  !q || [n.name, n.signal, n.type, n.id].some((s) => s?.toLowerCase().includes(q)) || !!n.children?.some((c) => matches(c, q));

function Row({ n, depth, q, vals, sel, onSel }: { n: N; depth: number; q: string; vals: Values; sel: string; onSel: (n: N) => void }) {
  if (!matches(n, q)) return null;
  const live = vals[n.id];
  const two = n.type === "TwoStateDiscreteType" && live !== undefined
    ? n.children?.find((c) => c.name === (live === "true" ? "TrueState" : "FalseState"))?.value : undefined;
  const value = live ?? n.value;
  const head = (
    <span className={`ua-row ${sel === n.id ? "sel" : ""}`} onClick={(e) => { e.preventDefault(); onSel(n); }}>
      <i className={`ua-cls ${n.cls.toLowerCase()}`} title={n.cls}>{n.cls[0]}</i>
      <b>{n.name}</b>
      {n.type && <em>{n.type.replace(/Type$/, "")}</em>}
      {value !== undefined && value !== "None" && (
        <span className={`ua-v ${live === "true" ? "on" : ""} ${live !== undefined ? "live" : ""}`}>{two ?? value}</span>
      )}
    </span>
  );
  // the type-declared properties of a signal (FalseState, EURange …) stay folded under it
  const kids = n.children ?? [];
  if (!kids.length) return <div className="ua-leaf">{head}</div>;
  return (
    <details className="ua-node" open={!!q || depth < 1} onToggle={(e) => e.stopPropagation()}>
      <summary>{head}</summary>
      <div className="ua-kids">{kids.map((c) => <Row key={c.id} n={c} depth={depth + 1} q={q} vals={vals} sel={sel} onSel={onSel} />)}</div>
    </details>
  );
}

export function OpcuaPanel() {
  const { data: r, error } = useJson<Result>("opcua/opcua.json");
  const [on, setOn] = useState(true);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<N | null>(null);
  const { vals, err, ready, phase, restart } = useValues(r?.tree, on);
  if (error) return <Empty text="No address space: run opcua/check.py." />;
  if (!r) return <Empty text="loading…" />;
  const sec = r.security;
  const refused = ["no security", "anonymous", "wrong password", "untrusted certificate"];
  const held = refused.filter((k) => sec[k] !== "ACCEPTED").length + (sec.write !== "ACCEPTED" ? 1 : 0);
  const caught = r.mutants.filter((m) => m.caught).length;
  const pick = (n: N) => setSel(sel?.id === n.id ? null : n);

  return (
    <div className="np ua">
      <div className="np-head">
        <div><b>OPC UA server</b><span>IEC 62541 · Machinery (OPC 40001-1) on DI and IA</span></div>
        <a className="ui-btn" href={`${BASE}opcua/stf.NodeSet2.xml`} download>NodeSet2</a>
      </div>
      <div className="np-stats">
        <Stat label="Nodes" value={`${r.nodes}`} sub={`${r.signals} PLC signals, one node each`} />
        <Stat label="Attacks refused" value={`${held}/5`} sub="Basic256Sha256 Sign & Encrypt only" tone={held === 5 ? "ok" : "bad"} />
        <Stat label="Live order" value={r.live ? `${r.live.order_s.toFixed(1)} s` : "–"} sub={r.live ? `${r.live.jobs} jobs, as Upgrade 13` : ""} tone="ok" />
        <Stat label="Mutants caught" value={`${caught}/${r.mutants.length}`} sub="the checks can fail" tone={caught === r.mutants.length ? "ok" : "bad"} />
      </div>

      <div className="ua-sec">
        {refused.map((k) => (
          <div key={k}><span>{k}</span><code className={sec[k] === "ACCEPTED" ? "bad" : ""}>{String(sec[k])}</code></div>
        ))}
        <div><span>write a variable</span><code className={sec.write === "ACCEPTED" ? "bad" : ""}>{String(sec.write)}</code></div>
      </div>

      <div className="plc-bar">
        <button className="ui-btn icon" onClick={() => setOn(!on)} aria-label={on ? "Pause values" : "Run values"}><Icon name={on ? "pause" : "play"} size={15} /></button>
        <button className="ui-btn" onClick={restart}>StartOrder</button>
        <span className="tag">{err ? `PLC: ${err}` : !ready ? "compiling the PLC…" : `values: PLC in this browser · ${PHASES[phase]}`}</span>
      </div>
      <input className="ui-select ua-q" placeholder="Find a node: name, signal, type (e.g. hbw_I1, AnalogUnit)" value={q}
        onChange={(e) => setQ(e.target.value.trim().toLowerCase())} aria-label="Find a node" />

      <div className="ua-tree">
        <Row n={r.tree} depth={0} q={q} vals={vals} sel={sel?.id ?? ""} onSel={pick} />
      </div>
      {sel && (
        <div className="ua-sel">
          <div><span>NodeId</span><code>{sel.id}</code></div>
          <div><span>NodeClass</span><code>{sel.cls}</code></div>
          {sel.type && <div><span>TypeDefinition</span><code>{sel.type}</code></div>}
          {sel.signal && <div><span>PLC signal</span><code>{sel.signal}</code></div>}
          {sel.desc && <p>{sel.desc}</p>}
        </div>
      )}
      <p className="np-foot">
        The address space as the server exported it. Run it with <code>make opcua</code> (Python, asyncua) and connect a client
        such as UaExpert: one endpoint on 127.0.0.1:4840, Sign & Encrypt with Basic256Sha256, a trusted client certificate and
        the operator password; every variable is read-only. The cell's ProductInstanceUri is its Asset Administration Shell's asset id.
        <a href={`${BASE}opcua/opcua.json`} download>JSON</a>
      </p>
    </div>
  );
}
